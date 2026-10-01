"""
graph/builder/plan_edits.py
───────────────────────────
Typed changes to the plan AFTER it exists: "make it $40 a day", "end it Dec 24",
"only Instagram". Before this, a campaign field named once the spec was built
only reopened the plan editor — the value the user typed was never written.

Pure over ``CampaignSpec.model_dump(mode="json")`` dicts. Every change is
validated against the real ``CampaignSpec`` (passed in), so a value Meta would
reject is REFUSED with the reason, never written. Money is the sharp edge, so
the rules are conservative: an amount in a different basis than the plan (a
per-day figure for a lifetime-budget plan) is refused, not converted on a guess,
and the result always states the actual amount that was set.

The user's edit lands in ``marketing_plan`` while ``plan_base`` stays what Punk
generated, so a later geo/audience regeneration sees it as a user edit and
carries it over (``meta_spec/merge.py``).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.graph.meta_spec.parsing import (
    BudgetParseError, DateParseError, minor_units, parse_budget_to_cents, parse_campaign_date,
)

PLAN_TYPED_FIELDS: tuple[str, ...] = (
    "budget", "campaign_start_date", "campaign_end_date", "publisher_platforms",
)


@dataclass
class PlanEditResult:
    spec: Optional[dict]          # the edited plan, or None when nothing changed
    results: list[dict]           # one {"field","status","detail"} per requested field


_PLATFORMS = {
    "facebook": "facebook", "fb": "facebook", "instagram": "instagram", "ig": "instagram",
    "insta": "instagram", "messenger": "messenger",
    "audience network": "audience_network", "audience_network": "audience_network",
}
_AUTOMATIC = ("advantage", "automatic", "all placements", "everywhere", "anywhere", "let meta")


def money_period(text: Any) -> Optional[str]:
    """The period the user named for an amount — day / week / month / total —
    or None. The AMOUNT itself is read by ``parse_budget_to_cents`` (currency-
    aware: a JPY account has no cents), never re-parsed here."""
    raw = str(text or "").lower()
    if re.search(r"(/|per |a |each |every )\s*day|daily", raw):
        return "day"
    if re.search(r"(/|per |a |each |every )\s*week|weekly", raw):
        return "week"
    if re.search(r"(/|per |a |each |every )\s*month|monthly", raw):
        return "month"
    if re.search(r"total|lifetime|overall|in all", raw):
        return "total"
    return None


def _money(minor: int, currency: str) -> str:
    return f"{minor / minor_units(currency):,.2f}{(' ' + currency) if currency else ''}"


def _parse_when(text: Any, tz) -> Optional[datetime]:
    """The shared campaign-date parser first (strict — raises on anything it
    doesn't know); a year-less "Dec 24" falls back to the fuzzy parser."""
    try:
        return parse_campaign_date(text)
    except DateParseError:
        pass
    try:
        from dateutil import parser as _dp

        base = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        parsed = _dp.parse(str(text), default=base, fuzzy=True)
    except (ValueError, OverflowError, TypeError, ImportError):
        return None
    parsed = parsed.replace(tzinfo=parsed.tzinfo or tz)
    # "Dec 24" typed in December for next year etc. is beyond what a default
    # can settle — if it landed in the past, the next occurrence is meant.
    if parsed < datetime.now(tz) - timedelta(days=1) and not re.search(r"\b(19|20)\d{2}\b", str(text)):
        try:
            parsed = parsed.replace(year=parsed.year + 1)
        except ValueError:
            return None
    return parsed


def _load(s: Any, fallback_tz=timezone.utc) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=fallback_tz)


def _budget(spec: dict, value: Any, currency: str) -> tuple[bool, str]:
    try:
        cents = parse_budget_to_cents(value, currency)
    except BudgetParseError:
        return False, f"I couldn't read {str(value)[:30]!r} as an amount"
    period = money_period(value)
    adsets = spec.get("adsets") or []
    at_campaign = spec.get("daily_budget") or spec.get("lifetime_budget")
    lifetime = bool(spec.get("lifetime_budget")) or (
        not at_campaign and any(a.get("lifetime_budget") for a in adsets)
    )
    if lifetime:
        if period not in (None, "total"):
            return False, (
                "this plan uses a total (lifetime) budget — give me the total amount "
                "for the whole run, not a per-day figure"
            )
        key, new_total = "lifetime_budget", cents
    else:
        if period == "total":
            return False, (
                "this plan uses a daily budget — give me an amount per day "
                "(or per week) and I'll set it"
            )
        key = "daily_budget"
        new_total = {"week": int(round(cents / 7)), "month": int(round(cents * 12 / 365))}.get(period, cents)

    if at_campaign:
        old = int(spec.get(key) or 0)
        if old == new_total:
            return True, f"the {key.split('_')[0]} budget was already {_money(new_total, currency)}"
        spec[key] = new_total
        return True, f"the {key.split('_')[0]} budget is now {_money(new_total, currency)} (was {_money(old, currency)})"

    current = [int(a.get(key) or 0) for a in adsets]
    total_now = sum(current)
    if not total_now:
        return False, "no ad set has a budget to scale"
    if total_now == new_total:
        return True, f"the {key.split('_')[0]} budget was already {_money(new_total, currency)} across {len(adsets)} ad set(s)"
    factor = new_total / total_now
    from app.graph.meta_spec.models import MIN_BUDGET_CENTS

    scaled = [int(round(b * factor)) if b else b for b in current]
    if any(b and b < MIN_BUDGET_CENTS for b in scaled):
        return False, (
            f"that's below Meta's minimum of {_money(MIN_BUDGET_CENTS, currency)} for an ad set "
            f"once it's split across {len(adsets)} ad sets"
        )
    for adset, b in zip(adsets, scaled):
        if b:
            adset[key] = b
    actual = sum(scaled)
    note = f"the {key.split('_')[0]} budget is now {_money(actual, currency)} across {len(adsets)} ad set(s) (was {_money(total_now, currency)})"
    if actual != new_total:
        note += f" — rounded from {_money(new_total, currency)}"
    return True, note


