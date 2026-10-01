"""
graph/meta_spec/builder.py
──────────────────────────
Deterministic assembly of the Meta campaign spec.

This replaces ``generate_meta_campaign_json`` — a second Gemini Pro call (16k
thinking budget, two retries) that invented the Meta JSON from a brief. That
call was the weakest link in the publish path: its output was validated only by
a permissive model, and the publish code then ignored most of it and rebuilt the
payload from ``geo_data`` anyway. The LLM was spending tokens and latency to
produce a document that barely mattered.

The division of labour now:

  LLM (``generate_campaign_brief``)  — strategy, naming, headline and body copy,
                                       budget split rationale, CTA suggestion.
  This module                        — every structural field Meta validates.

``build_campaign_spec`` is pure: no I/O, no LLM, no clock beyond an explicit
"now" for an absent start date. Targeting dicts are passed in because building
them needs a Graph API call (city name resolution), which belongs in the publish
executor, not here.

Overrides are applied to the plain dict tree *before* validation, so a user edit
that produces an invalid combination surfaces as a Pydantic error keyed to the
field the user touched — which is what the campaign form renders back to them.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from string import capwords
from typing import Any

from app.graph.maid_query import audience_headline_count as _audience_headline_count
from app.graph.meta_spec.catalog import CREATE_DATASET
from app.graph.meta_spec.enums import (
    APP_PLATFORMS,
    BID_STRATEGIES_REQUIRING_AMOUNT,
    BID_STRATEGY_REQUIRING_ROAS_FLOOR,
    CATEGORIES_BLOCKING_DEMOGRAPHICS,
    CREATIVE_BODY_MAX,
    CREATIVE_DESCRIPTION_MAX,
    CREATIVE_TITLE_MAX,
    FREQUENCY_DEFAULT_INTERVAL_DAYS,
    FREQUENCY_DEFAULT_MAX,
    FREQUENCY_MAX_INTERVAL_DAYS,
    PUBLISHER_PLATFORMS,
    SPECIAL_CATEGORY_MIN_RADIUS_MILES,
    BidStrategy,
    CallToAction,
    DestinationType,
    Objective,
    OptimizationGoal,
    meta_label,
    normalize_objective,
    radius_meets_special_category_floor,
)
from app.graph.meta_spec.models import (
    CREATIVE_MAX_SUGGESTIONS,
    MIN_BUDGET_CENTS,
    min_budget_cents,
    CampaignSpec,
)
from app.graph.meta_spec.objective_matrix import (
    DEFAULT_PIXEL_EVENT,
    MESSENGER_NEEDS_COMPANION,
    PROMOTED_APPLICATION,
    PROMOTED_NONE,
    PROMOTED_PAGE,
    PROMOTED_PIXEL,
    goal_rules,
    matrix_for,
)
from app.graph.meta_spec.parsing import minor_units, parse_budget_to_cents, resolve_flight
from app.graph.meta_spec.special_categories import detect_special_ad_categories

logger = logging.getLogger(__name__)


class SpecBuildError(ValueError):
    """The inputs cannot produce a publishable campaign.

    Distinct from a Pydantic ``ValidationError``: this is a missing
    prerequisite (no objective, no pixel for a conversion campaign), not a badly
    shaped field.
    """


# ── promoted object ──────────────────────────────────────────────────────────


# Every ad Punk publishes carries these unless the user edits them. Without a
# tagged link the advertiser's own analytics files every visit under "direct",
# which is the version of "tracking is broken" that nobody notices for months —
# and a UTM string is free, unlike a pixel, which has to be installed.
#
# The braces are Meta's delivery-time macros, not our templating: Meta substitutes
# the real campaign, ad and placement names per impression, so one string stays
# correct across every ad in the plan and across later edits to their names.
DEFAULT_URL_TAGS: str = (
    "utm_source=facebook&utm_medium=paid"
    "&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{placement}}"
)


def _real_pixel_id(raw: Any) -> str | None:
    """A dataset id, or None for the "create one for me" sentinel.

    The sentinel is a request the executor fulfils (``media_select_pixel``), never
    an id. It reaches here only when creation failed, and Meta would be sent the
    literal string.
    """
    value = str(raw or "").strip()
    return None if not value or value == CREATE_DATASET else value


def _promoted_object(
    kind: str,
    *,
    objective: Objective,
    pixel_id: str | None,
    page_id: str | None,
    application_id: str | None,
    app_store_url: str | None,
    pixel_event: str | None,
    custom_conversion_id: str | None = None,
) -> dict[str, Any] | None:
    if kind == PROMOTED_NONE:
        return None
    if kind == PROMOTED_PIXEL:
        # A missing pixel is NOT fatal here: the plan editor renders a pixel
        # picker for exactly this goal, and that is the only place the user is
        # asked. The event is prefilled so the editor asks for one thing. Without
        # a pixel_id the tree fails CampaignSpec validation, which is what puts
        # the editor in front of the user (see builder_node.generate_meta_json).
        #
        # A custom conversion answers both halves at once — it names the dataset
        # and the rule — so it replaces the event rather than joining it.
        if custom_conversion_id:
            po = {"custom_conversion_id": str(custom_conversion_id)}
            if pixel_id:
                po["pixel_id"] = str(pixel_id)
            return po
        po = {"custom_event_type": pixel_event or DEFAULT_PIXEL_EVENT.get(objective, "PURCHASE")}
        if pixel_id:
            po["pixel_id"] = str(pixel_id)
        return po
    if kind == PROMOTED_PAGE:
        if not page_id:
            raise SpecBuildError(
                "This objective needs a connected Facebook Page. Reconnect your Meta "
                "account and grant access to the Page you advertise under."
            )
        return {"page_id": str(page_id)}
    if kind == PROMOTED_APPLICATION:
        if not (application_id and app_store_url):
            raise SpecBuildError(
                "App promotion needs an app linked to your ad account and its store URL."
            )
        return {"application_id": str(application_id), "object_store_url": app_store_url}
    raise SpecBuildError(f"unknown promoted object kind {kind!r}")


# ── budget split ─────────────────────────────────────────────────────────────


def _adset_budgets(user_info: dict, brief: dict) -> list[dict[str, Any]]:
    """Per-ad-set budget split from the brief's percentages.

    The brief proposes ``adset_budget_breakdown`` with ``budget_pct`` values;
    the user's chosen total is authoritative.

    Every campaign runs at least two ad sets: the MAID seed served directly, and
    a broader one Meta expands into. A brief that proposed only one gets the
    second synthesized here rather than shipping a plan with no prospecting
    reach — the brief's own count is a budget heuristic, and it collapses to one
    ad set exactly when the recommended budget came out low.

    Meta applies its per-ad-set minimum to each, so a total that cannot cover the
    floor twice is spent as two floored ad sets — above what the user asked for.
    ``build_campaign_tree`` says so in ``compliance_notes``; silently publishing a
    different daily spend is the one outcome worse than the note.
    """
    total_cents = parse_budget_to_cents(user_info.get("budget"), user_info.get("ad_account_currency"))
    floor = min_budget_cents(user_info)
    breakdown = [row for row in (brief.get("adset_budget_breakdown") or []) if isinstance(row, dict)]

    rows: list[tuple[int, str]] = []
    for row in breakdown:
        try:
            pct = int(row.get("budget_pct") or 0)
        except (TypeError, ValueError):
            pct = 0
        pct = pct if 0 < pct <= 100 else (100 // max(len(breakdown), 1))
        rows.append((pct, (row.get("audience_type") or "primary").lower()))

    if not rows:
        rows = [(60, "primary")]
    if len(rows) == 1:
        # 60/40 seed-heavy: the seed list is the product, the second ad set buys
        # reach beyond it. "lookalike" resolves to the lookalike audience when one
        # was built and to broad otherwise — both prospect with Advantage+ on.
        rows = [(60, rows[0][1]), (40, "lookalike")]

    weight = sum(pct for pct, _a in rows) or 1
    plain = [int(total_cents * pct / weight) for pct, _a in rows]
    # The plain split is kept whenever it clears the floor on its own — that is
    # the funded case and it spends exactly the total. Only when a slice would
    # dip under Meta's minimum does every slice get the floor first, with
    # whatever is left over shared out by the same weights.
    if min(plain) < floor:
        spare = max(total_cents - floor * len(rows), 0)
        plain = [floor + int(spare * pct / weight) for pct, _a in rows]

    return [
        {"budget_cents": cents, "audience_type": atype}
        for (_pct, atype), cents in zip(rows, plain)
    ]


def _audience_role(index: int, audience_type: str, *, has_lookalike: bool) -> str:
    """Ad set 0 always gets the MAID seed list — it is the product. Later ad
    sets prospect against the lookalike when one exists, otherwise broad."""
    if index == 0:
        return "seed"
    if "lookalike" in audience_type or "prospect" in audience_type:
        return "lookalike" if has_lookalike else "broad"
    return "broad"


# Plain-English role labels for prose that describes the budget split. Ad set
# NAMES are built separately (``_adset_name``, below) so they can say more than
# the role. Keyed on the resolved role, not the brief, so the label cannot
# contradict what the ad set targets: "Expanded Visitor Audience" on a plain
# broad ad set (no lookalike was built) would claim a visitor list that is not
# there.
AUDIENCE_ROLE_LABELS = {
    "seed": "Real Visitor Audience",
    "lookalike": "Expanded Visitor Audience",
    "broad": "New Prospects — Expanded Reach",
}


# ── names ────────────────────────────────────────────────────────────────────
#
# A name has to tell THIS campaign from the user's other ones in Ads Manager, so
# it says what differs — goal, who, where, when — and never the business or Page
# name: the ad account already carries that, and it is identical on every
# campaign the user ever makes. Built from facts the plan already holds, not
# from LLM prose, so a name cannot claim an audience the ad set does not target.

_NAME_SEP = " · "
_NAME_MAX = 120  # Meta allows 255; Ads Manager's columns cut off far earlier.


def _clip(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _with_more(labels: list[str]) -> str:
    """``"Toronto"`` for one, ``"Toronto +2"`` for three — the first is the name,
    the count says there is more behind it."""
    return labels[0] + (f" +{len(labels) - 1}" if len(labels) > 1 else "") if labels else ""


def _place_label(geo_data: dict, user_info: dict) -> str:
    """Where the campaign runs: the geocoded cities, else what the user typed.
    Street addresses and postal codes never make it in — they are not a place a
    person would look for. ``""`` when there is nothing to say."""
    raw: list[Any] = [
        loc.get("locality") or loc.get("location_name")
        for loc in geo_data.get("locations") or []
        if isinstance(loc, dict)
    ]
    if not raw:
        # Only when nothing was geocoded: "Downtown Toronto" typed beside a
        # geocoded "Toronto" would read as two places.
        typed = user_info.get("location")
        raw = typed if isinstance(typed, list) else [typed]
    seen: dict[str, str] = {}
    for item in raw:
        name = str(item or "").split(",")[0].strip()
        if name and not any(c.isdigit() for c in name):
            seen.setdefault(name.casefold(), name)
    return _with_more(list(seen.values()))


def _poi_focus(geo_data: dict) -> str:
    """What the seed audience actually visited — the commonest search term across
    its POIs ("Coffee Shop", "Starbucks"), which is the thing a user recognises."""
    counts = Counter(
        str(p.get("parent_poi_type") or "").strip()
        for p in geo_data.get("targetable_pois") or []
        if isinstance(p, dict)
    )
    counts.pop("", None)
    # Search terms arrive lower-case ("coffee shop"); a brand ("McDonald's") is
    # already cased and capwords would mangle it.
    return _with_more([
        capwords(term) if term.islower() else term for term, _n in counts.most_common()
    ])


def _demographic_label(targeting: dict) -> str:
    """Age and gender when they narrow the audience; nothing for the 18–65 / all
    default, which says nothing."""
    parts: list[str] = []
    lo, hi = targeting.get("age_min"), targeting.get("age_max")
    if (lo, hi) not in ((None, None), (18, 65)):
        parts.append(f"{lo}–{hi}")
    parts += {(1,): ["Men"], (2,): ["Women"]}.get(tuple(targeting.get("genders") or ()), [])
    return " ".join(parts)


def _adset_name(
    role: str, *, focus: str, targeting: dict, index: int, used: set[str]
) -> str:
    if role == "seed":
        parts = ["Real Visitors", focus]
    elif role == "lookalike":
        parts = ["Lookalike of Visitors", focus]
    else:
        parts = ["New Prospects", _demographic_label(targeting) or "Broad Reach"]
    name = _clip(_NAME_SEP.join(p for p in parts if p), _NAME_MAX)
    # A brief with 3+ ad sets lands every extra one on "broad"; numbering keeps
    # them apart in the editor and in Meta's reporting.
    if name in used:
        name = f"{name} {index + 1}"
    used.add(name)
    return name


def ad_name(headline: str, adset_name: str) -> str:
    # The ad set rides along because ``utm_content={{ad.name}}`` is the only thing
    # that tells the advertiser's analytics WHICH audience a click came from.
    return _clip(f"{_clip(headline, 40)}{_NAME_SEP}{adset_name}", _NAME_MAX)


def _strip_business(name: str, business: str) -> str:
    """Drop a leading "Business —" the brief may still write. The prompt no longer
    asks for it, but old checkpointed briefs and a stubborn model both carry it."""
    if not business:
        return name
    lead = re.compile(rf"^\s*{re.escape(business)}\s*[|\-–—:·]\s*", re.I)
    return lead.sub("", name).strip()


# ── creative copy ────────────────────────────────────────────────────────────


def _first_or(values: Any, fallback: str, limit: int) -> str:
    """First non-empty suggestion from the brief, clipped to the hard ceiling.

    ``limit`` is ``CREATIVE_*_MAX`` — the length Meta actually refuses, not the
    recommended length. Copy that runs past the recommendation is kept whole and
    flagged in the editor; clipping only guards against an LLM that ran away.
    """
    items = values if isinstance(values, list) else [values]
    for item in items:
        text = str(item or "").strip()
        if text:
            return text[:limit]
    return fallback[:limit]


def _options(values: Any, fallback: str, limit: int) -> list[str]:
    """All non-empty suggestions from the brief, clipped to the hard ceiling,
    de-duplicated, and capped at ``CREATIVE_MAX_SUGGESTIONS`` — the copy dropdown's
    candidate list. Falls back to a single-element list. Like ``_first_or``, ``limit``
    is ``CREATIVE_*_MAX``, so a headline the LLM wrote at 60 characters reaches the
    user intact rather than cut mid-word at 40."""
    items = values if isinstance(values, list) else [values]
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            out.append(text[:limit])
    seen: set[str] = set()
    deduped = [x for x in out if not (x in seen or seen.add(x))]
    if not deduped:
        deduped = [fallback[:limit]]
    return deduped[:CREATIVE_MAX_SUGGESTIONS]


def _resolve_cta(brief: dict, dest, overrides_cta: str | None) -> CallToAction:
    """CTA from the user's pick, else the brief's recommendation, else the
    destination's default. Anything the destination disallows falls back rather
    than failing — a stale CTA should not block a plan."""
    for candidate in (overrides_cta, brief.get("cta_recommendation")):
        if not candidate:
            continue
        code = str(candidate).split(" — ")[0].split(" - ")[0].strip().upper()
        if dest.allows_call_to_action(code):
            return CallToAction(code)
        if code:
            logger.info("CTA %s not valid for %s — using default", code, dest.label)
    return dest.default_call_to_action


# ── the brief's structural picks ─────────────────────────────────────────────
# The brief recommends more than copy: a conversion location, an optimization
# goal, a bid strategy, CBO vs per-ad-set budgets, a frequency cap and a
# placement approach. Those used to be generated, printed on the plan card, and
# then dropped — the tree took the matrix default regardless, so a card could
# read "CBO" above a spec that was per-ad-set.
#
# Every resolver below follows ``_resolve_cta``: take the brief's value, check it
# against the layer that owns it, fall back to the default and log. A brief is a
# suggestion — a hallucinated value narrows the plan back to the default, it
# never raises.


def _first_enum_mention(text: Any, enum_cls) -> str:
    """First member of ``enum_cls`` named anywhere in a brief string.

    The brief writes prose around its picks ("LOWEST_COST_WITHOUT_CAP for the
    first 7 days, then COST_CAP once learning exits"), so ``_resolve_cta``'s
    leading-token parse misses them. Earliest mention wins: that is the launch
    recommendation, and anything after it is the brief's next-step note.

    Matching is on word boundaries, which the underscores make exact: ``COST_CAP``
    does not match inside ``LOWEST_COST_WITH_BID_CAP``, and ``APP`` does not match
    inside ``WHATSAPP``.
    """
    haystack = str(text or "").upper()
    hits = [
        (m.start(), value)
        for value in (member.value for member in enum_cls)
        if (m := re.search(rf"\b{re.escape(value)}\b", haystack))
    ]
    return min(hits)[1] if hits else ""


def _resolve_goal(brief: dict, dest, *, warm_dataset: bool = True) -> OptimizationGoal:
    """The optimization goal the brief picked, else the destination's default.

    The clamp runs in whichever direction the account can actually deliver, and
    ``warm_dataset`` — a dataset on this account that has fired at least once —
    is what decides which:

    * **With one**, a destination that CAN optimize on a pixel is held to one.
      The brief writes prose and ``_first_enum_mention`` takes the earliest enum
      name in it, so "reach purchase-ready shoppers" resolves to REACH — a Sales
      campaign with no pixel on the ad set, no pixel picker in the plan editor (it
      renders off ``promoted_object_kind_by_goal[goal]``), and the same brief
      resolving differently on the next run.
    * **Without one**, the same clamp is backwards. It reinstates
      OFFSITE_CONVERSIONS on Sales → Website for an advertiser who has no dataset
      to report those conversions, publishing an ad set that optimizes toward an
      event that can never arrive. So the clamp inverts: pixel goals are refused
      and the first goal the destination offers that needs no pixel wins
      (LANDING_PAGE_VIEWS on Sales → Website, CONVERSATIONS on Sales →
      Messenger). ``campaign._objective_options`` has already withheld them from
      the brief; this is the same rule on the fallback path, which the brief does
      not go through.

    Either way the goals on the other side of the clamp stay reachable in the
    editor, where the trade-off is visible and the pixel can be connected.
    """
    code = _first_enum_mention(brief.get("optimization_goal"), OptimizationGoal)
    pixel_goals = {
        g.value for g, kind in dest.promoted_object_by_goal.items()
        if kind == PROMOTED_PIXEL
    }
    if warm_dataset:
        allowed = (lambda c: not pixel_goals or c in pixel_goals)
    else:
        allowed = (lambda c: c not in pixel_goals)

    if code and dest.allows_optimization_goal(code) and allowed(code):
        return OptimizationGoal(code)
    if code:
        logger.info("goal %s not used for %s — using default", code, dest.label)

    # The destination's default is the first element of its tuple, which for a
    # conversion destination IS the pixel goal — so it cannot be the fallback for
    # an account with no dataset.
    if not warm_dataset:
        for goal in dest.optimization_goals:
            if goal.value not in pixel_goals:
                return goal
    return dest.default_optimization_goal


def _resolve_bid_strategy(brief: dict, rules, goal: OptimizationGoal) -> BidStrategy:
    """Bid strategy from the brief, intersected with the objective AND the goal.

    Capped strategies are declined even when both layers allow them: they need a
    companion ``bid_amount`` (or ``roas_average_floor``) that the brief has no
    number for, and inventing one is inventing a spend limit. The plan editor is
    where a cap gets picked, because that is where the number can be typed —
    which is also what the prompt recommends, as a next step rather than a launch
    setting.
    """
    code = _first_enum_mention(brief.get("bid_strategy"), BidStrategy)
    goal_r = goal_rules(goal)
    if code and code not in BID_STRATEGIES_REQUIRING_AMOUNT and code != BID_STRATEGY_REQUIRING_ROAS_FLOOR:
        if rules.allows_bid_strategy(code) and goal_r.allows_bid_strategy(code):
            return BidStrategy(code)
        logger.info("bid strategy %s not valid for %s — using default", code, goal.value)

    # The objective's default is not automatically legal for the goal: the goal
    # layer strips COST_CAP off the frequency goals. Fall through to the first
    # strategy both layers accept rather than shipping a pair Meta rejects.
    default = rules.default_bid_strategy
    if goal_r.allows_bid_strategy(default.value):
        return default
    for candidate in rules.bid_strategies:
        if goal_r.allows_bid_strategy(candidate.value):
            return candidate
    return default


# "CBO" / "ABO" as the leading verdict, before any reasoning. Anchored, because
# the reasoning routinely names the option that was *not* chosen ("ABO — CBO
# would starve the seed ad set"), and a bare substring test reads that as CBO.
_BUDGET_VERDICT_RE = re.compile(r"^\W*(CBO|ABO)\b")


def _wants_campaign_budget(brief: dict) -> bool:
    """Did the brief ask for CBO (one campaign budget Meta distributes)?

    ``budget_optimization_type`` leads with the verdict and follows with a
    sentence of reasoning, so only the leading token counts. Anything that does
    not start with a verdict falls back to ABO: per-ad-set budgets are what the
    plan already computed (``_adset_budgets``), and CBO discards them.
    """
    match = _BUDGET_VERDICT_RE.match(str(brief.get("budget_optimization_type") or "").upper())
    return bool(match) and match.group(1) == "CBO"


# "3/week", "3x per week", "cap 4 per 30 days" → (max_frequency, interval_days).
_FREQUENCY_RE = re.compile(
    r"(\d+)\s*(?:x|times)?\s*(?:/|per)\s*(\d+)?\s*(day|week|month)", re.I
)
_FREQUENCY_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}


def _resolve_frequency_cap(brief: dict, rules, goal: OptimizationGoal) -> list[dict] | None:
    """The brief's frequency cap, or Meta's default, or none.

    Two gates, because Meta has two: only the frequency goals (Reach, ThruPlay)
    accept ``frequency_control_specs``, and only the Awareness / Engagement
    objectives do. Reach is a goal under Traffic and Sales as well, so the goal
    check alone shipped a capped Traffic ad set that Meta rejected at preflight.
    Meta marks the field immutable once the ad set is written, so the value
    chosen here is the value that runs. An unparseable recommendation falls back
    to Meta's own Reach default rather than to no cap: the brief asked for a cap
    either way.
    """
    if not (rules.allows_frequency_control and goal_rules(goal).allows_frequency_control):
        return None

    text = str(brief.get("frequency_recommendation") or "")
    if re.search(r"\bno cap\b|\buncapped\b", text, re.I):
        return None

    max_frequency, interval_days = FREQUENCY_DEFAULT_MAX, FREQUENCY_DEFAULT_INTERVAL_DAYS
    match = _FREQUENCY_RE.search(text)
    if match:
        count, multiple, unit = match.groups()
        days = int(multiple or 1) * _FREQUENCY_UNIT_DAYS[unit.lower()]
        if int(count) >= 1 and 1 <= days <= FREQUENCY_MAX_INTERVAL_DAYS:
            max_frequency, interval_days = int(count), days

    return [{
        "event": "IMPRESSIONS",
        "interval_days": interval_days,
        "max_frequency": max_frequency,
    }]


def _resolve_placements(brief: dict, dest=None) -> list[str]:
    """Publisher platforms the brief named, or ``[]`` for Advantage+ placements.

    Absent ``publisher_platforms`` is how the spec says "let Meta choose", which
    is both Meta's recommendation and the right answer whenever the brief is
    vague — so anything mentioning Advantage+ short-circuits, and an unrecognized
    strategy leaves placements automatic. Positions stay empty: naming a platform
    is a claim the brief can make, naming every surface within it is not.

    Narrowed to what the conversion location can serve on, because the brief is
    LLM prose and a Messenger campaign whose rationale mentions Audience Network
    would otherwise build a spec ``CampaignSpec`` rejects — killing plan
    generation over a phrase, where dropping the platform still produces a
    campaign the user can publish. ``messenger`` alone is dropped for the same
    reason: Meta needs a companion placement beside it.
    """
    text = str(brief.get("placement_strategy") or "").lower()
    if not text or "advantage" in text:
        return []
    named = [
        p for p in PUBLISHER_PLATFORMS if p.replace("_", " ") in text.replace("_", " ")
    ]
    if dest is not None and named:
        allowed = dest.publisher_platforms
        if allowed is not None:
            named = [p for p in named if p in allowed]
        if "messenger" in named and not set(named) & set(MESSENGER_NEEDS_COMPANION):
            named = [p for p in named if p != "messenger"]
    return named


# ── link destination ─────────────────────────────────────────────────────────


def _resolve_destination(rules, raw: Any, brief: dict | None = None):
    """The user's conversion location, else the brief's, else the objective's default.

    The two sources are treated differently on purpose. ``raw`` is a human choice
    carried in ``user_info``, so an unrecognized value is a hard error rather than
    a silent fallback: the destination decides the goal, the billing event and the
    promoted object, and guessing it wrong publishes a campaign nobody designed.
    The brief's pick is a *suggestion*, so an invalid one falls back to the
    default and logs — a hallucinated destination must not kill a run.
    """
    if raw:
        try:
            return rules.for_destination(raw)
        except KeyError as exc:
            raise SpecBuildError(str(exc)) from exc

    code = _first_enum_mention((brief or {}).get("conversion_location"), DestinationType)
    if code and rules.allows_destination_type(code):
        suggested = rules.for_destination(code)
        # A boost destination (On your post / video / event) is an ad that IS an
        # existing Page post, so it cannot be built without an object_story_id —
        # and the brief has no idea which post exists. Suggesting one produced a
        # plan that opened on a blocking validation error, beside a page of
        # composed copy the destination ignores. The user can still choose it
        # deliberately: that arrives as ``raw`` above, with the post picker.
        if not suggested.object_story_kind:
            return suggested
        logger.info(
            "brief suggested boost destination %s with no post to boost — using default",
            code,
        )
        return rules.default_destination
    if code:
        logger.info(
            "conversion location %s not offered by %s — using default",
            code, rules.objective.value,
        )
    return rules.default_destination


# "… | May 2024" / "… - Jan 2026" tail the brief appends to a campaign name.
_NAME_MONTH_TAIL = re.compile(
    r"\s*[|\-–—]\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"\.?\s+\d{4}\s*$",
    re.I,
)


def _strip_name_month(name: Any) -> str:
    """The campaign name without its trailing month, so the caller can stamp the
    real one. Names with no date tail come back unchanged."""
    return _NAME_MONTH_TAIL.sub("", str(name or "").strip()).strip(" |-–—")


def _app_platform_split(user_info: dict) -> list[tuple[str, str, str]]:
    """Which app stores this campaign has links for.

    One ad set per store, because ``promoted_object.object_store_url`` is a
    single URL and an ad set targets one platform. ``_destination_link`` used to
    take the App Store link and silently drop the Play link, so an advertiser who
    gave us both got an iOS-only campaign and no indication why.

    Returns ``[(store_url, user_os, label), …]`` — empty when neither link exists,
    which leaves the normal single-ad-set path alone.
    """
    out: list[tuple[str, str, str]] = []
    for key, user_os, label in APP_PLATFORMS:
        url = str(user_info.get(key) or "").strip()
        if url:
            out.append((url, user_os, label))
    return out


def _destination_link(dest, user_info: dict, page_id: str | None) -> str:
    """Where the ad sends people.

    Driven by the conversion location, not the objective: Sales-to-app and
    Traffic-to-app both want the store URL, and a Sales-to-website campaign wants
    the site even though the same objective can target an app. An advertiser with
    neither gets their connected Facebook Page — the website-less local shop path.
    The old code fell through to ``https://example.com``, a live ad pointing at a
    placeholder.
    """
    if dest.destination_type is DestinationType.APP:
        # One store URL per ad set (Ads Manager's own model). iOS first when
        # both stores were given; the other URL stays in user_info, shown
        # read-only in the plan form. Per-platform ad set splits are a
        # follow-up, not an MVP concern.
        link = (
            user_info.get("app_store_url")
            or user_info.get("play_store_url")
            or user_info.get("website_url")
        )
    elif dest.destination_type is DestinationType.WHATSAPP:
        # Click-to-WhatsApp does not route by URL: the button carries
        # ``app_destination: WHATSAPP`` and Meta dials the number linked to the
        # promoted Page. This link is the constant Meta's own examples use — it
        # exists because link_data requires one, not because anyone follows it.
        # (This used to synthesize wa.me/<number> from a user_info key nothing
        # ever wrote, so every WhatsApp ad silently fell through to the Page URL
        # below and opened Facebook.)
        link = "https://api.whatsapp.com/send"
    else:
        link = user_info.get("website_url")

    if not link and page_id:
        link = f"https://www.facebook.com/{page_id}"

    if not link:
        raise SpecBuildError(
            "This campaign has nowhere to send people — add a website URL, an app "
            "store link, or connect a Facebook Page."
        )

    if not str(link).startswith(("http://", "https://")):
        link = f"https://{link}"
    return str(link)


# ── entry point ──────────────────────────────────────────────────────────────


def build_campaign_spec(
    *,
    user_info: dict,
    geo_data: dict,
    brief: dict,
    seed_targeting: dict,
    broad_targeting: dict,
    lookalike_targeting: dict | None = None,
    page_id: str | None = None,
    instagram_user_id: str | None = None,
    pixel_id: str | None = None,
    application_id: str | None = None,
) -> CampaignSpec:
    """``build_campaign_tree`` + validation — the spec, or an error.

    Raises ``SpecBuildError`` for a missing prerequisite and Pydantic's
    ``ValidationError`` for a field-level problem. Callers that want to hand an
    invalid tree to the plan editor (a conversion goal with no pixel on the
    account) build the tree and validate it themselves.
    """
    return CampaignSpec.model_validate(build_campaign_tree(
        user_info=user_info,
        geo_data=geo_data,
        brief=brief,
        seed_targeting=seed_targeting,
        broad_targeting=broad_targeting,
        lookalike_targeting=lookalike_targeting,
        page_id=page_id,
        instagram_user_id=instagram_user_id,
        pixel_id=pixel_id,
        application_id=application_id,
    ))


def build_campaign_tree(
    *,
    user_info: dict,
    geo_data: dict,
    brief: dict,
    seed_targeting: dict,
    broad_targeting: dict,
    lookalike_targeting: dict | None = None,
    page_id: str | None = None,
    instagram_user_id: str | None = None,
    pixel_id: str | None = None,
    application_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the INITIAL campaign tree from the brief + matrix — unvalidated.

    The user's edits no longer flow through here: the campaign editor submits the
    whole edited spec, validated directly against ``CampaignSpec`` (see
    ``builder_node._apply_plan_form_submission``). This builds the first tree the
    editor renders.

    Raises ``SpecBuildError`` for a missing prerequisite that no edit can fix
    (unknown objective, no Page, no app). A conversion goal with no pixel is NOT
    one of those — it comes back as a tree whose ``promoted_object`` has no
    ``pixel_id``, so the editor can ask for it.
    """
    objective = normalize_objective(user_info.get("campaign_objective"))
    if objective is None:
        raise SpecBuildError(
            f"unrecognized campaign objective: {user_info.get('campaign_objective')!r}"
        )
    rules = matrix_for(objective)
    dest = _resolve_destination(rules, user_info.get("conversion_location"), brief)

    # ── campaign level ───────────────────────────────────────────────────────
    categories = detect_special_ad_categories(
        business_desc=user_info.get("business_description"),
        industry=user_info.get("industry"),
        product_offer=user_info.get("product_offer"),
    )
    business_name = user_info.get("business_name") or "Campaign"

    # ── ad set level ─────────────────────────────────────────────────────────
    is_lifetime = str(user_info.get("budget_type") or "daily").lower() == "lifetime"
    budget_key = "lifetime_budget" if is_lifetime else "daily_budget"
    start, end = resolve_flight(
        user_info.get("campaign_start_date"),
        user_info.get("campaign_end_date"),
        is_lifetime=is_lifetime,
    )

    # The month belongs on the name, but the LLM has no clock: it wrote whatever
    # month it thought it was, which is how a campaign starting August 2026 got
    # named "May 2024". Stamp it from the resolved flight start instead, after
    # dropping whatever date the brief guessed.
    stem = _clip(
        _strip_business(
            _strip_name_month(brief.get("campaign_name")),
            str(user_info.get("business_name") or ""),
        ),
        70,
    ) or rules.label
    place = _place_label(geo_data, user_info)
    campaign_name = _NAME_SEP.join(
        part
        for part in (
            stem,
            # The brief's own audience signal often already names the city.
            place if place and place.split(" +")[0].casefold() not in stem.casefold() else "",
            start.strftime("%b %Y"),
        )
        if part
    )

    # Conversion optimization is on the table when the account has a dataset that
    # has fired (media_detect_pixel), when the user named one on the intake form
    # (intake_to_slots), or when one was resolved for this very tree — a caller
    # that passes an id has already been through media_select_pixel, which only
    # resolves one for a pixel-promoted campaign.
    goal = _resolve_goal(
        brief, dest,
        warm_dataset=bool(user_info.get("has_warm_dataset") or pixel_id),
    )
    bid_strategy = _resolve_bid_strategy(brief, rules, goal)
    # CBO puts one budget on the campaign and none on the ad sets; ABO is the
    # reverse. CampaignSpec rejects both levels carrying money, so the flag has to
    # decide the whole tree rather than each level independently. A campaign
    # lifetime budget also needs every ad set to carry an end_time, so CBO is only
    # honoured when the flight has one.
    campaign_budget = _wants_campaign_budget(brief) and (not is_lifetime or end is not None)
    frequency_control_specs = _resolve_frequency_cap(brief, rules, goal)
    publisher_platforms = _resolve_placements(brief, dest)
    # Naming a platform is a delivery *restriction*: Meta stops serving everywhere
    # else. It is inferred from LLM prose, so it can be inferred wrongly — say so
    # in the plan the same way a special-category removal is said, rather than
    # letting the user discover it from where the ads did not appear.
    placement_notes = [
        "Placements limited to "
        + ", ".join(p.replace("_", " ").title() for p in publisher_platforms)
        + " — everywhere else is switched off. Clear this to let Meta place the "
          "ads automatically (Advantage+), which usually delivers more cheaply."
    ] if publisher_platforms else []
    promoted = _promoted_object(
        dest.promoted_object_kind(goal),
        objective=objective,
        # The "create one for me" sentinel is a request, not an id — it only
        # survives here when dataset creation failed, and publishing it would send
        # Meta the literal string. Fall through to no pixel, which is what puts
        # the editor's dataset picker in front of the user.
        pixel_id=pixel_id or _real_pixel_id(user_info.get("pixel_id")),
        page_id=page_id or user_info.get("meta_page_id"),
        application_id=application_id,
        app_store_url=user_info.get("app_store_url") or user_info.get("play_store_url"),
        pixel_event=user_info.get("pixel_event"),
        custom_conversion_id=user_info.get("custom_conversion_id"),
    )

    # Special ad categories forbid demographic narrowing. Strip it here rather
    # than letting validation reject a plan the user never had a chance to fix.
    strip_demographics = bool({c.value for c in categories} & CATEGORIES_BLOCKING_DEMOGRAPHICS)

    targeting_by_role = {
        "seed": seed_targeting,
        "lookalike": lookalike_targeting or broad_targeting,
        "broad": broad_targeting,
    }
    # A declared category rules out lookalikes entirely (Special Ad Audiences
    # were retired), so prospecting ad sets fall back to broad rather than
    # pointing at an audience Meta will not serve.
    has_lookalike = lookalike_targeting is not None and not categories

    # App promotion: one ad set per store, each with its own store URL and OS
    # targeting. With both links the budget splits between them; with one the
    # loop below is unchanged.
    platforms = (
        _app_platform_split(user_info)
        if dest.destination_type is DestinationType.APP
        else []
    )

    slices = _adset_budgets(user_info, brief)
    adsets: list[dict[str, Any]] = []
    category_removals: list[str] = []
    platform_notes: list[str] = []
    used_names: set[str] = set()
    focus = _poi_focus(geo_data)
    for i, slice_ in enumerate(slices):
        role = _audience_role(i, slice_["audience_type"], has_lookalike=has_lookalike)
        base_targeting = targeting_by_role[role]
        if categories:
            base_targeting, removals = _sanitize_for_special_category(
                base_targeting, geo_data
            )
            # Accumulate, deduped and in order: the ad sets do not share targeting,
            # so the seed's removals differ from the prospecting ones. Reassigning
            # here dropped every note but the last ad set's — the user was told
            # about one change and silently given several.
            for note in removals:
                if note not in category_removals:
                    category_removals.append(note)
        targeting = _prepare_targeting(
            base_targeting, user_info, strip_demographics, role=role
        )
        # An absent publisher_platforms key IS Advantage+ placements, so this is
        # only written when the brief named specific platforms.
        if publisher_platforms:
            targeting = {**targeting, "publisher_platforms": publisher_platforms}
        # After _prepare_targeting: the name reads the age and gender that will
        # actually publish, not the ones a special category just stripped.
        slice_name = _adset_name(
            role, focus=focus, targeting=targeting, index=i, used=used_names
        )
        base_adset = {
            "audience_role": role,
            "optimization_goal": goal.value,
            "billing_event": dest.default_billing_event.value,
            "destination_type": dest.destination_type.value,
            "bid_strategy": bid_strategy.value,
            "start_time": start,
            "end_time": end,
        }
        # Frequency-capped goals (Reach, ThruPlay) open with the brief's cap, or
        # Meta's own default, rather than two blank boxes — every other field in
        # the editor arrives filled in, so an empty pair read as a broken field,
        # not as "no cap". None on every other goal, which rejects the field.
        if frequency_control_specs:
            base_adset["frequency_control_specs"] = frequency_control_specs

        if len(platforms) > 1:
            # Split this slice across the stores. Each ad set keeps the same app
            # (one Meta app carries both platforms) but its own store URL, so
            # Android users are no longer sent to the App Store.
            share = max(slice_["budget_cents"] // len(platforms), min_budget_cents(user_info))
            for store_url, user_os, label in platforms:
                adsets.append({
                    **base_adset,
                    "name": f"{slice_name} — {label}",
                    **({} if campaign_budget else {budget_key: share}),
                    "targeting": {**targeting, "user_os": [user_os]},
                    "promoted_object": (
                        {**promoted, "object_store_url": store_url} if promoted else None
                    ),
                })
            platform_notes = [
                "Split into one ad set per app store — Android and iOS need "
                "different store links.",
                "This publishes as TWO Meta campaigns, one per store. Meta puts "
                "the promoted app on the campaign, and iOS installs need their "
                "own SKAdNetwork campaign that cannot carry Android ad sets.",
            ]
        else:
            adsets.append({
                **base_adset,
                "name": slice_name,
                **({} if campaign_budget else {budget_key: slice_["budget_cents"]}),
                "targeting": targeting,
                "promoted_object": promoted,
            })

    # Meta's per-ad-set minimum can push the plan above the budget the user chose
    # — two ad sets on an account with a high floor cost two floors whatever the
    # brief proposed. The user picked a number; if we are about to spend a
    # different one, the plan has to say it in the account's own currency.
    requested_cents = parse_budget_to_cents(user_info.get("budget"), user_info.get("ad_account_currency"))
    spend_cents = (
        max(requested_cents, min_budget_cents(user_info))
        if campaign_budget
        else sum(s["budget_cents"] for s in slices)
    )
    budget_notes: list[str] = []
    if spend_cents > requested_cents:
        currency = str(user_info.get("ad_account_currency") or "").upper()
        unit = f"{currency} " if currency else ""
        # Both figures are in the account's minor units; a zero-decimal currency
        # divides by 1 and shows no cents.
        scale = minor_units(currency)
        places = 0 if scale == 1 else 2
        period = "total" if is_lifetime else "day"
        budget_notes = [
            f"Budget raised to {unit}{spend_cents / scale:,.{places}f} per {period} — Meta's "
            f"minimum for this ad account is {unit}{min_budget_cents(user_info) / scale:,.{places}f} "
            f"per ad set, and this plan runs {len(slices)}. Lower it by removing an "
            f"ad set, or leave it and the extra buys the broader audience."
        ]

    # ── ad level ─────────────────────────────────────────────────────────────
    link = _destination_link(dest, user_info, page_id or user_info.get("meta_page_id"))
    cta = _resolve_cta(brief, dest, None)
    # The plan LLM produces five headlines and five bodies. The first becomes the
    # primary (published) value; the rest only fill the editor's dropdown. They
    # do not publish — the user opts into extra Meta text variations by adding
    # them to ``*_variants`` in the editor. See CreativeSpec.
    titles = _options(brief.get("headline_suggestions"), business_name, CREATIVE_TITLE_MAX)
    bodies = _options(
        brief.get("body_copy_suggestions"),
        user_info.get("product_offer") or user_info.get("business_description") or business_name,
        CREATIVE_BODY_MAX,
    )
    # Optional — the brief is told to return null when the headline already says
    # everything worth saying, and an empty description is better than filler.
    description = str(brief.get("description_suggestion") or "").strip()[
        :CREATIVE_DESCRIPTION_MAX
    ]

    # Each ad set is seeded with one ad; the editor lets the user add more, each
    # with its own copy + image. Ads are nested under their ad set (Ads-Manager
    # shape) rather than a flat campaign-level list paired by index.
    ad_format = dest.default_ad_format
    for adset in adsets:
        # An app ad set that owns a store URL sends people to *that* store — the
        # single campaign-wide link is what sent Android users to the App Store.
        adset_link = (adset.get("promoted_object") or {}).get("object_store_url") or link
        creative: dict[str, Any] = {
            "title": titles[0],
            "body": bodies[0],
            "call_to_action": cta.value,
            "link": adset_link,
            "format": ad_format.value,
            "url_tags": DEFAULT_URL_TAGS,
        }
        if len(titles) > 1:
            creative["title_suggestions"] = titles
        if len(bodies) > 1:
            creative["body_suggestions"] = bodies
        if description:
            creative["description"] = description
        adset["ads"] = [{"name": ad_name(titles[0], adset["name"]), "creative": creative}]

    tree: dict[str, Any] = {
        "name": campaign_name,
        "objective": objective.value,
        # CBO: the whole budget sits here and the ad sets carry none, plus the
        # campaign-level bid_strategy CampaignSpec requires alongside it. Under
        # ABO both keys stay absent and each ad set owns its own slice.
        **(
            {
                budget_key: max(
                    parse_budget_to_cents(user_info.get("budget"), user_info.get("ad_account_currency")),
                    min_budget_cents(user_info),
                ),
                "bid_strategy": bid_strategy.value,
            }
            if campaign_budget
            else {}
        ),
        "special_ad_categories": [c.value for c in categories],
        # Display-only: what the category forced us to drop, so the editor can
        # say so instead of the user finding out from the delivered audience.
        "compliance_notes": category_removals + platform_notes + placement_notes + budget_notes,
        # Only meaningful with a category, and CampaignSpec rejects it without
        # one — so it is derived only when something was actually detected.
        "special_ad_category_country": (
            _special_ad_category_countries(adsets[0]["targeting"], geo_data, user_info)
            if categories else []
        ),
        "adsets": adsets,
        # The publishing identity, carried on the plan rather than read from
        # user_info at publish: an advertiser with several Pages picks one in the
        # editor, and the ads must run as the Page they picked.
        "page_id": page_id or user_info.get("meta_page_id"),
        "instagram_user_id": instagram_user_id or user_info.get("meta_instagram_user_id"),
        "estimated_reach": {
            # The filtered audience actually uploaded, not the raw superset.
            "maid_count": _audience_headline_count(geo_data),
            "radius_km": geo_data.get("poi_radius_km"),
        },
    }

    return tree


def _special_ad_category_countries(
    targeting: dict, geo_data: dict, user_info: dict
) -> list[str]:
    """The country whose special-ad-category rules this campaign is declared under.

    Meta requires ``special_ad_category_country`` alongside any category and
    rejects the campaign without it. It is the country of the *ad audience*, so
    it comes from the campaign's geography rather than the advertiser's own
    address.

    Meta ZIP keys are ``COUNTRY:CODE`` ("CA:M5V"), which is the most reliable
    source we have — but this runs on the **sanitized** targeting, and the ZIPs
    are the first thing a special ad category strips. Reading them off
    ``targeting`` alone therefore missed on exactly the runs this function exists
    for, and a Toronto advertiser declared under US rules. ``geo_data`` is the
    pre-sanitize source and still has them.
    """
    geo = targeting.get("geo_locations") or {}

    countries = geo.get("countries")
    if countries:
        return sorted({str(c).upper() for c in countries})

    def _prefixes(keys) -> set[str]:
        return {
            str(k).split(":")[0].strip().upper()
            for k in keys
            if ":" in str(k)
        }

    # Surviving ZIPs (no category declared), then the ones sanitization removed.
    for keys in (
        [z.get("key", "") for z in (geo.get("zips") or [])],
        geo_data.get("target_zips") or [],
    ):
        found = _prefixes(keys)
        if found:
            return sorted(found)

    # Geocoded POIs carry their own ISO code — the same source
    # ``meta_ads._derive_lookalike_countries`` falls back to.
    from_locations = {
        str(loc.get("country_code")).strip().upper()
        for loc in (geo_data.get("locations") or [])
        if loc.get("country_code")
    }
    if from_locations:
        return sorted(from_locations)

    explicit = user_info.get("country") or user_info.get("country_code")
    if explicit:
        return [str(explicit).upper()]

    logger.warning(
        "special ad category declared with no country in targeting — defaulting to US"
    )
    return ["US"]


def _radius_pins(geo_data: dict, radius_miles: int) -> list[dict[str, Any]]:
    """``geo_locations.custom_locations`` from the coordinates geo already has.

    The obvious substitute for a ZIP is a city, but Meta's ``cities`` block takes
    an **adgeolocation key**, not a name — ``{"name": "Toronto"}`` is what the API
    returns on a read and is rejected on a write. Resolving a key means a
    ``/search?type=adgeolocation`` call, and this module is pure by contract (it
    runs on every plan build and every checkpoint replay).

    Coordinates need no lookup, and ``geo_data["locations"]`` already carries them
    from the geocode step. A radius ring around each geocoded location is also
    closer to what the user asked for than a whole city.
    """
    pins: list[dict[str, Any]] = []
    for loc in geo_data.get("locations") or []:
        try:
            pins.append({
                "latitude": float(loc["latitude"]),
                "longitude": float(loc["longitude"]),
                "radius": radius_miles,
                "distance_unit": "mile",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return pins


def _widen_radii(geo: dict, floor_miles: int) -> int:
    """Raise every ``custom_locations`` ring to ``floor_miles``. Returns how many
    were widened.

    Replaces the entries rather than mutating them: ``geo`` is a shallow copy, so
    editing a pin in place would reach back into the caller's targeting dict and
    silently widen the ad set we were handed.
    """
    pins = geo.get("custom_locations")
    if not pins:
        return 0

    out: list[dict[str, Any]] = []
    widened = 0
    for pin in pins:
        if radius_meets_special_category_floor(pin.get("radius"), pin.get("distance_unit")):
            out.append(pin)
            continue
        out.append({**pin, "radius": floor_miles, "distance_unit": "mile"})
        widened += 1

    if widened:
        geo["custom_locations"] = out
    return widened


def _sanitize_for_special_category(targeting: dict, geo_data: dict) -> tuple[dict, list[str]]:
    """Strip everything a special ad category forbids, and say what was removed.

    This is the compliance hole the audit found. Housing, employment and credit
    ads may not:

      * target by **ZIP code** — the floor is a city or a radius, and any radius
        must be at least 15 miles. Punk's whole geo model is ZIPs resolved from
        POIs, so a detected category made every plan non-compliant, not merely
        narrow.
      * use **lookalike audiences** — Special Ad Audiences were retired in 2022,
        which removes the MAID-seeded lookalike that is the rest of the product.
      * use **detailed targeting** (interests/behaviors), and exclusions are
        forbidden outright.

    Age/gender are handled separately by ``strip_demographics``, because Meta
    blocks those for a narrower set of categories.

    Returns the cleaned targeting plus a list of human-readable removals, so the
    caller can tell the user what changed instead of silently shrinking their
    campaign. Custom audiences are **kept**: only Special Ad Audiences went away,
    and a customer/device list remains permitted.

    This is the build-time half. ``CampaignSpec`` enforces the same rules at
    validation, because the plan is editable and a user can put a ZIP back.
    """
    cleaned = dict(targeting)
    removed: list[str] = []

    geo = dict(cleaned.get("geo_locations") or {})
    if geo.get("zips"):
        countries = sorted({
            str(z.get("key", "")).split(":")[0].upper()
            for z in geo["zips"]
            if ":" in str(z.get("key", ""))
        })
        geo.pop("zips", None)
        # Prefer a 15-mile ring around each geocoded location; fall back to the
        # country the ZIPs were in, which is coarse but legal. Never leave the
        # block empty — AdSetSpec rejects targeting with no geo, and a silent
        # nationwide spend is the failure mode that check exists to prevent.
        #
        # Rings already on the ad set win: they are the POIs this campaign was
        # built around, and the widening below brings them up to the floor.
        # Synthesizing over them would throw that geography away.
        pins = geo.get("custom_locations") or _radius_pins(
            geo_data, SPECIAL_CATEGORY_MIN_RADIUS_MILES
        )
        if pins:
            geo["custom_locations"] = pins
            removed.append(
                f"ZIP targeting replaced with a {SPECIAL_CATEGORY_MIN_RADIUS_MILES}-mile "
                f"radius around {len(pins)} location(s) — Meta's minimum for this category"
            )
        else:
            geo["countries"] = countries or ["US"]
            removed.append(
                f"ZIP targeting replaced with country targeting ({', '.join(countries) or 'US'})"
            )
        cleaned["geo_locations"] = geo

    # A ring that was already there is just as restricted as one we just built.
    # The MAID seed ad set targets a ~2 km radius around each POI, which is well
    # under Meta's floor — widening it is the only legal option, and the user is
    # told the audience grew.
    widened = _widen_radii(geo, SPECIAL_CATEGORY_MIN_RADIUS_MILES)
    if widened:
        cleaned["geo_locations"] = geo
        removed.append(
            f"radius targeting widened to Meta's {SPECIAL_CATEGORY_MIN_RADIUS_MILES}-mile "
            f"minimum for this category ({widened} location(s))"
        )

    if cleaned.pop("flexible_spec", None):
        removed.append("interest and behavior targeting removed")
    if cleaned.pop("exclusions", None):
        removed.append("audience exclusions removed")

    return cleaned, removed


def _prepare_targeting(
    base: dict, user_info: dict, strip_demographics: bool, *, role: str = "broad"
) -> dict:
    """Layer the user's demographic preferences onto a geo targeting spec.

    ``build_targeting`` produces geo + audience only; age and gender live in
    ``user_info``. They were assembled into ``build_meta_precomputed``'s
    ``targeting_spec`` before — which never reached Meta, because publish used
    ``build_targeting``'s output directly. Merging here is what actually makes
    the user's age/gender choice take effect.

    Advantage+ audience defaults by role: the MAID seed list IS the product, so
    the seed ad set keeps it strict (0); prospecting ad sets (lookalike/broad)
    let Meta expand (1). Placement keys are deliberately NOT seeded — absent keys
    mean Advantage+ placements; the editor seeds them only when the user picks
    manual placements.
    """
    targeting = {k: v for k, v in dict(base).items() if not k.startswith("_")}
    targeting["targeting_automation"] = {
        "advantage_audience": 0 if role == "seed" else 1
    }

    if strip_demographics:
        targeting["genders"] = []
        targeting["age_min"] = 18
        targeting["age_max"] = 65
        return targeting

    targeting["age_min"] = int(user_info.get("target_age_min") or 18)
    targeting["age_max"] = int(user_info.get("target_age_max") or 65)
    gender = str(user_info.get("target_gender") or "").strip().lower()
    targeting["genders"] = {"male": [1], "female": [2]}.get(gender, [])
    return targeting


# ── reusing a previous campaign's setup ──────────────────────────────────────


def _truncation_note(noun: str, picked: int, fits: int, *, prefix: str = "") -> str:
    """Why some of the previous campaign didn't land.

    The overlay maps positionally onto the plan this run built, so a template
    carrying more ad sets (or more ads in one ad set) than the plan has loses the
    extras. Saying so beats a user counting the cards and finding one short.
    """
    plural = noun if fits == 1 else f"{noun}s"
    head = f"{prefix}: " if prefix else ""
    return (
        f"{head}{picked - fits} of the {picked} {noun}s from that campaign didn't "
        f"fit — this plan has {fits} {plural}, so the extras weren't used."
    )


def apply_campaign_template(
    tree: dict,
    template: dict,
    *,
    page_id: str | None = None,
    pixel_id: str | None = None,
) -> dict:
    """Overlay a previous campaign's settings onto a freshly built plan tree.

    ``tree`` is what ``build_campaign_spec`` just produced from *this* session:
    this run's geo, this run's MAID seed and lookalike, this run's budget split.
    The template supplies only the shape around that — objective, conversion
    location, optimization goal, billing, bidding, and the creative.

    **Targeting is never touched.** That is not a rule enforced by a check here;
    it is a property of overlaying rather than replacing. The template carries no
    targeting key at all (see ``importer.campaign_template``), so the audience
    this run built cannot be overwritten.

    Ad sets are matched positionally, and the template's last ad set is reused
    when the new plan has more of them — the budget split comes from this run's
    brief and need not match the old campaign's shape. Creatives likewise.

    Returns a new tree; the caller validates it. An overlay that produces a
    combination the matrix rejects is surfaced to the user as field errors in the
    plan editor, the same as any invalid edit.
    """
    if not template:
        return tree

    out = dict(tree)
    for key in ("objective", "bid_strategy"):
        if template.get(key):
            out[key] = template[key]
    # The two category keys are copied even when empty. `if template.get(key)`
    # made the overlay additive-only: starting from an unregulated campaign
    # could not clear a category already on the plan, and the pair has to move
    # together or CampaignSpec rejects a country with no category. The template
    # IS the answer to "what kind of campaign is this".
    for key in ("special_ad_categories", "special_ad_category_country"):
        out[key] = template.get(key) or []

    tpl_adsets = template.get("adsets") or []
    if not tpl_adsets:
        return out

    notes: list[str] = []
    plan_adsets = out.get("adsets") or []
    if len(tpl_adsets) > len(plan_adsets):
        # More ad sets came from the old campaign than this plan has slots for.
        # They are dropped rather than added: this run owns the budget split and
        # the seed/lookalike audience roles, and a new ad set would have neither.
        notes.append(_truncation_note("ad set", len(tpl_adsets), len(plan_adsets)))

    adsets: list[dict[str, Any]] = []
    for idx, adset in enumerate(plan_adsets):
        # min() rather than modulo: with fewer template ad sets than new ones, the
        # last one repeats. Cycling would assign the seed ad set's settings to a
        # prospecting one purely by position.
        tpl = tpl_adsets[min(idx, len(tpl_adsets) - 1)]
        merged = dict(adset)
        for key, value in tpl.items():
            if key in ("creatives", "promoted_object"):
                continue
            merged[key] = value

        # The promoted object is merged, not replaced. Both halves matter:
        #
        #   * This run's ids win where it has them — they were resolved against
        #     the live account moments ago.
        #   * The template fills what this run has none of. The plan was built
        #     under whatever objective the intake form carried; if the template
        #     changes it to a conversion objective, this run never resolved a
        #     pixel and the ad set would be a conversion goal with nothing to
        #     optimize against. The template's ids are safe to use because the
        #     template came from the same ad account we are publishing to.
        #   * The event type always comes from the template — it is the thing the
        #     user chose to optimize for last time, and the reason they picked
        #     this campaign as a starting point.
        tpl_promoted = tpl.get("promoted_object") or {}
        if tpl_promoted:
            combined = dict(tpl_promoted)
            for key in ("pixel_id", "page_id", "application_id", "object_store_url"):
                if (merged.get("promoted_object") or {}).get(key):
                    combined[key] = merged["promoted_object"][key]
            merged["promoted_object"] = combined

        creatives = tpl.get("creatives") or []
        if creatives:
            plan_ads = merged.get("ads") or []
            if len(creatives) > len(plan_ads):
                notes.append(_truncation_note(
                    "ad", len(creatives), len(plan_ads),
                    prefix=str(merged.get("name") or ""),
                ))
            merged["ads"] = [
                {
                    **ad,
                    "creative": _merge_creative(
                        ad.get("creative") or {},
                        creatives[min(jdx, len(creatives) - 1)],
                    ),
                }
                for jdx, ad in enumerate(plan_ads)
            ]
        adsets.append(merged)

    out["adsets"] = [
        _reconcile_adset(a, out.get("objective"), notes, page_id=page_id, pixel_id=pixel_id)
        for a in adsets
    ]
    if notes:
        out["compliance_notes"] = [*(out.get("compliance_notes") or []), *notes]
    return out


def _reconcile_promoted_object(
    kind: str, promoted: dict, *, page_id: str | None, pixel_id: str | None
) -> dict[str, Any] | None:
    """A promoted object holding only what the required kind uses.

    Filtering rather than filling is the point: ``PromotedObject.kind()`` reads by
    precedence (a pixel_id wins over a page_id), so a leftover pixel from the
    template makes a Page-promoted ad set *look* like a pixel one and the spec is
    rejected for a field the user never touched. This run's id fills a gap the
    template left, but never overrides one the template carried — the template's
    ids come from the same ad account we publish to.
    """
    if kind == PROMOTED_NONE:
        return None
    if kind == PROMOTED_PAGE:
        # This run's Page wins over the template's, unlike the pixel below: the
        # template may be a campaign from a different brand Page on the same ad
        # account, and the Page is what the ads publish AS. Carrying the old one
        # over would advertise last quarter's brand under this quarter's plan.
        return {"page_id": page_id or promoted.get("page_id")}
    if kind == PROMOTED_PIXEL:
        # A template built on a custom conversion keeps it: the conversion is
        # account-scoped, so it is still valid here, and it names the rule the
        # advertiser actually optimizes for. Its own event definition replaces
        # custom_event_type, which Meta has no use for beside it.
        if promoted.get("custom_conversion_id"):
            return {
                "custom_conversion_id": promoted["custom_conversion_id"],
                "pixel_id": promoted.get("pixel_id") or pixel_id,
            }
        return {
            "pixel_id": promoted.get("pixel_id") or pixel_id,
            "custom_event_type": promoted.get("custom_event_type"),
        }
    # PROMOTED_APPLICATION — both halves come from this run's app ad set, which the
    # template has no equivalent of.
    return {
        k: promoted.get(k) for k in ("application_id", "object_store_url")
    }


def _reconcile_bidding(
    out: dict, rules: Any, goal_enum: OptimizationGoal | None, notes: list[str]
) -> None:
    """Make the template's bid settings legal for the reconciled objective + goal.

    ``CampaignSpec`` checks the bid strategy against BOTH the objective and the
    goal, and checks that ``bid_amount``/``bid_constraints`` accompany exactly the
    strategy that takes them. A template carrying a ROAS goal onto an Awareness
    plan, or a cost cap onto a Reach goal, satisfied none of that — and the user
    saw a field error on a value they never typed.

    ``LOWEST_COST_WITHOUT_CAP`` is the fallback because it is the one strategy
    every objective and every goal allows, and it needs no companion amount.
    """
    allowed = {s.value for s in rules.bid_strategies}
    if goal_enum is not None:
        allowed &= {s.value for s in goal_rules(goal_enum).bid_strategies}

    strategy = str(out.get("bid_strategy") or "")
    # A capped strategy with no amount to cap at is as unpublishable as an
    # illegal one, and there is no sane amount to invent.
    needs_amount = strategy in BID_STRATEGIES_REQUIRING_AMOUNT and not out.get("bid_amount")
    needs_floor = strategy == BID_STRATEGY_REQUIRING_ROAS_FLOOR and not out.get("bid_constraints")

    if strategy and (strategy not in allowed or needs_amount or needs_floor):
        fallback = (
            BidStrategy.LOWEST_COST_WITHOUT_CAP.value
            if BidStrategy.LOWEST_COST_WITHOUT_CAP.value in allowed
            else next(iter(sorted(allowed)), strategy)
        )
        notes.append(
            f"{out.get('name') or 'An ad set'} used the "
            f"{meta_label(strategy)} bid strategy, which doesn't apply here — "
            f"switched to {meta_label(fallback)}."
        )
        out["bid_strategy"] = fallback
        strategy = fallback

    if strategy not in BID_STRATEGIES_REQUIRING_AMOUNT:
        out.pop("bid_amount", None)
    if strategy != BID_STRATEGY_REQUIRING_ROAS_FLOOR:
        out.pop("bid_constraints", None)


def _reconcile_goal_only_fields(
    out: dict, obj_rules, goal_enum: OptimizationGoal | None
) -> None:
    """Drop the two ad-set fields Meta only accepts for certain objectives / goals.

    Both are copied verbatim from the template (``_ADSET_TEMPLATE_KEYS``), and
    both are rejected by ``CampaignSpec._check_goal_only_fields``: a frequency
    cap needs an Awareness/Engagement objective AND a Reach or ThruPlay goal, an
    attribution window needs a goal that reports a conversion.
    """
    if not obj_rules.allows_frequency_control:
        out.pop("frequency_control_specs", None)
    if goal_enum is None:
        return
    rules = goal_rules(goal_enum)
    if not rules.allows_frequency_control:
        out.pop("frequency_control_specs", None)
    if not rules.allows_attribution_spec:
        out.pop("attribution_spec", None)


def _reconcile_adset(
    adset: dict,
    objective: Any,
    notes: list[str],
    *,
    page_id: str | None = None,
    pixel_id: str | None = None,
) -> dict[str, Any]:
    """Drop template values the merged objective's matrix rejects.

    The overlay copies the template's objective AND its ad-set settings, but a
    template ad set is only legal under the objective it came from. Copying a Leads
    ad set onto a plan built for Awareness produced a tree the matrix refuses,
    which reached the user as an unfixable field error in the plan editor rather
    than as an editable plan. Falling back to the destination's own default keeps
    the plan openable; the note says what changed so nothing is lost silently.
    """
    obj = normalize_objective(objective)
    if obj is None:
        return adset
    rules = matrix_for(obj)
    out = dict(adset)

    try:
        dest = rules.for_destination(out.get("destination_type"))
    except KeyError:
        dest = rules.default_destination
        notes.append(
            f"{out.get('name') or 'An ad set'} used a conversion location "
            f"{rules.label} campaigns don't offer — switched to {dest.label}."
        )
        out["destination_type"] = dest.destination_type.value

    if not dest.allows_optimization_goal(str(out.get("optimization_goal") or "")):
        notes.append(
            f"{out.get('name') or 'An ad set'} optimized for something "
            f"{dest.label} doesn't support — switched to "
            f"{meta_label(dest.default_optimization_goal.value)}."
        )
        out["optimization_goal"] = dest.default_optimization_goal.value

    # Resolved before anything is validated against it: every check below is the
    # intersection of the destination's rules and the RECONCILED goal's, not the
    # goal the template came in with. The spec builder resolved this run's ids
    # before the overlay existed, so a goal the template introduced can arrive
    # with the wrong kind of promoted object, or none at all.
    goal_enum = next(
        (g for g in dest.optimization_goals if g.value == out.get("optimization_goal")),
        None,
    )
    goal_r = goal_rules(goal_enum) if goal_enum is not None else None

    # Billing was checked against the destination alone, so a template carrying
    # LINK_CLICKS billing survived onto a Conversions goal that only bills on
    # impressions — legal for the conversion location, rejected by CampaignSpec.
    allowed_billing = [
        e.value for e in dest.billing_events
        if goal_r is None or goal_r.allows_billing_event(e.value)
    ]
    if str(out.get("billing_event") or "") not in allowed_billing:
        out["billing_event"] = (allowed_billing or [dest.default_billing_event.value])[0]

    if goal_enum is not None:
        out["promoted_object"] = _reconcile_promoted_object(
            dest.promoted_object_kind(goal_enum),
            dict(out.get("promoted_object") or {}),
            page_id=page_id,
            pixel_id=pixel_id,
        )

    _reconcile_bidding(out, rules, goal_enum, notes)
    _reconcile_goal_only_fields(out, rules, goal_enum)

    if not dest.requires_lead_form:
        out.pop("lead_form_draft", None)

    # Same intersection for the ad format: ThruPlay narrows the destination's
    # {single, carousel} to single, and a carousel template kept its format.
    goal_formats = goal_r.ad_formats if goal_r else None
    allowed_formats = [
        f.value for f in dest.ad_formats if goal_formats is None or f in goal_formats
    ]

    ads = []
    for ad in out.get("ads") or []:
        creative = dict(ad.get("creative") or {})
        if not dest.allows_call_to_action(str(creative.get("call_to_action") or "")):
            creative["call_to_action"] = dest.default_call_to_action.value
        if str(creative.get("format") or "") not in allowed_formats:
            creative["format"] = (allowed_formats or [dest.default_ad_format.value])[0]
        if not dest.requires_lead_form:
            creative.pop("lead_gen_form_id", None)
        ads.append({**ad, "creative": creative})
    if ads:
        out["ads"] = ads
    return out


def _merge_creative(built: dict, tpl: dict) -> dict[str, Any]:
    """The template's copy and media over a built creative.

    ``link`` is kept from the built creative: it comes from *this* campaign's
    destination (website, store URL, wa.me number), and the old campaign's link
    could point somewhere that no longer applies.

    A boosted-post template replaces the composed fields outright — there is no
    copy on that kind of ad.
    """
    merged = dict(built)
    if tpl.get("object_story_id"):
        for composed in ("title", "body", "call_to_action", "media_id",
                         "image_hash", "video_id", "cards"):
            merged.pop(composed, None)
        merged["object_story_id"] = tpl["object_story_id"]
        return merged

    for key in ("title", "body", "call_to_action", "format", "url_tags",
                "image_hash", "video_id"):
        if tpl.get(key):
            merged[key] = tpl[key]
    # Reusing the old asset means dropping this run's (empty) upload reference,
    # or CreativeSpec sees two media references and rejects the pair.
    if tpl.get("image_hash") or tpl.get("video_id"):
        merged.pop("media_id", None)
    return merged


# ── publish-time campaign split ──────────────────────────────────────────────


def _adset_user_os(adset) -> str:
    """The single OS an ad set targets, or "" when it targets every device."""
    values = adset.targeting.get("user_os") or []
    return str(values[0]) if len(values) == 1 else ""


def split_for_publish(spec: CampaignSpec) -> list[tuple[CampaignSpec, list[int]]]:
    """Split one approved plan into the campaigns Meta actually needs.

    App promotion is the only objective that splits. Meta carries the promoted
    app and its attribution mode on the **campaign**, not the ad set, and an
    iOS 14.5+ install campaign is a dedicated SKAdNetwork campaign type that
    cannot carry Android ad sets. We used to emit one campaign holding an iOS ad
    set and an Android ad set — a shape Meta accepts at create time and then
    silently denies SKAdNetwork attribution, which is worse than a rejection
    because nothing surfaces it.

    The plan itself stays ONE ``CampaignSpec``: the editor, the draft row, the
    graph state and every downstream reader of ``meta_campaign_ids`` are built
    around a single campaign. Splitting here, at the last moment before publish,
    keeps all of that untouched.

    Returns ``[(campaign_spec, original_adset_indices), …]``. The indices are the
    positions those ad sets held in ``spec.adsets``, and the publish ledger keys
    its media/creative/adset/ad maps by them. Carrying them through is what lets
    the split stay invisible to the ledger: ad sets are *partitioned* across the
    campaigns, never duplicated, so every existing key stays unique and a ledger
    written before this existed still resumes.

    Anything that is not a multi-store app campaign returns a single entry, so
    every other objective takes exactly the path it took before.
    """
    everything = list(range(len(spec.adsets)))
    if spec.objective is not Objective.APP_PROMOTION:
        return [(spec, everything)]

    # Preserve APP_PLATFORMS order (iOS first) rather than ad set order, so the
    # primary campaign — the one whose id flows to campaign_manager — is stable.
    by_os: dict[str, list[int]] = {}
    for i, adset in enumerate(spec.adsets):
        by_os.setdefault(_adset_user_os(adset), []).append(i)
    ordered = [os_ for _key, os_, _label in APP_PLATFORMS if os_ in by_os]
    if len(ordered) < 2:
        # One store, or ad sets with no OS targeting at all. Nothing to split.
        return [(spec, everything)]

    labels = {os_: label for _key, os_, label in APP_PLATFORMS}
    base = spec.model_dump()
    # A campaign (CBO) budget belongs to one campaign, so it splits with them.
    # Ad-set budgets were already halved by _adset_budgets and need no change.
    budget_keys = [k for k in ("daily_budget", "lifetime_budget") if base.get(k)]

    out: list[tuple[CampaignSpec, list[int]]] = []
    for user_os in ordered:
        indices = by_os[user_os]
        first = spec.adsets[indices[0]]
        data = {
            **base,
            "name": f"{spec.name} — {labels[user_os]}"[:255],
            "adsets": [base["adsets"][i] for i in indices],
            # Lift the app off the ad set: same app, this store's listing.
            "promoted_object": (
                first.promoted_object.model_dump() if first.promoted_object else None
            ),
            # Apple's rules, so iOS only. Android keeps normal attribution.
            "is_skadnetwork_attribution": user_os == "iOS",
        }
        for key in budget_keys:
            data[key] = max(base[key] // len(ordered), MIN_BUDGET_CENTS)
        out.append((CampaignSpec.model_validate(data), indices))
    return out


__all__ = [
    "SpecBuildError",
    "apply_campaign_template",
    "build_campaign_spec",
    "build_campaign_tree",
    "split_for_publish",
]
