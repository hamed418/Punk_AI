"""
graph/builder/intake_form.py
────────────────────────────
The campaign **intake form** — express-only now. Guide mode never sees it: the
entry gate collects business name and what-you-sell/USP before the build even
starts (WHAT is a required routing-gate signal, same as WHERE/WHO), and
``campaign.generate_brief`` infers the objective when the user never states one
— so guide walks straight from the publish-mode question to the plan editor.

Express still needs a form: its editor locks the campaign and ad-set panes
entirely (see ``_plan_form_extra``), so budget, flight dates, which Page, where
the ad points, and the objective select have no other surface to be asked on.
Business name and what-you-sell arrive here too, prefilled from the same entry
gate — express just doesn't get to skip the question the way guide does, since
it still needs *some* fields from this form regardless.

Everything else the old intake asked for beyond that — conversion location,
WhatsApp number, and which previous campaign to start from — opens as a
*filled-in* plan in the campaign editor instead of as an empty question here.
The editor already renders every one of those as an editable field, so asking
twice was the only thing the intake form was buying.

``app_store_url`` / ``play_store_url`` are the one exception, shown only for App
Promotion: Meta requires the application being promoted and a store URL, and
unlike a website — which falls back to the connected Page — there is nothing to
fall back to, so the spec cannot be built at all without them.

The website was not replaced by a default so much as by a better source: the
connected Facebook Page carries one, read at connect time
(``media_detect_page_assets``), so ``enrich_website`` still scrapes the site for
business category and current offers without anyone being asked.

It emits a field-descriptor contract (``key`` / ``label`` / ``type`` /
``options`` / ``visible_when`` / ``help`` / ``suggestion`` / ``editable``) the
client renders with DynamicForm. One contract extension lives here and nowhere
else: option dicts may carry ``description``, the long line the objective select
shows under each label.

Nothing here is objective-*matrix* aware beyond the objective option list — the
heavy Meta rules stay in ``meta_spec``. This module only turns a submission into
the same ``filled`` / ``user_info`` shape the downstream brief and spec builders
already expect.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.graph.meta_spec.enums import (
    Objective,
    normalize_objective,
)
from app.graph.meta_spec.objective_matrix import OBJECTIVE_MATRIX
from app.graph.meta_spec.parsing import CURRENCY_PREFIX, minor_units

logger = logging.getLogger(__name__)

INTAKE_ACTION_TYPE = "campaign_intake_form"
INTAKE_FIELD = "campaign_intake"

# The one objective whose plan cannot be built without a store link: Meta demands
# a promoted application, and unlike a website there is no Page-level fallback.
_APP_ONLY = {"objective": [Objective.APP_PROMOTION.value]}

_SKIP_TOKENS = {"skip", "none", "no", "n/a", "na", ""}


# ── URL normalization ────────────────────────────────────────────────────────


def normalize_url(raw: str | None) -> str:
    """Skip token → "" ; otherwise ensure an http(s) scheme. Moved here from the
    old ``_normalize_slot_answer`` website_url/app_link branches."""
    cleaned = str(raw or "").strip()
    if cleaned.lower() in _SKIP_TOKENS:
        return ""
    return cleaned if cleaned.startswith(("http://", "https://")) else f"https://{cleaned}"


# ── schema ───────────────────────────────────────────────────────────────────


def _field(key: str, label: str, type_: str, *, required: bool = False, **kw: Any) -> dict[str, Any]:
    """One field descriptor.

    ``required`` is emitted on EVERY field, never omitted: the client falls back
    to "every editable field is required" when the flag is absent, so an optional
    field that simply left it out would still block submit. Default False — only
    what ``parse_intake_submission`` actually rejects a submission over says True.
    """
    field: dict[str, Any] = {
        "key": key, "label": label, "type": type_, "editable": True, "required": required,
    }
    for name, value in kw.items():
        if value is None or value == "":
            continue
        # Trailing underscore avoids the Python keyword clash on `help`.
        field[name.rstrip("_")] = value
    return field


def _first_nonempty(*values: Any) -> str:
    for v in values:
        text = str(v or "").strip()
        if text:
            return text
    return ""


def build_intake_schema(
    *,
    user_info: dict,
    enrichment: dict | None = None,
    errors: dict | None = None,
    pages: list[dict] | None = None,
    currency: str = "USD",
    min_budget_cents: int | None = None,
    page_website: str = "",
    lead_forms: list[dict] | None = None,
    pixels: list[dict] | None = None,
    budget_suggestion: int | None = None,
    budget_reason: str = "",
) -> dict[str, Any]:
    """The intake form descriptor. Prefill lives in each field's ``suggestion``
    (there is no separate top-level values map — the form starts from these).

    Express-only (see the module docstring): the user never sees the campaign or
    ad-set halves of the plan editor, so the handful of fields that publishing
    genuinely cannot default — budget, flight dates, which Page, where the ad
    points, the objective — have to be asked here instead. Everything still
    defaultable (placements, bid strategy, optimization goal, targeting) stays
    defaulted.

    The dataset line here only ever shows one that has already fired, as a fact
    rather than a question (see ``_express_fields``) — a cold pixel cannot carry
    the campaign anyway (``_resolve_goal`` steers away from the conversion goal
    entirely), so there is nothing to offer creating one for.

    Where the ad's creative comes from (generate one / promote an existing
    post / reuse an older ad's post) is asked NOWHERE on this form any more —
    "Punk writes it" is the default, and a user who wants to promote something
    they already published still picks it per ad set in the plan editor's own ad
    card (``AdCard.tsx``'s "Write a new ad / Promote an existing post" toggle,
    and ``PagePostPicker``). Asking here bought a question in front of a user
    who has not yet seen an ad to judge it against — the same reasoning the rest
    of this module's docstring gives for everything else that moved to the
    editor.

    Which event and how the events reach Meta are asked NOWHERE any more. Both
    are defaultable (``DEFAULT_PIXEL_EVENT`` supplies the event,
    ``_derived_tracking_method`` the method) and both are rendered again in the
    plan editor — the ad-set panel's event select and the campaign panel's
    tracking-method select. Asking here bought a duplicate question in front of
    a user who has not yet seen a plan to judge it against.
    """
    enrichment = enrichment or {}

    name_sugg = _first_nonempty(user_info.get("business_name"), enrichment.get("business_name"))
    context_sugg = _first_nonempty(
        user_info.get("business_description"),
        user_info.get("product_offer"),
        enrichment.get("products_services"),
    )
    objective_sugg = _first_nonempty(user_info.get("campaign_objective")) or None
    if objective_sugg:
        obj = normalize_objective(objective_sugg)
        objective_sugg = obj.value if obj else None

    about_fields = [
        _field(
            "business_name", "Business name", "text",
            required=True,
            suggestion=name_sugg,
            help_="Only needed if we couldn't detect it from your Meta account.",
        ),
        _field(
            "business_context", "What you sell & what makes you the best", "textarea",
            required=True,
            suggestion=context_sugg,
            help_="One or two lines — your product or service and your edge. Shapes the whole plan.",
        ),
        _field(
            "objective", "Campaign objective", "select",
            required=True,
            options=[
                {
                    "value": o.value,
                    "label": rules.label,
                    "description": rules.help_text,
                }
                for o, rules in OBJECTIVE_MATRIX.items()
            ],
            suggestion=objective_sugg,
            help_=(
                "What the campaign is for. It decides which conversion "
                "options, ad format and pricing are available below."
            ),
        ),
        _field(
            "app_store_url", "App Store URL", "text",
            suggestion=user_info.get("app_store_url") or None,
            visible_when=_APP_ONLY,
            help_="Apple App Store link. App campaigns need at least one store link.",
        ),
        _field(
            "play_store_url", "Google Play URL", "text",
            suggestion=user_info.get("play_store_url") or None,
            visible_when=_APP_ONLY,
            help_="Google Play link. App campaigns need at least one store link.",
        ),
    ]

    targeting_fields, budget_fields = _express_fields(
        user_info=user_info,
        pages=pages or [],
        currency=currency,
        min_budget_cents=min_budget_cents,
        page_website=page_website,
        lead_forms=lead_forms or [],
        pixels=pixels or [],
        budget_suggestion=budget_suggestion,
        budget_reason=budget_reason,
    )

    # Two labeled sections beyond "about" — DynamicForm renders exactly the
    # ones that have fields.
    groups: list[dict[str, Any]] = [
        {"key": "about", "label": "About your business", "repeat": False, "fields": about_fields},
    ]
    if targeting_fields:
        groups.append(
            {"key": "targeting", "label": "Where this points", "repeat": False, "fields": targeting_fields}
        )
    if budget_fields:
        groups.append(
            {"key": "budget", "label": "Budget & schedule", "repeat": False, "fields": budget_fields}
        )

    schema: dict[str, Any] = {"groups": groups}
    if errors:
        schema["errors"] = errors
    return schema


def _express_fields(
    *,
    user_info: dict,
    pages: list[dict],
    currency: str,
    min_budget_cents: int | None,
    page_website: str,
    lead_forms: list[dict],
    pixels: list[dict] | None = None,
    budget_suggestion: int | None = None,
    budget_reason: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The extra express-mode questions, split into (targeting, budget) so
    ``build_intake_schema`` can render them as two labeled sections instead
    of one flat run — in the order image 2 shows them within each.

    Only two of the targeting fields are unconditional. The Page picker
    appears solely when the account has more than one Page (with one there is
    nothing to choose), and the website only when the connected Page did not
    already carry one — ``connect_meta`` reads it at
    ``media_detect_page_assets`` and asking again for something we have is the
    exact thing the slimmed-down intake exists to avoid.
    """
    out: list[dict[str, Any]] = []
    budget: list[dict[str, Any]] = []

    if len(pages) > 1:
        out.append(_field(
            "page_id", "Facebook Page", "select",
            options=[
                {"value": str(p.get("id")), "label": str(p.get("name") or p.get("id"))}
                for p in pages if p.get("id")
            ],
            suggestion=str(user_info.get("meta_page_id") or "") or None,
            help_="The Page your ads run from.",
        ))

    if not page_website:
        out.append(_field(
            "website_url", "Website", "text",
            suggestion=user_info.get("website_url") or None,
            # Never required, on any objective. A website is a prerequisite of
            # the *destination*, not of the objective — Sales sells through
            # Messenger or WhatsApp, Engagement runs on a post — and
            # build_conversion_options already drops every destination whose
            # required_user_info is missing, so a blank here steers the brief
            # onto a location that needs no site rather than breaking the plan.
            help_=(
                "Where the ad sends people. Leave it blank and we'll point the "
                "ad somewhere that doesn't need one — your Page, Messenger or "
                "WhatsApp."
            ),
        ))

    # Not the tracking group — one line of it, and only the half that is a fact
    # rather than a question. Express hides the ad-set panel, so which event and
    # how the events arrive are still resolved by media_select_pixel (see
    # build_intake_schema); WHICH dataset the money is measured against is worth
    # showing, because a Sales campaign is about to be built on it.
    #
    # Shown only when a dataset on this account has actually fired: a cold one
    # cannot carry the campaign (_resolve_goal steers away from the conversion
    # goal entirely), so naming it here would promise measurement that is not
    # going to happen. And only for Sales — Leads runs on an instant form, whose
    # conversions are counted by Meta with no dataset in the picture at all.
    #
    # A select over the warm datasets rather than a read-only label: DynamicForm
    # has no read-only kind, the submitted value pins the dataset the user was
    # actually shown, and an advertiser with two live datasets does get a say.
    warm = [
        p for p in (pixels or [])
        if p.get("id") and str(p.get("last_fired_time") or "").strip()
    ]
    if warm:
        out.append(_field(
            "pixel_id", "Conversion tracking", "select",
            options=[
                {
                    "value": str(p["id"]), "label": str(p.get("name") or p["id"]),
                    "description": f"Last fired {p['last_fired_time']}",
                }
                for p in warm
            ],
            # No warm[0] default: a preselected pixel reads as "Punk verified
            # this" and gets submitted without looking. Blank is a real,
            # submittable answer even here.
            suggestion=str(user_info.get("pixel_id") or ""),
            visible_when={"objective": [Objective.SALES.value]},
            help_="Where this campaign's conversions get reported. It stays in your Meta account.",
        ))

    # The form leads land in. Only Leads uses one, and only its instant-form
    # destination — which is the objective's default, and the one express takes.
    # Publish creates a name/email/phone form when this is blank
    # (media._resolve_lead_form), so "" is a real answer, not a skip.
    out.append(_field(
        "lead_form_id", "Instant form", "select",
        options=[
            {"value": "", "label": "Create a default one for me",
             "description": "Name, email and phone number."},
            *(
                {"value": str(f["id"]), "label": str(f.get("name") or f["id"])}
                for f in lead_forms if f.get("id")
            ),
        ],
        visible_when={"objective": [Objective.LEADS.value]},
        help_="Where the people who click your ad leave their details.",
    ))

    budget.append(_field(
        "budget_type", "Campaign budget type", "select",
        options=[
            {"value": "daily", "label": "Daily", "description": "Spend up to this much every day."},
            {"value": "lifetime", "label": "Lifetime",
             "description": "Spend this much in total across the whole flight."},
        ],
        suggestion=str(user_info.get("budget_type") or "daily"),
        help_="Set at the campaign level — Meta spreads it across ad sets for you.",
    ))
    budget.append(_field(
        "budget_amount", "Campaign budget", "currency",
        required=True,
        prefix=CURRENCY_PREFIX.get(currency.upper(), f"{currency.upper()} "),
        min=min_budget_cents,
        # How many minor units the widget's stored value packs into one whole
        # unit. 100 everywhere except JPY & co, where Meta's number IS whole yen
        # and dividing by 100 would show a ¥100 floor as ¥1.
        minor_units=minor_units(currency),
        # Express asks for a budget before the user has seen anything to judge it
        # against — the one question on this form nobody can answer cold. The
        # recommendation guide mode opens the plan on is already sized against the
        # objective, targeting method and audience count, so start the box there
        # and say what it buys. It is a DAILY spend (build_budget_options only
        # emits daily tiers) and the reason text says so, so a user who switches
        # to lifetime can see the number is not sized for the pot they picked.
        suggestion=budget_suggestion,
        help_=(
            f"{budget_reason.rstrip('. ')} — editable, and Meta needs a minimum "
            "per day for this account's currency."
            if budget_reason
            else "Meta needs a minimum per day for this account's currency."
        ),
    ))
    budget.append(_field(
        "campaign_start_date", "Campaign start date", "date",
        suggestion=user_info.get("campaign_start_date") or None,
        help_="Leave blank to start as soon as it's approved.",
    ))
    budget.append(_field(
        "campaign_end_date", "Campaign end date", "date",
        suggestion=user_info.get("campaign_end_date") or None,
        # Meta rejects a lifetime budget with no end date — it has no window to
        # spread the money over.
        required_when={"budget_type": "lifetime"},
        help_="Leave blank to keep it running until you stop it.",
    ))
    return out, budget


