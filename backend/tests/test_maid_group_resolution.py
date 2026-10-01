"""
tests/test_maid_group_resolution.py
────────────────────────────────────
`resolve_group_labels_verbose`'s fallback match used to be a bare substring
test, either direction — "bar" resolved to "category:barbershop" and "gym"
resolved to "category:gymnastics studio" whenever no EXACT "bar"/"gym" group
was in scope. Because it "resolved" to something, `missing` stayed empty and
the caller's own "group not found" narration never fired: the user got an
audience from the WRONG category with zero signal anything was off.

Fixed to whole-word containment. These pin the fix and the cases it must not
break.
"""
from __future__ import annotations

from app.services.maid_store import resolve_group_labels_verbose


def _poi(angle: str, poi_type: str, lat: float = 1.0, lng: float = 1.0) -> dict:
    return {"lat": lat, "lng": lng, "source_angle": angle, "parent_poi_type": poi_type}


def test_bar_does_not_match_barbershop():
    pois = [_poi("category", "barbershop")]
    resolved, missing = resolve_group_labels_verbose(["bar"], pois)
    assert resolved == []
    assert missing == ["bar"]


def test_gym_does_not_match_gymnastics_studio():
    pois = [_poi("category", "gymnastics studio")]
    resolved, missing = resolve_group_labels_verbose(["gym"], pois)
    assert resolved == []
    assert missing == ["gym"]


def test_coffee_still_matches_coffee_shop():
    """The fallback must still catch a genuine whole-word narrowing."""
    pois = [_poi("category", "coffee shop")]
    resolved, missing = resolve_group_labels_verbose(["coffee"], pois)
    assert resolved == ["category:coffee shop"]
    assert missing == []


def test_coffee_shop_matches_coffee_shop_chain():
    """Containment the OTHER direction: the label is the longer phrase."""
    pois = [_poi("category", "coffee shop chain")]
    resolved, missing = resolve_group_labels_verbose(["coffee shop"], pois)
    assert resolved == ["category:coffee shop chain"]
    assert missing == []


def test_a_label_matching_two_groups_returns_both():
    """No exact "gym" group exists, so both word-superset groups qualify —
    exact match (tested above) always wins outright and stops here."""
    pois = [_poi("category", "boutique gym"), _poi("category", "budget gym")]
    resolved, missing = resolve_group_labels_verbose(["gym"], pois)
    assert set(resolved) == {"category:boutique gym", "category:budget gym"}
    assert missing == []


def test_exact_match_wins_over_partial_when_both_exist():
    pois = [_poi("category", "bar"), _poi("category", "barbershop")]
    resolved, missing = resolve_group_labels_verbose(["bar"], pois)
    assert resolved == ["category:bar"]
    assert missing == []


def test_no_word_overlap_at_all_is_missing():
    pois = [_poi("category", "gym")]
    resolved, missing = resolve_group_labels_verbose(["nonexistent place"], pois)
    assert resolved == []
    assert missing == ["nonexistent place"]


# ── self-reference resolution ("my store" -> the store_set group) ──────────
#
# A store_set POI is stamped parent_poi_type="my stores" (executors/geo.py),
# so its group key tokenizes to {"my","stores"} — a real word-overlap with
# "my store"'s {"my","store"} IF stores/store stemmed the same, which
# _label_words does not do. Self-reference resolution is therefore its own
# path, keyed on `source_angle == "store_set"`, not the display key — these
# pin that it fires only for a genuine self-reference phrase, never for a
# third-party venue that happens to be named "Store"/"Shop".


def test_my_store_resolves_to_the_store_set_group():
    pois = [_poi("store_set", "my stores"), _poi("category", "pilates studio")]
    resolved, missing = resolve_group_labels_verbose(["my store"], pois)
    assert resolved == ["store_set:my stores"]
    assert missing == []


def test_self_reference_variants_resolve():
    pois = [_poi("store_set", "my stores")]
    for label in ("my shops", "our locations", "my business", "one of my stores", "my own store"):
        resolved, missing = resolve_group_labels_verbose([label], pois)
        assert resolved == ["store_set:my stores"], label
        assert missing == [], label


def test_a_third_party_store_name_is_not_swallowed():
    """A REAL venue named "Store"/"Shop" claims the label first — the
    self-reference fallback only fires when nothing else matched."""
    pois = [_poi("named_places", "The Corner Store")]
    resolved, missing = resolve_group_labels_verbose(["store"], pois)
    assert resolved == ["named_places:The Corner Store"]
    assert missing == []

    # "my store"/"Apple Store" share no group at all when there's no
    # store_set POI in the pool — the self-reference match requires an
    # ACTUAL store_set group to resolve to, so a bare "my store" with only
    # an unrelated named venue in scope stays missing, never guesses.
    resolved, missing = resolve_group_labels_verbose(["my store"], pois)
    assert resolved == []
    assert missing == ["my store"]


def test_self_reference_with_no_store_pois_is_reported_missing():
    pois = [_poi("category", "pilates studio")]
    resolved, missing = resolve_group_labels_verbose(["my store"], pois)
    assert resolved == []
    assert missing == ["my store"]
