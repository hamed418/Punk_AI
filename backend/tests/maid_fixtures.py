"""
tests/maid_fixtures.py
──────────────────────
A synthetic but realistically SHAPED audience, for tests only.

This used to be ``executors/_maid_demo_fallback.py`` and ran in the product
whenever a real query came back empty. The audience path is Unacast-only now and
never invents an audience, so the generator lives here, where its only job is to
give audience-filter tests rows with real signal to select on.

Rows have the exact shape the pipeline produces — ``{lat, lng, maid, count,
poi_key, visits, days}`` with visits carrying ``ts``, ``dwell_min``,
``dwell_lower_s``, ``n_pings`` and ``gap_s`` — so filter code tested against this
behaves as it does against a real extraction.

Each device is drawn from a behavioral ARCHETYPE (commuter, owner, weekender,
lapsed, ...) that governs WHEN it visits, in the POIs' real local time zone, so
day-of-week, hour, dwell, trend and cadence predicates all have something to
match.
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import datetime, timedelta, timezone

_PER_DAY_MIN = 80
_PER_DAY_MAX = 250
_BASELINE_RADIUS_KM = 0.5
_MIN_RADIUS_MULT = 0.3
_MAX_RADIUS_MULT = 10.0
_MAX_DEVICES_PER_POI = 4000

_HOTSPOT_MIN = 2
_HOTSPOT_MAX = 7
_HOTSPOT_SIGMA_FRAC_MIN = 0.05
_HOTSPOT_SIGMA_FRAC_MAX = 0.18
_BACKGROUND_FRAC = 0.12
_SAME_SPOT_PROB = 0.5
_GAP_S = 20 * 60

_ARCHETYPE_WEIGHTS: dict[str, float] = {
    "commuter": 0.10,      # weekday mornings, short dwell
    "owner": 0.05,         # weekday all-day, long dwell — staff, not customer
    "regular": 0.15,       # 2-4x/week, mixed hours
    "weekender": 0.10,     # Fri/Sat night, long dwell
    "weekday_only": 0.08,  # Tue-Thu daytime only
    "lapsed": 0.07,        # dense until ~60d ago, nothing since
    "new": 0.07,           # nothing until ~14d ago, dense since
    "payday": 0.03,        # ~biweekly on a schedule
    "monthly": 0.05,       # ~monthly on a schedule
    "oneoff": 0.30,        # a single visit
}


def _zone(pois: list[dict] | None):
    """The POIs' real IANA zone — the same lookup the filter evaluates with."""
    from app.services.maid_store import _zone_for

    return _zone_for(pois) or timezone.utc


def _uniform_disk_km(r_km: float) -> tuple[float, float]:
    theta = random.uniform(0.0, 2.0 * math.pi)
    dist = r_km * math.sqrt(random.random())
    return dist * math.cos(theta), dist * math.sin(theta)


