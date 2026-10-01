"""
app/graph/maid_history.py
─────────────────────────
How many days of history an audience filter actually needs BOUGHT.

``run_maid_query`` used to size the vendor purchase from ``lookback_days``
alone. Several filter predicates read history *outside* that window, so buying
only the lookback does not make them strict — it makes them **unevaluable**, and
``_apply_clause`` cannot tell "no older visits exist" from "we never bought the
older window":

  * ``trend`` compares ``[now-W, now]`` against ``[now-2W, now-W)``. The default
    filter sets ``window_days = lookback_days`` (executors/maid.py), so the
    older window falls entirely outside the purchase and is empty by
    construction. ``trend: "started"`` therefore matched EVERY device with a
    recent visit, and ``trend: "lapsed"`` matched NOBODY, ever. Silently.
  * ``cadence_days`` needs enough span to observe repeated on-cadence gaps —
    at least ``cadence_days x (occurrences + 1)`` days.
  * ``window_days`` can simply exceed ``lookback_days``: the extractor treats
    the two as deliberately distinct (graph/prompts.py — one is "how far back to
    search", the other "a post-hoc narrowing"), so "in the last 45 days" over a
    7-day purchase filtered a 7-day audience and reported it as 45.

Four of the advertised landing-page prompts are in that set: the lapsed-gym
win-back, the "suddenly started going to a laundromat", the every-week chain
manager, and the every-payday casino.

This module answers the sizing question; ``AudienceFilterUnevaluable`` (raised
from maid_store) is the other half — a predicate whose history was never bought
must fail loudly rather than return everyone or nobody.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The DIRECT endpoint caps ONE request at 90 days, but `_contiguous_ranges`
# splits a longer span into several legal features, so this ceiling is about
# cost and relevance rather than legality: half a year is enough to judge a
# lapsed habit or a monthly cadence, and every extra day is paid for.
#
# Deliberately ABOVE UNACAST_RAW_RETENTION_DAYS (90). The nightly sweep deletes
# pings older than that together with their coverage rows, so days 91-180 bought
# for a trend or cadence are used by the extraction that bought them and then
# re-bought by any later one. Capping here at 90 instead would turn "lapsed over
# the last 60 days" (needs 120) from an answer into a refusal.
MAX_HISTORY_DAYS = 180

# `trend` compares two adjacent windows, so it needs twice its own window.
_TREND_MULTIPLIER = 2

# Default minimum on-cadence gaps before a recurrence is credited — mirrors
# `_apply_clause`'s own `max(1, (min_visits or 3) - 1)`.
_DEFAULT_CADENCE_OCCURRENCES = 2

# Must agree with maid_store._DEFAULT_TREND_WINDOW_DAYS. Duplicated rather than
# imported because maid_store imports from the graph package and the cycle is
# not worth one integer; test_maid_history pins that they match.
_DEFAULT_TREND_WINDOW_DAYS_FALLBACK = 30


def _clause_history_days(spec: dict, lookback_days: int) -> int:
    """History one flat clause needs, ignoring ``any_of``."""
    window = int(spec.get("window_days") or 0)
    need = max(int(lookback_days or 1), window)

    if spec.get("trend"):
        # Explicit asymmetric windows win when given: "suddenly started after
        # never going before" wants a SHORT recent window and a LONG prior one,
        # which a symmetric 2x cannot express.
        recent = int(spec.get("trend_recent_days") or window or 0)
        prior = int(spec.get("trend_prior_days") or 0)
        if recent and prior:
            need = max(need, recent + prior)
        else:
            need = max(need, (window or _DEFAULT_TREND_WINDOW_DAYS_FALLBACK) * _TREND_MULTIPLIER)

    cadence = int(spec.get("cadence_days") or 0)
    if cadence:
        occurrences = max(1, int(spec.get("min_visits") or 3) - 1)
        need = max(need, cadence * (occurrences + 1))

    return need


def required_history_days(lookback_days: int, spec: dict | None) -> int:
    """Days of history to actually BUY so ``spec`` can be evaluated.

    Returns at least ``lookback_days``, never more than ``MAX_HISTORY_DAYS``.
    For an ``any_of`` spec, the widest branch wins — every branch must be
    evaluable or the OR silently drops one.
    """
    base = max(1, int(lookback_days or 1))
    if not spec:
        return base

    if spec.get("any_of"):
        need = max(
            [base] + [_clause_history_days(c or {}, base) for c in spec["any_of"]]
        )
    else:
        need = _clause_history_days(spec, base)

    capped = min(need, MAX_HISTORY_DAYS)
    if capped > base:
        logger.info(
            "MAID history: filter needs %d day(s) of history for a %d-day lookback "
            "(capped at %d)", need, base, MAX_HISTORY_DAYS,
        )
    if need > MAX_HISTORY_DAYS:
        logger.warning(
            "MAID history: filter wanted %d days, clamped to %d — trend/cadence "
            "may still be under-evidenced", need, MAX_HISTORY_DAYS,
        )
    return capped


def history_shortfall(spec: dict | None, history_days_bought: int | None) -> int:
    """How many days short the purchased history is for ``spec``, or 0.

    ``history_days_bought`` is what the extraction actually paid for. ``None``
    means an event-based extraction, which buys the event dates themselves rather
    than a lookback, so there is no lookback shortfall to measure.
    """
    if not spec or history_days_bought is None:
        return 0
    needed = required_history_days(1, spec)
    return max(0, needed - int(history_days_bought))
