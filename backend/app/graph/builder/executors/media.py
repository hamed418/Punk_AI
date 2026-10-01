"""
graph/builder/executors/media.py
────────────────────────────────
Meta publish pipeline core, relocated verbatim from wizards/media_wizard.py
``media_execute`` (phase 5.2). Pure execution — no interrupts, no state
writes: custom/lookalike audience creation, per-ad-set targeting variants,
campaign + ad set + creative + ad creation, activation.

Callers (media_wizard.media_execute and builder_act's publish op) own
checkpointing and milestone narration; this returns the publish facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import tempfile
from urllib.parse import urlsplit
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID as _UUID

import httpx
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import MaidExtraction
from app.modules.media.models import MediaFile
from app.graph.meta_spec import (
    DEFAULT_PIXEL_EVENT,
    AdFormat,
    CampaignSpec,
    Objective,
    normalize_objective,
    split_for_publish,
)
from app.graph.maid_query import audience_headline_count
from app.graph.meta_spec.catalog import CREATE_DATASET, errors_to_form_keys
from app.graph.meta_spec.enums import LEAD_FORM_DEFAULT_QUESTIONS, meta_label
from app.graph.meta_spec.objective_matrix import (
    PROMOTED_NONE,
    PROMOTED_PIXEL,
    goal_rules,
    matrix_for,
)
from app.graph.builder.edits import stash_edits
from app.graph.wizard_exit import StepPaused
from app.graph.builder.executors.publish_ledger import PublishLedger
from app.graph.narrator import add_beat, flush_narration, peek as _narrator_peek

if TYPE_CHECKING:  # meta_ads is imported lazily inside functions to avoid a cycle
    from app.services.meta_ads import MetaAdsError

logger = logging.getLogger(__name__)

# Publish steps where the user can fix the problem (re-upload creative) without
# abandoning the whole builder session.
RECOVERABLE_PUBLISH_STEPS = frozenset({
    "creative_resolution",
    "creative_download",
    "media_upload",
    # Meta accepted the bytes but never finished transcoding. The fix is a
    # different file, which is exactly what "recoverable" means here.
    "video_processing",
    "ad_creative",
})

# Steps that leave the ad account clean — nothing in Meta, or a campaign that
# `_fail_after_create` already tore down — so the plan the user edits next is the
# plan that actually publishes. Every publish failure routes to the editor now
# (see the `MetaPublishError` handler in `builder_node`); this set is only what
# exempts a step from the 3-strike retry cap, because an edit made against a
# clean account is a genuinely different attempt rather than the same one again.
PLAN_FIXABLE_PUBLISH_STEPS = frozenset({
    "spec_validation",
    "preflight_campaign",
    "preflight_adset",
    # `_fail_after_create` raises these only after deleting the campaigns and
    # clearing the ledger's campaign tree.
    "adset_rejected",
    "ad_creative_rejected",
    "ad_rejected",
})


class MetaPublishError(RuntimeError):
    """A core publish step failed — the campaign cannot ship as promised.

    Carries a user-facing message; callers surface it via the failure
    milestone instead of silently degrading.

    ``plan_errors`` is the same ``{form_key: message}`` shape the plan editor
    already takes from Pydantic (``errors_to_form_keys``), so a Meta rejection
    marks the control it is about instead of arriving as a field-less banner
    over a plan the user cannot see anything wrong with.

    ``remediation`` is set when the refusal is one Punk cannot fix at all — a
    Terms of Service nobody has accepted, an account with no card on it. The plan
    is not the problem in those cases, so the caller must NOT send the user to the
    plan editor; see ``meta_remediation`` for what it carries instead.
    """

    def __init__(
        self,
        user_message: str,
        *,
        step: str,
        plan_errors: dict[str, str] | None = None,
        remediation: dict | None = None,
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.step = step
        self.plan_errors = plan_errors or {}
        self.remediation = remediation


def _plan_has_creatives(marketing_plan: dict) -> bool:
    """True when any ad in the plan carries an image (upload UUID or a pre-uploaded
    Meta reference) — i.e. we will create at least one ad, which needs a Page."""
    for adset in marketing_plan.get("adsets") or []:
        for ad in adset.get("ads") or []:
            c = ad.get("creative") or {}
            if c.get("media_id") or c.get("image_hash") or c.get("video_id"):
                return True
    return False


def _iter_creative_media_slots(plan: dict):
    """Yield every dict that carries a media reference — each ad's creative, the
    extra media combined into it, and each card of a carousel (a carousel holds
    its media per card, not on the ad).

    ``MediaRef`` and ``CarouselCard`` both name their media with the same four
    fields as the creative itself, which is what lets one walk cover all three.

    One place knows this shape: the publish resolver below and the editor's
    preview hydration both walk it.
    """
    for adset in plan.get("adsets") or []:
        for ad in adset.get("ads") or []:
            creative = ad.get("creative") or {}
            yield creative
            yield from creative.get("extra_media") or []
            yield from creative.get("cards") or []


async def hydrate_media_urls(plan: dict, user_id: str | None) -> None:
    """Inject the client-only ``media_url`` preview onto each creative/card from
    its stored ``MediaFile``, in place.

    The editor strips ``media_url`` before submitting (the server spec is
    ``extra="forbid"``), so a reopened editor holds ``media_id`` with nothing to
    render — the ad still has its image and publishes fine, the card just looks
    empty, which reads as "my image is gone".

    Forgiving by design: unlike ``_resolve_ad_media`` this is display code, so a
    missing row or a database hiccup costs a thumbnail, never the whole editor.
    """
    # ponytail: only media_id resolves. A creative carrying just image_hash /
    # video_id (already uploaded to Meta) has no MediaFile row and gets no
    # preview — same as today. Add a Meta-side lookup if those reach the editor.
    slots = [s for s in _iter_creative_media_slots(plan) if s.get("media_id")]
    ids: dict[str, _UUID] = {}
    for slot in slots:
        mid = str(slot["media_id"])
        if mid not in ids:
            try:
                ids[mid] = _UUID(mid)
            except (ValueError, TypeError):
                continue
    if not ids:
        return

    try:
        async with AsyncSessionLocal() as db:
            stmt = select(MediaFile).where(MediaFile.id.in_(list(ids.values())))
            if user_id:
                # Same guard as _resolve_ad_media: a guessed UUID must not hand
                # back another user's asset URL.
                stmt = stmt.where(MediaFile.user_id == _UUID(str(user_id)))
            rows = (await db.execute(stmt)).scalars().all()
    except Exception:
        logger.warning("plan editor: media preview lookup failed", exc_info=True)
        return

    by_id = {str(row.id): row.file_path for row in rows}
    for slot in slots:
        url = by_id.get(str(slot["media_id"]))
        if url:
            slot["media_url"] = url


async def _resolve_ad_media(marketing_plan: dict, user_id: str | None) -> dict[str, dict]:
    """Map every ad's ``creative.media_id`` to its stored file.

    The editor stores each ad's chosen asset (uploaded via POST /media/upload or
    generated via /creatives/generate) as a ``MediaFile`` UUID on
    ``creative.media_id``. Publish resolves those UUIDs to R2 file paths here,
    once, so the create loop can upload each ad's own image.

    Returns ``{media_id_str: {file_path, media_type, original_filename}}``. A
    media_id that does not resolve is a hard failure — an ad the user built with
    an image must not publish without it.
    """
    # Walks each ad's creative AND each carousel card (a carousel carries one
    # asset per card) — see _iter_creative_media_slots.
    media_ids = {
        str(slot["media_id"])
        for slot in _iter_creative_media_slots(marketing_plan)
        if slot.get("media_id")
    }
    if not media_ids:
        return {}

    resolved: dict[str, dict] = {}
    async with AsyncSessionLocal() as db:
        for mid in media_ids:
            try:
                media_uuid = _UUID(mid)
            except (ValueError, TypeError):
                raise MetaPublishError(
                    "One of your ad images didn't upload correctly — please re-add it "
                    "in the campaign editor and try publishing again.",
                    step="creative_resolution",
                )
            stmt = select(MediaFile).where(MediaFile.id == media_uuid)
            if user_id:
                stmt = stmt.where(MediaFile.user_id == _UUID(str(user_id)))
            mf = (await db.execute(stmt)).scalar_one_or_none()
            if mf is None:
                raise MetaPublishError(
                    "I couldn't find one of the images you added to an ad — please "
                    "re-add it in the campaign editor and try publishing again.",
                    step="creative_resolution",
                )
            resolved[mid] = {
                "file_path": mf.file_path,
                "media_type": mf.media_type,
                "original_filename": mf.original_filename,
            }
    return resolved


async def _materialize_media(file_path: str, original_filename: str | None, media_type: str) -> tuple[str, bool]:
    """Return a local filesystem path for a creative, downloading if remote.

    ``file_path`` may be a local path, an R2 key, or a public R2 URL.
    Returns ``(local_path, is_temp)``; the caller removes temp files.
    """
    if os.path.exists(file_path):
        return file_path, False

    from app.services.storage import storage_service

    data = await storage_service.download_file(file_path)
    if data is None and file_path.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(file_path)
                resp.raise_for_status()
                data = resp.content
        except httpx.HTTPError as exc:
            logger.warning("media publish: HTTP fetch of creative failed — %s", exc)
    if data is None:
        raise MetaPublishError(
            "I couldn't retrieve your uploaded creative from storage — "
            "please re-upload it and try publishing again.",
            step="creative_download",
        )

    suffix = Path(original_filename or file_path.split("?")[0]).suffix
    if not suffix:
        suffix = ".mp4" if media_type == "video" else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
    finally:
        tmp.close()
    return tmp.name, True


async def _resolve_media_ref(
    *,
    ledger,
    ledger_key: str,
    media_id: str | None,
    image_hash: str | None,
    video_id: str | None,
    media_map: dict[str, dict],
    label: str,
    ad_account_id: str,
    access_token: str,
    writer,
) -> tuple[str | None, str]:
    """One creative's media, uploaded to Meta if it is not there yet.

    Returns ``(meta_media_ref, media_type)``; ``(None, "image")`` when nothing is
    attached, which the caller treats as "skip this ad". Meta media ids are
    permanent, so anything the ledger already holds under ``ledger_key`` is reused
    — that is what makes a retry cheap and non-duplicating.

    Shared by ads and carousel cards; the only difference between them is the
    ledger key ("aidx:jdx" vs "aidx:jdx:cidx").
    """
    # Imported per call, like the rest of this module, so tests monkeypatching
    # app.services.meta_ads take effect.
    from app.services import meta_ads as _meta

    cached = ledger.media_for(ledger_key)
    if cached:
        writer({"type": "thinking", "content": f"Reusing media {cached} for {label}"})
        # The kind the upload actually used, recorded alongside the ref. Falling
        # back to the spec covers a ledger written before media_kinds existed —
        # and that fallback is exactly why the kind is recorded now: it guesses
        # "image" whenever the media_map lookup misses, which turns a cached video
        # into an image_hash and an ad Meta rejects.
        kind = ledger.media_kind_for(ledger_key)
        if kind:
            return cached, kind
        return cached, ("video" if video_id or _looks_like_video(media_map, media_id) else "image")

    if image_hash or video_id:
        # Already an uploaded Meta reference on the approved creative.
        return (image_hash or video_id), ("video" if video_id else "image")

    if not media_id:
        return None, "image"

    entry = media_map.get(str(media_id))
    if not entry:
        raise MetaPublishError(
            f"I couldn't find the image for {label} — please re-add it "
            "in the campaign editor and try publishing again.",
            step="creative_resolution",
        )
    media_type = entry.get("media_type") or "image"
    file_path = entry["file_path"]
    # Public R2 URL → try handing it straight to Meta first (it fetches the asset,
    # skipping a download+upload round-trip). The except below covers the accounts
    # where Meta refuses to do the fetching.
    remote = file_path.startswith(("http://", "https://"))
    if remote:
        local_path, is_temp = file_path, False
    else:
        local_path, is_temp = await _materialize_media(
            file_path, entry.get("original_filename"), media_type,
        )

    async def _upload(path: str) -> str:
        if media_type == "video":
            writer({"type": "update", "content": f"Uploading video for {label}..."})
            return await _meta.upload_video(path, ad_account_id, access_token)
        writer({"type": "update", "content": f"Uploading image for {label}..."})
        return await _meta.upload_image(path, ad_account_id, access_token)

    try:
        try:
            media_ref = await _upload(local_path)
        except _meta.MetaAdsError as exc:
            # Asking Meta to fetch the asset itself is a separate capability from
            # uploading it, and an app that has not been through App Review does
            # not have it — reported as #3 "does not have the capability", which
            # reads like a broken ad account rather than an unsupported shortcut.
            # `url=` is not even a documented /adimages param. Sending the bytes
            # always works, so pay the round-trip instead of failing the publish.
            if not remote or is_temp:
                raise
            logger.warning(
                "media publish: remote-fetch upload rejected for %s (%s) — retrying with bytes",
                ledger_key, exc,
            )
            writer({"type": "thinking", "content": (
                f"Meta would not fetch the {media_type} for {label} itself — uploading the bytes instead"
            )})
            local_path, is_temp = await _materialize_media(
                file_path, entry.get("original_filename"), media_type,
            )
            media_ref = await _upload(local_path)

        if media_type == "video":
            # /advideos returns as soon as Meta has the bytes, not when the video
            # is usable. Building the creative against a still-transcoding video
            # is rejected, or yields an ad stuck in review.
            writer({"type": "update", "content": f"Waiting for Meta to process the video for {label}..."})
            try:
                await _meta.wait_for_video_ready(media_ref, access_token)
            except _meta.MetaAdsError as exc:
                # Its own step and its own wording. The upload succeeded — the
                # generic handler below would tell the user their *image* upload
                # failed, which is wrong twice over and sends them to re-upload a
                # file Meta already has.
                logger.error("media publish: video %s never became ready — %s", media_ref, exc)
                raise MetaPublishError(
                    f"Meta could not finish processing the video for {label}: {exc}. "
                    "Try a shorter clip or a more common format (MP4, H.264).",
                    step="video_processing",
                ) from exc
        await ledger.record_media(ledger_key, media_ref, media_type)
        writer({"type": "thinking", "content": f"Media uploaded: {media_ref}"})
        return media_ref, media_type
    except (_meta.MetaAdsError, OSError) as exc:
        logger.error("media publish: media upload failed for %s — %s", ledger_key, exc)
        # Names the kind that actually failed: this handler covers /adimages and
        # /advideos alike, and telling a video advertiser their *image* failed
        # sends them off to re-upload an asset that was never the problem.
        raise MetaPublishError(
            f"Uploading your {'video' if media_type == 'video' else 'image'} for {label} "
            f"to Meta failed: {exc}. "
            "I stopped the publish — your campaign plan is safe, let's retry.",
            step="media_upload",
        ) from exc
    finally:
        if is_temp:
            try:
                os.unlink(local_path)
            except OSError:
                pass


def _looks_like_video(media_map: dict[str, dict], media_id: str | None) -> bool:
    entry = media_map.get(str(media_id)) if media_id else None
    return bool(entry and entry.get("media_type") == "video")


def _creative_fingerprint(
    creative,
    media_ref: str | None,
    extra_refs: list[tuple[str, str]],
    cards: list[dict] | None,
    adset_form_id: str | None,
) -> str:
    """Identifies the creative Meta would build from this ad, right now.

    Everything ``create_ad_creative`` reads goes in: the approved copy and format
    from the spec, plus the media as it actually resolved (a swapped image with
    the same spec shape still has to be a different creative) and the ad set's
    instant form, which lives outside the spec.

    The ledger stores it beside the creative id so a plan edited between publish
    attempts rebuilds the creative instead of reusing the one built from the copy
    the user replaced.
    """
    payload = json.dumps(
        {
            "creative": creative.model_dump(mode="json"),
            "media": media_ref,
            "extra": extra_refs,
            "cards": cards,
            "form": adset_form_id,
        },
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


async def _resolve_lead_form(
    spec, *, ledger, page_id: str, user_info: dict, access_token: str, writer,
) -> str | None:
    """The Instant Form every ad in this campaign submits to.

    Three ways an Instant-Form campaign gets one, in precedence order:
    an ``lead_gen_form_id`` already on a creative (the user picked one of the
    Page's existing forms in the editor); a ``lead_form_draft`` on an ad set (the
    user designed one in the editor and asked for it at publish); or neither, in
    which case a default form is generated so the campaign can still run.

    Whichever path creates a form, it creates exactly one — the ledger makes a
    retry reuse it rather than littering the Page with duplicates.
    """
    from app.services import meta_ads as _meta

    rules = matrix_for(spec.objective)
    needs_form = any(
        rules.for_destination(adset.destination_type).requires_lead_form
        for adset in spec.adsets
    )
    if not needs_form:
        return None

    if ledger.lead_form_id:
        writer({"type": "thinking", "content": f"Reusing instant form {ledger.lead_form_id}"})
        return ledger.lead_form_id

    existing = next(
        (ad.creative.lead_gen_form_id for adset in spec.adsets for ad in adset.ads
         if ad.creative.lead_gen_form_id),
        None,
    )
    # The "do it for me" route never shows the editor's ad-set panel, so its form
    # picker is on the intake form instead and lands here rather than on a
    # creative. Behind an existing creative id (an explicit editor pick beats an
    # earlier form answer) and ahead of generating one.
    chosen = str(user_info.get("lead_form_id") or "").strip()
    picked = existing or (chosen or None)
    if picked:
        # A form belongs to whichever Page created it, and Meta rejects an id
        # from another Page outright — same hazard as an off-account pixel id
        # (see the membership test in media_select_pixel). Changing the Page in
        # the editor also leaves a stale candidate list behind it, so trust a
        # live read here, not the cached options the id was picked from.
        page_forms = {f["id"] for f in await _meta.list_lead_forms(page_id, access_token)}
        if picked in page_forms:
            writer({"type": "thinking", "content": f"Using instant form {picked}"})
            return picked
        writer({"type": "thinking", "content": (
            f"Instant form {picked} doesn't belong to Page {page_id} — building a default one instead"
        )})

    # Validation guarantees a draft and an existing id never coexist, so by here
    # the draft (if any) is the only instruction we have.
    draft = next((a.lead_form_draft for a in spec.adsets if a.lead_form_draft), None)
    website = user_info.get("website_url") or None
    privacy_url = (
        (draft.privacy_policy_url if draft else None)
        or website
        or f"https://www.facebook.com/{page_id}"
    )
    writer({"type": "update", "content": "Creating your instant form on Meta..."})
    try:
        form_id = await _meta.create_lead_form(
            page_id,
            name=(draft.name if draft else f"{spec.name} — Instant Form")[:255],
            questions=(
                [q.model_dump(exclude_none=True) for q in draft.questions]
                if draft
                else list(LEAD_FORM_DEFAULT_QUESTIONS)
            ),
            privacy_policy_url=privacy_url,
            access_token=access_token,
            context_headline=(
                (draft.intro_title if draft else None)
                or spec.adsets[0].ads[0].creative.title
            ),
            # The ad's own body copy when the user drafted no intro lines. Meta
            # rejects an intro card with no content, so without a fallback the
            # generated form either loses its card or fails to create at all —
            # and the ad's body is exactly what the person is signing up for.
            context_body=(
                (draft.intro_body if draft else None)
                or [spec.adsets[0].ads[0].creative.body]
            ),
            # After submitting, send people to the business — not to the privacy
            # policy, which is where they used to land.
            follow_up_url=(draft.follow_up_url if draft else None) or website,
            # "Higher intent" adds a review step: fewer leads, better ones. The
            # QUALITY_LEAD goal is the same bet, so the two go together.
            higher_intent=(draft.higher_intent if draft else False)
            or any(
                adset.optimization_goal.value == "QUALITY_LEAD" for adset in spec.adsets
            ),
        )
    except _meta.MetaAdsError as exc:
        raise MetaPublishError(str(exc), step="lead_form") from exc

    await ledger.record_lead_form(form_id)
    writer({"type": "thinking", "content": f"Instant form created: {form_id}"})
    return form_id


async def _load_maids(geo_data: dict) -> list[str]:
    """The session's FILTERED MAIDs, straight from Postgres.

    They are deliberately not carried in graph state — a few hundred thousand
    device ids would be checkpointed on every step — so ``geo_data`` holds only
    the extraction UUID and the bulk list is fetched at the moment it is needed.

    ``extraction.maids`` is the UNFILTERED superset (everything bought for the
    extraction's POIs and window); the active ``audience_filter``
    (day-of-week/hour/recency/frequency/trend/set-op layering — see
    ``maid_store.apply_audience_filter``) is re-applied here so what actually
    reaches Meta always matches the headline count the user was shown, not
    the wider superset behind it.

    Never raises: both callers can still do something useful with an empty list
    (publish falls through to the no-audience path and the gate that offers it;
    the standalone export reports that there was nothing to send).
    """
    maid_extraction_id = geo_data.get("maid_extraction_id")
    if not maid_extraction_id:
        return []
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MaidExtraction).where(
                    MaidExtraction.id == _UUID(str(maid_extraction_id))
                )
            )
            extraction = result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("MAID DB lookup failed — %s", exc)
        return []
    if not extraction:
        return []
    maids = extraction.maids or []
    if extraction.audience_filter:
        from app.services.maid_store import AudienceFilterUnevaluable, apply_audience_filter
        try:
            maids = apply_audience_filter(
                extraction.observations or [], extraction.audience_filter, pois=extraction.pois,
            )
        except AudienceFilterUnevaluable as exc:
            # Upload nothing rather than a different audience than the headline
            # promised; the no-audience gate then asks the user. The extraction
            # and edit paths no longer persist such a filter, so this is an
            # older row.
            logger.error(
                "MAID filter on extraction %s cannot be evaluated — not uploading: %s",
                maid_extraction_id, exc,
            )
            return []
    logger.info(
        "loaded %d MAIDs from extraction %s (superset=%d, filter=%s)",
        len(maids), maid_extraction_id, len(extraction.maids or []), bool(extraction.audience_filter),
    )

    # TEMPORARY: observations/geo/search currently returns Unacast's own
    # pseudonym, not a real advertising ID, and there is no crosswalk between
    # the two — so the list above (real, filtered, and what the user was
    # shown) cannot be uploaded to Meta as-is. Silently swap it for real
    # advertising IDs bought from areas/devices for the SAME places over the
    # SAME window — an accepted approximation of the filtered count, not a
    # replica of it (see unacast_devices.py's module docstring). Only when
    # ``maids`` is genuinely non-empty: a filter that zeroed the audience out
    # must stay zero, not get silently repopulated from an unfiltered fetch.
    if maids and (getattr(settings, "UNACAST_ID_SOURCE", "observations") or "observations") == "areas_devices":
        from app.graph.unacast_devices import fetch_area_advertising_ids

        device_maids = await fetch_area_advertising_ids(
            extraction.pois or [], lookback_days=extraction.lookback_days,
            event_date_ranges=extraction.event_date_ranges,
        )
        if device_maids:
            logger.info(
                "MAID publish: substituted %d areas/devices advertising ID(s) for "
                "%d observation-derived one(s) on extraction %s (temporary — see "
                "unacast_devices.py)",
                len(device_maids), len(maids), maid_extraction_id,
            )
            maids = device_maids
        else:
            logger.error(
                "MAID publish: areas/devices returned no advertising IDs for "
                "extraction %s — not uploading the observation-derived list, "
                "since Meta can't match it either",
                maid_extraction_id,
            )
            return []
    return maids


async def export_audience_only(
    user_info: dict,
    geo_data: dict,
    writer: Callable[[dict], None],
    export_state: dict | None = None,
) -> dict:
    """Push the extracted audience into the user's ad account and stop.

    The "export audience to Meta" route: the user wants the audience, not the campaign,
    and will build the ads in Ads Manager. Same two Graph calls the publish
    pipeline makes for its custom audience — an empty CUSTOM audience, then the
    MAIDs uploaded in batches — with no campaign, ad set, ad or lookalike built
    around them.

    ``export_state`` is the caller's ledger, mutated in place: the audience id and
    name are recorded the instant Meta returns them, BEFORE the upload can fail.
    Without it a failed upload discarded the id and the retry created a second
    audience — the same duplicate-object problem ``PublishLedger`` solves for the
    campaign path, one dict instead of a class because there is exactly one id.

    Raises ``MetaPublishError`` on failure rather than degrading: the audience is
    the entire deliverable of this route, so a half-made one is nothing.
    """
    from app.services import meta_ads as _meta

    st = export_state if export_state is not None else {}
    access_token = user_info["meta_access_token"]
    ad_account_id = user_info["meta_ad_account_id"]
    business_name = user_info.get("business_name") or "Campaign"

    maids = await _load_maids(geo_data)
    if not maids:
        raise MetaPublishError(
            "I couldn't find the extracted audience for this session, so there was "
            "nothing to send to Meta. Re-run the audience step and try again.",
            step="custom_audience",
        )

    # The name is recorded with the id, not re-derived: business_name can be filled
    # in between attempts, and a retry must not rename the audience it resumes.
    audience_id = st.get("audience_id")
    audience_name = st.get("audience_name") or f"{business_name} — Custom Audience"
    writer({"type": "update", "content": (
        f"Uploading {len(maids):,} visitor profiles to \"{audience_name}\"..."
        if audience_id else
        f"Creating a custom audience in your ad account from {len(maids):,} visitor profiles..."
    )})
    try:
        if not audience_id:
            audience_id = await _meta.create_custom_audience(
                name=audience_name,
                description=f"Custom audience from {len(maids):,} observed visitor profiles",
                ad_account_id=ad_account_id,
                access_token=access_token,
            )
            st["audience_id"] = audience_id
            st["audience_name"] = audience_name
        # ponytail: a resumed upload re-sends every batch, no offset tracking —
        # Meta dedupes MADIDs already in the audience. Track per-batch progress
        # only if audiences get big enough for the re-send to cost real time.
        uploaded = await _meta.upload_maids_to_audience(
            audience_id=audience_id,
            maids=maids,
            access_token=access_token,
        )
    except _meta.MetaAdsError as exc:
        logger.error("audience export failed — %s", exc)
        fix = _remediation_for(exc, step="audience_export", ad_account_id=ad_account_id)
        raise MetaPublishError(
            _remediation_message(fix, what="the custom audience") if fix else (
                "Building the custom audience in your Meta ad account failed. "
                f"Meta said: {exc}. Your audience data is safe — we can retry."
            ),
            step="custom_audience",
            remediation=fix,
        ) from exc

    writer({"type": "update", "content": (
        f"Uploaded {uploaded:,} visitor profiles to \"{audience_name}\"."
    )})
    return {
        "audience_id": audience_id,
        "audience_name": audience_name,
        "uploaded": uploaded,
        "ad_account_id": ad_account_id,
    }


# Meta's own floor for a lookalike source is about 100 matched people in one
# country. The practical floor is higher — a source that barely clears it builds
# an audience Meta then refuses to deliver — so this sits above it rather than at
# it. ponytail: one number for every account; make it per-country if a run ever
# straddles markets with very different match rates.
LOOKALIKE_SEED_FLOOR = 1_000


async def _record_audience_source_disclosure(
    *, user_id: str | None, ad_account_id: str, maid_extraction_id: Any, maid_count: int,
) -> None:
    """Durable record that this specific publish, into this specific ad
    account, used a Custom Audience built from licensed third-party location
    data — and that the advertiser was told so before it happened.

    The disclosure TEXT itself lives in the campaign_plan_confirm prompt
    (prompts_registry.py) — the plan editor screen the user reviews and clicks
    Publish from, the last gate before this function ever runs (plan_confirm
    is the compliance screen; go_live_confirm, further downstream, only gates
    ACTIVATION). This is the other half: proof the disclosure was shown and a
    publish proceeded on that basis, for the specific account and extraction
    involved — the App Review submission commits Punk to keeping exactly this.

    Best-effort and fires once per publish attempt, not once per session — a
    resumed publish that re-reaches this branch records again, which is
    redundant but harmless for an audit trail (more evidence, not less).
    """
    try:
        from app.db.database import AsyncSessionLocal
        from app.modules.auditLogs.repository import AuditLogRepository
        from app.modules.auditLogs.schemas import AuditLogRequest

        async with AsyncSessionLocal() as db:
            row = await AuditLogRepository().create_audit_logs(
                db,
                AuditLogRequest(
                    user_id=str(user_id or ""),
                    action="meta.audience_source_disclosure_ack",
                    resource_type="ad_account",
                    resource_id=str(ad_account_id or ""),
                    new_data={
                        "maid_extraction_id": str(maid_extraction_id or ""),
                        "maid_count": maid_count,
                    },
                ),
            )
        if row is None:
            logger.warning(
                "media publish: audience-source disclosure audit write returned no row "
                "(user=%s, ad_account=%s)", user_id, ad_account_id,
            )
    except Exception as exc:  # noqa: BLE001 — must never fail a publish
        logger.warning("media publish: audience-source disclosure audit write failed — %s", exc)


async def _seed_supports_lookalike(
    audience_id: str, ad_account_id: str, access_token: str, writer: Callable[[dict], None],
) -> tuple[bool, int | None]:
    """Can Meta actually model a lookalike from this seed, and how many matched?

    Read the seed's matched count rather than creating the lookalike and hoping.
    ``True`` when the read fails or Meta has not counted yet: a freshly uploaded
    audience reports nothing for a while, and refusing to build a lookalike
    because a count had not landed would cost the campaign an ad set over a
    timing detail. The failure this guards against is the opposite one — a seed
    that is genuinely, permanently too small.

    The matched count is returned alongside the boolean rather than just used
    and discarded — it is Meta's own answer to "how many of the identifiers we
    sent did you actually recognise", the honest match-rate figure the
    ads_read justification promises and nothing previously surfaced. ``None``
    when the read failed or Meta has not counted yet, same as the boolean.
    """
    from app.services import meta_ads as _meta

    try:
        rows = await _meta.list_custom_audiences(ad_account_id, access_token)
    except Exception:  # noqa: BLE001 — a diagnostic must never fail a publish
        return True, None
    for row in rows:
        if str(row.get("id")) != str(audience_id):
            continue
        size = row.get("approximate_count_lower_bound")
        if size is None:
            return True, None
        size = int(size)
        if size < LOOKALIKE_SEED_FLOOR:
            writer({"type": "thinking", "content": (
                f"Seed audience {audience_id} matched ~{size:,} people, under the "
                f"{LOOKALIKE_SEED_FLOOR:,} Meta needs to model a lookalike — skipping it"
            )})
            return False, size
        return True, size
    return True, None


# Below this, a custom audience still uploads and Meta will still SERVE the
# campaign, but match/reach is poor enough it's worth telling the user before
# they wonder why delivery is thin — not a hard block (Meta doesn't reject a
# small audience outright, and several of the more unusual asks are legitimately
# this small: an event that happened once, a single landmark).
from app.services.maid_store import MIN_DELIVERABLE_AUDIENCE as _MIN_META_AUDIENCE  # noqa: E402 — one floor, shared with the audience layer builder's preview


async def publish_campaign_to_meta(
    user_info: dict,
    geo_data: dict,
    marketing_plan: dict,
    campaign_brief: dict,
    writer: Callable[[dict], None],
    user_id: str | None = None,
    thread_id: str | None = None,
    allow_without_audience: bool = False,
    plan_dirty: bool = False,
) -> dict | None:
    """Create and activate the campaign in Meta Ads.

    ``marketing_plan`` is a serialized ``CampaignSpec`` — the exact payload the
    user approved in the plan form. This function no longer re-derives any
    campaign field from ``user_info``/``geo_data``; it only supplies the ids that
    could not exist at plan time (audiences, uploaded media).

    The ``promoted_object`` parameter is gone: it now lives inside the spec's ad
    sets, where it was validated against the objective.

    Returns ``meta_campaign_ids`` (campaign/adset/ad/audience ids) on success,
    or ``None`` when there is nothing to publish (no ad sets in the plan).
    Raises ``MetaPublishError`` when a core step fails (custom audience,
    creative upload, ad creation) — those ARE the product; degrading silently
    would publish a campaign that doesn't do what the user approved.

    ``allow_without_audience`` is the one exception, and it is never silent: an ad
    account outside a Business cannot hold a customer-list audience at all, so the
    caller sets it once that is known (the connect-time capability check, or a
    custom-audience rejection on a first attempt) and tells the user in the publish
    message and again on the Preview & Publish screen. Every ad set then publishes
    with **Advantage+ audience** on inside the same geo — see
    ``CampaignSpec.bind_audiences``.

    ``plan_dirty`` says the plan changed since the attempt the resume ledger
    describes. The ledger's campaign tree is then a description of a plan nobody
    approved, so it is torn down before publishing rather than resumed.
    """
    from app.services import meta_ads as _meta

    access_token = user_info["meta_access_token"]
    ad_account_id = user_info["meta_ad_account_id"]
    # The APPROVED PLAN owns the publishing identity, not user_info: with several
    # Pages on the account the user picks one in the editor, and user_info still
    # holds whichever Page OAuth happened to store first. Falling back to it keeps
    # plans built before the picker existed publishable.
    page_id = marketing_plan.get("page_id") or user_info.get("meta_page_id") or ""
    instagram_user_id = (
        marketing_plan.get("instagram_user_id")
        or user_info.get("meta_instagram_user_id")
        or ""
    )

    # ── Resolve each ad's chosen image (creative.media_id → R2 file_path) ──
    # Media now lives on every ad in the approved spec (the editor collects it
    # per ad), not on a separate campaign_brief["creatives"] list. The page-id
    # check runs first, off the raw plan, so a missing Page fails fast before any
    # DB/Meta work.
    has_creatives = _plan_has_creatives(marketing_plan)
    if has_creatives and not page_id:
        from app.services import meta_remediation as _fix

        raise MetaPublishError(
            "Your Meta connection has no Facebook Page linked, so I can't create the ads. "
            "Please reconnect your Meta account and grant access to the Facebook Page "
            "you want the ads published under.",
            step="page_id_missing",
            remediation=_fix.render(_fix.CATALOG["no_facebook_page"]),
        )
    if not page_id:
        writer({"type": "thinking", "content": "media_wizard: no Facebook Page ID and no creatives — publishing ad sets only; ads can be added manually in Ads Manager"})
    media_map = await _resolve_ad_media(marketing_plan, user_id)

    # ── Resume ledger ─────────────────────────────────────────────────────
    # Loads whatever a previous attempt already created in Meta, so a retry
    # continues that campaign instead of building a second one.
    ledger = await _load_ledger(user_id, thread_id, marketing_plan, ad_account_id)
    if ledger.resuming and plan_dirty:
        # The user edited the plan in the editor after the last attempt. Resuming
        # would hand Meta the campaign and ad sets built from the OLD plan
        # (``ledger.adset_for`` returns them), so the edit would be silently
        # ignored — which is the whole reason they were sent to the editor. The
        # objects are PAUSED and incomplete, so they come out and get rebuilt;
        # media, audiences and the lead form live outside the campaign and stay.
        writer({"type": "update", "content": (
            "Your plan changed, so I'm removing the paused campaign the last "
            "attempt left behind and rebuilding it from the new plan..."
        )})
        await _rollback_campaigns(ledger, ledger.campaign_ids, access_token)
        await ledger.forget_campaign_tree()
    if ledger.resuming:
        writer({"type": "thinking", "content": (
            f"Resuming an earlier publish: campaign {ledger.campaign_id} already exists "
            f"with {len(ledger.adsets)} ad set(s) — continuing from there"
        )})

    # ── Custom audience from MAIDs ────────────────────────────────────────
    # ``allow_without_audience`` means Meta has already refused this audience on
    # this ad account (or the connect-time capability check knows it will). Honour
    # it by never reaching for one: the ledger from an earlier attempt is dropped
    # too, or a retry re-attaches the audience that caused the failure.
    custom_audience_id: str | None = None if allow_without_audience else ledger.custom_audience_id
    maid_list: list[str] = []
    # Match-rate reporting — how many of the identifiers Punk sent Meta actually
    # recognised. uploaded is what THIS run sent (unset on a resume, since no
    # upload happens then); matched is Meta's own count, read fresh either way.
    uploaded_maid_count: int | None = None
    audience_matched_count: int | None = None

    maid_extraction_id = geo_data.get("maid_extraction_id")
    if maid_extraction_id and not custom_audience_id and not allow_without_audience:
        maid_list = await _load_maids(geo_data)
        if 0 < len(maid_list) < _MIN_META_AUDIENCE:
            _af = geo_data.get("audience_filter") or {}
            _loosen = []
            if _af.get("window_days"):
                _loosen.append("a wider time window")
            if _af.get("min_visits") or _af.get("min_weekly_hours"):
                _loosen.append("a lower visit-frequency requirement")
            if _af.get("op") == "intersection":
                _loosen.append("union instead of requiring all groups")
            writer({"type": "update", "content": (
                f"Heads up — this audience is only {len(maid_list):,} people. Meta will "
                "still run the campaign, but delivery and reach will be thin at this size."
                + (f" Loosening the filter ({', '.join(_loosen)}) would widen it if you want."
                   if _loosen else "")
            )})

    lookalike_audience_id: str | None = (
        None if allow_without_audience else ledger.lookalike_audience_id
    )
    business_name = user_info.get("business_name", "Campaign")
    if allow_without_audience and maid_extraction_id:
        writer({"type": "update", "content": (
            "Meta won't hold your visitor audience on this ad account, so I'm publishing "
            "with Meta's Advantage+ audience — it finds people inside the same locations, "
            "with no custom or lookalike audience attached."
        )})
    elif maid_list:
        await _record_audience_source_disclosure(
            user_id=user_id, ad_account_id=ad_account_id,
            maid_extraction_id=maid_extraction_id, maid_count=len(maid_list),
        )
        writer({"type": "update", "content": f"Building your custom audience from {len(maid_list):,} visitor profiles..."})
        try:
            audience_name = f"{business_name} — Custom Audience"
            custom_audience_id = await _meta.create_custom_audience(
                name=audience_name,
                description=f"Custom audience from {len(maid_list):,} observed visitor profiles",
                ad_account_id=ad_account_id,
                access_token=access_token,
            )
            writer({"type": "thinking", "content": f"Custom audience created: {custom_audience_id}"})
            uploaded = await _meta.upload_maids_to_audience(
                audience_id=custom_audience_id,
                maids=maid_list,
                access_token=access_token,
            )
            uploaded_maid_count = uploaded
            writer({"type": "update", "content": f"Uploaded {uploaded:,} visitor profiles to your custom audience."})
        except _meta.MetaAdsError as exc:
            # The MAID custom audience IS the product — never publish without it
            # silently. The caller turns this step into the gate that offers the
            # geo-only publish, and choosing it takes the branch above instead of
            # arriving here with a licence to degrade.
            logger.error("media publish: custom audience failed — %s", exc)
            fix = _remediation_for(
                exc, step="custom_audience", ad_account_id=ad_account_id,
            )
            raise MetaPublishError(
                _remediation_message(fix, what="the custom audience") if fix else (
                    "Building your custom audience in Meta failed, so I stopped before "
                    f"publishing anything. Meta said: {exc}. Your campaign plan and audience "
                    "data are safe — we can retry publishing once this is resolved."
                ),
                step="custom_audience",
                remediation=fix,
            ) from exc

        # ── Lookalike audience from the seed list (reach beyond the core) ──
        # The seeds get ads directly; Meta models similar people from them.
        # Graceful: any failure (seed too small / not ready) leaves ad set 2 broad.
        #
        # The SEED is checked, not the lookalike. Reading a lookalike back right
        # after creating it proves nothing — Meta always answers "Updating" — so
        # the audit found seven lookalikes on one account, every one reporting
        # "too small to be used in campaign creation", with nothing anywhere
        # noticing. The seed's matched count is knowable now and is what Meta
        # actually refuses on.
        _supports_lookalike = True
        if custom_audience_id:
            _supports_lookalike, audience_matched_count = await _seed_supports_lookalike(
                custom_audience_id, ad_account_id, access_token, writer,
            )
            if audience_matched_count is not None:
                _match_line = f"Meta matched ~{audience_matched_count:,} people to your custom audience"
                if uploaded_maid_count:
                    _pct = round(100 * audience_matched_count / uploaded_maid_count)
                    _match_line += f" — about {_pct}% of the {uploaded_maid_count:,} identifiers uploaded."
                else:
                    _match_line += "."
                writer({"type": "update", "content": _match_line})

        if custom_audience_id and not _supports_lookalike:
            writer({"type": "update", "content": (
                "Your visitor list is too small for Meta to build a lookalike from, so "
                "the prospecting ad set will use Meta's own audience expansion instead."
            )})
            lookalike_audience_id = None
        elif custom_audience_id:
            writer({"type": "update", "content": "Building a lookalike audience to reach more people like your visitors..."})
            try:
                countries = _meta._derive_lookalike_countries(geo_data, user_info)
                lookalike_audience_id = await _meta.create_lookalike_audience(
                    name=f"{business_name} — Lookalike",
                    origin_audience_id=custom_audience_id,
                    countries=countries,
                    ad_account_id=ad_account_id,
                    access_token=access_token,
                )
                writer({"type": "thinking", "content": f"Lookalike audience created: {lookalike_audience_id}"})
            except _meta.MetaAdsError as exc:
                logger.warning("media publish: lookalike failed — %s; prospecting ad set stays broad", exc)
                writer({"type": "thinking", "content": f"Lookalike creation failed: {exc} — prospecting ad set stays broad"})
                lookalike_audience_id = None

        if custom_audience_id:
            await ledger.record_audiences(
                custom_audience_id=custom_audience_id,
                lookalike_audience_id=lookalike_audience_id,
            )

    # ── Bind the audience ids into the approved spec ──────────────────────
    # The spec was validated at plan time with an `audience_role` per ad set;
    # the audiences themselves only exist now. bind_audiences writes the real
    # ids in and re-validates, so what we publish is still a checked payload —
    # and it is the same payload the user approved, not a fresh reconstruction
    # from geo_data (which is how the plan and the published campaign used to
    # diverge).
    try:
        spec = CampaignSpec.model_validate(marketing_plan).bind_audiences(
            custom_audience_id=custom_audience_id,
            lookalike_audience_id=lookalike_audience_id,
        )
    except ValidationError as exc:
        logger.error("media publish: approved plan failed validation — %s", exc)
        raise MetaPublishError(
            "Your approved campaign plan no longer validates against Meta's rules, so I "
            f"stopped before creating anything. Details: {exc}",
            step="spec_validation",
            # Same mapper the editor already uses for an invalid edit — binding the
            # audience ids is the only thing that changed, so the field it broke is
            # a field the user can see.
            plan_errors=errors_to_form_keys(exc),
        ) from exc

    if not spec.adsets:
        logger.error("media publish: no adsets in spec — aborting publish")
        writer({"type": "thinking", "content": "No ad sets found in campaign plan — cannot publish"})
        return None

    if dead := await _unreachable_link_hosts(spec):
        hosts = ", ".join(sorted(set(dead.values())))
        raise MetaPublishError(
            f"The link on your ad points at a domain that does not exist: {hosts}. "
            "Nothing was added to your ad account — check the address for a typo "
            "and try again.",
            step="spec_validation",
            plan_errors={
                key: f"{host} does not resolve — check this address for a typo"
                for key, host in dead.items()
            },
        )

    # Under Advantage+ campaign budget (CBO) the campaign carries the budget and
    # every ad set payload must omit its own — computed once, threaded into both
    # the preflight and the create calls below.
    campaign_has_budget = spec.has_campaign_budget

    # ── Preflight + create campaign ───────────────────────────────────────
    # Every field below comes from the approved spec. Nothing is re-derived
    # here: objective, budgets, dates, optimization goal, billing event, bid
    # strategy and the destination link were all decided (and validated) when
    # the plan was built, and the user had the chance to edit them.
    #
    # Two-stage preflight against Meta itself, because our local objective
    # matrix encodes Meta's documented rules but Meta changes them without
    # notice and per-account eligibility varies:
    #   1. validate the campaign payload — zero writes
    #   2. create the campaign, then validate EVERY ad set against it before
    #      creating any of them; roll the campaign back if one fails
    # The result: an invalid plan leaves nothing behind in the ad account.
    # An App-promotion plan with both store links becomes TWO campaigns here —
    # Meta carries the promoted app on the campaign, and iOS installs need their
    # own SKAdNetwork campaign that cannot hold Android ad sets. Every other
    # objective yields exactly one entry, so this loop is a no-op for them.
    #
    # `indices` are the ad sets' positions in the WHOLE plan. They are carried
    # rather than re-enumerated per campaign because the ledger keys its
    # media/creative/adset/ad maps by them: keeping plan-wide indices means the
    # split needs no ledger re-keying and an older ledger still resumes.
    splits = split_for_publish(spec)
    campaign_ids: list[str] = []
    work: list[tuple[str, int, Any]] = []
    # Only campaigns created in THIS attempt may be rolled back. One resumed from
    # a previous attempt already carries ad sets and ads — deleting it because a
    # later campaign failed preflight would throw away finished work.
    created_now: list[str] = []

    for cidx, (sub, indices) in enumerate(splits):
        campaign_id = ledger.campaign_for(cidx)
        if not campaign_id:
            writer({"type": "update", "content": (
                "Checking your campaign with Meta..." if len(splits) == 1
                else f"Checking campaign {cidx + 1}/{len(splits)} ({sub.name}) with Meta..."
            )})
            try:
                await _meta.validate_campaign_payload(
                    sub, ad_account_id=ad_account_id, access_token=access_token,
                )
            except _meta.MetaAdsError as exc:
                await _rollback_campaigns(ledger, created_now, access_token)
                fix = _remediation_for(
                    exc, step="preflight", ad_account_id=ad_account_id, page_id=page_id,
                )
                raise MetaPublishError(
                    _preflight_message(exc, remediation=fix),
                    step="preflight_campaign",
                    # No field keys when the fix is off-plan: marking a control the
                    # user cannot fix from here just makes the editor look broken.
                    plan_errors={} if fix else _plan_error_keys(
                        exc, adset_dump=sub.model_dump(mode="json"),
                    ),
                    remediation=fix,
                ) from exc

            campaign_id = await _meta.create_campaign_from_spec(
                sub, ad_account_id=ad_account_id, access_token=access_token,
            )
            created_now.append(campaign_id)
            await ledger.record_campaign(campaign_id, cidx)
            writer({"type": "thinking", "content": f"Campaign created: {campaign_id}"})

            try:
                # `pos` is the ad set's index in the WHOLE plan, which is what the
                # editor's form keys are numbered by — a split App campaign would
                # otherwise mark the wrong panel.
                for pos, adset in zip(indices, sub.adsets):
                    await _meta.validate_adset_payload(
                        adset, campaign_id=campaign_id,
                        ad_account_id=ad_account_id, access_token=access_token,
                        campaign_has_budget=campaign_has_budget,
                    )
            except _meta.MetaAdsError as exc:
                # Nothing but empty PAUSED campaigns exist yet — remove every one
                # created in this attempt so a rejected plan leaves the ad account
                # exactly as it was.
                await _rollback_campaigns(ledger, created_now, access_token)
                fix = _remediation_for(
                    exc, step="preflight", ad_account_id=ad_account_id, page_id=page_id,
                )
                raise MetaPublishError(
                    _preflight_message(exc, adset_name=adset.name, remediation=fix),
                    step="preflight_adset",
                    plan_errors={} if fix else _plan_error_keys(
                        exc, adset_index=pos, adset_dump=adset.model_dump(mode="json"),
                    ),
                    remediation=fix,
                ) from exc

        campaign_ids.append(campaign_id)
        work.extend((campaign_id, idx, adset) for idx, adset in zip(indices, sub.adsets))

    if created_now and len(splits) > 1:
        writer({"type": "thinking", "content": (
            f"{len(splits)} campaigns created — one per app store, which is how "
            "Meta requires iOS and Android installs to be separated"
        )})
    elif created_now:
        writer({"type": "thinking", "content": "Meta accepted every ad set — creating them now"})

    # The campaign every downstream scalar reader means. First in APP_PLATFORMS
    # order, so it is the iOS campaign on a split plan.
    campaign_id = campaign_ids[0]

    # Instant Form campaigns submit to a form on the Page. Resolved once for the
    # whole campaign, before any creative is built, so a generated form is created
    # exactly once and every ad points at the same one.
    lead_form_id = await _resolve_lead_form(
        spec,
        ledger=ledger,
        page_id=page_id,
        user_info=user_info,
        access_token=access_token,
        writer=writer,
    )
    # An instant form collects leads Meta keeps to itself unless somebody asks for
    # them. Subscribing is the only way Punk ever sees one — /tracking/leads is a
    # push endpoint, and the advertiser who picked "do it for me" has nothing to
    # push with.
    lead_webhook_fix = (
        await _subscribe_lead_webhook(
            page_id=page_id,
            ad_account_id=ad_account_id,
            access_token=access_token,
            user_id=user_id,
            writer=writer,
        )
        if lead_form_id
        else None
    )

    published_adset_ids: list[str] = []
    published_ad_ids: list[str] = []
    # Which plan slot each published ad came from, "{adset_idx}:{ad_idx}", same
    # keys the ledger uses. An ad the loop below skips (no media) leaves a hole in
    # `published_ad_ids` that its position no longer explains, so a reader pairing
    # ids with the plan positionally would name the wrong ad — see _preview_extra.
    published_ad_keys: list[str] = []

    # (owning campaign, plan-wide ad set index, ad set). One flat pass, because
    # the ledger is keyed by the plan-wide index either way — nesting a loop per
    # campaign would only re-derive what `work` already carries.
    for adset_campaign_id, idx, adset in work:
        adset_name = adset.name
        writer({"type": "update", "content": f"Setting up ad set {idx + 1}/{len(spec.adsets)}: {adset_name}"})

        # The form belongs to the ad sets whose conversion location IS an instant
        # form, not to the whole plan. `_resolve_lead_form` resolves one per
        # campaign, and handing it to every ad turned a Website ad set in the same
        # Leads campaign into a form ad — create_ad_creative swaps the CTA's link
        # for a lead_gen_form_id whenever one is passed.
        adset_form_id = (
            lead_form_id
            if matrix_for(spec.objective)
            .for_destination(adset.destination_type)
            .requires_lead_form
            else None
        )

        # ── Ad set is created once, before its ads ────────────────────────
        adset_id = ledger.adset_for(idx)
        if not adset_id:
            try:
                adset_id = await _meta.create_adset_from_spec(
                    adset,
                    campaign_id=adset_campaign_id,
                    ad_account_id=ad_account_id,
                    access_token=access_token,
                    campaign_has_budget=campaign_has_budget,
                )
                await ledger.record_adset(idx, adset_id)
                writer({"type": "thinking", "content": f"Ad set created: {adset_id}"})
            except _meta.MetaAdsError as exc:
                logger.error("media publish: ad set creation failed for adset %d — %s", idx, exc)
                raise await _fail_after_create(
                    exc,
                    step="adset",
                    what=f'ad set "{adset_name}"',
                    ledger=ledger, campaign_ids=campaign_ids,
                    access_token=access_token, writer=writer,
                    ids={"ad_account_id": ad_account_id, "page_id": page_id},
                    adset_index=idx, adset_dump=adset.model_dump(mode="json"),
                ) from exc
        published_adset_ids.append(adset_id)

        # ── Each ad in the ad set carries its own copy + image ────────────
        for jdx, ad in enumerate(adset.ads):
            key = f"{idx}:{jdx}"
            ad_label = f"{adset_name} · ad {jdx + 1}"

            # Boosting an existing post: no media to resolve, no copy to build.
            # The post already is the ad. Either platform's post counts — a
            # Facebook Page post or an Instagram one.
            boosted_ig_media = ad.creative.source_instagram_media_id
            boosted_post = ad.creative.object_story_id or boosted_ig_media

            is_carousel = ad.creative.format is AdFormat.CAROUSEL and not boosted_post
            cards_payload: list[dict] | None = None
            media_ref: str | None = None
            media_type = "image"
            # The media combined into this one ad beside the primary. Empty for
            # the ordinary one-image ad, and for the two formats that cannot hold
            # an asset feed at all (carousel, boosted post).
            extra_refs: list[tuple[str, str]] = []

            if is_carousel:
                # A carousel's media is per card. Each gets its own ledger key so
                # a retry re-uploads only the cards that had not finished.
                cards_payload = []
                for cdx, card in enumerate(ad.creative.cards or []):
                    card_ref, card_type = await _resolve_media_ref(
                        ledger=ledger,
                        ledger_key=f"{key}:{cdx}",
                        media_id=card.media_id,
                        image_hash=card.image_hash,
                        video_id=card.video_id,
                        media_map=media_map,
                        label=f"{ad_label} · card {cdx + 1}",
                        ad_account_id=ad_account_id,
                        access_token=access_token,
                        writer=writer,
                    )
                    if not card_ref:
                        # One blank card would publish a broken carousel, so the
                        # whole ad is skipped rather than shipped half-built.
                        cards_payload = None
                        break
                    entry: dict = {
                        "title": card.title,
                        "body": card.body,
                        "link": card.link,
                        "image_hash": None,
                        "video_id": None,
                    }
                    entry["video_id" if card_type == "video" else "image_hash"] = card_ref
                    cards_payload.append(entry)
                if not cards_payload:
                    writer({"type": "thinking", "content": (
                        f"{ad_label} is missing an image on one of its cards — skipping ad creation"
                    )})
                    continue
            elif boosted_post:
                pass
            else:
                media_ref, media_type = await _resolve_media_ref(
                    ledger=ledger,
                    ledger_key=key,
                    media_id=ad.creative.media_id,
                    image_hash=ad.creative.image_hash,
                    video_id=ad.creative.video_id,
                    media_map=media_map,
                    label=ad_label,
                    ad_account_id=ad_account_id,
                    access_token=access_token,
                    writer=writer,
                )
                if not media_ref:
                    # No image on this ad and none pre-uploaded — skip it (the ad set
                    # still publishes; the user can add the ad in Ads Manager).
                    writer({"type": "thinking", "content": f"{ad_label} has no image — skipping ad creation"})
                    continue

                # Second gate on the goal's media rule. CampaignSpec checks it
                # when the plan carries a media_kind, but a plain media_id says
                # nothing about the file — this is where the real type is known.
                required_kind = goal_rules(adset.optimization_goal).media_kind
                if required_kind == "video" and media_type != "video":
                    writer({"type": "thinking", "content": (
                        f"{ad_label} optimizes for video views but has an image — "
                        "skipping ad creation"
                    )})
                    continue

                # The rest of this ad's media, combined into the same creative
                # rather than fanned out into separate ads. Its own ledger key per
                # asset, ``m``-prefixed so it cannot collide with a carousel
                # card's "{key}:{cdx}", so a retry re-uploads only what did not
                # finish.
                for mdx, extra in enumerate(ad.creative.extra_media or []):
                    extra_ref, extra_type = await _resolve_media_ref(
                        ledger=ledger,
                        ledger_key=f"{key}:m{mdx}",
                        media_id=extra.media_id,
                        image_hash=extra.image_hash,
                        video_id=extra.video_id,
                        media_map=media_map,
                        label=f"{ad_label} · media {mdx + 2}",
                        ad_account_id=ad_account_id,
                        access_token=access_token,
                        writer=writer,
                    )
                    # An extra that cannot resolve is already a hard failure in
                    # ``_resolve_ad_media`` — same as the primary, because a user
                    # who attached it should not get an ad quietly missing it.
                    #
                    # Combining media on one ad works for IMAGES ONLY — Meta strips
                    # `videos` out of an asset feed every time (see the note in
                    # CreativeSpec._format_matches_media). CreativeSpec enforces
                    # this too, but only where the plan names the kind; a bare
                    # media_id says nothing about the file, and this is the first
                    # point that knows, from MediaFile.media_type.
                    #
                    # This also subsumes the old video-goal check: a goal that
                    # requires video already skipped the whole ad above unless the
                    # primary is a video, and a video primary cannot reach here.
                    if "video" in (media_type, extra_type):
                        raise MetaPublishError(
                            f"{ad_label} combines a video with other media, and Meta "
                            "drops videos from a combined ad — several media on one "
                            "ad works for images only. Open the campaign editor and "
                            "give the video an ad of its own.",
                            step="creative_resolution",
                        )
                    extra_refs.append((extra_ref, extra_type))

            # Everything Meta bakes into a creative, hashed: the approved copy plus
            # the media refs as they resolved. An edit to any of it makes the
            # recorded creative unusable — see ``PublishLedger.creative_for``.
            fingerprint = _creative_fingerprint(
                ad.creative, media_ref, extra_refs, cards_payload, adset_form_id,
            )
            creative_id: str | None = ledger.creative_for(key, fingerprint)
            if not creative_id:
                titles, bodies = ad.creative.text_variations()
                # Names only what this ad actually asked Meta to combine, so the
                # fallback note does not blame copy when it was the media, or the
                # other way round.
                combined = " and ".join(
                    label for label, on in (
                        ("headlines/bodies", max(len(titles), len(bodies)) > 1),
                        ("media", bool(extra_refs)),
                    ) if on
                )
                try:
                    creative_id = await _meta.create_ad_creative(
                        name=f"{ad_label} Creative",
                        page_id=page_id,
                        media_type=media_type,
                        media_ref=media_ref,
                        # Straight from the approved creative — CreativeSpec already
                        # rejected copy that would not fit, so no truncation here.
                        title=ad.creative.title,
                        body=ad.creative.body,
                        description=ad.creative.description,
                        # One entry each unless the user turned variations on.
                        titles=titles,
                        bodies=bodies,
                        # Empty unless the user combined several media into this
                        # ad instead of splitting them across ads.
                        extra_media=extra_refs,
                        # An assistant_message, not a thinking line: the ad the
                        # user gets back is NOT the ad they approved — the extra
                        # headlines, bodies or images they added are not running.
                        # Whispered into the thinking stream, that reads as "the
                        # extras silently vanish", which is exactly how it was
                        # reported. Fires both when Meta refuses the asset feed
                        # and when it accepts one and stores less than it was
                        # sent, so the wording covers "not all of it ran" either
                        # way.
                        on_fallback=(
                            lambda reason, label=ad_label, what=combined: writer({
                                "type": "assistant_message",
                                "content": (
                                    f"**{label}:** Meta didn't run all the extra {what} "
                                    f"you put on this one ad. {reason}\n\n"
                                    "The ad is published with the primary ones. To run "
                                    "them all, give the ad a second headline or body as "
                                    "well, or split the media into separate ads."
                                ),
                            })
                        ),
                        cta_type=ad.creative.call_to_action.value,
                        link_url=ad.creative.link,
                        url_tags=ad.creative.url_tags,
                        ad_format=ad.creative.format.value,
                        cards=cards_payload,
                        lead_gen_form_id=adset_form_id or ad.creative.lead_gen_form_id,
                        object_story_id=ad.creative.object_story_id,
                        source_instagram_media_id=boosted_ig_media,
                        instagram_user_id=instagram_user_id or None,
                        ad_account_id=ad_account_id,
                        access_token=access_token,
                    )
                    await ledger.record_creative(key, creative_id, fingerprint)
                    writer({"type": "thinking", "content": f"Creative created: {creative_id}"})
                    # An ad from an earlier attempt still points at the creative
                    # this one replaced, and ads are only created below when the
                    # ledger has none — so without this the new creative would be
                    # built, recorded, and never actually run.
                    stale_ad_id = ledger.ad_for(key)
                    if stale_ad_id:
                        await _meta.update_ad_creative(
                            stale_ad_id, creative_id, access_token,
                        )
                        writer({"type": "thinking", "content": (
                            f"Ad {stale_ad_id} re-pointed at the rebuilt creative"
                        )})
                except _meta.MetaAdsError as exc:
                    logger.error("media publish: creative creation failed for %s — %s", key, exc)
                    raise await _fail_after_create(
                        exc,
                        step="ad_creative",
                        what=f"the creative for {ad_label}",
                        ledger=ledger, campaign_ids=campaign_ids,
                        access_token=access_token, writer=writer,
                        ids={"ad_account_id": ad_account_id, "page_id": page_id},
                        adset_index=idx, adset_dump=adset.model_dump(mode="json"),
                        ad_index=jdx,
                    ) from exc

            ad_id = ledger.ad_for(key)
            if not ad_id:
                try:
                    # Only ads that optimize toward a dataset event need a
                    # conversion domain: it exists so Aggregated Event Measurement
                    # (the iOS-opt-out reporting path) has a verified domain to
                    # attribute against. An instant-form or messaging ad converts
                    # on Meta and carries a link only because the spec requires
                    # one, so naming a domain there would describe a conversion
                    # that never happens off-platform.
                    po = adset.promoted_object
                    tracks_offsite = bool(po and (po.pixel_id or po.custom_conversion_id))
                    ad_id = await _meta.create_ad(
                        name=ad.name or f"{adset_name} Ad {jdx + 1}",
                        adset_id=adset_id,
                        creative_id=creative_id,
                        ad_account_id=ad_account_id,
                        access_token=access_token,
                        conversion_domain=(
                            ad.conversion_domain or "" if tracks_offsite else ""
                        ),
                    )
                    await ledger.record_ad(key, ad_id)
                    writer({"type": "thinking", "content": f"Ad created: {ad_id}"})
                except _meta.MetaAdsError as exc:
                    logger.error("media publish: ad creation failed for %s — %s", key, exc)
                    raise await _fail_after_create(
                        exc,
                        step="ad",
                        what=ad_label,
                        ledger=ledger, campaign_ids=campaign_ids,
                        access_token=access_token, writer=writer,
                        ids={"ad_account_id": ad_account_id, "page_id": page_id},
                        adset_index=idx, adset_dump=adset.model_dump(mode="json"),
                        ad_index=jdx,
                    ) from exc
            published_ad_ids.append(ad_id)
            published_ad_keys.append(key)

    # Activation is NOT part of publishing any more — see activate_published_tree.
    # The user reviews the built-but-PAUSED campaign (and the real Meta ad
    # previews of it) at the go_live_confirm gate, and only their answer there
    # flips it live.
    if not published_ad_ids:
        writer({"type": "thinking", "content": "No ads published — campaign left PAUSED"})

    # Publish succeeded — the audience's raw device IDs are in Meta now and
    # Punk has no further use for them. Only reached on a clean return: any
    # exception above skips this, so a resume after a mid-publish failure
    # still finds its maids/observations intact. Best-effort: purge failing
    # must not turn a successful publish into an error the user sees.
    if maid_extraction_id:
        try:
            from app.services.maid_store import purge_maid_extraction

            await purge_maid_extraction(str(maid_extraction_id), reason="publish succeeded")
        except Exception as exc:  # noqa: BLE001 — cleanup must never fail a publish
            logger.warning("media publish: MAID purge failed for %s — %s", maid_extraction_id, exc)

    return {
        # Scalar and singular on purpose: graph routing, the campaign_manager
        # focus, the chatbot context and the draft row all read this one key.
        # `campaign_ids` is additive — an app plan split across both stores puts
        # every campaign there, with the primary repeated here.
        "campaign_id": campaign_id,
        "campaign_ids": campaign_ids,
        "adset_ids": published_adset_ids,
        "ad_ids": published_ad_ids,
        # Parallel to ad_ids, one "{adset_idx}:{ad_idx}" plan slot each.
        "ad_keys": published_ad_keys,
        # Whether anything is actually live. Ads exist ≠ ads run: the activation
        # pass is skipped when there are no ads and when META_PUBLISH_ACTIVATE is
        # off, so callers must read this rather than infer "ACTIVE" from ad_ids.
        "activated": ledger.activated,
        "custom_audience_id": custom_audience_id,
        "lookalike_audience_id": lookalike_audience_id,
        # Meta's own match-rate answer — how many of the uploaded identifiers it
        # actually recognised. audience_uploaded_count is unset on a resumed
        # publish (no upload happens then); audience_matched_count is read fresh
        # from Meta either way, so it can be present without the other.
        "audience_uploaded_count": uploaded_maid_count,
        "audience_matched_count": audience_matched_count,
        "ad_account_id": ad_account_id,
        # Only present when subscribing the Page's leads failed. The publish
        # handler moves it onto publish_remediation and drops it — it is a fix-it
        # card, not an id.
        **({"lead_webhook_remediation": lead_webhook_fix} if lead_webhook_fix else {}),
    }


async def activate_published_tree(
    meta_ids: dict,
    user_info: dict,
    marketing_plan: dict,
    writer: Callable[[dict], None],
    user_id: str | None = None,
    thread_id: str | None = None,
) -> bool:
    """Flip an already-published, PAUSED campaign tree live. Returns ``activated``.

    Split out of ``publish_campaign_to_meta`` so the user can see the real Meta ad
    previews of what was built before anything spends: publishing now always ends
    PAUSED, and this is the only thing that starts delivery.

    The ledger is reloaded rather than passed in, because the publish that created
    these objects finished in an earlier graph step — an interrupt sits between
    the two. That is also what makes this resumable: every id is recorded the
    moment Meta accepts it, so a failure part-way down the ad list resumes from
    that ad instead of re-POSTing the whole tree and losing track of what is
    already live.
    """
    from app.services import meta_ads as _meta

    access_token = user_info["meta_access_token"]
    campaign_ids = list(meta_ids.get("campaign_ids") or [])
    adset_ids = list(meta_ids.get("adset_ids") or [])
    ad_ids = list(meta_ids.get("ad_ids") or [])

    if not ad_ids:
        writer({"type": "thinking", "content": "No ads to activate — campaign stays PAUSED"})
        return False
    if not settings.META_PUBLISH_ACTIVATE:
        writer({"type": "update", "content": (
            "Campaign built and left PAUSED — activation is switched off on this "
            "environment. Nothing is spending; flip it to Active in Ads Manager "
            "when you're ready."
        )})
        return False

    ledger = await _load_ledger(
        user_id, thread_id, marketing_plan, user_info.get("meta_ad_account_id") or ""
    )
    if ledger.activated:
        return True

    writer({"type": "update", "content": "Setting your campaign live..."})
    try:
        for cid in campaign_ids:
            if cid not in ledger.activated_ids:
                await _meta.activate_campaign(cid, access_token)
                await ledger.record_activated_id(cid)
        await _meta.activate_adsets(
            ledger.needs_activation(adset_ids), access_token, ledger.record_activated_id,
        )
        await _meta.activate_ads(
            ledger.needs_activation(ad_ids), access_token, ledger.record_activated_id,
        )
        await ledger.record_activated()
        writer({"type": "thinking", "content": "All items activated successfully"})
        return True
    except _meta.MetaAdsError as exc:
        # The objects exist and are correct — only the status flip failed — so
        # this raises as a recoverable step rather than discarding the work.
        logger.error("activation failed — %s", exc)
        # ponytail: activation keeps its ledger — the campaign is fully built and
        # correct, only the status flip failed, so tearing it down would throw
        # away work a retry resumes for free. Cost: an edit made in the editor
        # after an activation failure is ignored on retry. Clear the ledger's
        # campaign tree on plan submit if that ever bites.
        raise MetaPublishError(
            f"Your campaign is fully built in Meta but I couldn't switch it live: {exc}. "
            "Nothing is spending. Retry, or flip it to Active in Ads Manager.",
            step="activation",
        ) from exc


async def _rollback_campaigns(
    ledger: "PublishLedger", campaign_ids: list[str], access_token: str
) -> None:
    """Delete campaigns created in a failed attempt and clear them from the ledger.

    Best-effort per campaign (``delete_campaign`` never raises), so one stubborn
    campaign does not leave the others behind.
    """
    from app.services import meta_ads as _meta

    for cid in campaign_ids:
        await _meta.delete_campaign(cid, access_token)
    await ledger.forget_campaigns(campaign_ids)


async def _load_ledger(
    user_id: str | None, thread_id: str | None, marketing_plan: dict,
    ad_account_id: str = "",
) -> PublishLedger:
    """Persist the approved plan as a draft and load any prior publish ledger.

    ``thread_id`` is the LangGraph session key; ``Conversation.thread_id`` maps
    it to the conversation row the draft hangs off.

    Without a user and thread there is nowhere to persist, so the ledger runs in
    memory: publish still works, it just cannot resume across processes. A DB
    failure degrades the same way rather than blocking a publish.
    """
    if not (user_id and thread_id):
        return PublishLedger()

    try:
        from app.db.database import AsyncSessionLocal
        from app.modules.campaigns.repository import CampaignsRepository
        from app.modules.chat.models import Conversation

        repo = CampaignsRepository()
        async with AsyncSessionLocal() as db:
            conv = (
                await db.execute(
                    select(Conversation).where(Conversation.thread_id == str(thread_id))
                )
            ).scalars().first()

            draft = await repo.upsert_draft(
                db,
                user_id=_UUID(str(user_id)),
                conversation_id=conv.id if conv else None,
                name=marketing_plan.get("name") or "Campaign",
                campaign_plan=marketing_plan,
                meta_ads_id=ad_account_id or None,
            )
            return PublishLedger(draft.publish_state, draft_id=draft.id)
    except Exception as exc:  # noqa: BLE001 — publish must not die on a DB problem
        logger.error(
            "publish: could not load/create the draft row — %s. Publishing without "
            "resume support; a failure mid-publish will not be retryable.", exc,
        )
        return PublishLedger()


async def _resolves(host: str) -> bool:
    try:
        await asyncio.get_running_loop().getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False
    except OSError:  # no resolver, blocked socket — not the link's fault
        return True


async def _unreachable_link_hosts(spec: "CampaignSpec") -> dict[str, str]:
    """``{form_key: hostname}`` for every ad link whose domain does not exist.

    A published plan carried ``https://www.emptyadccom`` — a ``.com`` typed
    without its dot. Nothing about that string is malformed, so it passed model
    validation and previewed cleanly; Meta only refused it at ad-creation time,
    by which point the campaign and every ad set already existed in the account
    and the plan editor was no longer reachable. Whether a domain exists is a
    fact about the world, not about the string, so it is checked here — the last
    plan-fixable step, before anything is created.

    Offline is not a verdict: if a control host we are about to call ourselves
    fails to resolve, there is no working resolver and every answer would be a
    false accusation, so the check is skipped entirely.
    """
    links: dict[str, str] = {}
    for i, adset in enumerate(spec.adsets):
        for j, ad in enumerate(adset.ads or []):
            base = f"adsets[{i}].ads[{j}].creative"
            links[f"{base}.link"] = ad.creative.link
            for k, card in enumerate(ad.creative.cards or []):
                links[f"{base}.cards[{k}].link"] = card.link

    # RFC 6761/2606 names are reserved never to resolve, so a lookup on one is
    # guaranteed to come back negative and would say nothing about a typo. Meta
    # refuses them on its own; what this check is for is the domain that looks
    # ordinary and simply isn't there.
    hosts = {
        host for link in links.values()
        if (host := urlsplit(link).hostname)
        and host.rsplit(".", 1)[-1] not in ("example", "invalid", "localhost", "test")
    }
    if not hosts or not await _resolves("graph.facebook.com"):
        return {}

    resolved = dict(zip(hosts, await asyncio.gather(*(_resolves(h) for h in hosts))))
    return {
        key: urlsplit(link).hostname
        for key, link in links.items()
        if not resolved.get(urlsplit(link).hostname, True)
    }


def _remediation_for(exc: "MetaAdsError", *, step: str, **ids: str) -> dict | None:
    """The manual fix for a rejection Punk cannot resolve itself, or None.

    Kept as one call so every publish failure path asks the same question in the
    same way: "is this something the user has to go do on a Meta screen?" Most
    rejections are not, and None is the ordinary answer.
    """
    from app.services import meta_remediation

    found = meta_remediation.resolve(exc, step=step)
    return meta_remediation.render(found, **ids) if found else None


def _remediation_message(rem: dict, *, what: str) -> str:
    """Fallback prose for a remediation, used when the narrator is not in play.

    The composed beat is the normal surface (``builder_node`` buffers one), but a
    publish failure also carries a plain user_message through several paths that
    predate the narrator, and "Meta refused X" with no steps is what this exists to
    stop being the last word.
    """
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(rem["steps"], 1))
    link = f"\n\n{rem['url']}" if rem["url"] else ""
    tail = f"\n\n{rem['effect']}" if rem["effect"] else ""
    return f"**{rem['title']}** — {rem['cause']}\n\n{steps}{link}{tail}"


async def _fail_after_create(
    exc: "MetaAdsError",
    *,
    step: str,
    ledger: "PublishLedger",
    campaign_ids: list[str],
    access_token: str,
    writer: Callable[[dict], None],
    what: str,
    adset_index: int | None = None,
    adset_dump: dict | None = None,
    ad_index: int | None = None,
    ids: dict[str, str] | None = None,
) -> MetaPublishError:
    """The error to raise when Meta refuses something *after* the campaign exists.

    Every publish failure lands the user in the plan editor now, but the ledger is
    what decides whether an edit there can take effect: past preflight it holds
    real ids, so ``ledger.adset_for(idx)`` hands the retry the ad set built from
    the OLD plan. Two different cases:

    * Meta named a field (``blame_field_specs``, or ``_SUBCODE_BLAME_FIELDS`` for
      the rejections that only say it in prose) — the PLAN is what is wrong and it
      cannot be fixed while the campaign stands, so the campaign is torn down. It
      is PAUSED, incomplete, and was created by this same publish seconds ago.
      Uploaded media, audiences and any instant form survive in the ledger: they
      live on the ad account and the Page, not inside the campaign.
    * Meta named nothing (permission, throttle, an outage) — not the plan's fault,
      so nothing is deleted and an unchanged retry resumes from what already
      succeeded. Editing the plan is still possible; the teardown then happens at
      the next publish instead (``plan_dirty``), which is what keeps the resume
      path from silently ignoring the edit.
    """
    # Asked before the blame fields, and it wins: a Terms of Service nobody has
    # accepted or an account with no card on it is not a plan problem, and Meta
    # sometimes names a field on those anyway. Tearing down the campaign and
    # sending the user to the editor would be two wrong moves at once.
    remediation = _remediation_for(exc, step=step, **(ids or {}))
    if remediation:
        # The catalog's own effect line assumes nothing was built yet, which is the
        # common case and wrong here by definition — this path only runs once the
        # campaign exists. Say what is actually true about the user's money.
        remediation = {
            **remediation,
            # Whatever the catalog calls it in the abstract, an entry reached from
            # HERE is the thing that stopped this publish — "warns" would sort it
            # below cards the user could safely ignore.
            "severity": "blocks",
            "effect": (
                "Anything already created in Meta is PAUSED and not spending. "
                "Publish again once this is sorted and it picks up where it stopped."
            ),
        }
        return MetaPublishError(
            _remediation_message(remediation, what=what),
            step=step,
            remediation=remediation,
        )

    plan_errors = _plan_error_keys(
        exc, adset_index=adset_index, adset_dump=adset_dump, ad_index=ad_index,
    )
    if not plan_errors:
        detail = getattr(exc, "user_msg", None) or str(exc)
        return MetaPublishError(
            f"Meta refused {what}: {detail} Anything already created is PAUSED and "
            "not spending — adjust the plan below, or publish again as-is.",
            step=step,
        )

    writer({"type": "update", "content": (
        "Meta rejected the plan. Removing the paused campaign it had already "
        "created so you can fix this and publish cleanly..."
    )})
    await _rollback_campaigns(ledger, campaign_ids, access_token)
    await ledger.forget_campaign_tree()

    detail = getattr(exc, "user_msg", None) or str(exc)
    return MetaPublishError(
        f"Meta rejected {what}: {detail} I removed the paused campaign it had "
        "created, so nothing is left in your ad account — fix the highlighted "
        "field and publish again.",
        step=f"{step}_rejected",
        plan_errors=plan_errors,
    )


def _preflight_message(
    exc: "MetaAdsError", *, adset_name: str | None = None, remediation: dict | None = None
) -> str:
    """User-facing copy for a Meta preflight rejection.

    Prefers Meta's own ``error_user_msg`` — it names the actual account or policy
    problem, which is almost always more useful than a paraphrase. A rejection the
    catalog recognises beats both: "adjust the plan and try again" is actively
    wrong advice when the plan is fine and the fix is a Meta screen.
    """
    if remediation:
        return _remediation_message(remediation, what="your campaign")
    where = f'ad set "{adset_name}"' if adset_name else "your campaign"
    detail = getattr(exc, "user_msg", None) or str(exc)
    return (
        f"Meta rejected {where} before anything was created: {detail} "
        "Nothing was added to your ad account — adjust the plan and try again."
    )


def _find_form_path(node: Any, field: str) -> str | None:
    """Where ``field`` lives inside a spec dump, in the editor's own path syntax.

    Breadth-first on purpose: ``name`` and ``status`` exist on the ad set and on
    every ad under it, and Meta blaming one of them means the level it was sent
    at — the shallowest match — not the first one a depth-first walk trips over.
    """
    queue: list[tuple[Any, str]] = [(node, "")]
    while queue:
        current, prefix = queue.pop(0)
        if isinstance(current, dict):
            if field in current:
                return f"{prefix}.{field}" if prefix else field
            for key, value in current.items():
                if isinstance(value, (dict, list)):
                    queue.append((value, f"{prefix}.{key}" if prefix else key))
        elif isinstance(current, list):
            for i, value in enumerate(current):
                if isinstance(value, (dict, list)):
                    queue.append((value, f"{prefix}[{i}]"))
    return None


# Rejections where Meta names the offending plan field only in prose and sends
# no ``blame_field_specs``. Without a field the whole thing lands on ``__root__``
# and the publish gate is re-asked instead of the editor — so the user's only
# move is to press Publish against the identical spec until the 3-strike cap.
_SUBCODE_BLAME_FIELDS: dict[int, str] = {
    # "Lead Generation Ads should always link to external content ... this ad
    # links to a Facebook page." The Page URL is exactly what the spec builder
    # falls back to when the business has no website, so this is reachable on
    # any Leads plan built without one — and the fix is the ad's link field.
    1815316: "link",
}


def _plan_error_keys(
    exc: "MetaAdsError",
    *,
    adset_index: int | None = None,
    adset_dump: dict | None = None,
    ad_index: int | None = None,
) -> dict[str, str]:
    """Meta's rejection, keyed onto the plan editor's form fields.

    Meta names the fields it refused in ``error_data.blame_field_specs``; the
    editor addresses them as ``adsets[0].targeting.age_max``. Without this the
    whole rejection landed on ``__root__`` — a banner saying "adjust the plan"
    with nothing marked, so the only move left was to press publish again and
    fail identically. ``_SUBCODE_BLAME_FIELDS`` covers the rejections that name
    no field at all but are still the plan's fault.

    A field we cannot locate in the spec still gets a key rather than being
    dropped: the banner reads the same either way, and a key that marks nothing
    costs nothing.
    """
    detail = getattr(exc, "user_msg", None) or str(exc)
    prefix = f"adsets[{adset_index}]" if adset_index is not None else ""
    node = adset_dump
    # Scope to the ad that actually failed. BFS from the ad set would mark ad 0
    # on every ad, so the second ad's bad link highlighted the first one's field.
    if ad_index is not None and isinstance(adset_dump, dict):
        ads = adset_dump.get("ads") or []
        if ad_index < len(ads):
            node = ads[ad_index]
            prefix = f"{prefix}.ads[{ad_index}]" if prefix else f"ads[{ad_index}]"
    fields = list(getattr(exc, "blame_field", None) or [])
    if not fields:
        known = _SUBCODE_BLAME_FIELDS.get(getattr(exc, "subcode", None))
        if known:
            fields = [known]
    errors: dict[str, str] = {}
    for field in fields:
        path = _find_form_path(node, field) if node is not None else None
        path = path or field
        errors[f"{prefix}.{path}" if prefix else path] = detail
    return errors


# ── Pre-publish auth/account/pixel nodes (relocated from wizards/media_wizard.py) ──
# Builder-only consolidation. These are interrupt-driven subgraph node functions
# (take AgentState, return a dict). The builder publish op runs them on a state-view
# overlay before the publish core; the media wizard ran them as graph nodes.

from app.graph.state import AgentState
from app.graph.wizard_helpers import (
    _session_summary,
    get_writer,
    resolve_option,
    wizard_interrupt,
    wizard_milestone_narrate,
)
from app.modules.ads.repository import AdsRepository
from app.modules.ads.service import build_meta_auth_url
from app.services.entitlement import ad_account_is_paid
from app.services.oauth import get_meta_credentials, list_meta_ad_accounts


def _ws(state: AgentState) -> dict:
    return dict(state.get("media_wizard_state") or {})


def _single_interrupt(state: AgentState) -> bool:
    """This build runs the one-interrupt-per-task contract (see StepPaused)."""
    return bool((state.get("campaign_builder_state") or {}).get("_single_interrupt"))


def _build_media_progress(ws: dict, user_info: dict | None = None) -> list[dict]:
    """Build confirmed-steps list from media_wizard_state."""
    user_info = user_info or {}
    items: list[dict] = []
    if ws.get("ad_account_id"):
        items.append({"label": "Ad Account", "value": ws["ad_account_id"][:20] + ("…" if len(ws.get("ad_account_id", "")) > 20 else "")})
    if ws.get("promoted_object"):
        items.append({"label": "Pixel", "value": ws["promoted_object"].get("pixel_id", "")[:20] + ("…" if len(ws.get("promoted_object", {}).get("pixel_id", "")) > 20 else "")})
    return items


async def media_check_meta_auth(state: AgentState) -> dict:
    """
    Verify the user has a connected Meta Ads account.

    Happy path (already connected): loads credentials into media_wizard_state
    and user_info, sets needs_account_selection flag if multiple accounts exist.

    Unhappy path (not connected): fires an oauth_connect interrupt so the
    frontend can show a single "Connect Meta" button. After the user completes
    OAuth and the callback stores the token in DB, the interrupt resumes and
    we re-query to load the fresh credentials.
    """
    writer = get_writer()
    ws = _ws(state)
    # media_collect_creatives (wizard path) emits the stage-open milestone and
    # sets this flag; the builder publish op calls this node directly with a
    # fresh scratch, so the milestone still fires there.
    is_first_entry = not ws.get("_media_entry_done")
    user_id: str | None = state.get("user_id")
    user_info: dict = dict(state.get("user_info") or {})

    if not user_id:
        writer({"type": "thinking", "content": "media_wizard: no user_id in state — skipping OAuth check"})
        return {"media_wizard_state": ws}

    creds = await get_meta_credentials(user_id)
    # Whether Meta was ALREADY connected on entry. Below this point creds is
    # always non-None (the unconnected path either returns or resumes with a
    # fresh token), so this is the only thing that still distinguishes the two —
    # and the entry handoff must not talk about connecting in either case.
    was_connected = creds is not None

    if creds is None:
        # Drain any reveal beats buffered upstream (audience found, plan drafted)
        # as their OWN message FIRST. The maid_confirm gate is required=False for
        # some paths, so those reveals never flush at their own screen and would
        # otherwise be woven into the OAuth connect framing below — re-summarizing
        # work on the connect screen. Flushing here keeps connect framing clean.
        if _narrator_peek(state):
            await flush_narration(state, writer)

        # Ask, then re-query. One retry: the caller raises "Meta credentials
        # unavailable after auth flow" the moment we return without creds, so a
        # user who closed the Meta window early used to crash the run instead of
        # getting the button back. Each pass mints a FRESH authorization URL —
        # the state token is single-use (exchange_meta_code pops it), so re-showing
        # the old URL would fail CSRF validation on the second attempt.
        # Single-interrupt mode: at most one interrupt per task, so the retry is
        # a persisted attempt counter + a pause, not a second interrupt here.
        _single = _single_interrupt(state)
        _shared = state.get("media_wizard_state") or ws
        _start = int(_shared.get("_oauth_attempt") or 0) if _single else 0
        for attempt in range(_start, 2):
            oauth_url = build_meta_auth_url(user_id)["authorization_url"]
            writer({"type": "thinking", "content": "media_wizard: user not connected, OAuth URL generated"})

            _oauth_result = await wizard_interrupt(
                writer,
                step_key="media_check_meta_auth",
                context=_session_summary(state) + "; Meta Ads account not connected",
                state=state,
                options_override=[oauth_url],
                action_type_override="oauth_connect",
                field_override="meta_oauth_connect",
                prompt_override=(
                    "Quick one-time step — let's connect your Meta ad account. "
                    "Connecting now lets me build your plan around your real ad account and page, "
                    "so everything's ready to launch straight from here later — no Ads Manager needed."
                    if attempt == 0 else
                    "That connection didn't come through — Meta never handed back an account. "
                    "Give it one more go: the button opens Meta's login, and I'll pick up as soon "
                    "as it's authorized. If Meta showed an error instead of a login, your account "
                    "may not be invited to test Punk on Meta yet — tell us and we'll add you."
                ),
                skip_ask=False,
            )

            # Any OTHER field the user changed while the OAuth popup was up.
            # Parked for builder_plan; this call's return value was not even
            # bound before, so an edit here vanished without a trace.
            #
            # Stash onto `state["media_wizard_state"]`, NOT the local `ws` — `ws`
            # is `_ws(state)`'s defensive COPY, unreachable if this node pauses
            # again or the caller (WizardExit / an exception) never gets a return
            # value back from it. `_run_media_overlay` seeds `live["media_ws"]`
            # onto this exact shared dict before the node loop starts, so a stash
            # here survives even when the node never returns.
            stash_edits(state.get("media_wizard_state") or ws, _oauth_result)
            if not getattr(_oauth_result, "answered", True):
                # A question / edit typed while the connect button was up —
                # not a connection attempt. Re-ask the same prompt next task.
                raise StepPaused()

            # OAuth callback should have stored the token — re-query
            creds = await get_meta_credentials(user_id)
            if creds is not None:
                _shared.pop("_oauth_attempt", None)
                ws.pop("_oauth_attempt", None)
                break
            writer({"type": "thinking", "content": (
                f"media_wizard: OAuth returned but no credentials in DB (attempt {attempt + 1}/2)"
            )})
            if _single and attempt == 0:
                _shared["_oauth_attempt"] = 1
                raise StepPaused()

        if creds is None:
            return {"media_wizard_state": ws, "pending_action": None}

    # Emitted once on fresh entry, AFTER the ad account is resolved below — the
    # handoff names the real next step, which isn't known until then.
    _entry_update: dict = {}

    # ── Credentials available ─────────────────────────────────────────────
    access_token = creds["access_token"]
    stored_account_id = creds.get("ad_account_id")
    accessible_accounts: list[dict] = creds.get("accessible_accounts") or []

    # If no account list cached, fetch live from Meta API
    if not accessible_accounts:
        writer({"type": "thinking", "content": "media_wizard: fetching ad accounts from Meta API"})
        accessible_accounts = await list_meta_ad_accounts(access_token)

    # Connected, yet Meta shared no ad account: a new advertiser who has not made one,
    # or one who did not tick it on the consent screen. Publishing needs one, and this
    # used to end in a bare "credentials unavailable" crash further up. Ask them to
    # sort it on Meta and connect again — the same button as the first connect, so the
    # reconnect re-reads what Meta now shares. Two tries, like the connect prompt above.
    if not (stored_account_id or accessible_accounts):
        from app.services import meta_remediation as _fix

        _single = _single_interrupt(state)
        _shared = state.get("media_wizard_state") or ws
        _start = int(_shared.get("_acct_attempt") or 0) if _single else 0
        for _attempt in range(_start, 2):
            writer({"type": "thinking", "content": (
                f"media_wizard: connected but Meta shared no ad account (attempt {_attempt + 1}/2)"
            )})
            _acct_result = await wizard_interrupt(
                writer,
                step_key="media_check_meta_auth",
                context=_session_summary(state) + "; Meta connected but no ad account shared",
                state=state,
                options_override=[build_meta_auth_url(user_id)["authorization_url"]],
                action_type_override="oauth_connect",
                field_override="meta_oauth_connect",
                prompt_override=_fix.prose(_fix.CATALOG["no_ad_account"]),
                skip_ask=False,
            )
            stash_edits(state.get("media_wizard_state") or ws, _acct_result)
            if not getattr(_acct_result, "answered", True):
                raise StepPaused()
            creds = await get_meta_credentials(user_id) or creds
            access_token = creds["access_token"]
            stored_account_id = creds.get("ad_account_id")
            accessible_accounts = creds.get("accessible_accounts") or await list_meta_ad_accounts(
                access_token
            )
            if stored_account_id or accessible_accounts:
                _shared.pop("_acct_attempt", None)
                ws.pop("_acct_attempt", None)
                break
            if _single and _attempt == 0:
                _shared["_acct_attempt"] = 1
                raise StepPaused()

    ws["access_token"] = access_token
    ws["page_id"] = creds.get("page_id") or ""
    ws["page_name"] = creds.get("page_name") or ""
    ws["accessible_accounts"] = accessible_accounts

    # Determine whether we need the user to pick an account
    if stored_account_id:
        # Previously selected account — use it directly
        ws["ad_account_id"] = stored_account_id
        ws["needs_account_selection"] = False
    elif len(accessible_accounts) == 1:
        ws["ad_account_id"] = accessible_accounts[0]["id"]
        ws["needs_account_selection"] = False
    elif len(accessible_accounts) > 1:
        ws["needs_account_selection"] = True
    else:
        # No accounts found — can't publish
        ws["ad_account_id"] = None
        ws["needs_account_selection"] = False
        writer({"type": "thinking", "content": "media_wizard: no ad accounts found for this token"})

    # Entry handoff. Fires right after the audience is confirmed and BEFORE the
    # plan is built — Meta is resolved up front so the intake + plan are tailored
    # to the user's real ad account/page. (No plan/campaign name exists yet, so
    # don't reference one.) Meta is CONNECTED by the time we get here in every
    # path, so this never asks the user to connect: an already-connected user was
    # getting "before I build your plan, let's connect your Meta account" on the
    # intake screen, where no OAuth step happens at all.
    if is_first_entry:
        ws["_media_entry_done"] = True
        geo_data_local = state.get("geo_data") or {}
        picking_account = bool(ws.get("needs_account_selection"))
        account_name = "" if picking_account else (creds.get("ad_account_name") or "")

        if picking_account:
            _fallback = (
                "Audience locked in, and your Meta account's connected. "
                "Pick which ad account to use and we'll keep going."
            )
        elif was_connected:
            _fallback = (
                "Audience locked in — your Meta account's already connected, so we're "
                "set. Next, a few campaign details so I can draft your plan."
            )
        else:
            _fallback = (
                "Audience locked in and your Meta account's connected. Next, a few "
                "campaign details so I can draft your plan."
            )

        # Beat, NOT a direct emit. The audience reveal is still buffered from the
        # maid stage and the caller's Business-capability check adds another beat
        # right after this node — a direct narrate() here shipped its own message
        # between them, so the user got three independently-written paragraphs on
        # one screen (and the capability warning landed contradicting the reveal).
        # Buffered, the next pause's flush composes all of it as one message.
        add_beat(
            state, "handoff",
            facts={
                "stage": "campaign_to_media",
                "business_name": user_info.get("business_name") or "",
                "audience_count": audience_headline_count(geo_data_local) or 0,
                "meta_connection": "already_connected" if was_connected else "just_connected",
                "ad_account_name": account_name,
                "next_step": (
                    "pick which ad account to use"
                    if picking_account
                    else "fill in a few campaign details so I can draft the plan"
                ),
            },
            fallback=_fallback,
        )

    # If account already determined, populate user_info now
    if not ws.get("needs_account_selection") and ws.get("ad_account_id"):
        user_info["meta_access_token"] = access_token
        user_info["meta_ad_account_id"] = ws["ad_account_id"]
        user_info["meta_page_id"] = ws["page_id"]
        writer({"type": "thinking", "content": f"media_wizard: auto-selected account {ws['ad_account_id']}"})
        account_paid = await ad_account_is_paid(user_id, ws["ad_account_id"])
        ws["account_paid"] = account_paid
        if not account_paid:
            add_beat(
                state, "failure",
                facts={
                    "stage": "account_unpaid",
                    "ad_account_name": (creds.get("ad_account_name") or ""),
                },
                fallback=(
                    "Heads up — this ad account isn't on a Punk subscription yet. "
                    "We can build the whole campaign; you'll just need a plan for "
                    "this account before it can go live."
                ),
            )
        return {"media_wizard_state": ws, "user_info": user_info, "pending_action": None, **_entry_update}

    return {"media_wizard_state": ws, "pending_action": None, **_entry_update}


async def media_select_ad_account(state: AgentState) -> dict:
    writer = get_writer()
    ws = _ws(state)
    user_info: dict = dict(state.get("user_info") or {})

    if not ws.get("needs_account_selection"):
        return {"media_wizard_state": ws}

    accounts: list[dict] = ws.get("accessible_accounts") or []
    options = [
        f"{a.get('name', 'Unknown account')} — {a.get('id', '')}"
        for a in accounts
    ]

    # Beat (not direct emit): woven into the account-select pause's single
    # composed message instead of stacking ahead of the step framing.
    add_beat(state, "reveal", {"ad_account_count": len(accounts)},
        fallback=f"You've got **{len(accounts)} Meta ad accounts** connected.")

    response = await wizard_interrupt(
        writer,
        step_key="media_select_ad_account",
        context=_session_summary(state) + f"; Choosing among {len(accounts)} Meta ad accounts",
        state=state,
        options_override=options,
        skip_ask=True,
        progress=_build_media_progress(ws, state.get("user_info")),
    )

    # Any OTHER field the user changed in the same breath ("and add Toronto").
    # Parked for builder_plan; before this it was acked and dropped. Edits to
    # the Meta account/pixel/page themselves never reach here — edit_block_reason
    # refuses those upstream as `meta_account`.
    #
    # Stash onto the shared `media_wizard_state`, not the local `ws` copy — see
    # the matching note in media_check_meta_auth.
    stash_edits(state.get("media_wizard_state") or ws, response)
    if not getattr(response, "answered", True):
        # Not a pick (an edit / question) — never read it as an unmatched
        # choice. Re-ask once builder_plan has applied its edits.
        raise StepPaused()
    resolved = resolve_option(response, options)
    selected = next(
        (
            a for a in accounts
            if a.get("id", "") in resolved or a.get("name", "") in resolved
        ),
        None,
    )
    if selected is None:
        # An unparsed answer used to silently fall back to accounts[0] —
        # the same class of money bug as guessing a budget: never assume
        # which live ad account the user meant. Re-ask instead.
        add_beat(state, "reveal", {"ad_account_count": len(accounts)},
            fallback="I didn't catch which account that was — pick one from the list.")
        return {"media_wizard_state": ws, "pending_action": None}

    user_info["meta_access_token"] = ws["access_token"]
    user_info["meta_ad_account_id"] = selected["id"]
    user_info["meta_page_id"] = ws.get("page_id") or ""

    ws["ad_account_id"] = selected["id"]
    ws["needs_account_selection"] = False

    account_paid = await ad_account_is_paid(state.get("user_id"), selected["id"])
    ws["account_paid"] = account_paid
    if not account_paid:
        add_beat(
            state, "failure",
            facts={
                "stage": "account_unpaid",
                "ad_account_name": selected.get("name", "")[:60],
            },
            fallback=(
                f"Heads up — **{selected.get('name', 'this account')}** isn't on a "
                "Punk subscription yet. We can build the whole campaign; you'll "
                "just need a plan for this account before it can go live."
            ),
        )

    # Milestone — narrate the locked ad account. Runs before the plan is built
    # now, so keep it neutral (don't imply publish/setup is underway).
    marketing_plan_local = state.get("marketing_plan") or {}
    campaign_name_local = (marketing_plan_local.get("campaign") or {}).get("name", "")
    _narrator_update = await wizard_milestone_narrate(
        writer, state, "media_account_locked",
        facts={
            "ad_account_name": selected.get("name", "")[:60],
            "ad_account_id": selected.get("id", ""),
            "campaign_name": campaign_name_local,
        },
        fallback=f"Locked in **{selected.get('name', 'your Meta account')}**.",
    )

    writer({"type": "thinking", "content": f"media_wizard: user selected account {selected['id']}"})
    return {"media_wizard_state": ws, "user_info": user_info, "pending_action": None, **_narrator_update}


_PIXEL_OBJECTIVES: frozenset[str] = frozenset({Objective.SALES, Objective.LEADS})



def _candidate(pixel: dict) -> dict:
    """One dataset as the editor and the picker want it.

    ``last_fired_time`` rides along because it is the difference between a dataset
    that is measuring something and one nobody ever installed — the single most
    useful thing to show next to a pixel name, and what ``_pick_dataset`` sorts on.
    """
    return {
        "id": str(pixel["id"]),
        "name": pixel.get("name", ""),
        "last_fired_time": pixel.get("last_fired_time") or "",
    }


def _pick_dataset(candidates: list[dict], stored_id: str = "") -> tuple[str, str]:
    """Which dataset to use, and why — ``("", "")`` when the user has to choose.

    Order matters more than it looks:

    1. **The one we used last time.** Meta returns datasets in no guaranteed
       order, so without this a user who picked one of three could silently be
       switched to another on the next run — and a switched dataset means the ad
       set optimizes against an event store with none of the history.
    2. **The only one there is.** No choice to offer.
    3. **The only warm one.** A dataset that has fired has the advertiser's
       delivery history and audience behind it; a cold sibling has nothing. Asking
       the user to choose between "the one that works" and "the ones that don't"
       is a question with one answer.

    Anything else — several warm datasets, or several cold ones — is a real choice
    and goes to the picker.
    """
    by_id = {c["id"]: c for c in candidates}
    if stored_id and stored_id in by_id:
        return stored_id, "remembered from your last campaign"
    if len(candidates) == 1:
        return candidates[0]["id"], "the only one on this ad account"
    warm = [c for c in candidates if c["last_fired_time"]]
    if len(warm) == 1:
        return warm[0]["id"], "the only one currently receiving events"
    return "", ""


async def _stored_tracking_dataset(user_id: str | None) -> tuple[str, str]:
    """``(dataset_id, business_id)`` remembered for the selected ad account.

    ``("", "")`` when there is nothing remembered. Read rather than recomputed:
    see ``_pick_dataset``. Degrades to empty on any failure — a database hiccup
    must not stop a campaign, it just costs the user the picker again.
    """
    if not user_id:
        return "", ""
    try:
        async with AsyncSessionLocal() as db:
            row = await AdsRepository().get_tracking_account(db, str(user_id))
    except Exception:
        logger.warning("media_wizard: tracking dataset lookup failed", exc_info=True)
        return "", ""
    if not row:
        return "", ""
    return str(row.tracking_dataset_id or ""), str(row.tracking_business_id or "")


def _tracking_promoted_object(
    dataset_id: str, user_info: dict, event_type: str
) -> dict:
    """The ad set's promoted_object for a resolved dataset.

    A custom conversion the user chose replaces the standard event: it names the
    dataset AND the rule, so sending an event type beside it describes a different
    conversion than the one they picked. Everything else is unchanged.
    """
    custom = str(user_info.get("custom_conversion_id") or "").strip()
    if custom:
        return {"pixel_id": dataset_id, "custom_conversion_id": custom}
    return {
        "pixel_id": dataset_id,
        "custom_event_type": str(user_info.get("pixel_event") or event_type),
    }


def _resolved_event_type(ws: dict) -> str:
    """The standard event the ad set just committed to, or "" for a custom conversion."""
    return str((ws.get("promoted_object") or {}).get("custom_event_type") or "")


def _resolved_shape(user_info: dict, brief: dict):
    """The (conversion location, optimization goal) this campaign will publish with.

    Resolved through the two helpers ``build_campaign_spec`` itself uses, so the
    pixel step and the spec cannot disagree about whether a dataset is involved.
    The objective alone is not enough to answer this: Leads defaults to instant
    forms, whose promoted object is the Page, and Sales on an account with no
    dataset resolves to a landing-page-view goal that promotes nothing.

    Returns ``(DestinationRules, OptimizationGoal)``, or ``(None, None)`` for
    anything unresolvable. A bad objective or an impossible conversion location
    is ``build_campaign_spec``'s error to raise with the full context; the only
    thing it means here is that there is no dataset worth fetching.
    """
    from app.graph.meta_spec.builder import _resolve_destination, _resolve_goal

    objective = normalize_objective(user_info.get("campaign_objective"))
    if objective is None:
        return None, None
    try:
        rules = matrix_for(objective)
        dest = _resolve_destination(rules, user_info.get("conversion_location"), brief)
        goal = _resolve_goal(
            brief, dest, warm_dataset=bool(user_info.get("has_warm_dataset")),
        )
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.info("media_wizard: could not resolve the campaign shape — %s", exc)
        return None, None
    return dest, goal


def _derived_tracking_method(dest, goal) -> str:
    """How conversions reach Meta, for a run that was never asked — or "".

    Express never sees the tracking group, and an empty method is a member of
    both ``_METHODS_WITH_PIXEL`` and ``_METHODS_WITH_SERVER`` — so left unset it
    reads as "browser pixel AND server events", and the publish gate hands a
    beginner an ingest key, a server code sample and a secret to keep.

    Only the two shapes with an honest answer get one. A pixel-promoted ad set is
    ``pixel_only``: the browser tag is the whole install, and the server half is
    an upgrade the advertiser opts into. An instant form is ``lead_forms``: the
    lead is submitted inside Facebook and there is nothing to install anywhere.
    Everything else — a Messenger sale, a Sales campaign stepped down to
    landing-page views — comes back empty on purpose. None of the four methods
    describes it, and stamping the closest-looking one on the account row would
    hand the advertiser instructions for a setup they do not have.
    """
    if dest is None or goal is None:
        return ""
    if dest.promoted_object_kind(goal) == PROMOTED_PIXEL:
        return "pixel_only"
    return "lead_forms" if dest.requires_lead_form else ""


async def _subscribe_lead_webhook(
    *, page_id: str, ad_account_id: str, access_token: str, user_id: str | None, writer,
) -> dict | None:
    """Subscribe the Page's leads to Punk. Returns a fix-it card, or None.

    Best-effort by construction: the campaign is already created by the time this
    runs, and a Page that will not accept the subscription is a missing feedback
    loop, not a failed publish. Meta still counts every lead either way, so
    delivery optimizes normally regardless.

    The Page id is persisted on the ad account because it is the ONLY thing that
    can route an inbound delivery back here — Meta's payload names the Page and
    nothing that identifies us.

    A dataset is resolved here too, and this is the only place it can be. An
    instant-form ad set promotes the *Page*, so ``media_select_pixel`` returns
    before it ever resolves one — which left every one of these accounts with a
    null ``tracking_dataset_id``, and every lead Meta pushed was read and then
    dropped for want of somewhere to report it. Subscribing is the moment the
    account acquires an inbound feed, so it is the moment it needs a destination.
    """
    from app.services import meta_ads as _meta
    from app.services import meta_remediation as _fix

    if not (page_id and access_token):
        return None

    page_token = await _meta.fetch_page_token(page_id, access_token)
    if not await _meta.subscribe_page_leadgen(page_id, page_token):
        writer({"type": "thinking", "content": (
            f"Could not subscribe to page {page_id} leads — the campaign still runs"
        )})
        return _fix.render(_fix.CATALOG["lead_webhook_not_subscribed"], page_id=page_id)

    if user_id:
        try:
            async with AsyncSessionLocal() as db:
                await AdsRepository().save_tracking_state(
                    db, str(user_id), tracking_lead_page_id=str(page_id),
                )
        except Exception:
            logger.warning(
                "publish: subscribed page %s but could not remember it", page_id,
                exc_info=True,
            )
    writer({"type": "thinking", "content": f"Subscribed to page {page_id} leads"})

    stored_id, stored_business = await _stored_tracking_dataset(user_id)
    if stored_id:
        return None

    # Reuse whatever the account already has. Punk does NOT create one here: a
    # dataset made on our initiative measures nothing until somebody installs it,
    # and the standing rule is that only the user asks for one. An account with
    # none keeps working — Meta counts the leads — and the tracking card raises
    # ``lead_dataset_missing`` so the gap is visible rather than silent.
    candidates = [
        _candidate(pixel)
        for pixel in await _meta.fetch_ad_pixels(ad_account_id, access_token)
    ]
    chosen, why = _pick_dataset(candidates, stored_id)
    if not chosen:
        writer({"type": "thinking", "content": (
            f"No single dataset to report page {page_id} leads into "
            f"({len(candidates)} candidate(s)) — lead quality feedback is off "
            "until one is picked in Punk"
        )})
        return None

    # LEAD, not the objective default: every event this feed will ever send is a
    # lead coming back from an instant form.
    await _remember_tracking_dataset(
        user_id, chosen, stored_business, "LEAD", "lead_forms",
    )
    writer({"type": "thinking", "content": (
        f"Page {page_id} leads will be reported into dataset {chosen} — {why}"
    )})
    return None


async def _remember_tracking_method(user_id: str | None, method: str) -> None:
    """Persist the method alone, for a campaign that resolved to no dataset.

    ``_remember_tracking_dataset`` cannot: it needs a dataset id, and the runs
    that most need their method recorded — instant-form leads, Messenger sales —
    are exactly the ones with none. Without this the account row stays null and
    the Profile tracking card goes on offering a website snippet.
    """
    if not (user_id and method):
        return
    try:
        async with AsyncSessionLocal() as db:
            await AdsRepository().save_tracking_state(
                db, str(user_id), tracking_method=method,
            )
    except Exception:
        logger.warning("media_wizard: could not remember tracking method", exc_info=True)


async def _remember_tracking_dataset(
    user_id: str | None, dataset_id: str, business_id: str = "",
    event_type: str = "", method: str = "",
) -> None:
    """Persist the resolved dataset on the ad account it belongs to. Best-effort.

    ``event_type`` is the ad set's ``custom_event_type`` and rides along so the
    tracking card can hand out a snippet firing the same event delivery optimizes
    for. Empty for a custom conversion — that names its own rule, and there is no
    standard event to put in a snippet — and empty is not written, because
    ``save_tracking_state`` only touches the fields it is passed.

    ``method`` is the intake form's "how your conversions reach Meta" answer. It
    is persisted here because this is the only place that already writes this row,
    and because the tracking card cannot decide what to hand the user — snippet,
    ingest key, both, neither — without it. Express never answers it and leaves it
    null, which reads as the default.
    """
    if not (user_id and dataset_id):
        return
    try:
        async with AsyncSessionLocal() as db:
            await AdsRepository().save_tracking_state(
                db, str(user_id),
                tracking_dataset_id=dataset_id,
                tracking_business_id=business_id or None,
                **({"tracking_event_type": event_type} if event_type else {}),
                **({"tracking_method": method} if method else {}),
            )
            # Mint the ingest key here rather than leaving it to whenever someone
            # happens to open the tracking card. It was minted lazily by
            # /tracking/snippet, so an advertiser who never visited Profile →
            # Connections → Meta had no key at all and the server half of their
            # chosen setup could not have worked. Skipped for a setup with no
            # server half — see TrackingService.uses_server.
            from app.modules.tracking.service import TrackingService, uses_server

            if uses_server(method):
                await TrackingService(AdsRepository()).ensure_ingest_key(db, str(user_id))
    except Exception:
        logger.warning("media_wizard: could not remember dataset %s", dataset_id, exc_info=True)


async def media_detect_pixel(state: AgentState) -> dict:
    """Fetch the connected ad account's Meta Pixels up front (at connect time).

    Non-interrupting and objective-independent — runs inside connect_meta, right
    after the account is picked and before the intake questions. The candidates
    are cached so media_select_pixel (which DOES know the objective + event type)
    doesn't re-fetch, and so the plan editor's pixel picker — the only place the
    pixel is ever asked — has the account's real options. The objective-specific
    promoted_object is still built later in media_select_pixel.
    """
    from app.services import meta_ads as _meta

    writer = get_writer()
    ws = _ws(state)
    user_info: dict = dict(state.get("user_info") or {})

    access_token = user_info.get("meta_access_token", "")
    ad_account_id = user_info.get("meta_ad_account_id", "")
    if not access_token or not ad_account_id:
        return {"media_wizard_state": ws}

    # All three reads are account-scoped and none blocks the others. The timezone
    # is what the editor's dayparting control is labelled with: Meta reads those
    # start/end minutes in the AD ACCOUNT's zone, and the control collects them
    # from a browser clock. The currency is the same class of problem for money:
    # every budget is sent in the account's currency in minor units, and Meta's
    # minimum daily budget is per-currency — so a plan built to a USD floor is
    # rejected outright on a BDT or CAD account.
    pixels, ws["ad_account_timezone"], currency, conversions, audiences = await asyncio.gather(
        _meta.fetch_ad_pixels(ad_account_id, access_token),
        _meta.fetch_ad_account_timezone(ad_account_id, access_token),
        _meta.fetch_ad_account_currency(ad_account_id, access_token),
        # The advertiser's own conversion rules ("URL contains /thank-you"). Read
        # here with the rest because for someone who has the base pixel installed
        # and no event code, one of these is the only conversion they can actually
        # optimize toward — and the editor has to be able to offer it.
        _meta.fetch_custom_conversions(ad_account_id, access_token),
        # The audiences already on the account, for the editor's include/exclude
        # pickers. Read at connect time with the others rather than when the
        # editor renders: it is the same account-scoped read, it costs nothing
        # extra here, and the plan is built before the editor is ever shown.
        _meta.list_custom_audiences(ad_account_id, access_token),
    )
    ws["pixel_candidates"] = [_candidate(p) for p in pixels]
    ws["custom_conversions"] = [
        {
            "id": str(c["id"]),
            "name": c.get("name") or str(c["id"]),
            "custom_event_type": c.get("custom_event_type") or "",
        }
        for c in conversions if c.get("id")
    ]
    # ``usable`` travels with each one so the picker can say WHY an audience is
    # not selectable. An audience Meta calls too small still appears — hiding it
    # makes the user's own audience look like it vanished — but it says so.
    ws["audience_candidates"] = [
        {
            "id": str(a["id"]),
            "name": a.get("name") or str(a["id"]),
            "subtype": a.get("subtype") or "",
            "size": a.get("approximate_count_lower_bound"),
            "usable": _meta.audience_is_usable(a),
            "status": (a.get("delivery_status") or {}).get("description") or "",
        }
        for a in audiences
    ]
    if currency.get("currency"):
        user_info["ad_account_currency"] = currency["currency"]
    if currency.get("min_daily_budget"):
        user_info["min_daily_budget"] = currency["min_daily_budget"]
    ws["ad_account_currency"] = currency.get("currency") or ""
    ws["min_daily_budget"] = currency.get("min_daily_budget") or 0

    if not pixels:
        # Nothing on the ad account is not the same as nothing at all: a dataset
        # the advertiser owns in their business portfolio but never assigned to
        # this ad account is invisible to /adspixels, and reusing it beats running
        # the campaign as if they had none. Two extra Graph calls, paid only by
        # the accounts that have no pixel of their own — which is exactly the
        # population the answer changes anything for.
        #
        # Read HERE rather than in media_select_pixel (where it used to live)
        # because ``has_warm_dataset`` below is what steers the brief away from
        # conversion goals, and that decision is made before the objective is.
        business = await _meta.fetch_ad_account_business(ad_account_id, access_token)
        business_id = str((business or {}).get("id") or "")
        if business_id:
            ws["tracking_business_id"] = business_id
            pixels = await _meta.fetch_business_datasets(business_id, access_token)
            ws["pixel_candidates"] = [_candidate(p) for p in pixels]
            if pixels:
                writer({"type": "thinking", "content": (
                    f"media_wizard: {len(pixels)} dataset(s) in business {business_id} "
                    "but none assigned to this ad account — offering those"
                )})

    # Whether this account can optimize toward a conversion AT ALL. A dataset that
    # has never fired is not a smaller version of one that has — it is the same as
    # having none, because delivery learns from events and there are none. The
    # brief reads this to stop recommending a goal whose signal will never arrive
    # (see campaign._objective_options), so it must be the honest answer, not
    # "a pixel row exists".
    user_info["has_warm_dataset"] = any(
        c.get("last_fired_time") for c in ws["pixel_candidates"]
    )

    if not pixels:
        # Nothing anywhere — the campaign is built on a non-conversion goal, and
        # the plan editor's pixel field opens empty for anyone who wants to change
        # that.
        writer({"type": "thinking", "content": f"media_wizard: no Meta Pixel on {ad_account_id}"})
        # user_info goes back even here — the currency read above lands in it, and
        # an account with no pixel needs the right budget floor just as much.
        return {"media_wizard_state": ws, "user_info": user_info}

    # The account has a Pixel → conversion tracking is available (pixel_status is
    # narration only now). Whichever one ``_pick_dataset`` can settle is resolved
    # outright; a genuine choice is made later (with the objective) in
    # media_select_pixel.
    user_info["pixel_status"] = "verified"
    stored_id, _stored_business = await _stored_tracking_dataset(state.get("user_id"))
    chosen, why = _pick_dataset(ws["pixel_candidates"], stored_id)
    if chosen:
        ws["pixel_id"] = chosen
        user_info["pixel_id"] = chosen
        writer({"type": "thinking", "content": (
            f"media_wizard: using dataset {chosen} — {why}"
        )})
    else:
        writer({"type": "thinking", "content": (
            f"media_wizard: {len(pixels)} datasets on account, none obviously the "
            "one — will pick after objective is set"
        )})
    return {"media_wizard_state": ws, "user_info": user_info}


async def media_detect_page_assets(state: AgentState) -> dict:
    """What the connected Page already tells us, read once at connect time.

    Same shape and timing as ``media_detect_pixel``: non-interrupting,
    objective-independent, runs inside connect_meta. Three things come off the
    Page(s):

      * **the Pages themselves** — OAuth stores exactly one (whichever Meta listed
        first) and Meta does not order that list meaningfully, so an advertiser
        managing several brands published under an arbitrary Page. The live list,
        each Page's linked Instagram account, and each Page's instant forms feed
        the editor's Page picker. Read here rather than at render time for the
        same reason as the forms below.
      * **instant forms** — the plan editor's Instant form dropdown. They have to
        be in hand before the plan is built; fetching at render time would put a
        Graph call on every re-render of the editor. An empty list is normal, not
        a failure: the editor then offers only "Create one for me", which publish
        handles (``_resolve_lead_form``). Fetched per Page so switching Page in
        the editor does not leave the dropdown showing another Page's forms.
      * **website** — the intake form stopped asking for one, but ``enrich_website``
        still wants it (site scrape → business category, current offers, Meta
        Pixel). A Page that runs ads usually has it, so we read it instead of
        asking. Never overwrites a URL the user gave us.
    """
    from app.services import meta_ads as _meta

    ws = _ws(state)
    user_info: dict = dict(state.get("user_info") or {})

    access_token = user_info.get("meta_access_token", "")
    if not access_token:
        return {"media_wizard_state": ws}

    pages = await _meta.list_meta_pages(access_token)
    # The instant-form edge rejects the user token, so every read needs the Page's
    # own. Traded once for all Pages here rather than inside each list_lead_forms —
    # the trade IS a me/accounts call, and per-Page it would be one per Page.
    # Deliberately not written onto the page dicts: page_candidates is streamed to
    # the browser, and a Page token acts as the Page.
    page_tokens = await _meta.list_page_tokens(access_token)
    # ponytail: one lead-form call per Page. Fine at the handful of Pages a real
    # advertiser has; slice the list if someone shows up managing fifty.
    forms_per_page = await asyncio.gather(
        *(
            _meta.list_lead_forms(
                p["id"], access_token, page_token=page_tokens.get(p["id"], "")
            )
            for p in pages
        )
    )
    for page, forms in zip(pages, forms_per_page):
        page["lead_forms"] = forms
    ws["page_candidates"] = pages

    # The stored Page stays the default — unless the token can no longer see it,
    # in which case any Page beats publishing against one that will be rejected.
    page_ids = {p["id"] for p in pages}
    page_id = user_info.get("meta_page_id") or ws.get("page_id") or ""
    if page_id not in page_ids:
        page_id = pages[0]["id"] if pages else ""
    # Facts about the default Page, for the caller to say out loud (``connect_meta``).
    # Set only on a PROVABLE answer — ``is_published`` / ``can_advertise`` are absent
    # from the dict when the token could not read them, and absent is not "no".
    _default = next((p for p in pages if p["id"] == page_id), None) or {}
    for _flag, _key in (("page_unpublished", "is_published"), ("page_role_missing", "can_advertise")):
        if _default.get(_key) is False:
            ws[_flag] = True
        else:
            ws.pop(_flag, None)
    if not page_id:
        # Nothing to publish as. Said out loud by the caller (``connect_meta``) rather
        # than left for publish to trip on — a brand-new advertiser has no Page yet, or
        # left it unticked on the consent screen.
        ws["no_facebook_page"] = True
        return {"media_wizard_state": ws}

    ws.pop("no_facebook_page", None)
    ws["page_id"] = page_id
    chosen = next((p for p in pages if p["id"] == page_id), None)
    ws["lead_form_candidates"] = (
        (chosen or {}).get("lead_forms")
        if chosen else await _meta.list_lead_forms(
            page_id, access_token, page_token=page_tokens.get(page_id, "")
        )
    ) or []
    ig = (chosen or {}).get("instagram") or {}
    ws["instagram_user_id"] = ig.get("id") or ""

    patch: dict = {"meta_page_id": page_id}
    if not str(user_info.get("website_url") or "").strip():
        website = await _meta.fetch_page_website(page_id, access_token)
        if website:
            logger.info("media_wizard: website %s read from Page %s", website, page_id)
            patch["website_url"] = website
    return {"media_wizard_state": ws, "user_info": patch}


async def media_select_pixel(state: AgentState) -> dict:
    """
    Resolve which dataset this campaign's ad sets promote, if any.

    Skips immediately unless the campaign actually resolves to a pixel-promoted
    ad set — see ``_resolved_shape``. Auto-selects when only one dataset
    exists; fires an option_selection interrupt on a genuine choice. Stores the
    result in media_wizard_state; build_campaign_spec turns it into the ad set's
    promoted_object.

    Also fills in ``tracking_method`` for a run that was never asked (express),
    because an empty method reads as "browser pixel AND server events" in
    TrackingService and hands a beginner an ingest key they cannot use.

    Reads the objective from ``user_info`` (the collected slot), NOT from
    ``marketing_plan`` — this node runs before the plan is built, so the plan can
    be built against a real pixel id instead of being patched afterwards. The
    brief is already on the state by then, which is what makes the destination
    and goal resolvable here.
    """
    from app.services import meta_ads as _meta

    writer = get_writer()
    ws = _ws(state)
    user_info: dict = dict(state.get("user_info") or {})

    objective = normalize_objective(user_info.get("campaign_objective"))
    if objective is None:
        return {"media_wizard_state": ws}

    access_token = user_info.get("meta_access_token", "")
    ad_account_id = user_info.get("meta_ad_account_id", "")
    event_type = DEFAULT_PIXEL_EVENT.get(objective, "PURCHASE")
    # Guide mode's answer. Express is never asked and leaves this empty — filled
    # in below from the shape the campaign actually resolved to, because empty
    # reads as "pixel AND server" everywhere downstream.
    tracking_method = str(user_info.get("tracking_method") or "").strip()
    label = objective.value
    user_id = state.get("user_id")

    # Whether THIS campaign promotes a dataset — not whether its objective could.
    #
    # The old gate was the objective alone, which was wrong in both directions.
    # Leads defaults to instant forms, whose promoted object is the Page: that run
    # had a dataset resolved for it, created if the account had none, was told to
    # install it, and was then reported as never firing for the rest of time. And
    # Sales on an account with no dataset now resolves to a landing-page-view
    # goal, which promotes nothing either.
    dest, goal = _resolved_shape(user_info, dict(state.get("campaign_brief") or {}))
    promoted_kind = dest.promoted_object_kind(goal) if dest and goal else PROMOTED_NONE
    if promoted_kind != PROMOTED_PIXEL:
        # Only for the objectives where conversion tracking is a question at all.
        # The account row is shared by every campaign this account runs, and
        # stamping "lead_forms" on it because someone published an Awareness
        # campaign would overwrite a real answer given for a Sales one.
        if objective in _PIXEL_OBJECTIVES and not tracking_method:
            tracking_method = _derived_tracking_method(dest, goal)
            if tracking_method:
                user_info["tracking_method"] = tracking_method
                await _remember_tracking_method(user_id, tracking_method)
        ws["promoted_object"] = None
        goal_label = goal.value if goal else ""
        writer({"type": "thinking", "content": (
            f"media_wizard: {label} resolved to a {promoted_kind}-promoted ad set "
            f"on {goal_label or 'the default goal'} — no dataset involved"
        )})
        # Say it out loud when the campaign is NOT optimizing for the thing the
        # objective's name promises. Picking "Sales" and getting an ad set that
        # optimizes for landing-page views is the right call on an account with no
        # dataset — and a nasty surprise to discover from the reporting three days
        # later. Only when the account genuinely has nothing: an instant-form
        # Leads campaign is what Leads means, and needs no apology.
        if objective in _PIXEL_OBJECTIVES and not user_info.get("has_warm_dataset"):
            add_beat(
                state, "reveal",
                {
                    "stage": "conversion_goal_downgraded",
                    "objective": label,
                    "optimization_goal": goal_label,
                },
                fallback=(
                    "No Meta dataset on this account has ever recorded an event, so "
                    f"I built this to optimize for **{meta_label(goal_label)}** instead of "
                    "conversions — Meta can only learn from signals it actually "
                    "receives. Install a Pixel and fire one event, and the next "
                    "campaign can optimize for the conversion itself."
                ),
            )
        return {"media_wizard_state": ws, "user_info": user_info}

    if not tracking_method:
        tracking_method = _derived_tracking_method(dest, goal)
        user_info["tracking_method"] = tracking_method

    stored_id, stored_business = await _stored_tracking_dataset(user_id)
    # media_detect_pixel looks the business up when the ad account has no dataset
    # of its own, so this is usually already answered.
    business_id = str(ws.get("tracking_business_id") or "") or stored_business

    # Reuse the candidates media_detect_pixel already fetched at connect time
    # (avoids a second Graph API call); fall back to a live fetch if absent.
    cached = ws.get("pixel_candidates")
    pixels = [
        _candidate(p)
        for p in (cached if cached else await _meta.fetch_ad_pixels(ad_account_id, access_token))
    ]

    if not pixels:
        # Reaching here at all means somebody asked for conversion optimization on
        # an account with nothing to optimize against — which now only happens
        # when a guide user picked "Create one for me" on the intake form.
        #
        # Punk does not create a dataset on its own initiative any more. It used
        # to, on the theory that Sales and Leads cannot publish without one; they
        # can, and _objective_options + _resolve_goal now steer an account with no
        # warm dataset onto the goal that needs none. A dataset created here
        # measures nothing until it is installed on the site, so it bought the
        # advertiser a campaign optimizing toward an event that would never
        # arrive — strictly worse than the landing-page-view campaign they get
        # instead.
        if str(user_info.get("pixel_id") or "").strip() != CREATE_DATASET:
            writer({"type": "thinking", "content": (
                f"media_wizard: no dataset on {ad_account_id} — leaving the "
                "promoted object unset for the plan editor"
            )})
            ws["promoted_object"] = None
            ws["pixel_id"] = None
            ws["pixel_candidates"] = []
            return {"media_wizard_state": ws, "user_info": user_info}

        # Creating the Pixel is NOT the same as tracking working: it still has to
        # be installed on the site. The beat below says so, and the publish
        # preview reads last_fired_time before offering to go live.
        pixel_name = f"{user_info.get('business_name') or 'Punk'} Pixel"
        try:
            writer({"type": "update", "content": "Setting up conversion tracking in your ad account..."})
            # In the user's business portfolio when they have one, so the dataset
            # can serve every ad account they own and is not capped by the
            # one-pixel-per-account rule. The dataset belongs to THEM either way —
            # Punk owns no Meta assets.
            if business_id:
                new_id = await _meta.create_business_dataset(
                    pixel_name, business_id, access_token
                )
                # Owning it in the business is not enough: an ad set's
                # promoted_object only accepts a dataset assigned to the ad account
                # running the ads.
                if not await _meta.share_dataset_with_account(
                    new_id, ad_account_id, access_token
                ):
                    writer({"type": "thinking", "content": (
                        f"Dataset {new_id} created but not assigned to {ad_account_id} — "
                        "publish preflight will confirm whether it is usable"
                    )})
            else:
                # No business portfolio (a personal ad account) — nothing to
                # create in, so the dataset lives on the ad account itself.
                new_id = await _meta.create_ad_pixel(pixel_name, ad_account_id, access_token)
        except _meta.MetaAdsError as exc:
            # Leave the pixel unset and let the plan editor be the place the user
            # resolves it. Creating one is a convenience, never a prerequisite.
            logger.warning("media_wizard: pixel creation failed — %s", exc)
            writer({"type": "thinking", "content": f"Could not create a Pixel: {exc}"})
            ws["promoted_object"] = None
            ws["pixel_id"] = None
            ws["pixel_candidates"] = []
            return {"media_wizard_state": ws, "user_info": user_info}

        ws["pixel_id"] = new_id
        # Same builder every other branch uses, so a standard event the user
        # picked on the intake form survives instead of being overwritten with the
        # objective default. A custom conversion cannot: it is a rule defined over
        # a DIFFERENT dataset, and naming it against a brand-new one publishes an
        # ad set that optimizes for something that can never fire.
        ws["promoted_object"] = _tracking_promoted_object(
            new_id,
            {k: v for k, v in user_info.items() if k != "custom_conversion_id"},
            event_type,
        )
        ws["pixel_candidates"] = [{"id": new_id, "name": pixel_name, "last_fired_time": ""}]
        ws["pixel_created"] = True
        # Read back by _tracking_extra for the publish gate and the tracking card;
        # without this write it was permanently "".
        ws["tracking_business_id"] = business_id
        await _remember_tracking_dataset(
            user_id, new_id, business_id, _resolved_event_type(ws), tracking_method,
        )
        add_beat(
            state, "reveal",
            {
                "stage": "pixel_created",
                "pixel_name": pixel_name,
                "pixel_id": new_id,
                "objective": label,
            },
            fallback=(
                f"I set up a Meta Pixel called **{pixel_name}** in your ad account, "
                "the way you asked. Install it on your site so Meta can see the "
                "conversions it drives; until it fires, delivery is optimizing "
                "without that signal."
            ),
        )
        return {"media_wizard_state": ws, "user_info": user_info}

    ws["pixel_candidates"] = pixels

    # Already answered on the express intake form — don't ask again.
    #
    # The membership test is the point, not a formality: this same slot can hold
    # a Pixel scraped off the advertiser's WEBSITE, which may belong to an
    # entirely different ad account. Publishing that id fails, and the editor's
    # account-scoped picker cannot even display it — the hazard _resolved_pixel_id
    # documents. An id that is not on this account falls through to the normal
    # auto-select / picker below.
    picked = str(user_info.get("pixel_id") or "").strip()
    if picked and any(str(p["id"]) == picked for p in pixels):
        ws["pixel_id"] = picked
        ws["promoted_object"] = _tracking_promoted_object(picked, user_info, event_type)
        ws["tracking_business_id"] = business_id
        await _remember_tracking_dataset(
            user_id, picked, business_id, _resolved_event_type(ws), tracking_method,
        )
        writer({"type": "thinking", "content": f"Using pixel {picked} (chosen on the intake form) for {label}"})
        return {"media_wizard_state": ws, "user_info": user_info}

    chosen, why = _pick_dataset(pixels, stored_id)
    if chosen:
        ws["pixel_id"] = chosen
        ws["promoted_object"] = _tracking_promoted_object(chosen, user_info, event_type)
        ws["tracking_business_id"] = business_id
        await _remember_tracking_dataset(
            user_id, chosen, business_id, _resolved_event_type(ws), tracking_method,
        )
        writer({"type": "thinking", "content": (
            f"Using dataset {chosen} for {label} — {why}"
        )})
        return {"media_wizard_state": ws, "user_info": user_info}

    # A real choice — several warm datasets, or several cold ones. Let the user pick.
    options = [f"{p.get('name', 'Unnamed')} — {p['id']}" for p in pixels]
    pixel_status = user_info.get("pixel_status", "")
    status_note = {
        "verified": "Great — your Pixel is installed and verified. ",
        "unverified": "Got it — your Pixel is installed. ",
    }.get(pixel_status, "")
    writer({"type": "assistant_message", "content": (
        f"{status_note}I found **{len(pixels)} Pixels** in your ad account."
    )})
    response = await wizard_interrupt(
        writer,
        step_key="media_select_pixel",
        context=_session_summary(state) + f"; Pixel selection for {label} objective — {len(pixels)} pixels found",
        state=state,
        options_override=options,
        skip_ask=True,
        progress=_build_media_progress(ws, state.get("user_info")),
    )
    # Any OTHER field the user changed in the same breath ("and add Toronto").
    # Parked for builder_plan; before this it was acked and dropped. Edits to
    # the Meta account/pixel/page themselves never reach here — edit_block_reason
    # refuses those upstream as `meta_account`.
    #
    # Stash onto the shared `media_wizard_state`, not the local `ws` copy — see
    # the matching note in media_check_meta_auth.
    stash_edits(state.get("media_wizard_state") or ws, response)
    if not getattr(response, "answered", True):
        # Not a pick (an edit / question) — never read it as an unmatched
        # choice. Re-ask once builder_plan has applied its edits.
        raise StepPaused()
    resolved = resolve_option(response, options)
    selected = next(
        (p for p in pixels if p["id"] in resolved or p.get("name", "") in resolved),
        None,
    )
    if selected is None:
        # An unmatched reply used to fall back to pixels[0] — a silent guess at
        # the exact moment the user's answer proved unreadable. Leave the
        # dataset unset instead: _resolve_goal steps the optimization goal
        # down, same as an account with nothing to pick, and the user can name
        # a pixel later from the plan editor.
        writer({"type": "thinking", "content": (
            f"Couldn't match a pixel from the reply for {label}; leaving conversion tracking unset."
        )})
        return {"media_wizard_state": ws, "user_info": user_info, "pending_action": None}
    ws["pixel_id"] = selected["id"]
    ws["promoted_object"] = _tracking_promoted_object(selected["id"], user_info, event_type)
    ws["tracking_business_id"] = business_id
    await _remember_tracking_dataset(
        user_id, selected["id"], business_id, _resolved_event_type(ws), tracking_method,
    )
    writer({"type": "thinking", "content": f"User selected pixel {selected['id']} for {label}"})
    return {"media_wizard_state": ws, "user_info": user_info, "pending_action": None}