def _build_hotspots(r_km: float) -> tuple[list[tuple[float, float, float]], list[float]]:
    n = random.randint(_HOTSPOT_MIN, _HOTSPOT_MAX)
    n = min(_HOTSPOT_MAX, n + int(r_km / _BASELINE_RADIUS_KM) // 3)
    hotspots: list[tuple[float, float, float]] = []
    weights: list[float] = []
    for _ in range(n):
        ex, ny = _uniform_disk_km(r_km * 0.8)
        sigma = r_km * random.uniform(_HOTSPOT_SIGMA_FRAC_MIN, _HOTSPOT_SIGMA_FRAC_MAX)
        hotspots.append((ex, ny, sigma))
        weights.append(random.random() ** 2 + 0.05)
    total = sum(weights)
    cum: list[float] = []
    acc = 0.0
    for w in weights:
        acc += w / total
        cum.append(acc)
    return hotspots, cum


def _pick_hotspot(hotspots, cum):
    r = random.random()
    for i, c in enumerate(cum):
        if r <= c:
            return hotspots[i]
    return hotspots[-1]


def _pick_archetype() -> str:
    r = random.random()
    total = sum(_ARCHETYPE_WEIGHTS.values())
    acc = 0.0
    for name, w in _ARCHETYPE_WEIGHTS.items():
        acc += w / total
        if r <= acc:
            return name
    return "oneoff"


def _days_with_weekday(window_days: int, weekdays: tuple[int, ...], freq: float, zone, *,
                       since_days_ago: int = 0, until_days_ago: int | None = None) -> list[int]:
    hi = window_days if until_days_ago is None else min(window_days, until_days_ago)
    now = datetime.now(zone)
    return [
        d for d in range(since_days_ago, hi)
        if (now - timedelta(days=d)).weekday() in weekdays and random.random() < freq
    ]


def _at(days_ago: int, hour: int, zone, minute: int | None = None) -> datetime:
    """The UTC instant that is ``hour`` LOCAL time, ``days_ago`` days back."""
    minute = random.randint(0, 59) if minute is None else minute
    local = datetime.now(zone) - timedelta(days=days_ago)
    local = local.replace(hour=hour % 24, minute=minute, second=random.randint(0, 59), microsecond=0)
    return local.astimezone(timezone.utc)


def _gen_visits(archetype: str, window_days: int, zone) -> list[tuple[datetime, int]]:
    """(timestamp, dwell_minutes) pairs for one device over the window."""
    visits: list[tuple[datetime, int]] = []

    if archetype == "commuter":
        for d in _days_with_weekday(window_days, (0, 1, 2, 3, 4), 0.7, zone):
            visits.append((_at(d, random.choice([7, 8]), zone), random.randint(5, 15)))
    elif archetype == "owner":
        for d in _days_with_weekday(window_days, (0, 1, 2, 3, 4), 0.9, zone):
            visits.append((_at(d, 9, zone), random.randint(300, 540)))
    elif archetype == "regular":
        for d in range(window_days):
            if random.random() < 0.35:
                visits.append((_at(d, random.randint(6, 22), zone), random.randint(20, 60)))
    elif archetype == "weekender":
        for d in _days_with_weekday(window_days, (4, 5), 0.8, zone):
            visits.append((_at(d, random.randint(20, 23), zone), random.randint(120, 240)))
    elif archetype == "weekday_only":
        for d in _days_with_weekday(window_days, (1, 2, 3), 0.6, zone):
            visits.append((_at(d, random.randint(10, 18), zone), random.randint(15, 45)))
    elif archetype == "lapsed":
        for d in _days_with_weekday(window_days, tuple(range(7)), 0.4, zone, since_days_ago=60):
            visits.append((_at(d, random.randint(6, 22), zone), random.randint(20, 60)))
    elif archetype == "new":
        for d in _days_with_weekday(window_days, tuple(range(7)), 0.6, zone, until_days_ago=14):
            visits.append((_at(d, random.randint(6, 22), zone), random.randint(15, 45)))
    elif archetype == "payday":
        d = random.randint(0, 6)
        while d < window_days:
            visits.append((_at(d, random.randint(11, 20), zone), random.randint(15, 60)))
            d += 14 + random.randint(-1, 1)
    elif archetype == "monthly":
        d = random.randint(0, 10)
        while d < window_days:
            visits.append((_at(d, random.randint(9, 21), zone), random.randint(15, 90)))
            d += 30 + random.randint(-3, 3)
    elif archetype == "oneoff":
        d = random.randint(0, max(0, window_days - 1))
        visits.append((_at(d, random.randint(6, 22), zone), random.randint(5, 30)))

    if not visits:
        d = random.randint(0, max(0, window_days - 1))
        visits.append((_at(d, random.randint(6, 22), zone), random.randint(5, 30)))
    return visits


def synth_audience(
    *, lookback_days: int, pois: list[dict]
) -> tuple[list[str], list[dict]]:
    """Return ``(maids, observation_rows)`` scaled per POI by window x radius.

    Every row carries the ``poi_key`` of the POI it was generated at — what
    ``attribute_audience`` matches on — so pass the same POI dicts (with the
    same ``radius_km``) to the code under test.
    """
    from app.graph.unacast_query import poi_key

    days = max(1, int(lookback_days or 7))
    maids: list[str] = []
    obs: list[dict] = []
    if not pois:
        return maids, obs

    zone = _zone(pois)

    def _point_gen(lat0: float, lng0: float, r_km: float):
        cos_lat = max(0.1, math.cos(math.radians(lat0)))
        hotspots, cum = _build_hotspots(r_km)

        def _gen() -> tuple[float, float]:
            if random.random() < _BACKGROUND_FRAC:
                ex, ny = _uniform_disk_km(r_km * 0.995)
            else:
                hx, hy, sigma = _pick_hotspot(hotspots, cum)
                ex = hx + random.gauss(0.0, sigma)
                ny = hy + random.gauss(0.0, sigma)
                d = math.hypot(ex, ny)
                if d > r_km:
                    scale = (r_km * 0.995) / d
                    ex *= scale
                    ny *= scale
            return (lat0 + ny / 111.0, lng0 + ex / (111.0 * cos_lat))
        return _gen

    def _emit_device(mid: str, archetype: str, venues: list[tuple]) -> None:
        """One device's visits across its venues (usually one). A repeat visit
        often lands back on the same dot at the same venue."""
        per_dot: dict[tuple, list[tuple[datetime, int]]] = {}
        venue_idx = 0
        gen, key = venues[venue_idx]
        anchor = gen()
        for i, (ts, dwell) in enumerate(_gen_visits(archetype, days, zone)):
            if len(venues) > 1 and i > 0 and random.random() < 0.5:
                venue_idx = (venue_idx + 1) % len(venues)
                gen, key = venues[venue_idx]
            pt = anchor if (i and random.random() < _SAME_SPOT_PROB) else gen()
            per_dot.setdefault((key, pt), []).append((ts, dwell))
            anchor = pt

        for (key, (la, ln)), vlist in per_dot.items():
            vlist.sort(key=lambda v: v[0])
            obs.append({
                "lat": la,
                "lng": ln,
                "maid": mid,
                "count": len(vlist),
                "poi_key": key,
                "visits": [
                    {"ts": ts.isoformat(), "dwell_min": dwell, "dwell_lower_s": dwell * 60,
                     "n_pings": 2, "gap_s": _GAP_S}
                    for ts, dwell in vlist
                ],
                "days": sorted({ts.date().isoformat() for ts, _ in vlist}),
            })

    venues: list[tuple] = []
    device_counts: list[int] = []
    for p in pois:
        lat0, lng0 = p.get("lat"), p.get("lng")
        if lat0 is None or lng0 is None:
            continue
        r_km = float(p.get("radius_km") or _BASELINE_RADIUS_KM)
        radius_mult = max(_MIN_RADIUS_MULT, min(_MAX_RADIUS_MULT, r_km / _BASELINE_RADIUS_KM))
        n_devices = max(5, int(random.randint(_PER_DAY_MIN, _PER_DAY_MAX) * radius_mult * (days / 30.0)))
        n_devices = min(n_devices, _MAX_DEVICES_PER_POI)
        venue = (_point_gen(lat0, lng0, r_km), poi_key(p))
        venues.append(venue)
        device_counts.append(n_devices)
        for _ in range(n_devices):
            mid = uuid.uuid4().hex
            maids.append(mid)
            _emit_device(mid, _pick_archetype(), [venue])

    # Cross-venue devices, so intersection and min_distinct_pois predicates have
    # something to select — without them every device is single-venue.
    if len(venues) >= 2:
        for _ in range(max(3, int(sum(device_counts) * 0.05))):
            k = min(len(venues), random.choice([2, 2, 2, 3]))
            mid = uuid.uuid4().hex
            maids.append(mid)
            archetype = _pick_archetype()
            if archetype in ("oneoff", "new"):
                archetype = "regular"
            _emit_device(mid, archetype, random.sample(venues, k))

    return maids, obs