def _dates(spec: dict, field: str, value: Any) -> tuple[bool, str]:
    adsets = spec.get("adsets") or []
    first = _load((adsets[0] if adsets else {}).get("start_time"))
    tz = first.tzinfo if first else timezone.utc
    when = _parse_when(value, tz)
    if when is None:
        return False, f"I couldn't read {str(value)[:30]!r} as a date"
    key = "start_time" if field == "campaign_start_date" else "end_time"
    if key == "end_time":
        when = when.replace(hour=23, minute=59, second=0, microsecond=0)
    if key == "start_time" and when < datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0):
        return False, "that start date has already passed"
    changed = False
    for adset in adsets:
        start = _load(adset.get("start_time"), tz)
        end = _load(adset.get("end_time"), tz)
        if key == "end_time" and start and when <= start:
            return False, "the end date has to be after the start date"
        if key == "start_time" and end and end <= when:
            return False, "the start date has to be before the end date"
        if _load(adset.get(key), tz) != when:
            adset[key] = when.isoformat()
            changed = True
    label = "start" if key == "start_time" else "end"
    return True, (
        f"the campaign will {label} on {when:%b %d, %Y}" if changed
        else f"the campaign already {label}s on {when:%b %d, %Y}"
    )


def _platforms(spec: dict, value: Any) -> tuple[bool, str]:
    text = " ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value or "")
    low = text.lower()
    if any(w in low for w in _AUTOMATIC):
        chosen: list[str] = []
    else:
        chosen = []
        for token in sorted(_PLATFORMS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(token)}\b", low) and _PLATFORMS[token] not in chosen:
                chosen.append(_PLATFORMS[token])
        if not chosen:
            return False, f"I didn't recognise a placement in {text[:30]!r} (Facebook, Instagram, Messenger, Audience Network)"
    changed = False
    for adset in spec.get("adsets") or []:
        targeting = adset.setdefault("targeting", {})
        if chosen:
            if targeting.get("publisher_platforms") != chosen:
                targeting["publisher_platforms"] = list(chosen)
                changed = True
        elif "publisher_platforms" in targeting:
            targeting.pop("publisher_platforms")
            changed = True
    said = ", ".join(p.replace("_", " ").title() for p in chosen) or "Advantage+ (Meta chooses)"
    return True, f"ads will run on {said}" if changed else f"placements were already {said}"


def apply_plan_edits(
    plan: dict, ops: dict[str, Any], *, currency: str = "",
    validate: Optional[Callable[[dict], Any]] = None,
) -> PlanEditResult:
    """Apply ``{field: value}`` to a copy of ``plan``. Every field yields a
    result; the edited spec is returned only when at least one landed AND the
    whole thing validates — otherwise the plan is left exactly as it was."""
    work = copy.deepcopy(plan)
    results: list[dict] = []
    landed: list[str] = []
    for field, value in ops.items():
        try:
            if field == "budget":
                ok, detail = _budget(work, value, currency)
            elif field in ("campaign_start_date", "campaign_end_date"):
                ok, detail = _dates(work, field, value)
            elif field == "publisher_platforms":
                ok, detail = _platforms(work, value)
            else:
                ok, detail = False, f"{field} can't be changed on the built plan from chat yet"
        except Exception as exc:                          # noqa: BLE001 — never crash a turn
            ok, detail = False, f"couldn't apply that ({type(exc).__name__})"
        already = ok and "already" in detail
        results.append({"field": field, "status": ("no_op" if already else "applied") if ok else "refused",
                        "detail": detail})
        if ok and not already:
            landed.append(field)

    if not landed:
        return PlanEditResult(None, results)
    if validate is not None:
        try:
            validate(work)
        except Exception as exc:                          # noqa: BLE001
            reason = _first_error(exc)
            for r in results:
                if r["field"] in landed:
                    r["status"], r["detail"] = "refused", f"Meta wouldn't accept that: {reason}"
            return PlanEditResult(None, results)
    return PlanEditResult(work, results)


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            return f"{'.'.join(str(p) for p in first.get('loc', ()))}: {first.get('msg', exc)}"[:160]
        except Exception:                                 # noqa: BLE001
            pass
    return str(exc)[:160]


__all__ = ["PLAN_TYPED_FIELDS", "PlanEditResult", "apply_plan_edits", "money_period"]
