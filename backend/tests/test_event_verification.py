"""Event targeting verification: an event POI is only returned when it is in the
evidence it cites, dated inside the window, and located by Google inside the
target area. No network — grounding, Tavily, Places, geocoding and the LLM are stubbed.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.graph.tools as tools
from app.graph.tools import (
    _EventExtraction,
    _EventItem,
    _locate_event_venue,
    resolve_event_window,
    search_events,
    verify_event_claim,
)

WINDOW = (date(2024, 6, 1), date(2024, 9, 30))
MONTREAL = {"lat_min": 45.4, "lat_max": 45.7, "lng_min": -73.9, "lng_max": -73.4}
TEXT = (
    "Osheaga Music Festival took place at Parc Jean-Drapeau, 1 Circuit Gilles "
    "Villeneuve, Montreal from July 26 to July 28, 2024."
)


def _ev(**kw) -> _EventItem:
    base = dict(
        event_name="Osheaga Music Festival", venue_name="Parc Jean-Drapeau",
        address="1 Circuit Gilles Villeneuve, Montreal",
        start_date="2024-07-26", end_date="2024-07-28",
        evidence_index=0, evidence_quote="Osheaga Music Festival took place at Parc Jean-Drapeau",
    )
    base.update(kw)
    return _EventItem(**base)


# ── verify_event_claim ────────────────────────────────────────────────────────

def test_supported_event_passes_with_dates():
    dates, reason = verify_event_claim(_ev(), [TEXT], WINDOW, 31)
    assert reason == "" and dates == (date(2024, 7, 26), date(2024, 7, 28))


def test_event_not_in_its_cited_source_is_rejected():
    _, reason = verify_event_claim(_ev(evidence_quote="Lollapalooza headlined by nobody"), [TEXT], WINDOW, 31)
    assert reason == "not_in_evidence"
    _, reason = verify_event_claim(_ev(event_name="Tomorrowland Belgium Mega Fest"), [TEXT], WINDOW, 31)
    assert reason == "not_in_evidence"


def test_bad_evidence_index_is_rejected():
    assert verify_event_claim(_ev(evidence_index=5), [TEXT], WINDOW, 31)[1] == "no_evidence"
    assert verify_event_claim(_ev(evidence_quote=""), [TEXT], WINDOW, 31)[1] == "no_evidence"


@pytest.mark.parametrize("kw, reason", [
    (dict(start_date=None), "no_date"),
    (dict(start_date="TBD"), "no_date"),
    (dict(end_date="2024-07-01"), "bad_dates"),
    (dict(end_date="2024-09-30"), "span_too_long"),
    (dict(start_date="2024-07-01", end_date="2024-07-01"), "date_unsupported"),  # day/month not in source
    (dict(start_date="2027-07-26", end_date="2027-07-28"), "outside_window"),    # future
    (dict(start_date="2023-07-26", end_date="2023-07-28"), "outside_window"),    # stale
])
def test_date_failures(kw, reason):
    assert verify_event_claim(_ev(**kw), [TEXT], WINDOW, 31)[1] == reason


def test_event_straddling_the_window_is_clipped():
    dates, _ = verify_event_claim(_ev(start_date="2024-05-30", end_date="2024-06-02"),
                                  ["May 30 to June 2 2024 Osheaga Music Festival took place at Parc Jean-Drapeau"],
                                  WINDOW, 31)
    assert dates == (date(2024, 6, 1), date(2024, 6, 2))


# ── window resolution ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_iso_range_parses_without_llm_and_clamps_to_yesterday():
    today = date(2026, 9, 29)
    lo, hi = await resolve_event_window("2026-09-01 to 2026-12-31", today)
    assert (lo, hi) == (date(2026, 9, 1), date(2026, 9, 28))


@pytest.mark.asyncio
async def test_empty_range_is_the_past_year_and_future_only_is_empty():
    today = date(2026, 9, 29)
    lo, hi = await resolve_event_window("", today)
    assert hi == date(2026, 9, 28) and (hi - lo).days == 365
    lo, hi = await resolve_event_window("2027-01-01 to 2027-02-01", today)
    assert lo > hi


@pytest.mark.asyncio
async def test_stated_recency_becomes_the_event_window_not_the_default_year():
    from app.graph.tools import event_range_from_days

    today = date(2026, 9, 29)
    rng = event_range_from_days(180, today)          # "last 6 months"
    assert rng == "2026-04-02 to 2026-09-28"
    lo, hi = await resolve_event_window(rng, today)   # ISO → no LLM
    assert (hi - lo).days == 179 and hi == date(2026, 9, 28)
    assert event_range_from_days("30", today).startswith("2026-08-30")
    assert event_range_from_days(None, today) == "" and event_range_from_days(0, today) == ""
    assert event_range_from_days("soon", today) == ""


# ── venue location: Google only, inside the area ──────────────────────────────

def _place(lat, lng):
    return [{"lat": lat, "lng": lng, "postal_code": "H3C", "country_code": "CA"}]


def _geo(lat, lng):
    return {"latitude": lat, "longitude": lng, "postal_code": "H3C", "country_code": "CA"}


async def _locate(place, geo, **kw):
    with patch.object(tools, "_google_places_text_search", new=AsyncMock(return_value=place)), \
         patch.object(tools, "_geocode_core", new=AsyncMock(return_value=geo)) as g:
        out = await _locate_event_venue(
            _ev(), "Montreal", latitude=45.5, longitude=-73.55,
            bounds=kw.get("bounds", MONTREAL), region_polygon=kw.get("polygon"),
        )
    return out, g


@pytest.mark.asyncio
async def test_venue_inside_area_is_located_and_geocode_never_uses_osm():
    (point, reason), g = await _locate(_place(45.51, -73.53), _geo(45.5105, -73.5305))
    assert reason == "" and point["postal_code"] == "H3C"
    assert g.call_args.kwargs["osm_fallback"] is False


@pytest.mark.asyncio
async def test_venue_outside_area_is_rejected():
    (point, reason), _ = await _locate(_place(46.8, -71.2), _geo(46.8, -71.2))  # Quebec City
    assert point is None and reason == "outside_area"


@pytest.mark.asyncio
async def test_places_and_geocode_disagreeing_is_ambiguous():
    (point, reason), _ = await _locate(_place(45.50, -73.55), _geo(45.60, -73.55))  # ~11 km apart
    assert point is None and reason == "venue_ambiguous"


@pytest.mark.asyncio
async def test_unresolvable_venue_is_dropped_not_guessed():
    (point, reason), _ = await _locate([], {"latitude": None, "error": "geocoding_failed"})
    assert point is None and reason == "not_geocoded"


@pytest.mark.asyncio
async def test_polygon_wins_over_bbox():
    tiny = [[(-73.60, 45.45), (-73.59, 45.45), (-73.59, 45.46), (-73.60, 45.46), (-73.60, 45.45)]]
    (point, reason), _ = await _locate(_place(45.51, -73.53), _geo(45.51, -73.53), polygon=tiny)
    assert point is None and reason == "outside_area"


@pytest.mark.asyncio
async def test_geocode_core_without_osm_fallback_never_calls_nominatim():
    with patch.object(tools.settings, "GOOGLE_MAPS_API_KEY", ""), \
         patch.object(tools, "_nominatim_geocode", new=AsyncMock()) as osm:
        out = await tools._geocode_core("1 Main St", osm_fallback=False)
    osm.assert_not_called()
    assert out["error"] == "geocoding_failed"


# ── search_events end to end (all I/O stubbed) ────────────────────────────────

class _StubLLM:
    def __init__(self, *a, **k): ...
    def with_structured_output(self, *a, **k): return self


async def _run_search(extraction, *, place, geo):
    with patch.object(tools.settings, "GROUNDING_ENABLED", True), \
         patch.object(tools.settings, "TAVILY_API_KEY", ""), \
         patch.object(tools, "_gemini_grounded_text", new=AsyncMock(return_value=(TEXT, ["https://osheaga.com"]))), \
         patch.object(tools, "ChatGoogleGenerativeAI", _StubLLM), \
         patch.object(tools, "tracked_ainvoke", new=AsyncMock(return_value=(extraction, {}))), \
         patch.object(tools, "_google_places_text_search", new=AsyncMock(return_value=place)), \
         patch.object(tools, "_geocode_core", new=AsyncMock(return_value=geo)):
        return await search_events.ainvoke({
            "city": "Montreal", "event_query": "Osheaga", "date_range": "Summer 2024",
            "window_start": "2024-06-01", "window_end": "2024-09-30",
            "bounds": MONTREAL, "latitude": 45.5, "longitude": -73.55,
        })


@pytest.mark.asyncio
async def test_search_events_returns_only_verified_events():
    good = _ev()
    invented = _ev(event_name="Ghost Fest Quebec Edition", evidence_quote="Ghost Fest Quebec Edition happened")
    undated = _ev(event_name="Osheaga Music Festival", start_date=None)
    res = await _run_search(
        _EventExtraction(events=[good, invented, undated]),
        place=_place(45.51, -73.53), geo=_geo(45.51, -73.53),
    )
    pois = res["targetable_poi_coordinates"]
    assert len(pois) == 1 and res["total_events_found"] == 1
    assert pois[0]["event_start_date"] == "2024-07-26" and pois[0]["event_end_date"] == "2024-07-28"
    assert pois[0]["types"] == ["event_venue"]
    assert {r["reason"] for r in res["rejected"]} == {"not_in_evidence", "no_date"}


@pytest.mark.asyncio
async def test_search_events_future_only_window_searches_nothing():
    with patch.object(tools, "_gemini_grounded_text", new=AsyncMock()) as g:
        res = await search_events.ainvoke({
            "city": "Montreal", "event_query": "x",
            "window_start": "2999-01-01", "window_end": "2999-02-01",
        })
    g.assert_not_called()
    assert res["targetable_poi_coordinates"] == [] and res["rejected"][0]["reason"] == "outside_window"


# ── grounding: today's date + support ratio ───────────────────────────────────

@pytest.mark.asyncio
async def test_grounded_text_sends_today_and_reports_support_ratio():
    from app.graph import grounding

    text = "abcdefghij"     # 10 bytes; supports cover [0,4) and [6,8) → 6/10
    resp = SimpleNamespace(
        text=text, usage_metadata=None,
        candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(
            grounding_chunks=[SimpleNamespace(web=SimpleNamespace(uri="https://a.example"))],
            grounding_supports=[
                SimpleNamespace(segment=SimpleNamespace(start_index=0, end_index=4)),
                SimpleNamespace(segment=SimpleNamespace(start_index=6, end_index=8)),
            ],
        ))],
    )
    gen = AsyncMock(return_value=resp)
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=gen)))
    with patch.object(grounding, "_grounding_client", return_value=client), \
         patch.object(grounding.settings, "GROUNDING_ENABLED", True):
        out = await grounding.grounded_text("q", with_metadata=True)
    assert out == (text, ["https://a.example"], pytest.approx(0.6))
    cfg = gen.call_args.kwargs["config"]
    assert date.today().isoformat() in cfg.system_instruction
