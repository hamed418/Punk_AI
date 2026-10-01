"""
graph/builder/executors/campaign.py
───────────────────────────────────
Campaign-plan LLM core, relocated from wizards/campaign_wizard.py (phase 5.2).

  generate_campaign_brief – Pro+thinking brief generation (retry ×2)

This module owns the *creative and strategic* half of the plan: naming, budget
split rationale, headline and body suggestions, CTA recommendation, and the
human-readable card. Every structural field Meta validates now comes from
``app.graph.meta_spec`` instead.

Removed in that move: ``generate_meta_campaign_json`` (a second Pro call that
invented the Meta JSON), ``MetaCampaignModel`` (validated almost nothing), and
``build_meta_precomputed`` (its budget split now lives in meta_spec.builder,
where it actually reaches Meta).

No interrupts, no state writes — callers (campaign_wizard sub-nodes and
builder_act) own checkpointing, narration, and failure-state shaping. LLM
exhaustion raises ``CampaignGenerationError`` carrying the structured
tool-log entry the wizards previously built inline.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import settings
from app.graph.maid_query import audience_headline_count
from app.graph.meta_spec.parsing import (
    CURRENCY_PREFIX,
    BudgetParseError,
    minor_units,
    parse_budget_to_cents,
)
from app.graph.prompts import CAMPAIGN_PLAN_GENERATOR_PROMPT
from app.graph.usage import tracked_ainvoke, tracked_astream

logger = logging.getLogger(__name__)


# ── Output schemas (validated; this JSON becomes real ad spend) ────────────────


class CampaignBriefModel(BaseModel):
    """Human-readable brief. Lenient by design — most fields are display-only —
    but it MUST parse to a JSON object (not prose), which is what distinguishes
    a usable brief from an LLM that ignored the format. extra='allow' keeps every
    field the prompt emits; downstream readers (brief_to_plan_payload,
    build_campaign_spec) index optional keys with .get()."""

    model_config = ConfigDict(extra="allow")

    campaign_name: str | None = None
    # Set by the LLM only when user_info.campaign_objective was empty going in
    # (see generate_campaign_brief) — guide mode no longer asks for it up front,
    # so the brief picks one from the business/audience/geo signal instead.
    # Short name ("SALES", "AWARENESS", ...); None when the caller already had
    # an objective and the brief left it alone.
    objective: str | None = None
    adset_budget_breakdown: list[dict] | None = None
    headline_suggestions: list[str] | None = None
    body_copy_suggestions: list[str] | None = None
    description_suggestion: str | None = None
    cta_recommendation: str | None = None


# Mirrors _make_thinking_llm from nodes.py — duplicated to avoid cycle.
def _make_thinking_llm(budget: int = 8000, model: str | None = None) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model or settings.GEMINI_MODEL_PRO,
        **settings.llm_auth,
        temperature=settings.GEMINI_TEMPERATURE,
        thinking_budget=budget,
        include_thoughts=True,
    )


def _split_gemini_thinking(content: Any) -> tuple[str, str]:
    if isinstance(content, str):
        return "", content
    thinking_parts: list[str] = []
    answer_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            answer_parts.append(str(block))
            continue
        if block.get("type") == "thinking":
            thinking_parts.append(block.get("thinking", ""))
        else:
            answer_parts.append(block.get("text", ""))
    return "\n".join(thinking_parts), "\n".join(answer_parts)


def _parse_budget_to_cents(budget_str: str, currency: str | None = None) -> int:
    """Display-side budget parse. Delegates to the one shared implementation.

    Display callers (the plan card's metric strip, the budget reconcilers) want a
    number to render even when the string is junk, so an unparseable value
    degrades to 0 here — a visibly wrong "$0.00" rather than a plausible-looking
    "$50.00" that hides the problem. The publish path uses
    ``meta_spec.parsing.parse_budget_to_cents`` directly and raises instead.
    """
    try:
        return parse_budget_to_cents(budget_str, currency)
    except BudgetParseError:
        logger.warning("could not parse budget %r for display", budget_str)
        return 0


def _money_fmt(user_info: dict) -> tuple[str, int, int]:
    """``(symbol, minor_units, decimal_places)`` for the ad account's currency.

    Every amount on the plan card and in the reconciled brief is in the ad
    account's currency, not USD — the same three target markets that made
    ``min_budget_cents`` per-account (US, Canada, Bangladesh) make a hardcoded
    ``$`` wrong two times in three. Zero-decimal currencies also drop the cents:
    ``¥500.00`` is not a thing.
    """
    code = str(user_info.get("ad_account_currency") or "").upper()
    scale = minor_units(code)
    return CURRENCY_PREFIX.get(code, f"{code} " if code else "$"), scale, (0 if scale == 1 else 2)


class CampaignGenerationError(Exception):
    """LLM generation exhausted its retries. ``log_entry`` is the structured
    tool-log dict the caller persists into tool_calls_log / failure state."""

    def __init__(self, message: str, log_entry: dict):
        super().__init__(message)
        self.log_entry = log_entry


def _strip_json_fences(text: str) -> str:
    """Remove ```json … ``` markdown fences the LLM sometimes wraps around JSON."""
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines).strip()
    return clean


def _objective_options(objective: Any, user_info: dict | None = None) -> dict[str, Any]:
    """What the objective matrix actually allows, for the brief to choose from.

    Only the two axes the brief is asked to recommend: the conversion locations
    with their optimization goals, and the objective's bid strategies. An
    unrecognized objective yields ``{}`` — the brief still runs and the tree falls
    back to the matrix default, exactly as before.

    Two kinds of location are withheld, because the brief cannot pick them
    honestly and picking one anyway cost the user a plan they could not publish:

    * A boost location (On your post / video / event) needs an existing Page post
      to promote, which the brief has no knowledge of — it produced a plan that
      opened on a blocking ``object_story_id`` error, next to composed copy the
      location ignores.
    * A location whose prerequisite is missing (Website with no website URL).
      The prompt already says not to, but a rule the model has to remember is a
      rule it sometimes forgets, and there is no reason to offer the option.

    All of them stay available in the editor, where the user can supply what they
    need.

    The optimization goals are filtered the same way and for the same reason. A
    goal that promotes a pixel is withheld from an account with no dataset that
    has ever fired: Meta accepts the ad set and then optimizes toward an event
    that cannot arrive. Every objective has a pixel-less shape — Sales sells
    through Messenger conversations or optimizes for landing-page views on the
    advertiser's own site — so withholding the conversion goals steers the brief
    onto one that works on day one rather than onto a campaign propped up by a
    dataset nobody has installed.
    """
    from app.graph.meta_spec import matrix_for
    from app.graph.meta_spec.catalog import _prerequisite_present
    from app.graph.meta_spec.objective_matrix import PROMOTED_PIXEL

    try:
        rules = matrix_for(objective)
    except KeyError:
        return {}
    info = user_info or {}
    # Written at connect time by media_detect_pixel, off last_fired_time.
    warm_dataset = bool(info.get("has_warm_dataset"))

    locations = []
    for d in rules.destinations:
        if d.object_story_kind:
            continue
        if not all(_prerequisite_present(info, k) for k in d.required_user_info):
            continue
        goals = [
            g.value for g in d.optimization_goals
            if warm_dataset or d.promoted_object_kind(g) != PROMOTED_PIXEL
        ]
        # No destination is all-pixel today, but one added later would otherwise
        # be offered with an empty goal list — which the brief reads as "any".
        if not goals:
            continue
        locations.append({
            "value": d.destination_type.value,
            "label": d.label,
            "help": d.help_text,
            "optimization_goals": goals,
        })

    return {
        "conversion_locations": locations,
        "bid_strategies": [s.value for s in rules.bid_strategies],
    }


async def _grounded_policy_advisory(user_info: dict, enrichment: dict) -> str | None:
    """Advisory-only check for a real Meta Advertising Standards restriction
    (health claims, restricted supplements, pharma, etc.) applying to this
    business — the gap that let a peptide-wellness campaign through with no
    flag at all. Deliberately separate from meta_spec.special_categories:
    that module is keyword-only and non-LLM ON PURPOSE (determinism across
    checkpoint replay; see its own docstring) — this stays advisory text
    surfaced in the brief, never wired into the special_ad_categories
    declaration itself."""
    context = " | ".join(
        str(v).strip() for v in (
            user_info.get("business_description"),
            user_info.get("industry"),
            user_info.get("product_offer"),
            enrichment.get("business_category"),
        ) if str(v or "").strip()
    )
    if not context:
        return None
    from app.graph.grounding import grounded_text

    try:
        result = (await grounded_text(POLICY_RISK_LOOKUP_PROMPT.format(business_context=context))).strip()
    except Exception as exc:
        logger.info("generate_campaign_brief: policy advisory lookup skipped/failed — %s", exc)
        return None
    return None if result in ("", "NONE") else result


async def generate_campaign_brief(
    user_info: dict,
    geo_data: dict,
    enrichment: dict,
    writer: Callable[[dict], None],
    *,
    node: str = "campaign_generate_brief",
) -> dict:
    """Generate the human-readable campaign brief dict (retry ×2).

    Raises CampaignGenerationError when retries are exhausted — whether the
    failure was an LLM exception OR an unparseable / schema-invalid answer.
    A response that won't parse to a JSON object is regenerated, then fails
    loudly; it is never returned as ``{"raw": ...}``. Plan edits go through the
    campaign editor (a full edited spec), not a brief regeneration.
    """
    thinking_llm = _make_thinking_llm(budget=12000)
    policy_advisory = await _grounded_policy_advisory(user_info, enrichment)

    brief_context = json.dumps({
        "user_info": user_info,
        "policy_advisory": policy_advisory,
        "geo_data": {
            "targeting_method": geo_data.get("targeting_method"),
            # The filtered headline (not the raw superset) — the audience an
            # active audience_filter actually leaves, and what gets uploaded
            # to Meta; the brief should never cite a bigger number than that.
            "maid_count": audience_headline_count(geo_data),
            "targeting_type": geo_data.get("targeting_type"),
            "meta_targeting": geo_data.get("meta_targeting"),
            "poi_radius_km": geo_data.get("poi_radius_km"),
            "lookback_days": geo_data.get("lookback_days"),
        },
        "website_enrichment": enrichment,
        # The legal option lists for the objective. Without them the brief
        # recommended a conversion location and bid strategy from memory, and
        # the tree silently replaced anything the matrix rejects — so the plan
        # card could promise settings the plan did not have.
        #
        # Guide mode no longer asks for the objective up front, so when
        # campaign_objective is empty this is every objective's option list,
        # keyed by short name — the prompt (OBJECTIVE section) picks one itself
        # and reads its sub-object. A known objective keeps the flat single-
        # objective shape, unchanged.
        "meta_options": (
            _objective_options(user_info["campaign_objective"], user_info)
            if user_info.get("campaign_objective")
            else {short: _objective_options(short, user_info) for short in _VALID_OBJECTIVES}
        ),
    }, indent=2)

    last_err = "unknown error"
    for _attempt in range(1, 3):
        try:
            # Stream the (unchanged, budget=12000) reasoning live so the 5-10s
            # generation isn't a dead screen; source="punk" persists it to history.
            raw_brief, _ = await tracked_astream(
                thinking_llm,
                [SystemMessage(content=CAMPAIGN_PLAN_GENERATOR_PROMPT), HumanMessage(content=brief_context)],
                node_name="campaign_wizard/brief_gen",
                writer=writer,
                emit_thinking=True,
                thinking_source="punk",
            )
            _, answer_text = _split_gemini_thinking(raw_brief.content)
            parsed = json.loads(_strip_json_fences(answer_text))
            return CampaignBriefModel.model_validate(parsed).model_dump(exclude_none=True)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_err = f"brief did not match the required JSON shape: {exc}"
            logger.warning("campaign brief_gen attempt %d invalid: %s", _attempt, exc)
        except Exception as exc:
            last_err = str(exc)
            logger.warning("campaign brief_gen attempt %d failed: %s", _attempt, exc)
        if _attempt < 2:
            await asyncio.sleep(2.0)

    raise CampaignGenerationError(last_err, {
        "tool": "brief_gen_llm", "status": "error", "error_msg": last_err,
        "attempts": 2, "duration_ms": 0.0, "args": {}, "node": node,
    })


# ── Presentation / parsing helpers ──────────────────────────────────────────
# Objective canonicalization, the structured (v2) campaign-plan payload, brief
# reconciliation, and the LLM-ranked budget option builder. Shared by the
# campaign builder agent and the chatbot node (_normalize_objective).

import re

from app.graph.prompts import (
    BUDGET_RECOMMENDATION_PROMPT,
    CPM_BENCHMARK_LOOKUP_PROMPT,
    POLICY_RISK_LOOKUP_PROMPT,
)
from app.graph.narrator.post_process import scrub_jargon
from app.graph.wizard_helpers import _make_llm

_INTENT_TO_OBJECTIVE: dict[str, str] = {
    # sales / conversions
    "sales": "SALES",
    "conversions": "SALES",
    "conversion": "SALES",
    "revenue": "SALES",
    "purchases": "SALES",
    "ecommerce": "SALES",
    "e-commerce": "SALES",
    "sell": "SALES",
    # leads
    "leads": "LEADS",
    "lead generation": "LEADS",
    "lead gen": "LEADS",
    "signups": "LEADS",
    "sign-ups": "LEADS",
    "sign ups": "LEADS",
    "inquiries": "LEADS",
    "form fills": "LEADS",
    # traffic / foot traffic
    "traffic": "TRAFFIC",
    "foot traffic": "TRAFFIC",
    "website traffic": "TRAFFIC",
    "clicks": "TRAFFIC",
    "visits": "TRAFFIC",
    "store visits": "TRAFFIC",
    # awareness
    "awareness": "AWARENESS",
    "brand awareness": "AWARENESS",
    "reach": "AWARENESS",
    "visibility": "AWARENESS",
    "exposure": "AWARENESS",
    # engagement
    "engagement": "ENGAGEMENT",
    "likes": "ENGAGEMENT",
    "comments": "ENGAGEMENT",
    "shares": "ENGAGEMENT",
    "interactions": "ENGAGEMENT",
    # app
    "app installs": "APP_PROMOTION",
    "app promotion": "APP_PROMOTION",
    "app downloads": "APP_PROMOTION",
    "installs": "APP_PROMOTION",
    "downloads": "APP_PROMOTION",
}

_VALID_OBJECTIVES = {"AWARENESS", "TRAFFIC", "ENGAGEMENT", "LEADS", "APP_PROMOTION", "SALES"}


def _normalize_objective(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = raw.strip().upper()
    if upper in _VALID_OBJECTIVES:
        return upper
    lower = raw.strip().lower()
    return _INTENT_TO_OBJECTIVE.get(lower)


_OBJECTIVE_DISPLAY: dict[str, str] = {
    "AWARENESS": "Awareness",
    "TRAFFIC": "Traffic",
    "ENGAGEMENT": "Engagement",
    "LEADS": "Leads",
    "APP_PROMOTION": "App Promotion",
    "SALES": "Sales",
}


def _objective_display(obj: str | None) -> str:
    """Human-cased objective for chat text. Stored/Meta value stays uppercase."""
    key = (obj or "").strip().upper().replace(" ", "_")
    return _OBJECTIVE_DISPLAY.get(key, (obj or "").title())


def _scrub_brief_field(val: Any) -> Any:
    """Apply narrator jargon scrubber to brief field values before display.

    The LLM-generated campaign brief slips banned terms (MAID, CPM, ABO, custom
    audience) into prose fields because it bypasses the narrator pipeline.
    Strings get scrubbed; nested dicts/lists are walked. Non-string scalars
    pass through unchanged."""
    if isinstance(val, str):
        return scrub_jargon(val)
    if isinstance(val, list):
        return [_scrub_brief_field(v) for v in val]
    if isinstance(val, dict):
        return {k: _scrub_brief_field(v) for k, v in val.items()}
    return val


def _flight_days(user_info: dict) -> int | None:
    """Whole-day count between campaign start and end (inclusive). None if unknown."""
    from datetime import date
    start = (user_info.get("campaign_start_date") or "").strip()
    end = (user_info.get("campaign_end_date") or "").strip()
    if not start or not end:
        return None
    try:
        d0 = date.fromisoformat(start[:10])
        d1 = date.fromisoformat(end[:10])
        days = (d1 - d0).days
        return days if days > 0 else None
    except ValueError:
        return None


def _metric_cells(brief: dict, user_info: dict, geo_data: dict) -> list[tuple[str, str]]:
    """Derive the 4-cell metric strip: (value, label) pairs."""
    symbol, scale, places = _money_fmt(user_info)
    cents = _parse_budget_to_cents(user_info.get("budget") or "", user_info.get("ad_account_currency"))
    amount = cents / scale
    is_lifetime = (user_info.get("budget_type") or "").lower() == "lifetime"
    days = _flight_days(user_info)  # None ⇒ ongoing / unknown

    def _money(v: float | None) -> str:
        return f"{symbol}{v:,.{places}f}" if v is not None else "—"

    if is_lifetime:
        # Lifetime budget is a fixed pot; per-day derives from the flight length.
        total_cell = _money(amount)
        per_day_cell = _money((amount / days) if days else None)
    else:
        # Daily budget: total = daily × duration; "Ongoing" when no end date.
        per_day_cell = _money(amount)
        total_cell = _money(amount * days) if days else "Ongoing"

    cells: list[tuple[str, str]] = [
        (total_cell, "Total budget"),
        (per_day_cell, "Per day"),
    ]

    # Direct audience = the MAID seed list (deterministic targeting). The plan
    # also runs a broader lookalike/geo ad set, so label this as the *direct*
    # audience and surface the wider estimate separately.
    #
    # `filtered_maid_count` — not the raw `maid_count` superset — because
    # that's what media._load_maids actually uploads to Meta; showing the
    # unfiltered number here promised a bigger "Real Visitor Audience" than
    # the campaign would ever reach.
    maid = geo_data.get("filtered_maid_count")
    if maid is None:
        maid = geo_data.get("maid_count")
    cells.append((f"{maid:,}" if maid else "—", "Real Visitor Audience"))

    # Estimated total reach (incl. lookalike) — LLM brief estimate.
    kpis = brief.get("kpi_targets") or {}
    reach_raw = str(kpis.get("reach") or kpis.get("impressions") or "").strip()
    cells.append((_short_reach(reach_raw) if reach_raw else "—", "Est. Reach"))

    cells.append((f"{days} days" if days else "Ongoing", "Flight"))
    return cells


def _short_reach(text: str) -> str:
    """Trim a verbose reach string to the leading number/range for the 22px
    metric slot — e.g. '40,000–60,000 unique users' → '40,000–60,000'."""
    import re
    m = re.match(r"[\d.,]+(?:\s*[–\-]\s*[\d.,]+)?(?:\s*[KMkm]\+?)?", text)
    return m.group().strip() if m and m.group().strip() else text


def _selected_tier_reach(budget_label: str) -> str | None:
    """Pull the reach figure the budget tier promised, e.g.
    '...reaches ~38,000 over 14 days' → '38,000' or '~38,000–60,000' → '38,000–60,000'.

    The budget options stored whole into ``user_info['budget']`` carry the tier's
    REACH FRAMING copy (prompts REACH FRAMING block). None for a custom amount (no
    reach copy) so the LLM brief estimate is left untouched."""
    import re
    m = re.search(
        r"reach(?:es)?\s+~?([\d.,]+(?:\s*[–\-]\s*[\d.,]+)?(?:\s*[KMkm]\+?)?)",
        # str(): this slot is written from several places and a regex is not the
        # thing that should discover a type change. A float here (the express
        # intake used to store one) crashed the whole brief step.
        str(budget_label or ""),
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def reconcile_brief_reach(brief: dict, user_info: dict) -> dict:
    """Carry the picked budget tier's reach into the brief so the plan card's
    Est. Reach + KPI table match what the user was promised at budget pick. No
    tier reach (custom amount) ⇒ leave the LLM estimate untouched."""
    reach = _selected_tier_reach(user_info.get("budget") or "")
    if reach:
        brief.setdefault("kpi_targets", {})["reach"] = reach
    return brief


def _fmt_budget(amount: float, is_lifetime: bool, symbol: str = "$", places: int = 2) -> str:
    """'$280/day' / '৳1,650 total' — whole units unless the fraction is needed."""
    period = "total" if is_lifetime else "/day"
    body = (
        f"{symbol}{amount:,.0f}"
        if places == 0 or float(amount).is_integer()
        else f"{symbol}{amount:,.{places}f}"
    )
    return f"{body} {period}" if is_lifetime else f"{body}{period}"


def reconcile_brief_budget(brief: dict, user_info: dict) -> dict:
    """Force every budget figure the brief DISPLAYS to equal the user's chosen
    budget. The Meta JSON already uses the deterministic ``pre_computed`` cents,
    but ``generate_campaign_brief`` freely invents ``budget_breakdown`` /
    ``adset_budget_breakdown`` numbers that then show on the plan card and in the
    drafted-plan narration — the source of the "recommended $280 but plan says
    $490" mismatch. This overwrites the top-line budget string and each ad-set's
    amount from the chosen daily budget, normalizing ``budget_pct`` to sum to 100.
    Mirrors ``reconcile_brief_reach`` — deterministic, called right after it."""
    if not isinstance(brief, dict):
        return brief
    symbol, scale, places = _money_fmt(user_info)
    cents = _parse_budget_to_cents(user_info.get("budget") or "", user_info.get("ad_account_currency"))
    total = cents / scale
    is_lifetime = (user_info.get("budget_type") or "").lower() == "lifetime"
    brief["budget_breakdown"] = _fmt_budget(total, is_lifetime, symbol, places)

    adsets = brief.get("adset_budget_breakdown")
    if isinstance(adsets, list) and adsets:
        pcts = [max(float(ab.get("budget_pct") or 0), 0) for ab in adsets]
        if sum(pcts) <= 0:
            pcts = [100.0 / len(adsets)] * len(adsets)      # equal split
        scale = sum(pcts)
        norm = [round(p * 100.0 / scale) for p in pcts]
        norm[0] += 100 - sum(norm)                          # absorb rounding drift
        for ab, p in zip(adsets, norm):
            ab["budget_pct"] = p
            ab["budget_amount"] = _fmt_budget(total * p / 100.0, is_lifetime, symbol, places)
    return brief


# Campaign Setup rows for the structured (v2) plan payload.
_SETUP_MAP: tuple[tuple[str, str], ...] = (
    ("Objective", "objective_label"),
    # Why this conversion location + goal. The objective is immutable at Meta
    # once the campaign is created, so the reasoning belongs next to it rather
    # than buried in the strategy prose.
    ("Conversion Location", "conversion_location_rationale"),
    ("Dates", "flight_window"),
    ("Budget", "budget_breakdown"),
    ("Budget Optimization", "budget_optimization_type"),
    ("Bid Strategy", "bid_strategy"),
    ("Placements", "placement_strategy"),
    ("Frequency", "frequency_recommendation"),
    ("Learning Phase", "learning_phase_note"),
    ("Creative", "creative_format"),
)


def brief_to_plan_payload(brief: dict, user_info: dict, geo_data: dict) -> dict:
    """The campaign plan as structured data — the v2 ``campaign_plan`` payload.

    Replaces the self-contained HTML string the backend used to emit, which the
    client injected with ``dangerouslySetInnerHTML``. That put every styling
    decision in Python, made the card impossible to theme or restructure
    client-side, and rested its safety entirely on server-side escaping.

    Sections are typed so a renderer can map them to its own components:
      ``metrics``  – label/value tiles
      ``kv``       – label/value rows
      ``text``     – a paragraph
      ``list``     – bullets
      ``table``    – columns + rows
    """
    brief = brief or {}
    user_info = user_info or {}
    geo_data = geo_data or {}

    # Fallback shape: brief generation produced unparseable output.
    if not isinstance(brief, dict) or "raw" in brief:
        raw_text = brief.get("raw", "") if isinstance(brief, dict) else str(brief)
        return {
            "version": 2,
            "title": "Your Campaign Strategy is Ready",
            "subtitle": "",
            "sections": [{"key": "raw", "label": "", "type": "text", "text": raw_text}],
        }

    brief = _scrub_brief_field(brief)
    sections: list[dict] = []

    def _add(key: str, label: str, type_: str, **payload) -> None:
        sections.append({"key": key, "label": label, "type": type_, **payload})

    _add("metrics", "", "metrics", items=[
        {"label": label, "value": value}
        for value, label in _metric_cells(brief, user_info, geo_data)
    ])

    if brief.get("strategic_insight"):
        _add("strategy", "Strategy", "text", text=str(brief["strategic_insight"]))

    setup_rows = [
        {"label": label, "value": str(brief[key])}
        for label, key in _SETUP_MAP if brief.get(key)
    ]
    if setup_rows:
        _add("setup", "Campaign Setup", "kv", rows=setup_rows)

    creative_rows: list[dict] = []
    if brief.get("cta_recommendation"):
        creative_rows.append({"label": "Call to action", "value": str(brief["cta_recommendation"])})
    for i, headline in enumerate(brief.get("headline_suggestions") or [], 1):
        creative_rows.append({"label": f"Headline {i}", "value": str(headline)})
    for i, body in enumerate(brief.get("body_copy_suggestions") or [], 1):
        creative_rows.append({"label": f"Body copy {i}", "value": str(body)})
    if brief.get("description_suggestion"):
        creative_rows.append(
            {"label": "Description", "value": str(brief["description_suggestion"])}
        )
    if creative_rows:
        _add("creative", "Creative Direction", "kv", rows=creative_rows)

    for key, label in (("audience_summary", "Audience"), ("audience_persona", "Persona"),
                       ("adset_structure", "Ad Set Structure"),
                       ("full_funnel_recommendation", "What's Next")):
        if brief.get(key):
            _add(key, label, "text", text=str(brief[key]))

    breakdown = brief.get("adset_budget_breakdown") or []
    if breakdown:
        _add("adsets", "Ad Sets", "table",
             columns=["Ad Set", "Audience Type", "Share", "Budget"],
             rows=[
                 [
                     str(row.get("adset_name") or f"Ad Set {i + 1}"),
                     str(row.get("audience_type") or "—"),
                     f"{row.get('budget_pct')}%" if row.get("budget_pct") else "—",
                     str(row.get("budget_amount") or "—"),
                 ]
                 for i, row in enumerate(breakdown)
             ])

    kpis = brief.get("kpi_targets") or {}
    if isinstance(kpis, dict) and kpis:
        _add("kpis", "KPI Targets", "kv",
             rows=[{"label": k.replace("_", " ").title(), "value": str(v)}
                   for k, v in kpis.items() if v])

    timeline = brief.get("campaign_timeline") or []
    if timeline:
        _add("timeline", "Campaign Timeline", "table",
             columns=["Phase", "Dates", "Focus"],
             rows=[[str(p.get("phase") or "—"), str(p.get("dates") or "—"),
                    str(p.get("focus") or "—")] for p in timeline])

    if brief.get("pixel_warning"):
        _add("pixel_warning", "Heads up", "text", text=str(brief["pixel_warning"]))

    return {
        "version": 2,
        "title": brief.get("campaign_name") or "Campaign Plan",
        "subtitle": brief.get("campaign_type_label") or brief.get("campaign_type") or "",
        "sections": sections,
    }


# Anchored on a currency token so it cannot swallow the reach figures that share
# the label ("reaches ~38,000 lookalike matches"). Both spellings appear: the
# prompt asks for the account's ISO code, and older/US labels carry "$".
_MONEY_RE = re.compile(r"(?:[A-Z]{3}\s*|\$\s*)([\d,]+(?:\.\d+)?)")


def _budget_floor(user_info: dict, scale_type: str, flight_days: int) -> tuple[float, str]:
    """Meta's minimum for THIS ad account, in its own currency, plus that code.

    ``min_budget_cents`` already resolves the account's ``min_daily_budget``
    against the static constant and is the only floor that is right across US,
    Canada and Bangladesh — the dollar constant this used to read is wrong on
    every non-USD account (BDT 120 where USD is 1.00).
    """
    from app.graph.meta_spec.models import min_budget_cents

    floor = min_budget_cents(user_info) / 100
    code = str(user_info.get("ad_account_currency") or "USD").upper()
    return (floor * flight_days if scale_type == "lifetime" else floor), code


def _clamp_budget_label(
    label: str, user_info: dict, scale_type: str, flight_days: int
) -> str:
    """Raise the first money amount in a budget string to this account's floor.

    Safety net only — the prompt owns realistic numbers; this stops an LLM
    lowball (the seed-anchoring bug produced "$2.68/day") from ever shipping
    something Meta's API would reject. Rewrites just the first money token (the
    budget); the trailing "/day" / "total" and the reach copy are left intact.
    The replacement carries the account's currency code, because the amount is
    charged in that currency whatever symbol the label used.
    """
    m = _MONEY_RE.search(label or "")
    if not m:
        return label
    try:
        amount = float(m.group(1).replace(",", ""))
    except ValueError:
        return label
    floor, code = _budget_floor(user_info, scale_type, flight_days)
    if amount >= floor:
        return label
    amount_text = f"{int(floor)}" if floor.is_integer() else f"{floor:.2f}"
    return label[:m.start()] + f"{code} {amount_text}" + label[m.end():]


async def _grounded_cpm_context(
    industry: str | None, business_category: str | None, market: str, bs: dict | None,
) -> str | None:
    """Live CPM figure for this industry, cached in builder scratch so a resume
    (which re-derives the whole recommendation) reuses it instead of re-querying
    live search and risking a different figure between what the user saw and
    what gets stored — the same determinism concern that pins temperature=0
    above. Returns None when there's nothing to search for or nothing was found;
    the prompt's static benchmark table is the fallback either way."""
    if not (industry or business_category):
        return None
    key = f"{industry or ''}|{business_category or ''}|{market}"
    cache = (bs or {}).setdefault("_cpm_benchmark_cache", {}) if bs is not None else {}
    if key in cache:
        return cache[key] or None
    from app.graph.grounding import grounded_text

    try:
        result = await grounded_text(
            CPM_BENCHMARK_LOOKUP_PROMPT.format(
                industry=industry or "general", business_category=business_category or "", market=market,
            )
        )
        result = result.strip()
        result = "" if result == "NONE" else result
    except Exception as exc:
        logger.info("build_budget_options: CPM grounding skipped/failed — %s", exc)
        result = ""
    cache[key] = result
    return result or None


