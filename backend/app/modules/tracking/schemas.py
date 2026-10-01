"""Request/response shapes for conversion event ingest.

Deliberately not Meta's schema. The thing hitting these endpoints is the
advertiser's own site or CRM — a Shopify webhook, a Zapier step, a WordPress
plugin, someone's PHP — and asking them to learn ``user_data.em`` as a list of
SHA-256 digests is asking them not to integrate. They send readable fields; the
service normalizes, hashes and maps to Meta's wire format.
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Meta reads a hashed identifier as a lowercase hex SHA-256 digest and nothing
# else. An uppercase or truncated one is accepted by the API, matched to nobody,
# and reads as working tracking — the failure this module keeps closing — so it is
# refused here instead.
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# The identifiers a caller may hand us already hashed. Same names Meta's
# ``USER_DATA_HASHED`` maps to the wire, minus the two the request schema does not
# expose at all (date_of_birth, gender) — nothing can pre-hash a field it was never
# asked for.
PRE_HASHED_FIELDS: tuple[str, ...] = (
    "email", "phone", "first_name", "last_name", "city", "state", "zip", "country",
)


class TrackingEventRequest(BaseModel):
    """One conversion, as the advertiser's system knows it."""

    model_config = ConfigDict(extra="forbid")

    # "Purchase", "Lead", "CompleteRegistration" … or a custom event name.
    event_name: str = Field(min_length=1, max_length=100)
    # Unix seconds. Defaults to now, which is right for a webhook firing on the
    # event and wrong for a nightly CRM export — so an exporter should send it.
    event_time: int | None = None
    # Deduplication against the browser pixel. Omitted means we derive one; see
    # ``meta_capi.make_event_id`` for why a derived id still deduplicates.
    event_id: str | None = None
    # Where it happened. "website" is the common case; a CRM sending qualified
    # leads should say "system_generated", a call centre "phone_call".
    action_source: str = "website"
    event_source_url: str | None = None

    # ── value ────────────────────────────────────────────────────────────────
    value: float | None = None
    # Required alongside a value. No default: Punk sells into the US, Canada and
    # Bangladesh, so assuming USD silently misreports every non-US purchase and
    # corrupts the ROAS the campaign is optimized against.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    content_ids: list[str] | None = None
    order_id: str | None = None

    # ── identity ─────────────────────────────────────────────────────────────
    # Plain values. Hashed before they leave the process — never store or log the
    # raw ones.
    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    country: str | None = None
    # Your own customer id. Sent to Meta unhashed and never used to look anyone up
    # here — it only has to be stable per person.
    external_id: str | None = None
    # Meta's own cookies, read from _fbp / _fbc on the page. Worth more than
    # everything above for matching a website conversion, and the reason the
    # snippet forwards them.
    fbp: str | None = None
    fbc: str | None = None
    # Meta Lead ID, for instant-form leads coming back from a CRM.
    lead_id: str | None = None

    # ── identity, already hashed ─────────────────────────────────────────────
    # For a caller who would rather Punk never saw the raw value. Send these
    # INSTEAD of the plain field above, as a lowercase hex SHA-256 digest, and
    # apply Meta's normalization yourself first — lowercase and trim everything,
    # digits only for a phone (country code included), the 5-digit prefix for a
    # US zip, a 2-letter country code. A digest of un-normalized input is a valid
    # digest of the wrong string, and Meta cannot tell you that.
    email_sha256: str | None = None
    phone_sha256: str | None = None
    first_name_sha256: str | None = None
    last_name_sha256: str | None = None
    city_sha256: str | None = None
    state_sha256: str | None = None
    zip_sha256: str | None = None
    country_sha256: str | None = None

    # ── privacy ──────────────────────────────────────────────────────────────
    # Attribution only — the event will not feed ad optimization.
    opt_out: bool = False
    # Limited Data Use. Set it for visitors in US states whose laws require it.
    limited_data_use: bool = False

    @model_validator(mode="after")
    def _value_names_its_currency(self) -> TrackingEventRequest:
        if self.value is not None and not self.currency:
            raise ValueError(
                "currency is required with value — an amount with no currency "
                "cannot be reported or optimized against"
            )
        return self

    @model_validator(mode="after")
    def _has_something_to_match_on(self) -> TrackingEventRequest:
        """Meta needs at least one identifier to attribute an event.

        Without one the event is accepted, matched to nobody, and shows up as a
        conversion that no campaign gets credit for — the failure that looks like
        working tracking. The client IP and user agent are added by the endpoint,
        but those alone match almost nothing, so they do not count here.
        """
        if not any((
            self.email, self.phone, self.external_id, self.fbp, self.fbc,
            self.lead_id, self.email_sha256, self.phone_sha256,
        )):
            raise ValueError(
                "send at least one of: email, phone, external_id, fbp, fbc, "
                "lead_id (or email_sha256 / phone_sha256)"
            )
        return self

    @model_validator(mode="after")
    def _hashes_are_hashes(self) -> TrackingEventRequest:
        """A malformed digest is refused rather than forwarded.

        Meta accepts any string here and matches it to nobody, so a typo'd or
        uppercase digest produces a dataset that looks healthy while attributing
        nothing — worse than an error, because nothing ever surfaces it.
        """
        for field in PRE_HASHED_FIELDS:
            value = getattr(self, f"{field}_sha256", None)
            if value and not _SHA256_HEX.match(value):
                raise ValueError(
                    f"{field}_sha256 must be a lowercase hex SHA-256 digest "
                    "(64 characters)"
                )
        return self

    @model_validator(mode="after")
    def _one_form_per_identifier(self) -> TrackingEventRequest:
        """Plain and hashed for the same field is refused, not silently resolved.

        Which one won would be invisible to the caller, and the two can disagree —
        a digest of a different address than the plaintext beside it attributes the
        conversion to the wrong person, or to nobody.
        """
        both = [
            field for field in PRE_HASHED_FIELDS
            if getattr(self, field, None) and getattr(self, f"{field}_sha256", None)
        ]
        if both:
            raise ValueError(
                "send either the plain value or the hash, not both: "
                + ", ".join(sorted(both))
            )
        return self