# ── submission parsing ───────────────────────────────────────────────────────


def parse_intake_submission(raw: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the widget's JSON submission.

    Returns ``(values, errors)``. ``errors`` keyed by field key (plus
    ``__root__`` for a form-level banner) — same contract as the plan form. A
    non-JSON reply (someone typed into the chat instead of using the form) is a
    single ``__root__`` error, never an LLM extraction — the form is the
    contract.

    Only what cannot be defaulted is enforced. Everything the plan editor can fix
    is left alone: rejecting a submission over a value the user is about to see
    pre-filled, and can change in one click, is a question asked twice.
    """
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}, {"__root__": "Please use the form above to submit your campaign details."}

    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        return {}, {"__root__": "Please use the form above to submit your campaign details."}

    errors: dict[str, str] = {}

    if not str(values.get("business_name") or "").strip():
        errors["business_name"] = "Tell us your business name."
    if not str(values.get("business_context") or "").strip():
        errors["business_context"] = "Tell us what you sell."

    objective = normalize_objective(values.get("objective"))
    if objective is None:
        errors["objective"] = "Pick a campaign objective."
    elif objective is Objective.APP_PROMOTION and not (
        normalize_url(values.get("app_store_url")) or normalize_url(values.get("play_store_url"))
    ):
        # The only prerequisite with no fallback — a Page URL cannot stand in for
        # the app Meta is asked to promote.
        errors["app_store_url"] = "Add at least one app store link."

    # This form's only submitter now — an express user never reaches the campaign
    # half of the editor, so these two cannot be "fixed later": an unset budget
    # would reach build_campaign_spec as a BudgetParseError, and a lifetime
    # budget with no end date is rejected by Meta.
    if not _positive_int(values.get("budget_amount")):
        errors["budget_amount"] = "Set a campaign budget."
    if str(values.get("budget_type") or "") == "lifetime" and not str(
        values.get("campaign_end_date") or ""
    ).strip():
        errors["campaign_end_date"] = "A lifetime budget needs an end date."

    return values, errors


def _positive_int(raw: Any) -> int:
    """Cents off the currency widget → a positive int, or 0 when it is unusable."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _digits(raw: Any) -> str:
    return "".join(c for c in str(raw or "") if c.isdigit())


# ── submission → slots ───────────────────────────────────────────────────────


def intake_to_slots(
    values: dict, *, currency: str = "USD", pixel_candidates: list[dict] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map a validated submission onto ``(filled_patch, user_info_patch)``.

    ``pixel_candidates`` is ``media_ws["pixel_candidates"]`` — the same list the
    form's own options came from — used only to check whether the picked
    ``pixel_id`` has actually fired (see ``has_warm_dataset`` below).

    ``currency`` is the ad account's code, needed only by the express budget:
    the widget submits that currency's minor units and the slot stores a
    human-readable string.

    ``filled`` keeps the short objective form ("SALES") that ``slot_applies``
    gating expects; ``user_info`` carries the exact keys the brief prompt and
    ``build_campaign_spec`` already read.

    The conversion location is deliberately NOT written here. This form only asks
    the objective, so writing the objective's first destination looked like a
    choice and behaved like one — ``build_campaign_tree`` treats a present
    ``conversion_location`` as the user's own pick and lets it win over the
    brief's recommendation. Left absent, the brief recommends a location from the
    business and geo (and says why), and the matrix default still applies when it
    does not. The plan editor opens with the full list either way.
    """
    objective = normalize_objective(values.get("objective"))
    short = _OBJECTIVE_SHORT.get(objective, "AWARENESS") if objective else "AWARENESS"

    business_name = str(values.get("business_name") or "").strip()
    business_context = str(values.get("business_context") or "").strip()
    app_store = normalize_url(values.get("app_store_url"))
    play_store = normalize_url(values.get("play_store_url"))

    # website_url is deliberately absent from both patches: connect_meta resolved
    # it from the Page before this form was even shown, and writing "" here would
    # overwrite it — which would also block enrich_website, whose prereqs read the
    # slot store.
    filled = {
        "campaign_intake": "done",
        "objective": short,
        "business_name": business_name,
        "business_desc": business_context,
        "app_store_url": app_store,
        "play_store_url": play_store,
    }

    user_info = {
        "business_name": business_name,
        "business_description": business_context,
        "product_offer": business_context,
        "campaign_objective": short,
        "app_store_url": app_store,
        "play_store_url": play_store,
        # Dates are resolved by ``parsing.resolve_flight``: absent start means
        # "begin now", absent end means open-ended. Both are editable per ad set
        # in the plan. budget_type follows the same rule — daily unless the editor
        # switches it, which is the only place a lifetime budget can get the end
        # date Meta requires alongside it.
        "budget_type": "daily",
        "campaign_start_date": "",
        "campaign_end_date": "",
    }

    # ── express-only answers ─────────────────────────────────────────────────
    # Absent in guide mode (the fields are not even rendered), so each write is
    # guarded: an unconditional write would blank the Page id connect_meta
    # already resolved and re-introduce the "" website_url problem the note above
    # exists to avoid.
    budget_type = str(values.get("budget_type") or "").strip().lower()
    budget_cents = _positive_int(values.get("budget_amount"))
    if budget_cents:
        # A STRING, like every other producer of this slot ("Recommended: $280/day
        # — reaches ~140,000 people", or whichever tier the user picked). It used
        # to be stored as a float, which crashed generate_brief outright: two
        # readers regex this value (_selected_tier_reach, _extract_budget_amount)
        # and re.search does not take a float.
        #
        # The widget submits the account's MINOR units, so divide by that
        # currency's own divisor — 1 on a JPY account, where the number already
        # is whole yen. parse_budget_to_cents multiplies the same way going back.
        scale = minor_units(currency)
        symbol = CURRENCY_PREFIX.get(currency.upper(), f"{currency.upper()} ")
        period = " total" if budget_type == "lifetime" else "/day"
        # Fixed-point, not %g: %g goes exponential past a million ("1.23457e+06")
        # and there is nothing hypothetical about a ৳1,200,000 lifetime budget.
        body = f"{budget_cents / scale:,.{0 if scale == 1 else 2}f}"
        if "." in body:
            body = body.rstrip("0").rstrip(".")
        user_info["budget"] = f"{symbol}{body}{period}"
    if budget_type:
        user_info["budget_type"] = budget_type
    for key in ("campaign_start_date", "campaign_end_date"):
        if str(values.get(key) or "").strip():
            user_info[key] = str(values[key]).strip()
    website = normalize_url(values.get("website_url"))
    if website:
        user_info["website_url"] = website
        filled["website_url"] = website
    page_id = str(values.get("page_id") or "").strip()
    if page_id:
        user_info["meta_page_id"] = page_id
    # Blank means "create a default one for me", which is what publish already
    # does when nothing names a form — so only a real pick is written.
    lead_form_id = str(values.get("lead_form_id") or "").strip()
    if lead_form_id:
        user_info["lead_form_id"] = lead_form_id
    # media_select_pixel re-checks this against the account's own Pixels before
    # trusting it — the same key can already hold one scraped off the website,
    # which may belong to a different ad account. This form's pixel field only
    # ever lists warm datasets (see _express_fields) — no "create one for me"
    # option here; that choice lives in the editor's own Pixel picker now (see
    # AdSetPanel.tsx).
    pixel_id = str(values.get("pixel_id") or "").strip()
    if pixel_id:
        user_info["pixel_id"] = pixel_id
        # Naming an EXISTING, warm dataset is an explicit decision to optimize
        # for conversions, and overrides the heuristic media_detect_pixel wrote
        # off ``last_fired_time`` — without this a user who picked a dataset
        # would have the conversion goal clamped away from them by
        # _resolve_goal, the opposite of an answer winning. This form's own
        # pixel field only ever lists warm datasets (see _express_fields), so a
        # submitted pixel_id here is always one of these — the guard below is
        # just belt-and-suspenders against a stale/removed pixel.
        if any(
            str(p.get("id")) == pixel_id and str(p.get("last_fired_time") or "").strip()
            for p in (pixel_candidates or [])
        ):
            user_info["has_warm_dataset"] = True

    # What counts as a conversion, and how the events reach Meta, are NOT read
    # here — the form no longer asks either. The event is defaulted by
    # meta_spec.builder (DEFAULT_PIXEL_EVENT) and changed in the editor's ad-set
    # panel; the method is derived by media._derived_tracking_method and changed
    # in the editor's campaign panel, which writes filled["tracking_method"] via
    # _apply_plan_form_submission.

    # Neither mode's form asks this any more (see the module docstring), so
    # `values` never actually carries the key today. Left in rather than
    # deleted: it costs nothing, and a future submitter of the key still gets
    # it written through correctly instead of silently dropped.
    creative_source = str(values.get("creative_source") or "").strip()
    if creative_source:
        user_info["creative_source"] = creative_source

    return filled, user_info


_OBJECTIVE_SHORT: dict[Objective, str] = {
    Objective.AWARENESS: "AWARENESS",
    Objective.TRAFFIC: "TRAFFIC",
    Objective.ENGAGEMENT: "ENGAGEMENT",
    Objective.LEADS: "LEADS",
    Objective.APP_PROMOTION: "APP_PROMOTION",
    Objective.SALES: "SALES",
}


__all__ = [
    "INTAKE_ACTION_TYPE",
    "INTAKE_FIELD",
    "build_intake_schema",
    "intake_to_slots",
    "normalize_url",
    "parse_intake_submission",
]
