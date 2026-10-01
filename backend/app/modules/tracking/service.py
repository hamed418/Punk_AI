"""Conversion tracking — turn a customer's plain event into a Meta server event.

The dataset and the token are the connected user's own; Punk holds neither a
platform dataset nor a platform Meta credential. Everything here resolves off one
``ads_accounts`` row — the ad account the user has selected, which is also the
account they are billed for and the account campaigns publish into.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime

from app.core.config import settings
from app.core.logging import logger
from app.modules.ads.models import AdsAccount
from app.modules.ads.repository import AdsRepository
from app.modules.tracking.repository import TrackingRepository
from app.modules.tracking.schemas import (
    PRE_HASHED_FIELDS,
    TrackingEventBatch,
    TrackingEventRequest,
)
from app.services import meta_ads, meta_capi

# Events Manager deep link, so a user can go look at their own data.
_EVENTS_MANAGER = "https://business.facebook.com/events_manager2/list/dataset/{dataset_id}/overview"

# Header the customer's site or CRM authenticates with. Not the platform X-API-Key:
# that key is Punk's, and handing it to every advertiser's website would make each
# of them able to call the rest of the API.
INGEST_KEY_HEADER = "X-Punk-Tracking-Key"

_NOT_CONNECTED = (
    "Connect Meta and select an ad account before setting up conversion tracking"
)

# ── what tracking_method actually decides ────────────────────────────────────
# Two independent questions, which is why this is two sets and not a switch.
#
# Whether a browser tag is part of the setup. Instant-form leads happen inside
# Facebook and CRM uploads happen after the fact — neither involves the site, so
# handing those users a snippet is an instruction they cannot follow.
_METHODS_WITH_PIXEL = frozenset({"pixel_and_server", "pixel_only", ""})
# Whether conversions arrive at Punk over HTTP, which is what the ingest key is
# for. "pixel_only" is the one method that genuinely has no server half.
_METHODS_WITH_SERVER = frozenset({"pixel_and_server", "lead_forms", "offline_crm", ""})


# Every method the rest of this module knows how to honour. Derived rather than
# re-listed: a value in neither set changes nothing anywhere, so accepting one
# would store a preference that silently does nothing.
TRACKING_METHOD_VALUES = frozenset(
    (_METHODS_WITH_PIXEL | _METHODS_WITH_SERVER) - {""}
)


def uses_pixel(method: str | None) -> bool:
    """Does this setup involve a tag on the advertiser's website?"""
    return str(method or "").strip() in _METHODS_WITH_PIXEL


def uses_server(method: str | None) -> bool:
    """Does this setup post conversions to Punk over HTTP?"""
    return str(method or "").strip() in _METHODS_WITH_SERVER


def _fix_cards(*keys: str, **ids: str) -> list[dict]:
    """Catalog entries by key, rendered for the UI.

    Every one of these is something only the user can do — install a snippet, mint
    a system user token — so the honest answer to "why isn't tracking working" is
    instructions, not an error string.
    """
    from app.services import meta_remediation

    cards = []
    for key in keys:
        card = meta_remediation.render(meta_remediation.CATALOG[key], **ids)
        # An entry may name one of the ids in its prose ("…but not Lead"), which
        # ``render`` substitutes into the url only. Same rule as there: an id we
        # cannot fill leaves the sentence as written rather than showing a raw
        # placeholder — so a card with a placeholder is only ever raised on a path
        # that has the value.
        try:
            card["cause"] = card["cause"].format(**ids)
            card["steps"] = [step.format(**ids) for step in card["steps"]]
        except (KeyError, IndexError):
            pass
        cards.append(card)
    return cards