async def build_budget_options(
    user_info: dict, geo_data: dict, enrichment: dict, writer,
    *, include_custom: bool = True, bs: dict | None = None,
) -> tuple[list[str], str]:
    """Budget tier options + inferred budget_type ('daily'|'lifetime'). Shared by
    ``campaign_collect_budget_amount`` and the campaign-builder agent. The
    builder passes ``include_custom=False`` — it has no custom-amount follow-up
    slot. ``bs`` (builder scratch) is optional — pass it to cache the live CPM
    lookup across a resume; omitted callers just skip the live figure.

    temperature=0: the campaign-builder shows this recommendation at the batch
    ask and re-derives it on resume (langgraph discards a node's pre-interrupt
    writes). A non-deterministic tier would then differ between what the user saw
    and what gets stored — so pin it to 0 for a stable recommendation."""
    llm = _make_llm(temperature=0.0)
    budget_recs: list[dict] = []
    try:
        # Currency and floor are inputs, not decoration: the amount is charged in
        # the ad account's currency, so a tier sized in dollars for a BDT account
        # underspends by ~120x.
        _floor, _code = _budget_floor(user_info, "daily", 1)
        _market = ", ".join(str(loc) for loc in (user_info.get("location") or [])) or _code
        live_cpm = await _grounded_cpm_context(
            user_info.get("industry"), enrichment.get("business_category"), _market, bs,
        )
        ctx_payload = json.dumps({
            "campaign_objective": user_info.get("campaign_objective"),
            "targeting_method": geo_data.get("targeting_method"),
            "maid_count": geo_data.get("filtered_maid_count", geo_data.get("maid_count")),
            "industry": user_info.get("industry"),
            "business_category": enrichment.get("business_category"),
            "campaign_start_date": user_info.get("campaign_start_date"),
            "campaign_end_date": user_info.get("campaign_end_date"),
            "ad_account_currency": _code,
            "live_cpm_context": live_cpm,
            "min_daily_budget": _floor,
        })
        raw_budget_recs, _ = await tracked_ainvoke(
            llm,
            [SystemMessage(content=BUDGET_RECOMMENDATION_PROMPT), HumanMessage(content=ctx_payload)],
            node_name="campaign_wizard/budget_rec",
            writer=writer,
        )
        raw_text = raw_budget_recs.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```", 2)[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        budget_recs = json.loads(raw_text.strip())
    except Exception as exc:
        logger.warning("campaign_wizard: budget recommendation failed — %s", exc)

    # Budget is ALWAYS daily — the daily/lifetime choice was removed from the
    # wizard. Tiers are sized as daily spends regardless of what the LLM emits.
    scale_type = "daily"

    if not budget_recs:
        budget_recs = [
            {"tier": "Conservative", "scale_description": "Smallest scale, longer learning phase", "scale_type": scale_type, "reason": ""},
            {"tier": "Recommended",  "scale_description": "Balanced scale, optimal learning", "scale_type": scale_type, "reason": ""},
            {"tier": "Aggressive",   "scale_description": "Largest scale, rapid learning", "scale_type": scale_type, "reason": ""},
        ]

    def _option_label(r: dict) -> str:
        return scrub_jargon(f"{r['tier']}: {r['scale_description']}")

    _flight = _flight_days(user_info) or 1
    budget_options = [
        _clamp_budget_label(_option_label(r), user_info, scale_type, _flight)
        for r in budget_recs if isinstance(r, dict)
    ]
    if include_custom:
        budget_options = budget_options + ["Enter a custom amount"]
    return budget_options, scale_type
