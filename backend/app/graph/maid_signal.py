"""
app/graph/maid_signal.py
────────────────────────
Signal-quality gate for raw MAID observations.

Every Unacast observation carries a ``forensicFlags`` int64 bitmask. Until this
module existed the value was stored and never read, so every ping counted as
equally authoritative evidence that a device was inside a POI's ring — including
pings whose own accuracy band is wider than the ring, and pings the vendor
flagged as a vehicle driving past.

Measured on 287,000 real staging pings (see
docs/maid_signal_quality_baseline.md):

  * 16.1% carry NO usable accuracy at all ("unavailable / >10 km")
  * 17.8% have an accuracy band worse than a 100 m ring
  * 14.6% are ``LIKELY_DRIVING`` — drove past, did not visit
  * ``SPOOF_LOCATION`` and ``LAT_GRID_LOCATION``: zero occurrences. The two
    scariest bits in the vendor's own preset contribute nothing on real data;
    the preset's value here is almost entirely ``LIKELY_DRIVING``.

The gate runs CLIENT-SIDE, on already-stored pings, not as an ``excludeFlags``
query parameter. That is deliberate: the flags arrive on every observation
anyway, so filtering here means the gate can be retuned — or a stored extraction
re-derived under a stricter rule — without re-buying a single vendor call.
Server-side ``excludeFlags`` stays available for one narrow purpose, relieving
the 100k-per-feature truncation ceiling on a POI dense enough to hit it.

Bit meanings: ``Unacast documentation/unacast-forensic-flags.pdf``, consolidated
in UNACAST-API-REFERENCE.md section 6.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Flag bits ────────────────────────────────────────────────────────────────

FLAG_BITS: dict[str, int] = {
    "LAT_GRID_LOCATION": 7,
    "TOO_MANY_DEVICES_AT_LOCATION": 8,
    "SPOOF_LOCATION": 9,
    "RADIO_DERIVED": 10,
    "EU": 12,
    "OVER_CAPACITY_DEVICE": 13,
    "LIKELY_DRIVING": 14,
    "HIGH_ACCURACY": 15,
    "MODERATE_ACCURACY": 16,
    "LOW_ACCURACY": 17,
    "MOBILE_NETWORK": 19,
    "HYPERV_OUTSIDE_CLUSTER": 20,
    "HYPERV_WITHIN_CLUSTER": 21,
    "HYPERV_CLUSTER_INTERLEAVE": 22,
    "TIMESHIFT": 23,
    "US": 25,
    "IMPLAUSIBLE_MOVEMENT": 27,
    "APPROXIMATED_SIGNAL": 28,
    "DENSE_CIRCULAR_AREAS": 31,
    "IP_DERIVED": 32,
    "LOW_RECURRING_BEHAVIOR": 33,
    "MODERATE_RECURRING_BEHAVIOR": 34,
    "DENSE_CROSSES": 35,
}


def mask_for(*names: str) -> int:
    """OR the named flags into a bitmask. Raises on an unknown name rather than
    silently building a mask that filters nothing."""
    return sum(1 << FLAG_BITS[n] for n in names)


# The vendor's documented place-visit preset (reference section 6): spoofed,
# ad-fraud, grid-snapped and drive-by signals. `LIKELY_DRIVING` is the one that
# actually fires on our data.
PLACE_VISIT_EXCLUDE_MASK = mask_for(
    "SPOOF_LOCATION", "OVER_CAPACITY_DEVICE", "LAT_GRID_LOCATION", "LIKELY_DRIVING"
)

# For a POI whose whole point IS drive-by traffic (a billboard, a roadside
# sign — "target everyone who drives past it daily"): the default preset
# throws away exactly the audience being asked for. Same preset minus
# LIKELY_DRIVING — still drops spoofed/fraud/grid-snapped signals, which are
# junk for a drive-by audience too, just not the driving itself.
DRIVE_BY_EXCLUDE_MASK = mask_for(
    "SPOOF_LOCATION", "OVER_CAPACITY_DEVICE", "LAT_GRID_LOCATION"
)


# ── Horizontal accuracy ──────────────────────────────────────────────────────
# Bits 15/16/17 combine into a band, keyed (LOW, MOD, HIGH) -> (lower_m,
# upper_m). `upper_m` None means unbounded. The (1,1,1) and (1,0,1) rows are
# pre-Aug-2024 historical combos the vendor documents as still present in older
# data — they are not reachable in current data but cost nothing to accept.
_ACCURACY: dict[tuple[int, int, int], tuple[float, float | None]] = {
    (0, 0, 0): (10000.0, None),      # unavailable, or worse than 10 km
    (1, 0, 0): (250.0, 10000.0),
    (1, 1, 0): (220.0, 250.0),
    (0, 1, 0): (50.0, 220.0),
    (0, 1, 1): (35.0, 50.0),
    (0, 0, 1): (0.0, 35.0),
    (1, 1, 1): (35.0, 50.0),         # legacy
    (1, 0, 1): (0.0, 35.0),          # legacy
}


def accuracy_bounds(flags: int | None) -> tuple[float, float | None]:
    """Decode bits 15/16/17 into ``(lower_m, upper_m)`` metres.

    A ping with no flags is treated as the WORST band. Assuming the best would
    repeat the mistake this module exists to fix: an unknown accuracy is not
    evidence of a precise fix.
    """
    if not flags:
        return (10000.0, None)
    high = (flags >> 15) & 1
    mod = (flags >> 16) & 1
    low = (flags >> 17) & 1
    return _ACCURACY[(low, mod, high)]


# ── The gate ─────────────────────────────────────────────────────────────────

# Accuracy modes, in the language of "can this ping place the device inside the
# ring at all":
#   "off"        — no accuracy test (pre-gate behaviour)
#   "permissive" — the band's LOWER bound is within the ring: the device COULD
#                  have been inside. Default. Costs ~15% of devices.
#   "positional" — the ping's distance from the ring centre PLUS the band's
#                  LOWER bound is within the ring: even the smallest error the
#                  vendor reports still lands the device inside. "permissive"
#                  ignores where in the ring a ping sits, so an edge ping with a
#                  50-220 m band counts like a precise fix at the door. Needs
#                  the ping's dist_m; falls back to "permissive" without it.
#                  Not yet measured, so not the default.
#   "strict"     — the band's UPPER bound is within the ring: the device MUST
#                  have been inside. Costs ~29% of devices — measured too
#                  aggressive for a default, kept for callers that need
#                  certainty over reach.
_ACCURACY_MODES = ("off", "permissive", "positional", "strict")


def accuracy_upper_m(flags: int | None) -> float | None:
    """The band's upper bound in metres, or None when unbounded/unknown.

    "How precise is this fix, at worst" — the number a visit-confidence rule
    needs. Unbounded (no accuracy bits at all) returns None rather than a large
    number, so a caller cannot accidentally treat "unknown" as "10 km" and then
    compare it.
    """
    _lower, upper = accuracy_bounds(flags)
    return upper


def ping_admitted(
    flags: int | None,
    radius_m: float,
    *,
    exclude_mask: int,
    accuracy_mode: str,
    dist_m: float | None = None,
) -> bool:
    """Whether one ping counts as presence evidence for a ring of ``radius_m``.

    ``dist_m`` is the ping's distance from the ring centre; only the
    "positional" mode reads it, and without it that mode is "permissive".
    """
    if exclude_mask and flags and (flags & exclude_mask):
        return False
    if accuracy_mode == "off":
        return True
    lower, upper = accuracy_bounds(flags)
    if accuracy_mode == "strict":
        return upper is not None and upper <= radius_m
    if accuracy_mode == "positional" and dist_m is not None:
        return dist_m + lower <= radius_m
    return lower <= radius_m


def gate_settings() -> tuple[int, str]:
    """Resolve ``(exclude_mask, accuracy_mode)`` from app settings.

    Read at call time rather than import time so a test (or a re-derivation
    under a different rule) can monkeypatch settings without reloading modules.
    """
    from app.core.config import settings

    mode = (getattr(settings, "MAID_ACCURACY_MODE", "permissive") or "permissive").lower()
    if mode not in _ACCURACY_MODES:
        logger.warning(
            "MAID_ACCURACY_MODE=%r is not one of %s — falling back to 'permissive'",
            mode, _ACCURACY_MODES,
        )
        mode = "permissive"

    raw = (getattr(settings, "MAID_EXCLUDE_FLAGS", "") or "").strip()
    if not raw:
        return (PLACE_VISIT_EXCLUDE_MASK, mode)
    if raw.lstrip("-").isdigit():
        return (int(raw), mode)
    names = [n.strip().upper() for n in raw.split(",") if n.strip()]
    try:
        return (mask_for(*names), mode)
    except KeyError as exc:
        logger.warning(
            "MAID_EXCLUDE_FLAGS names unknown flag %s — using the place-visit preset", exc
        )
        return (PLACE_VISIT_EXCLUDE_MASK, mode)


def apply_gate(
    rows: list[dict], radius_m: float, *, exclude_mask: int | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Drop pings that cannot serve as presence evidence for a ``radius_m`` ring.

    ``rows`` are the per-ping dicts ``read_cached``/``query_maids`` return. A
    ping with no ``forensic_flags`` at all carries no accuracy evidence, which is
    the worst band (see ``accuracy_bounds``), not a free pass — so it is judged
    like any other ping and, outside ``accuracy_mode="off"``, dropped.

    ``exclude_mask``, when given, overrides the configured mask for this call
    only — settings still supply the accuracy mode. For a drive-by audience
    (a billboard: "target everyone who drives past it daily") the configured
    preset throws away exactly the pings being asked for; the caller passes
    ``DRIVE_BY_EXCLUDE_MASK`` per POI instead of changing global settings for
    every other extraction. ``None`` (the default) keeps today's behaviour.

    Returns ``(kept_rows, stats)``. ``stats`` feeds the extraction funnel so a
    surprising audience size can be explained instead of guessed at.
    """
    _default_mask, mode = gate_settings()
    if exclude_mask is None:
        exclude_mask = _default_mask
    kept: list[dict] = []
    dropped_flags = 0
    dropped_accuracy = 0
    no_flags = 0

    for row in rows:
        raw_flags = row.get("forensic_flags")
        if raw_flags is None:
            no_flags += 1
        flags = int(raw_flags or 0)
        if exclude_mask and (flags & exclude_mask):
            dropped_flags += 1
            continue
        if not ping_admitted(
            flags, radius_m, exclude_mask=0, accuracy_mode=mode, dist_m=row.get("dist_m"),
        ):
            dropped_accuracy += 1
            continue
        kept.append(row)

    stats = {
        "pings_in": len(rows),
        "pings_kept": len(kept),
        "dropped_flags": dropped_flags,
        "dropped_accuracy": dropped_accuracy,
        "pings_without_flags": no_flags,
        "exclude_mask": exclude_mask,
    }
    if rows:
        logger.info(
            "MAID signal gate (radius=%.0fm mode=%s mask=%d): %d/%d pings kept "
            "(-%d flagged, -%d low-accuracy, %d unflagged passthrough)",
            radius_m, mode, exclude_mask, len(kept), len(rows),
            dropped_flags, dropped_accuracy, no_flags,
        )
    return kept, stats


def describe_gate() -> dict[str, Any]:
    """The active gate, for the extraction funnel and for logs."""
    exclude_mask, mode = gate_settings()
    return {
        "accuracy_mode": mode,
        "exclude_mask": exclude_mask,
        "excluded_flags": [n for n, b in FLAG_BITS.items() if exclude_mask & (1 << b)],
    }