class TrackingError(Exception):
    """Something the caller can act on — surfaced as a 4xx, not a 500."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class TrackingService:
    def __init__(self, repository: AdsRepository, events: TrackingRepository | None = None):
        self.repository = repository
        self.events = events or TrackingRepository()

    # ── account state ───────────────────────────────────────────────────────

    def _token_for(self, acc: AdsAccount) -> str:
        """Which credential sends this account's events.

        A system user token the advertiser generated in their own Business Settings
        wins when present: a CAPI feed runs for months, and a user OAuth token
        expires. Both are theirs.
        """
        return str(acc.tracking_system_user_token or acc.oauth_token.access_token or "")

    async def ensure_ingest_key(self, db, user_id: str) -> str:
        """The ad account's ingest key, minting one on first use.

        Generated rather than derived from SECRET_KEY so it can be rotated without
        touching anything else, and so a leaked key reveals nothing about the
        signing secret.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc:
            raise TrackingError(_NOT_CONNECTED, 409)
        if acc.tracking_ingest_key:
            return str(acc.tracking_ingest_key)
        key = secrets.token_urlsafe(32)[:64]
        await self.repository.save_tracking_state(db, user_id, tracking_ingest_key=key)
        return key

    async def set_system_user_token(self, db, user_id: str, token: str) -> bool:
        """Store (or clear) the account's system user token.

        Encrypted at rest by the column type, like every other Meta credential —
        it spends and reads on the advertiser's own account. An empty token clears
        the override and drops the account back to its OAuth token.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc:
            raise TrackingError(_NOT_CONNECTED, 409)
        cleaned = str(token or "").strip()
        await self.repository.save_tracking_state(
            db, user_id, tracking_system_user_token=cleaned or None,
        )
        return bool(cleaned)

    async def rotate_ingest_key(self, db, user_id: str) -> str:
        key = secrets.token_urlsafe(32)[:64]
        if not await self.repository.save_tracking_state(
            db, user_id, tracking_ingest_key=key
        ):
            raise TrackingError(_NOT_CONNECTED, 409)
        return key

    async def account_for_key(self, db, ingest_key: str) -> AdsAccount:
        """Resolve the ad account from an ingest key, in constant time.

        ``compare_digest`` after the lookup rather than trusting SQL equality
        alone: the column is a secret, and an early-exit comparison anywhere on
        this path is a timing oracle over it.
        """
        if not ingest_key:
            raise TrackingError("missing tracking key", 401)
        acc = await self.repository.get_account_by_ingest_key(db, ingest_key)
        if not acc or not secrets.compare_digest(
            str(acc.tracking_ingest_key or ""), ingest_key
        ):
            raise TrackingError("invalid tracking key", 401)
        return acc

    # ── sending ─────────────────────────────────────────────────────────────

    def _to_meta_event(
        self,
        payload,
        *,
        dataset_id: str,
        client_ip: str,
        user_agent: str,
    ) -> tuple[dict, str]:
        """One request event → one Meta server event, plus the id we sent."""
        user_data = meta_capi.build_user_data(
            email=payload.email,
            phone=payload.phone,
            first_name=payload.first_name,
            last_name=payload.last_name,
            city=payload.city,
            state=payload.state,
            zip=payload.zip,
            country=payload.country,
            external_id=payload.external_id,
            fbp=payload.fbp,
            fbc=payload.fbc,
            lead_id=payload.lead_id,
            # Added here, not asked for: the caller cannot know the browser's IP
            # when the call comes from their server, and we already have both from
            # the request that carried the event.
            client_ip_address=client_ip,
            client_user_agent=user_agent,
            # The already-hashed half, for a caller who would rather Punk never saw
            # the raw value. Forwarded by name rather than listed one by one: this
            # call is an explicit keyword list, so a field added to the schema and
            # not added here is accepted by the API, dropped before the sender, and
            # reported as a conversion Meta matched to nobody.
            **{
                f"{field}_sha256": getattr(payload, f"{field}_sha256", None)
                for field in PRE_HASHED_FIELDS
            },
        )

        custom_data: dict = {}
        if payload.value is not None:
            custom_data["value"] = payload.value
            custom_data["currency"] = (payload.currency or "").upper()
        if payload.content_ids:
            custom_data["content_ids"] = payload.content_ids
        if payload.order_id:
            custom_data["order_id"] = payload.order_id

        event_time = payload.event_time or 0
        # The order id ITSELF when there is one, not a hash of it. The snippet tells
        # the browser to send ``eventID: ORDER_ID``, and Meta collapses the two
        # halves only when the strings match exactly — deriving one side while
        # printing the other on the other counted every conversion twice.
        event_id = payload.event_id or payload.order_id or meta_capi.make_event_id(
            event_name=payload.event_name,
            # No order id, so nothing is stable across both halves anyway. Name
            # whoever we can and let the id be ours alone.
            identity=(
                payload.external_id
                or payload.lead_id
                or payload.email
                or payload.fbp
                or ""
            ),
            event_time=event_time or int(time.time()),
            scope=dataset_id,
        )

        event = meta_capi.build_event(
            event_name=payload.event_name,
            user_data=user_data,
            action_source=payload.action_source,
            event_time=payload.event_time,
            event_id=event_id,
            event_source_url=payload.event_source_url,
            custom_data=custom_data or None,
            opt_out=payload.opt_out,
            limited_data_use=payload.limited_data_use,
        )
        return event, event_id

    async def send(
        self,
        db,
        *,
        ingest_key: str,
        batch,
        client_ip: str,
        user_agent: str,
    ) -> dict:
        """Ingest a batch from the customer's site or CRM.

        Raises TrackingError for anything the caller can fix (bad key, no dataset,
        malformed event) and reports Meta's own rejections in ``errors`` — a
        partially accepted batch is not a failed request.
        """
        acc = await self.account_for_key(db, ingest_key)

        # The method is the boundary, not a label. Without this an account set to
        # "website pixel only" still accepted conversions on a key issued back
        # when it was something else — so "pixel-only means nothing reaches Punk"
        # was a claim the code did not keep.
        #
        # Deliberately here and not in ``_send_for_account``: the leadgen webhook
        # shares that helper and is opted into by subscribing the Page, not by
        # this setting. Gating the shared path would silently stop forwarding
        # leads. "" stays permissive — it is every account predating the column,
        # and breaking them to close a theoretical gap is the wrong trade.
        if not uses_server(acc.tracking_method):
            raise TrackingError(
                "this ad account is set to receive conversions from the website "
                "pixel only, so server events are not accepted — change 'how your "
                "conversions reach Meta' in Punk's tracking settings to turn them "
                "back on",
                409,
            )

        return await self._send_for_account(
            db, acc, batch, client_ip=client_ip, user_agent=user_agent,
        )

    async def _send_for_account(
        self, db, acc, batch, *, client_ip: str = "", user_agent: str = "",
    ) -> dict:
        """Everything after the caller has been identified.

        Split out so the leadgen webhook can reuse it: Meta authenticates that
        delivery with an HMAC over the body rather than an ingest key, but from
        the dataset onward it is the same pipe — same dedup, same forwarding, same
        log row, same "nothing landed" rule.
        """
        # An ad account can hold several datasets — one site per dataset is common.
        # The caller names which one when they have more than one; the account's
        # remembered default covers everyone else, who never send the field.
        dataset_id = str(batch.dataset_id or acc.tracking_dataset_id or "")
        if not dataset_id:
            raise TrackingError(
                "no conversion dataset resolved for this account yet — publish a "
                "campaign with a conversion objective, or pick a dataset in Punk",
                409,
            )
        if not settings.CAPI_ENABLED:
            # Deliberately a success: the customer's site is in production and must
            # not start erroring because the feature is switched off here.
            logger.info("tracking: CAPI disabled — dropped %d event(s)", len(batch.events))
            return {"events_received": 0, "event_ids": [], "errors": []}

        events: list[dict] = []
        event_ids: list[str] = []
        for payload in batch.events:
            try:
                event, event_id = self._to_meta_event(
                    payload,
                    dataset_id=dataset_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            except ValueError as exc:
                raise TrackingError(str(exc), 422) from exc
            events.append(event)
            event_ids.append(event_id)

        token = self._token_for(acc)
        if not token:
            raise TrackingError("Meta connection has no usable token — reconnect", 409)

        # Bind the user so a dead token flips their connection to invalid instead of
        # failing silently every night for a month. This is the call most likely to
        # be the one that finds out.
        with meta_ads.acting_user(str(acc.user_id)):
            result = await meta_capi.send_events(
                dataset_id, events,
                access_token=token,
                test_event_code=batch.test_event_code,
            )

        # Best-effort, and deliberately after the send: the caller is the
        # advertiser's own checkout, and a conversion Meta already accepted must
        # not come back a 500 because our log write failed.
        #
        # ponytail: unbounded table — prune by created_at when it matters.
        try:
            await self.events.log_batch(
                db,
                ads_account_id=acc.id,
                dataset_id=dataset_id,
                payloads=list(batch.events),
                event_ids=event_ids,
                events_received=result["events_received"],
                errors=result["errors"],
            )
        except Exception:
            logger.warning("tracking: could not log %d event(s)", len(event_ids), exc_info=True)

        if result["errors"] and not result["events_received"]:
            # Nothing landed. The caller is the advertiser's own checkout webhook,
            # and a 2xx here means "delivered" to it — it will never retry, and the
            # log deliberately keeps no identifiers, so the conversion is gone for
            # good. 502 hands the retry back to the one party that still has the
            # data. A partial success stays a success.
            raise TrackingError(
                "Meta rejected every event in this batch: "
                + "; ".join(result["errors"])[:500],
                502,
            )

        return {
            "events_received": result["events_received"],
            "event_ids": event_ids,
            "errors": result["errors"],
        }

    # ── inbound: Meta's own leadgen webhook ─────────────────────────────────

    async def ingest_leadgen(self, db, entries: list[dict]) -> dict:
        """Forward instant-form leads Meta pushed to us.

        The one piece of event listening Punk can do on the advertiser's behalf.
        ``/tracking/leads`` only ever fires if the advertiser's own system POSTs to
        it — and the advertiser who chose "do it for me" has no system. Here Meta
        is the caller: it delivers the ids, we read the answers with the Page
        token, and the lead is reported back as a Lead conversion so delivery can
        learn from it.

        Every failure is swallowed into the count. A non-200 makes Meta redeliver
        the whole batch and eventually disable the subscription, which costs every
        later lead to save this one.
        """
        forwarded = 0
        for entry in entries or []:
            for change in (entry.get("changes") or []):
                if str(change.get("field") or "") != "leadgen":
                    continue
                value = change.get("value") or {}
                try:
                    forwarded += await self._forward_lead(db, value)
                except Exception:
                    logger.warning(
                        "tracking: could not forward lead %s",
                        value.get("leadgen_id"), exc_info=True,
                    )
        return {"forwarded": forwarded}

    async def _forward_lead(self, db, value: dict) -> int:
        """One pushed lead, reported back as a Lead conversion.

        **Nothing about the person is read, and nothing about them is sent.** The
        event carries ``lead_id`` and nothing else, because that is Meta's own id
        for the submission and the key Conversion Leads matches on — Meta already
        knows who filled the form in. This used to trade a Page token, read the
        answers with ``fetch_lead``, hash the name, email and phone, and send them
        back to the platform they had just been read from: a round trip of the
        advertiser's customers' personal data through Punk that bought no extra
        matching.

        Dropping it also drops two Graph calls and two failure modes per lead, and
        means the feedback loop no longer depends on ``leads_retrieval`` — that
        permission is still needed by the separate leads-viewing feature
        (``AdsService.list_form_leads``), which is untouched.
        """
        page_id = str(value.get("page_id") or "")
        leadgen_id = str(value.get("leadgen_id") or "")
        if not (page_id and leadgen_id):
            return 0

        acc = await self.repository.get_account_by_lead_page_id(db, page_id)
        if not acc:
            # A Page we never subscribed, or one whose account has since been
            # disconnected. Nothing to do, and nothing wrong.
            logger.info("tracking: leadgen for unknown page %s — dropped", page_id)
            return 0

        token = self._token_for(acc)
        if not token:
            logger.warning("tracking: no usable token for page %s — lead dropped", page_id)
            return 0

        # Named before the read, not discovered inside the catch-all in
        # ``ingest_leadgen``. "could not forward lead" reads as something
        # transient that a redelivery might fix; this is a permanent
        # misconfiguration that will drop every lead until somebody attaches a
        # dataset, and it is worth saying so in the one place anybody looks.
        if not (acc.tracking_dataset_id or ""):
            logger.warning(
                "tracking: lead %s on page %s dropped — the ad account has no "
                "dataset to report it into (Meta still counted the lead; attach "
                "one in Punk's conversion tracking settings)",
                leadgen_id, page_id,
            )
            return 0

        payload = TrackingEventRequest(
            event_name="Lead",
            # Meta's own id for the submission, so a redelivery of the same lead
            # is the same event rather than a second conversion.
            event_id=leadgen_id,
            lead_id=leadgen_id,
            # The lead was submitted inside Facebook, not on a website.
            action_source="system_generated",
            event_time=_lead_event_time(value),
        )
        result = await self._send_for_account(
            db, acc, TrackingEventBatch(events=[payload]),
        )
        return int(result.get("events_received") or 0)

    # ── what the user can change themselves ─────────────────────────────────

    async def datasets(self, db, user_id: str) -> dict:
        """The datasets this ad account can actually write to, plus the chosen one.

        Reads live rather than off the row, because the interesting case is a user
        who just made a Pixel in Events Manager and came here to attach it — a
        cached list is exactly the list that does not have it yet.

        Degrades to an empty list on any failure, like every other read behind this
        card. An empty list and a failed read are not distinguishable from here,
        which is why neither accuses the user of anything.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc:
            raise TrackingError(_NOT_CONNECTED, 409)
        token = self._token_for(acc)
        if not (token and acc.ad_account_id):
            return {"datasets": [], "selected": str(acc.tracking_dataset_id or "")}
        with meta_ads.acting_user(str(acc.user_id)):
            found = await meta_ads.fetch_ad_pixels(str(acc.ad_account_id), token)
        return {
            "datasets": [
                {
                    "id": str(pixel["id"]),
                    "name": str(pixel.get("name") or ""),
                    # Empty for a dataset nobody ever installed. The card shows it
                    # so a user picking between two is not choosing blind.
                    "last_fired_time": str(pixel.get("last_fired_time") or ""),
                }
                for pixel in found
            ],
            "selected": str(acc.tracking_dataset_id or ""),
        }

    async def set_dataset(self, db, user_id: str, dataset_id: str) -> str:
        """Point this account's conversions at a dataset it can reach.

        Validated against the account's own list rather than taken on trust: an id
        this ad account cannot write to publishes ad sets that optimize toward an
        event which can never fire, and Meta reports that as a campaign delivering
        normally.
        """
        cleaned = str(dataset_id or "").strip()
        if not cleaned:
            raise TrackingError("dataset_id is required", 422)
        available = await self.datasets(db, user_id)
        if not any(d["id"] == cleaned for d in available["datasets"]):
            raise TrackingError(
                f"{cleaned} is not a dataset this ad account can write to — assign "
                "it to the account in Business settings → Data sources first",
                422,
            )
        await self.repository.save_tracking_state(
            db, user_id, tracking_dataset_id=cleaned,
        )
        return cleaned

    async def create_custom_conversion(
        self, db, user_id: str, *, name: str, url_contains: str, custom_event_type: str,
    ) -> dict:
        """Define a conversion over the account's dataset from a page URL.

        The one conversion repair that needs no change to the advertiser's site.
        Until this existed Punk could READ an account's custom conversions (the
        editor offers them beside the standard events) and could not create one —
        so the advertiser who needed one most, the one with a base pixel and no
        event code anywhere, was sent to Events Manager to do it by hand.

        Raises rather than degrading: a conversion the user believes exists but
        does not is an ad set optimizing toward something that can never fire.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc:
            raise TrackingError(_NOT_CONNECTED, 409)
        dataset_id = str(acc.tracking_dataset_id or "")
        if not dataset_id:
            raise TrackingError(
                "pick a dataset in Punk's conversion tracking settings first — a "
                "custom conversion is a rule over one dataset's events",
                409,
            )
        token = self._token_for(acc)
        if not token:
            raise TrackingError("Meta connection has no usable token — reconnect", 409)

        try:
            with meta_ads.acting_user(str(acc.user_id)):
                conversion_id = await meta_ads.create_custom_conversion(
                    name,
                    dataset_id,
                    str(acc.ad_account_id or ""),
                    token,
                    url_contains=url_contains,
                    custom_event_type=custom_event_type,
                )
        except meta_ads.MetaAdsError as exc:
            raise TrackingError(exc.user_msg or str(exc), 502) from exc
        return {
            "id": conversion_id,
            "name": name,
            "custom_event_type": custom_event_type,
        }

    async def set_method(self, db, user_id: str, method: str) -> str:
        """Change how this account's conversions reach Meta.

        The only way to move off what publish derived. An express Sales run is
        stamped ``pixel_only`` from the shape of the campaign, and the instructions
        that setup prints tell the advertiser to switch to server events when ad
        blockers start costing them conversions — which, until this existed, they
        could not do.

        **The ingest key is deliberately not rotated here.** Switching to a method
        with no server half stops showing the key; it does not invalidate one that
        is live in a customer's checkout. Same rule ``save_tracking_state``
        documents, and rotation stays the explicit action it already is.
        """
        cleaned = str(method or "").strip()
        if cleaned not in TRACKING_METHOD_VALUES:
            raise TrackingError(
                f"unknown tracking method {cleaned!r} — one of "
                + ", ".join(sorted(TRACKING_METHOD_VALUES)),
                422,
            )
        if not await self.repository.save_tracking_state(
            db, user_id, tracking_method=cleaned,
        ):
            raise TrackingError(_NOT_CONNECTED, 409)
        return cleaned

    # ── diagnostics ─────────────────────────────────────────────────────────

    async def health(self, db, user_id: str) -> dict:
        """Is the selected ad account's tracking actually measuring anything?

        A thin wrapper over ``_health`` that adds one card the dataset diagnostics
        cannot see: a Meta connection short a permission. Doing it here rather than
        in each of ``_health``'s four exits keeps the rule in one place — a scope
        problem is true regardless of which branch the dataset check took.
        """
        result = await self._health(db, user_id)
        acc = await self.repository.get_tracking_account(db, user_id)
        if acc:
            from app.modules.ads.service import _scope_cards, missing_scopes

            cards = _scope_cards(missing_scopes(acc.oauth_token))
            if cards:
                result["remediation"] = cards + list(result.get("remediation") or [])
        return result

    async def _health(self, db, user_id: str) -> dict:
        """The dataset half of ``health``.

        Every read degrades, because this answers a question asked at the go-live
        gate: a missing diagnostic must never block a user standing in front of it.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc or not acc.tracking_dataset_id:
            # No dataset is the correct state for a setup that never uses one:
            # instant-form leads are counted by Meta inside Facebook, and a
            # Messenger sale has nothing to install anywhere. Raising a *blocking*
            # "connect a dataset" card at those advertisers accuses a setup that
            # is working exactly as chosen — the same rule the never-fired warning
            # below already follows.
            method = str(getattr(acc, "tracking_method", "") or "") if acc else ""
            if acc and method and not uses_pixel(method):
                # One exception, and it is not a setup working as chosen: a Page
                # whose leads Meta is actively pushing at us. Every one of those
                # deliveries is read and then dropped for want of somewhere to
                # report it, and the old blanket "ok" here is why that happened
                # silently. Still a warning, not a block — Meta counts the leads
                # regardless, so the campaign is fine and only the feedback loop
                # is missing.
                if method == "lead_forms" and getattr(acc, "tracking_lead_page_id", ""):
                    return {
                        "status": "no_dataset",
                        "tracking_method": method,
                        "remediation": _fix_cards("lead_dataset_missing"),
                    }
                return {"status": "ok", "tracking_method": method, "remediation": []}
            return {"status": "no_dataset", "remediation": _fix_cards("tracking_no_dataset")}
        dataset_id = str(acc.tracking_dataset_id)
        token = self._token_for(acc)
        if not token or not acc.oauth_token.is_valid:
            return {
                "dataset_id": dataset_id,
                "status": "token_invalid",
                "events_manager_url": _EVENTS_MANAGER.format(dataset_id=dataset_id),
                # A login token lasting 60 days behind a feed that runs for years
                # is not a bug to retry — it is the wrong kind of credential, and
                # only the user can mint the right one in their Business settings.
                "remediation": _fix_cards(
                    "tracking_token_expired",
                    business_id=str(acc.tracking_business_id or ""),
                    dataset_id=dataset_id,
                ),
            }

        # The event delivery actually learns from, in the wire spelling the stats
        # and the quality read both use. Empty for an account optimizing for a
        # custom conversion, whose rule fires off events already arriving — there
        # is nothing extra to install.
        wanted = meta_capi.event_name_for(acc.tracking_event_type or "")

        with meta_ads.acting_user(str(acc.user_id)):
            activity = await meta_ads.fetch_pixel_activity(dataset_id, token)
            # Scoped to the conversion event: Meta scores each event separately and
            # the account-wide best hides a Purchase that matches nobody.
            quality = await meta_ads.fetch_event_match_quality(
                dataset_id, token, event_name=wanted,
            )
            stats = await meta_ads.fetch_dataset_event_stats(dataset_id, token)

        last_fired = activity.get("last_fired_time")
        # Biggest first — the top of this list is what the dataset is mostly made
        # of, and a dataset that is all PageView is the case worth seeing.
        events = [
            {"name": name, "count": count}
            for name, count in sorted(stats.items(), key=lambda kv: -kv[1])
        ]
        method = str(acc.tracking_method or "")
        if not last_fired and not uses_pixel(method):
            # Instant-form leads and CRM uploads never produce a browser event, so
            # "this Pixel has not received any events" is a permanent, unfixable
            # warning for them — it describes the setup working as chosen.
            remediation = []
        elif not last_fired:
            remediation = _fix_cards("pixel_never_fired", dataset_id=dataset_id)
        elif wanted and stats and wanted not in stats:
            # Something is arriving, just not the thing being optimized for. Only
            # raised when the stats read succeeded — an empty ``stats`` is as likely
            # to be a failed read as an empty dataset, and accusing a working
            # integration is worse than staying quiet.
            remediation = _fix_cards(
                "tracking_event_missing",
                dataset_id=dataset_id,
                event_name=wanted,
            )
        else:
            remediation = []

        return {
            "remediation": remediation,
            "dataset_id": dataset_id,
            "dataset_name": activity.get("name") or "",
            "business_id": str(acc.tracking_business_id or ""),
            "last_fired_time": last_fired,
            "event_match_quality": quality,
            "events": events,
            "conversion_event": wanted,
            # Whether the SERVER half is live, which is the half Punk controls.
            # Counted off our own forwarding log: an ingest key exists from the
            # moment it is minted and ``last_fired_time`` is the BROWSER tag's, so
            # the old test called the server half live before a single server event
            # had ever been sent.
            "server_events_seen": await self.events.count(db, acc.id) > 0,
            "events_manager_url": _EVENTS_MANAGER.format(dataset_id=dataset_id),
            "tracking_method": method,
            "status": "ok" if last_fired else "never_fired",
        }

    async def recent_events(self, db, user_id: str, *, skip: int, limit: int):
        """The account's own forwarded events, newest first.

        Scoped to the ad account rather than the user for the same reason the
        ingest key is: one login can reach several ad accounts, and an agency must
        not read one client's conversions from another client's screen.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc:
            raise TrackingError(_NOT_CONNECTED, 409)
        return await self.events.recent(db, acc.id, skip=skip, limit=limit)

    async def snippet(self, db, user_id: str, *, event_name: str = "") -> dict:
        """The install helper: pixel base code, the event call, and the server call.

        The ``eventID`` in the browser call is the same derivation the server uses
        (``meta_capi.make_event_id``), which is what stops one purchase counting
        twice once both halves are live.

        ``event_name`` empty means "whatever this account's campaigns optimize
        toward". Handing a Leads advertiser a snippet firing ``Purchase`` — the
        old fixed default — installs the one event their ad set is not learning
        from, and the dataset then looks healthy while the campaign optimizes
        against nothing.
        """
        acc = await self.repository.get_tracking_account(db, user_id)
        if not acc:
            raise TrackingError(_NOT_CONNECTED, 409)
        dataset_id = str(acc.tracking_dataset_id or "")
        event_name = (
            event_name
            or meta_capi.event_name_for(acc.tracking_event_type or "")
            # No conversion campaign built yet, or the account optimizes for a
            # custom conversion (a URL rule, which needs no event code at all).
            or "Purchase"
        )
        method = str(acc.tracking_method or "")
        wants_pixel, wants_server = uses_pixel(method), uses_server(method)

        # The key is only minted for a setup that has something to authenticate.
        # "pixel_only" asked for a browser tag and nothing else; handing it a
        # secret to keep is an instruction with no purpose.
        key = await self.ensure_ingest_key(db, user_id) if wants_server else ""
        ingest_url = (
            f"{settings.BACKEND_PUBLIC_URL.rstrip('/')}/tracking/events"
            if wants_server else ""
        )
        # Instant forms are the one server path that is not the events endpoint —
        # a lead is a lead_id plus its status, not a purchase.
        if method == "lead_forms" and ingest_url:
            ingest_url = ingest_url.replace("/tracking/events", "/tracking/leads")

        # Meta reads the value in the AD ACCOUNT's currency. A hardcoded USD is
        # simply wrong on a CAD or BDT account, and a Purchase reported in the
        # wrong currency misprices every ROAS number built on it. Degrades to USD
        # like every other read behind this screen — a settings page must not fail
        # on a diagnostic.
        currency = "USD"
        token = self._token_for(acc)
        if token and acc.ad_account_id:
            with meta_ads.acting_user(str(acc.user_id)):
                account = await meta_ads.fetch_ad_account_currency(
                    str(acc.ad_account_id), token,
                )
            currency = str(account.get("currency") or "USD")

        pixel = _PIXEL_SNIPPET.format(
            dataset_id=dataset_id or "YOUR_DATASET_ID",
            event_name=event_name,
            currency=currency,
        ) if wants_pixel else ""
        server = _SERVER_EXAMPLE.format(
            ingest_url=ingest_url, event_name=event_name, currency=currency,
        ) if wants_server else ""
        # The same conversion with Punk taken out of the path. Offered rather than
        # argued for: the relay is a convenience (readable field names, no Meta
        # token in their store, the browser's IP and user agent, a log to look at
        # when conversions go missing), and an advertiser who would rather we never
        # saw the data should be able to see exactly what to send instead.
        #
        # META_GRAPH_URL rather than a version written out here — it is already the
        # one place the API version lives, and a second copy is the drift that
        # property exists to prevent.
        direct = _DIRECT_EXAMPLE.format(
            graph_url=settings.META_GRAPH_URL.rstrip("/"),
            dataset_id=dataset_id or "YOUR_DATASET_ID",
            event_name=event_name,
            currency=currency,
        ) if wants_server else ""
        return {
            "tracking_method": method,
            "dataset_id": dataset_id,
            "event_name": event_name,
            "currency": currency,
            "event_names": sorted(meta_capi.STANDARD_EVENTS),
            "pixel_snippet": pixel,
            "server_example": server,
            "server_direct_example": direct,
            "ingest_url": ingest_url,
            "ingest_key": key,
            "instructions": _instructions(method, event_name),
        }


# Instant-form question names → the identifier they carry. Meta's own standard
# questions use these keys; a custom question is named by the advertiser and is
# deliberately ignored rather than guessed at — a mis-mapped identifier is worse
# than a missing one, because it hashes to a person who is not the lead.
def _lead_event_time(value: dict) -> int | None:
    """When the lead was submitted, as a unix timestamp, or None for "now".

    Meta rejects an event older than seven days, so a backfilled delivery is
    better reported at its real time and refused loudly than silently stamped
    with today.

    Reads the webhook delivery only. ``created_time`` used to have a second source
    — the lead read — which went away with it; Meta puts the timestamp on the
    delivery itself, as an epoch int, and an unparseable one still degrades to
    "now" rather than losing the lead.
    """
    raw = value.get("created_time")
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            logger.info("tracking: unparseable lead created_time %r", raw)
    return None


def _instructions(method: str, event_name: str) -> list[str]:
    """Steps for the setup the advertiser actually chose.

    The old list was fixed, so a "leads come from instant forms" advertiser was
    told to paste a snippet into a site that has nothing to do with their leads,
    and a "pixel only" advertiser was told to keep a key they were never given.
    """
    pixel_steps = [
        "Paste the pixel snippet into every page of your site, just before </head>.",
        "On the page that confirms the conversion (order received, thank-you, "
        f"form sent), the {event_name} call fires — keep the eventID line, it "
        "is what stops the conversion being counted twice.",
        "Using Google Tag Manager? Add the pixel snippet as a Custom HTML tag "
        "on All Pages, and the event call as a second tag on your conversion "
        "page. WordPress: any header-scripts plugin works.",
    ]
    secret_step = (
        "Keep the tracking key secret — anyone holding it can report "
        "conversions to your dataset."
    )
    # Every method with a server half can carry these, and none of them did until
    # now: the fields have been on the request schema all along and nothing
    # user-facing mentioned them, so in practice nobody sent either one.
    consent_steps = [
        "Someone who declined tracking on your consent banner: send "
        "\"opt_out\": true with their conversion. Meta still attributes it to the "
        "ad, but it will not feed optimization.",
        "Visitors in US states with their own privacy laws: send "
        "\"limited_data_use\": true. Both flags are your call to make from your "
        "own banner — Punk carries the signal, it does not decide it.",
    ]
    # The one deduplication case make_event_id cannot solve, because the other
    # sender never sees our id. Two senders, two different event_ids, and Meta
    # counts the same purchase twice — which inflates the ROAS every later decision
    # is made on.
    double_count_step = (
        "Already on Shopify, BigCommerce, or WooCommerce with Meta's own "
        "extension? Those send server events themselves. Set Punk to \"Website "
        "pixel only\" and let the platform send that half — running both reports "
        "every purchase twice, and your ROAS reads about double what it is."
    )
    if method == "lead_forms":
        return [
            "Nothing to install. People fill the form inside Facebook or Instagram "
            "and Meta already counts the lead.",
            "When a lead turns into a customer, POST it to the endpoint below with "
            "the tracking key in the header, sending the lead_id Meta gave you. "
            "That is what teaches delivery which leads were worth having.",
            secret_step,
            *consent_steps,
        ]
    if method == "offline_crm":
        return [
            "Nothing to install on your site — the conversions happen off it.",
            "Have your CRM POST each closed sale to the endpoint below with the "
            "tracking key in the header. Send the customer's email or phone so "
            "Meta can match it back to the person who saw the ad.",
            "Send them within seven days of the sale. Meta rejects events older "
            "than that.",
            secret_step,
            *consent_steps,
        ]
    if method == "pixel_only":
        return pixel_steps + [
            "That is the whole setup. Ad blockers and iOS opt-outs will cost you "
            "some of these conversions — switch this setting to \"Website pixel + "
            "server events\" above when you want them back.",
            "Already sending server events from Shopify, BigCommerce or "
            "WooCommerce? Then pixel-only here is right — that platform is "
            "covering the server half already.",
        ]
    return pixel_steps[:2] + [
        "Have your server or CRM POST the same conversion to the endpoint "
        "below with the tracking key in the header. Send the order id in "
        "order_id so both halves agree on the event id.",
        pixel_steps[2],
        secret_step,
        double_count_step,
        *consent_steps,
    ]


_PIXEL_SNIPPET = """<!-- Meta Pixel (Punk AI) -->
<script>
!function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)}};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{dataset_id}');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id={dataset_id}&ev=PageView&noscript=1"/></noscript>
<!-- End Meta Pixel -->

