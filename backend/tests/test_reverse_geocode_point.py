"""
tests/test_reverse_geocode_point.py
────────────────────────────────────
``reverse_geocode_point`` names a user-dropped/dragged pin (executors/geo.py's
manual-pin add and drag-demote paths). The label it returns becomes both the
pin's display name AND, via `_confirm_label`, every POI's `parent_location`
found near that pin — so a POI accidentally tagged "Joe's Diner" instead of
"Austin" would misname the whole discovery result, not just the pin.

Google's raw reverse-geocode response is ordered most-to-least specific
(nearest POI/address first, country last); these tests lock in that a
business/POI/street-level entry is never picked as the label, even when it
sits first in that order.
"""
from __future__ import annotations

import asyncio

from app.graph import tools


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Routes by URL so a test can give Google's reverse-geocode call and the
    Nominatim fallback call different (or absent) payloads."""

    def __init__(self, google_payload: dict, nominatim_payload: dict | None = None):
        self._google = google_payload
        self._nominatim = nominatim_payload if nominatim_payload is not None else {"address": {}}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, *args, **kwargs):
        return _FakeResponse(self._nominatim if "nominatim" in url else self._google)


def _patch_google(monkeypatch, payload: dict, nominatim_payload: dict | None = None):
    monkeypatch.setattr(tools.settings, "GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(
        tools.httpx, "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(payload, nominatim_payload),
    )


# A coordinate that sits on a business — Google's reverse geocode returns the
# POI as results[0], same shape a real "click near a coffee shop" produces.
_GEOMETRY = {"location": {"lat": 30.27, "lng": -97.74}}

_POI_FIRST_PAYLOAD = {
    "results": [
        {
            "types": ["cafe", "point_of_interest", "establishment"],
            "formatted_address": "Joe's Coffee, 100 Congress Ave, Austin, TX 78701, USA",
            "address_components": [{"long_name": "Joe's Coffee", "types": ["establishment"]}],
            "geometry": _GEOMETRY,
        },
        {
            "types": ["street_address"],
            "formatted_address": "100 Congress Ave, Austin, TX 78701, USA",
            "address_components": [{"long_name": "100", "types": ["street_number"]}],
            "geometry": _GEOMETRY,
        },
        {
            "types": ["neighborhood", "political"],
            "formatted_address": "Downtown, Austin, TX, USA",
            "address_components": [{"long_name": "Downtown", "types": ["neighborhood", "political"]}],
            "geometry": _GEOMETRY,
        },
        {
            "types": ["locality", "political"],
            "formatted_address": "Austin, TX, USA",
            "address_components": [{"long_name": "Austin", "types": ["locality", "political"]}],
            "geometry": _GEOMETRY,
        },
        {
            "types": ["administrative_area_level_1", "political"],
            "formatted_address": "Texas, USA",
            "address_components": [{"long_name": "Texas", "types": ["administrative_area_level_1", "political"]}],
            "geometry": _GEOMETRY,
        },
    ],
}


def test_reverse_geocode_skips_poi_and_address_for_neighborhood(monkeypatch):
    _patch_google(monkeypatch, _POI_FIRST_PAYLOAD)
    loc = asyncio.run(tools.reverse_geocode_point(30.27, -97.74))
    assert loc is not None
    assert loc["location_name"] == "Downtown"


def test_reverse_geocode_falls_back_to_locality_when_no_neighborhood(monkeypatch):
    payload = {"results": [r for r in _POI_FIRST_PAYLOAD["results"] if "neighborhood" not in r["types"]]}
    _patch_google(monkeypatch, payload)
    loc = asyncio.run(tools.reverse_geocode_point(30.27, -97.74))
    assert loc is not None
    assert loc["location_name"] == "Austin"


def test_reverse_geocode_never_returns_a_poi_or_street_address(monkeypatch):
    # Only POI/street-level results exist (e.g. a stubbed/odd response) — no
    # locality-or-broader survivor at all, and the Nominatim fallback also
    # comes up empty. Must not silently hand back the business/address as a
    # last resort; returns None (caller keeps its own generic label) rather
    # than mislabeling every POI found near this pin.
    payload = {"results": [r for r in _POI_FIRST_PAYLOAD["results"][:2]]}
    _patch_google(monkeypatch, payload, nominatim_payload={"address": {}})
    loc = asyncio.run(tools.reverse_geocode_point(30.27, -97.74))
    assert loc is None
