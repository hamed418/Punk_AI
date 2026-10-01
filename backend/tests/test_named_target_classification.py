"""brand-vs-venue classification counts distinct SITES, not Google listings.

Google lists one venue several times a few metres apart (station entrance +
tunnel, duplicate submissions). Counting rows made a single spot read as a
multi-outlet chain, which returned every exact-name listing and skipped the
"which one?" ask — dropping the real venue when its display name carries an
article ("The Pentagon" != "Pentagon").
"""

import pytest

from app.graph import tools


def _place(name, lat, lng, address="somewhere"):
    return {"name": name, "lat": lat, "lng": lng, "types": [],
            "address": address, "formatted_address": address,
            "postal_code": "", "country_code": "US"}


# The live Places result for "Pentagon in Arlington, Virginia", trimmed: the real
# building, the Metro station listed twice ~20 m apart, and an unrelated shop 5 km north.
PENTAGON = [
    _place("The Pentagon", 38.87186, -77.05627, "Washington, VA, USA"),
    _place("Pentagon", 38.86921, -77.05376, "Arlington, VA 22202, USA"),
    _place("Pentagon", 38.86945, -77.05375, "Arlington, VA, USA"),
    _place("Pentagon", 38.89718, -77.15509, "6313 27th St N, Arlington, VA 22207, USA"),
]

# A real chain: three exact-name outlets, kilometres apart.
CHAIN = [
    _place("Bagel Co", 38.87, -77.05),
    _place("Bagel Co", 38.90, -77.10),
    _place("Bagel Co", 38.84, -77.02),
]


@pytest.fixture
def places(monkeypatch):
    box = {}

    async def _fake(*_a, **_kw):
        return box["rows"]

    monkeypatch.setattr(tools, "_collect_places_in_area", _fake)
    return box


async def _resolve(name):
    return await tools.resolve_named_target(
        name, "Arlington, Virginia", latitude=38.8816208, longitude=-77.0909809,
        hint="specific",
    )


@pytest.mark.asyncio
async def test_duplicate_listings_are_not_a_chain(places):
    places["rows"] = PENTAGON
    res = await _resolve("Pentagon")
    # 3 exact-name rows but only 2 sites → below NAMED_CHAIN_MIN_OUTLETS.
    assert res["kind"] == "ambiguous"
    # The real building leads the ask instead of being discarded.
    assert res["candidates"][0]["name"] == "The Pentagon"


@pytest.mark.asyncio
async def test_outlets_far_apart_still_classify_as_brand(places):
    places["rows"] = CHAIN
    res = await _resolve("Bagel Co")
    assert res["kind"] == "brand"
    assert len(res["pois"]) == 3


@pytest.mark.asyncio
async def test_one_venue_listed_twice_resolves_single(places):
    places["rows"] = PENTAGON[1:3]          # the Metro station, twice
    res = await _resolve("Pentagon")
    assert res["kind"] == "single"
    assert res["pois"][0]["lat"] == pytest.approx(38.86921)