<!-- On your conversion page only.
     ORDER_ID must be the same value your server sends as order_id, or the two
     halves will not deduplicate and every conversion is counted twice.
     ORDER_TOTAL must be the real order value — Meta keeps ONE of the two
     reports, so a hardcoded 0 here makes the conversion worth nothing and
     value-based bidding has nothing to bid on. -->
<script>
fbq('track', '{event_name}', {{value: ORDER_TOTAL, currency: '{currency}'}}, {{eventID: 'ORDER_ID'}});
</script>"""


_DIRECT_EXAMPLE = """# Punk out of the path entirely: your server talks to Meta.
#
# Costs you three things the endpoint above handles: you hash the identifiers
# yourself, you keep a Meta system user token on your server, and Meta never sees
# the browser's IP or user agent (your backend does not know them), which lowers
# match quality a little.
#
# Hash rules — get these wrong and the digest is valid, matches nobody, and
# nothing tells you: lowercase and trim everything first; digits only for a phone,
# country code included; the 5-digit prefix for a US zip; a 2-letter country code.
#
#   printf '%s' "customer@example.com" | sha256sum

curl -X POST {graph_url}/{dataset_id}/events \\
  -H 'Content-Type: application/json' \\
  -d '{{
    "access_token": "YOUR_SYSTEM_USER_TOKEN",
    "data": [{{
      "event_name": "{event_name}",
      "event_time": 1234567890,
      "event_id": "ORDER_ID",
      "action_source": "website",
      "user_data": {{
        "em": ["<sha256 of the lowercased email>"],
        "fbp": "the _fbp cookie value, if you have it",
        "fbc": "the _fbc cookie value, if you have it"
      }},
      "custom_data": {{"value": 49.99, "currency": "{currency}"}}
    }}]
  }}'"""


_SERVER_EXAMPLE = """curl -X POST {ingest_url} \\
  -H 'Content-Type: application/json' \\
  -H 'X-Punk-Tracking-Key: YOUR_TRACKING_KEY' \\
  -d '{{
    "events": [{{
      "event_name": "{event_name}",
      "action_source": "website",
      "order_id": "ORDER_ID",
      "email": "customer@example.com",
      "value": 49.99,
      "currency": "{currency}",
      "fbp": "the _fbp cookie value, if you have it",
      "fbc": "the _fbc cookie value, if you have it"
    }}]
  }}'

# Optional per event, both default false:
#   "opt_out": true            this person declined tracking — attribution only
#   "limited_data_use": true   US state privacy laws
# Rather not send us the raw values? Send "email_sha256" instead of "email"
# (lowercase hex SHA-256, normalized Meta's way first: trim and lowercase,
# digits only for a phone)."""