class TrackingEventBatch(BaseModel):
    """Several conversions in one call — a CRM export, or a retry queue flush."""

    model_config = ConfigDict(extra="forbid")

    events: list[TrackingEventRequest] = Field(min_length=1, max_length=1000)
    # Which dataset to report to, when the ad account has more than one — a second
    # website usually means a second dataset, and sending both sites' conversions
    # to the remembered default deduplicates against the wrong pixel and attributes
    # to the wrong campaign. Omit it and the account's default is used, which is
    # every advertiser with one site. Not validated here: send_events goes out on
    # the account's own token, so Meta rejects any dataset that token cannot write.
    dataset_id: str | None = None
    # Routes to Events Manager → Test events instead of live reporting. Never set
    # this in production.
    test_event_code: str | None = None


class TrackingEventResponse(BaseModel):
    # Meta's own count, not ours.
    events_received: int
    # The ids we sent, so the caller can reconcile or reuse them in a browser
    # pixel call for the same action.
    event_ids: list[str]
    errors: list[str] = []


class TrackingHealthResponse(BaseModel):
    """Is tracking actually working? The honest answer, for the go-live gate."""

    dataset_id: str = ""
    dataset_name: str = ""
    business_id: str = ""
    # None means it has never fired — a dataset that exists and measures nothing.
    last_fired_time: str | None = None
    # Meta's Event Match Quality, 0–10. Below ~6 means the identifiers being sent
    # resolve to too few real accounts to optimize well.
    event_match_quality: float | None = None
    # What the dataset actually received in the last 7 days, biggest first:
    # [{"name": "Purchase", "count": 412}]. Empty when the read failed OR when
    # nothing has arrived — the two are not distinguishable from here, which is
    # why nothing is accused on an empty list.
    events: list[dict] = []
    # The event this account's campaigns optimize toward, in Meta's wire spelling.
    # "" when no conversion campaign has been built, or when the account optimizes
    # for a custom conversion.
    conversion_event: str = ""
    server_events_seen: bool = False
    events_manager_url: str = ""
    # How this account's conversions reach Meta. "" until a campaign has resolved
    # one. A method with no browser half ("lead_forms", "offline_crm") is why a
    # healthy account can legitimately have no dataset at all.
    tracking_method: str = ""
    # "ok" | "no_dataset" | "never_fired" | "token_invalid"
    status: str = "ok"
    # What the user has to go do in Meta themselves, when the status says
    # something is wrong. Every entry is {key, title, cause, steps, url, effect,
    # severity} — see services/meta_remediation. Empty when tracking is healthy.
    remediation: list[dict] = []


