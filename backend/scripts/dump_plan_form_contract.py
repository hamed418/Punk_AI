"""
scripts/dump_plan_form_contract.py
──────────────────────────────────
Dump the exact ``pending_action`` and ``campaign_plan`` payloads the backend
emits across the campaign stage — the ``campaign_intake_form`` (step 1) and the
``campaign_plan_form`` (step 2), one sample per objective — for the frontend
team to build the DynamicForm widget against.

Everything here comes from the real code path — ``build_intake_schema`` /
``build_campaign_spec`` → ``_plan_form_extra`` → the same ``pending`` dict
``wizard_helpers`` assembles. Nothing is hand-written, so a change to the
objective matrix or the form schema shows up in the next dump instead of
silently drifting from what ships.

Run from ``backend/``:

    .venv/Scripts/python.exe scripts/dump_plan_form_contract.py

Writes to ``frontend/contracts/campaign_plan_form/``. Requires no ad account,
no Meta token and no network: the schema/spec builders are pure.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.encoders import jsonable_encoder  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.graph.builder.builder_node import _plan_form_extra  # noqa: E402
from app.graph.builder.executors.campaign import brief_to_plan_payload  # noqa: E402
from app.graph.builder.intake_form import build_intake_schema  # noqa: E402
from app.graph.meta_spec import (  # noqa: E402
    CampaignSpec,
    build_campaign_spec,
    build_campaign_tree,
    errors_to_form_keys,
)
from app.graph.prompts_registry import STEP_PROMPTS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "contracts" / "campaign_plan_form"

# ── Inputs ────────────────────────────────────────────────────────────────────
# A plausible mid-flow state: geo confirmed (ZIP-targeted), MAID audience
# extracted, brief written, Meta connected. Only the objective changes between
# samples.

_ZIPS = {"geo_locations": {"zips": [{"key": "CA:M5V"}, {"key": "CA:M5H"}],
                           "location_types": ["home", "recent"]}}
SEED_TARGETING = {**_ZIPS, "custom_audiences": [{"id": "seed_ca"}], "age_min": 21, "age_max": 55}
BROAD_TARGETING = {**_ZIPS, "age_min": 21, "age_max": 55}
LOOKALIKE_TARGETING = {**_ZIPS}

BASE_USER_INFO = {
    "business_name": "Bean There",
    "business_description": "Specialty coffee roaster and cafe",
    "industry": "Food & Beverage",
    "product_offer": "Single-origin roasts and espresso bar",
    "website_url": "https://beanthere.example",
    "budget": "$50/day",
    "budget_type": "daily",
    "campaign_start_date": "August 1, 2026",
    "meta_ad_account_id": "act_1234567890",
    "meta_page_id": "998877665544",
}

BASE_BRIEF = {
    "campaign_name": "Bean There — Summer Push",
    "adset_budget_breakdown": [
        {"adset_name": "Cafe Visitors", "budget_pct": 70, "audience_type": "primary"},
        {"adset_name": "Lookalike Prospecting", "budget_pct": 30, "audience_type": "lookalike"},
    ],
    "headline_suggestions": ["Fresh roast, every morning", "Your new usual"],
    "body_copy_suggestions": ["Small-batch beans, roasted two blocks away."],
    "cta_recommendation": "LEARN_MORE — low friction for a first visit",
    "targeting_rationale": "Foot-traffic seed audience plus a 1% lookalike.",
}

GEO_DATA = {"maid_count": 12480, "poi_radius_km": 1.5, "area_label": "Downtown Toronto"}

PIXEL_CANDIDATES = [
    {"id": "111222333444", "name": "Bean There Site Pixel"},
    {"id": "555666777888", "name": "Bean There Checkout"},
]

# Every Page the token can advertise under, each with its linked Instagram
# account, its WhatsApp number and its own instant forms. Two of them because one
# is the case the editor hides the picker for — the contract only means something
# with a choice, and the two Pages differ on every identity so the difference is
# what the sample shows.
#
# `whatsapp` is deliberately present on both: {number} is linked, None is
# provably unlinked, and OMITTING the key is the third state (the token could not
# read it), which is what a pre-WhatsApp checkpoint replays as.
PAGE_CANDIDATES = [
    {
        "id": "998877665544",
        "name": "Bean There",
        "instagram": {"id": "17841400000000001", "username": "beanthere"},
        "whatsapp": {"number": "+15550100"},
        "lead_forms": [{"id": "form_101", "name": "Bean There — Waitlist", "status": "ACTIVE"}],
    },
    {
        "id": "112233445566",
        "name": "Bean There Roasters",
        "instagram": None,
        "whatsapp": None,
        "lead_forms": [],
    },
]

# Objectives, and the extra prerequisite each one needs. This mirrors the
# matrix's per-destination `required_user_info` — a conversion location that
# needs a pixel (or an app, or an instant form) cannot build a spec without it.
#
# Leads appears twice on purpose: Instant forms and Website leads share nothing
# below the objective (different goal, different promoted object, different
# prerequisites), which is the clearest illustration of the two-axis contract.
OBJECTIVES = [
    ("OUTCOME_AWARENESS", {}, {}),
    ("OUTCOME_TRAFFIC", {}, {}),
    ("OUTCOME_ENGAGEMENT", {}, {}),
    ("OUTCOME_LEADS", {}, {}),
    (
        "OUTCOME_APP_PROMOTION",
        {"app_store_url": "https://apps.apple.com/app/id123456789"},
        {"application_id": "246813579"},
    ),
    ("OUTCOME_SALES", {}, {"pixel_id": "111222333444"}),
]

# Extra samples that vary the SECOND axis while holding the objective fixed.
# slug → (objective, user_extra, build_extra)
DESTINATION_SAMPLES = {
    "leads_website": (
        "OUTCOME_LEADS",
        {"conversion_location": "WEBSITE"},
        {"pixel_id": "111222333444"},
    ),
    "sales_messenger": (
        "OUTCOME_SALES",
        {"conversion_location": "MESSENGER"},
        {"pixel_id": "111222333444"},
    ),
    # Click-to-WhatsApp: promoted_object is the Page (that is where the WhatsApp
    # number lives) and the creative's button carries app_destination, not a URL.
    "traffic_whatsapp": (
        "OUTCOME_TRAFFIC",
        {"conversion_location": "WHATSAPP"},
        {},
    ),
}


def _build_state(objective: str, user_extra: dict, build_extra: dict) -> dict:
    """The builder-state slice the plan gate reads, for one objective."""
    user_info = {**BASE_USER_INFO, "campaign_objective": objective, **user_extra}
    # A run that resolved a dataset is by definition a run where conversion
    # optimization is on the table — otherwise _resolve_goal steers the ad set
    # onto a goal that promotes nothing and the pixel is never used. Derived from
    # build_extra rather than listed per scenario so the two cannot drift.
    if build_extra.get("pixel_id"):
        user_info["has_warm_dataset"] = True
    spec = build_campaign_spec(
        user_info=user_info,
        geo_data=GEO_DATA,
        brief=BASE_BRIEF,
        seed_targeting=SEED_TARGETING,
        broad_targeting=BROAD_TARGETING,
        lookalike_targeting=LOOKALIKE_TARGETING,
        page_id=user_info["meta_page_id"],
        instagram_user_id=PAGE_CANDIDATES[0]["instagram"]["id"],
        **build_extra,
    )
    return {
        "user_info": user_info,
        "marketing_plan": spec.model_dump(mode="json"),
        "media_ws": {
            "pixel_candidates": PIXEL_CANDIDATES,
            "page_candidates": PAGE_CANDIDATES,
            "lead_form_candidates": PAGE_CANDIDATES[0]["lead_forms"],
        },
    }


def _pending_action(bs: dict, *, errors: dict | None = None) -> dict:
    """Reassemble the wire payload exactly as wizard_helpers builds it.

    Mirrors the `pending` dict in wizard_helpers.wizard_interrupt plus the
    overrides _enrich_slot_ask supplies for the plan_confirm slot. Kept in one
    place here so the dump stays a faithful copy rather than an idealized one.
    """
    if errors is not None:
        bs = {**bs, "plan_errors": errors}
    cfg = STEP_PROMPTS["campaign_plan_confirm"]
    # user_info lives on the graph state, so the dump has to supply the same view
    # the node gets — that is where page_id and the prerequisite flags come from.
    # async only because it rehydrates ad-image previews from the DB; the fixtures
    # carry no media_id, so it short-circuits before touching one.
    form = asyncio.run(_plan_form_extra(bs, {"user_info": dict(BASE_USER_INFO)}))
    if form is None:
        raise SystemExit("_plan_form_extra returned None — the spec did not build")
    pending = {
        # Read from the registry, not restated. Both of these were hardcoded here
        # and had drifted from what the graph actually emits — every fixture
        # shipped the wrong action_type, so a client written against the contract
        # never matched the live payload.
        "action_type": cfg["action_type"],
        "options": cfg.get("options", []),
        "prompt": cfg["prompt"],
        "field": "campaign_plan_confirm",
        "step_key": "campaign_plan_confirm",
        "prefill": None,
        "prefill_source": None,
        "prefill_confidence": None,
        "stepper": cfg.get("stepper"),
        "steppers": cfg.get("steppers"),
        "progress": None,
        "title": cfg.get("title"),
        "subtitle": cfg.get("subtitle"),
    }
    pending.update(form)
    return {"type": "pending_action", "content": pending}


def _write(name: str, payload: dict) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {path.relative_to(OUT_DIR.parents[2])}  ({path.stat().st_size:,} bytes)")


def _intake_pending() -> dict:
    """The campaign_intake_form pending_action — first step of the campaign
    stage, before the plan form."""
    cfg = STEP_PROMPTS["campaign_intake_form"]
    schema = build_intake_schema(
        user_info={**BASE_USER_INFO, "campaign_objective": "OUTCOME_SALES"},
        enrichment={"business_category": "Cafe", "products_services": ["coffee"]},
    )
    return {
        "type": "pending_action",
        "content": {
            "action_type": "campaign_intake_form",
            "options": [],
            "prompt": cfg["prompt"],
            "field": "campaign_intake",
            "step_key": "campaign_intake_form",
            "prefill": None,
            "prefill_source": None,
            "title": cfg.get("title"),
            "subtitle": cfg.get("subtitle"),
            "form_schema": schema,
            "values": {},
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing contract samples to {OUT_DIR}\n")

    # Step 1: the intake form.
    _write("pending_action.intake.json", _intake_pending())
    _write(
        "intake_submission.example.json",
        {
            "_note": (
                "POST /chat/{session_id}/resume with this JSON.stringify'd. The "
                "intake form submits { values: {...} } with the fields the user filled."
            ),
            "values": {
                "business_name": "Bean There",
                "business_context": "Single-origin roasts and a neighbourhood espresso bar.",
                "objective": "OUTCOME_SALES",
            },
        },
    )

    dest_counts: dict[str, list[str]] = {}

    for objective, user_extra, build_extra in OBJECTIVES:
        bs = _build_state(objective, user_extra, build_extra)
        slug = objective.replace("OUTCOME_", "").lower()
        event = _pending_action(bs)
        _write(f"pending_action.{slug}.json", event)

        # What actually varies per objective is the conversion-location list in
        # the catalog, and everything hanging off each one.
        catalog = event["content"]["catalog"]
        dest_counts[objective] = [
            d["label"] for d in catalog["destinations_by_objective"][objective]
        ]

    # Same objective, different conversion location — the second axis.
    for slug, (objective, user_extra, build_extra) in DESTINATION_SAMPLES.items():
        _write(
            f"pending_action.{slug}.json",
            _pending_action(_build_state(objective, user_extra, build_extra)),
        )

    # The campaign_plan event — v2 structured payload, the full 12-section form.
    plan_bs = _build_state("OUTCOME_TRAFFIC", {}, {})
    _write(
        "campaign_plan.v2.json",
        {
            "type": "campaign_plan",
            "content": brief_to_plan_payload(BASE_BRIEF, plan_bs["user_info"], GEO_DATA),
        },
    )

    # A rejected submission: same widget re-rendered with per-field errors and
    # the user's edits preserved. This is the branch the widget must handle
    # without losing form state.
    # The editor submits the whole edited spec, so a rejection comes from
    # re-validating that tree — not from an overrides patch.
    edited = _build_state("OUTCOME_TRAFFIC", {}, {})["marketing_plan"]
    edited["adsets"][0]["daily_budget"] = 1          # below Meta's floor
    edited["adsets"][0]["optimization_goal"] = "APP_INSTALLS"   # wrong destination
    try:
        CampaignSpec.model_validate(edited)
    except ValidationError as exc:
        errors = errors_to_form_keys(exc)
    else:
        raise SystemExit("expected the edited spec to fail validation")

    _write(
        "pending_action.traffic.with_errors.json",
        _pending_action(_build_state("OUTCOME_TRAFFIC", {}, {}), errors=errors),
    )

    # A conversion objective whose pixel went missing. ``has_warm_dataset`` is
    # what makes this reachable at all: without it a Sales campaign on an account
    # with no dataset resolves to a landing-page-view goal that promotes nothing
    # and validates cleanly. Here the account HAS a dataset — the user picked one,
    # or one has been firing — and it is the id that is absent, which is the state
    # the editor's pixel picker exists to fix.
    no_pixel_tree = build_campaign_tree(
        user_info={
            **BASE_USER_INFO,
            "campaign_objective": "OUTCOME_SALES",
            "has_warm_dataset": True,
        },
        geo_data=GEO_DATA,
        brief=BASE_BRIEF,
        seed_targeting=SEED_TARGETING,
        broad_targeting=BROAD_TARGETING,
        lookalike_targeting=LOOKALIKE_TARGETING,
        page_id=BASE_USER_INFO["meta_page_id"],
    )
    try:
        CampaignSpec.model_validate(no_pixel_tree)
    except ValidationError as exc:
        no_pixel_errors = errors_to_form_keys(exc)
    else:
        raise SystemExit("expected a pixel-less SALES tree to fail validation")

    _write(
        "pending_action.sales.no_pixel.json",
        _pending_action(
            {
                "user_info": {**BASE_USER_INFO, "campaign_objective": "OUTCOME_SALES"},
                "marketing_plan_draft": jsonable_encoder(no_pixel_tree),
                "media_ws": {"pixel_candidates": [], "page_candidates": PAGE_CANDIDATES},
            },
            errors=no_pixel_errors,
        ),
    )

    # What the widget posts back, for the resume endpoint.
    submitted = _build_state("OUTCOME_TRAFFIC", {}, {})["marketing_plan"]
    submitted["name"] = "Bean There — Summer Push (edited)"
    submitted["adsets"][0]["daily_budget"] = 6000
    submitted["adsets"][0]["optimization_goal"] = "LANDING_PAGE_VIEWS"
    submitted["adsets"][0]["ads"][0]["creative"]["title"] = "Your new usual"
    _write(
        "submission.example.json",
        {
            "_note": (
                "POST /chat/{session_id}/resume with this JSON.stringify'd as the "
                "answer. The editor submits the WHOLE edited spec, not a patch — "
                "the server re-validates it against CampaignSpec and hands back "
                "per-field errors keyed the same way (see "
                "pending_action.traffic.with_errors.json)."
            ),
            "action": "publish",
            "spec": submitted,
        },
    )

    # Each objective ships the same field set; what varies is the conversion
    # location list and the option sets hanging off it. That is the two-axis
    # matrix the whole contract is built on — see the README.
    print("\nConversion locations per objective (this is what varies):")
    for objective, labels in dest_counts.items():
        print(f"  {objective:<24} {', '.join(labels)}")


if __name__ == "__main__":
    main()
