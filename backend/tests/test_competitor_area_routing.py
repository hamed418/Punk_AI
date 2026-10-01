"""The two competitor angles must ask for different things.

``competitor_nearby`` rings the advertiser's own address; ``competitor_area``
sweeps the whole targeting area for advertisers who have no address to ring
(SaaS, e-commerce, service-area). The split is carried entirely by the slot
gating tables, so that is what is pinned here.
"""

from app.graph.builder.builder_node import _det_det_type
from app.graph.builder.executors.geo import DET_ANGLE_LABELS, _MARKET_ANGLES
from app.graph.builder.slots import missing_required_slots
from app.graph.prompts_registry import GEO_DETERMINISTIC_OPTIONS

_ANCHOR_SLOTS = {"competitor_anchor", "competitor_anchor_confirm", "competitor_radius_km"}


def _geo_slots(det_type: str) -> set[str]:
    return {s.name for s in missing_required_slots("geo", {"det_type": det_type})}


def test_anchored_competitor_asks_for_an_address_and_a_radius():
    names = _geo_slots("competitor_nearby")
    assert {"competitor_anchor", "competitor_radius_km"} <= names
    assert not names & {"locations", "location_scope"}


def test_area_competitor_asks_where_to_target_and_never_for_an_address():
    names = _geo_slots("competitor_area")
    assert {"location_scope", "locations"} <= names
    assert not names & _ANCHOR_SLOTS


def test_store_pair_is_unaffected_by_the_new_angle():
    names = _geo_slots("store_set,competitor_nearby")
    assert "store_addresses" in names
    assert "competitor_radius_km" in names
    # The shared store address anchors both arms — no second anchor ask.
    assert not names & {"competitor_anchor", "competitor_anchor_confirm"}


def test_both_menu_options_resolve_to_their_own_angle():
    anchored, area = (
        o for o in GEO_DETERMINISTIC_OPTIONS if "my competitors" in o
    )
    assert _det_det_type(anchored) == "competitor_nearby"
    assert _det_det_type(area) == "competitor_area"


def test_retired_menu_label_still_resolves():
    # Old checkpoints replay the pre-split label.
    assert _det_det_type("Target people hanging out near my competitors") == "competitor_nearby"


def test_area_angle_is_a_market_angle():
    # Drives the map centroid and the bare-name disambiguation guard: an area run
    # has no anchor to centre on.
    assert "competitor_area" in _MARKET_ANGLES
    assert "competitor_nearby" not in _MARKET_ANGLES
    assert DET_ANGLE_LABELS["competitor_area"] != DET_ANGLE_LABELS["competitor_nearby"]


def test_no_user_facing_label_says_shop_or_store():
    surfaces = list(GEO_DETERMINISTIC_OPTIONS) + list(DET_ANGLE_LABELS.values())
    assert not [t for t in surfaces if "shop" in t.lower() or "store" in t.lower()]