class CustomConversionRequest(BaseModel):
    """Define a conversion from a page URL, without touching the site.

    The repair for the most common broken setup there is: the base pixel is
    installed site-wide (so PageView arrives), no event code was ever added to
    the thank-you page, and the campaign is therefore optimizing toward an event
    that will never fire. A URL rule turns the PageViews Meta already receives
    into the conversion — no developer, no deploy.
    """

    name: str = Field(min_length=1, max_length=100)
    # Matched case-insensitively against the whole URL, which is what Events
    # Manager's own "URL contains" builds.
    url_contains: str = Field(min_length=1, max_length=500)
    # What KIND of conversion this counts as. Meta uses it to categorize the
    # conversion and to pick the optimization it can offer.
    custom_event_type: str = Field(default="PURCHASE", max_length=50)


class CustomConversionResponse(BaseModel):
    id: str
    name: str
    custom_event_type: str = ""


class TrackingSnippetResponse(BaseModel):
    dataset_id: str = ""
    # The event the snippet actually fires. Defaults to whatever the account's
    # campaigns optimize toward, not a fixed "Purchase" — see
    # meta_capi.event_name_for for why the two spellings have to agree.
    event_name: str = ""
    # Meta's standard events, so the card can offer a picker without a second
    # round trip. A name outside this list is a custom event, which Meta accepts.
    event_names: list[str] = []
    # Browser pixel base code + the event call, ready to paste before </head>.
    pixel_snippet: str = ""
    # curl example for the server-side half, posted to Punk.
    server_example: str = ""
    # The same conversion posted straight to Meta instead, on a system user token
    # the advertiser holds. Punk never sees those requests. Offered beside the one
    # above so where the data goes is their choice rather than our default.
    server_direct_example: str = ""
    ingest_url: str = ""
    # The ad account's own currency, which is the one Meta reads a conversion
    # value in. Carried so the card can say so beside the snippet rather than the
    # user discovering it from a ROAS number priced in the wrong money.
    currency: str = "USD"
    # Shown once per rotation. Treat as a password.
    ingest_key: str = ""
    instructions: list[str] = []
    # How this account reports conversions. Decides which of the blocks above are
    # populated at all — a "pixel only" setup gets no key, a CRM setup no snippet.
    tracking_method: str = ""


class TrackingDatasetItem(BaseModel):
    id: str
    name: str = ""
    # "" for a dataset nobody ever installed. Shown beside the name so a user
    # choosing between two is not choosing blind.
    last_fired_time: str = ""


class TrackingDatasetsResponse(BaseModel):
    datasets: list[TrackingDatasetItem] = []
    # "" until one is resolved. Empty `datasets` means either the account has none
    # or the read failed — not distinguishable from here, so neither is accused.
    selected: str = ""


class TrackingDatasetRequest(BaseModel):
    """Attach a dataset the ad account can already write to.

    Rejected server-side if it is not on the account's own list — an id that
    cannot be written to publishes ad sets optimizing toward an event that can
    never fire, which Meta reports as a campaign delivering normally.
    """

    dataset_id: str = Field(min_length=1, max_length=100)


class TrackingMethodRequest(BaseModel):
    """How this account's conversions reach Meta.

    One of the four TRACKING_METHODS values. The ingest key is NOT rotated on a
    switch: moving to a method with no server half stops showing the key, it does
    not invalidate one that is live in a customer's checkout.
    """

    method: str = Field(min_length=1, max_length=32)


class TrackingSystemTokenRequest(BaseModel):
    """A system user token the advertiser generated in their OWN Business Settings.

    Optional everywhere: without one, server events ride the user's OAuth token,
    which expires — the whole reason ``tracking_token_expired`` exists as a fix-it
    card. Until now that card told users to mint a token with nowhere to put it.
    """

    # Meta tokens are long and have no fixed length; the bound is here to reject a
    # pasted essay, not to validate the token. Emptiness is how you clear one.
    token: str = Field(default="", max_length=1000)


class TrackingEventLogItem(BaseModel):
    """One forwarded event, as the log kept it.

    No identifiers — see ``models.TrackingEvent`` for why the log records the
    shape of a conversion and never who made it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    event_name: str
    event_id: str | None = None
    action_source: str | None = None
    value: float | None = None
    currency: str | None = None
    # Meta's count for the batch this event was part of.
    events_received: int = 0
    error: str | None = None
    created_at: datetime | None = None
