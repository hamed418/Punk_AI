"""
tests/test_poi_selection_corpus.py
───────────────────────────────────
Table-driven corpus for the POI selection spec pipeline
(``builder/executors/poi_selection.normalize_spec`` / ``apply_specs``).

Two tiers, per the module this tests:

  * always-run — (spec(s), superset) -> exact STATE DIFF (kept ids per
    category, protected_kept, deviations, unsupported). No LLM, no network.
    This is what pins "top 5 of each category over 3 categories = 15 kept,
    2 protected, deviation stated" as a regression guard.
  * ``@pytest.mark.llm`` — (utterance, step_key, context) -> the SPEC the
    live classifier emits. Opt-in (see pytest.ini's ``-m "not llm"``
    default); run when the classifier prompt changes, never in CI.

Assertions are always on the resulting STATE, never on any narrated prose —
that split (parse -&gt; state; state -&gt; prose) is the entire point of the
mechanism this module implements.
"""

from __future__ import annotations

import pytest

from app.graph.builder.executors.poi_selection import apply_specs, normalize_spec


def _poi(name: str, angle: str, ptype: str, market: str = "Montreal") -> dict:
    return {
        "name": name, "source_angle": angle, "parent_poi_type": ptype,
        "parent_label": market, "types": [ptype], "lat": 0.0, "lng": 0.0,
    }


def _superset() -> list[dict]:
    """3 categories (2 discovered, 1 named/brand), 18 POIs total — the exact
    shape of the reported bug: "top 5 of each category" over gym/restaurant/
    Starbucks should give 5 + 5 + 2 (the brand passes a count through)."""
    pois = [_poi(f"Gym {i}", "category", "gym") for i in range(8)]
    pois += [_poi(f"Restaurant {i}", "category", "restaurant") for i in range(8)]
    pois += [_poi(f"Starbucks {i}", "competitor_brand", "Starbucks") for i in range(2)]
    return pois


# ── normalize_spec: dict passthrough, string back-compat, unknown-key safety ──


@pytest.mark.parametrize("raw,expected", [
    ({"op": "keep", "n": 5, "scope": "each"},
     {"op": "keep", "n": 5, "scope": "each", "match": None, "unsupported": None, "ids": None}),
    ("top 5", {"op": "keep", "n": 5, "scope": "all", "match": None, "unsupported": None, "ids": None}),
    ("its too much places, i want the top 5 of each category",
     {"op": "keep", "n": 5, "scope": "each", "match": None, "unsupported": None, "ids": None}),
    ("only 5 per category",
     {"op": "keep", "n": 5, "scope": "each", "match": None, "unsupported": None, "ids": None}),
    ("drop everything in Laval",
     {"op": "drop", "n": None, "scope": "all", "match": "Laval", "unsupported": None, "ids": None}),
])
def test_normalize_spec_shapes(raw, expected):
    got = normalize_spec(raw)
    for k, v in expected.items():
        assert got[k] == v, f"{k}: {got[k]!r} != {v!r}"


def test_normalize_spec_drop_by_string_sets_op_drop():
    got = normalize_spec("drop everything in Laval")
    assert got["op"] == "drop"
    assert got["match"] == "Laval"


def test_normalize_spec_unknown_key_becomes_unsupported_not_dropped():
    got = normalize_spec({"op": "keep", "per_market": 5})
    assert got["n"] is None
    assert got["unsupported"] and "per_market" in got["unsupported"]


def test_normalize_spec_empty_string_is_unsupported():
    got = normalize_spec("")
    assert got["unsupported"]
    assert got["n"] is None and got["match"] is None


# ── apply_specs: the reported bug, exactly ────────────────────────────────────


def test_top_5_of_each_category_keeps_5_per_discovered_group_plus_named():
    report = apply_specs(_superset(), [normalize_spec({"op": "keep", "n": 5, "scope": "each"})])
    assert report.after_by_group == {
        "category:gym": 5, "category:restaurant": 5, "competitor_brand:Starbucks": 2,
    }
    assert len(report.kept) == 12
    assert report.protected_kept == {"competitor_brand:Starbucks": 2}
    assert report.applied  # something claims to have happened
    assert not report.unsupported


def test_bare_top_5_is_global_not_per_category():
    """The OLD behaviour ("top 5" with no scope) — global budget, round-robin
    across groups. Still correct after the rewrite."""
    report = apply_specs(_superset(), [normalize_spec({"op": "keep", "n": 5, "scope": "all"})])
    assert sum(v for k, v in report.after_by_group.items() if k != "competitor_brand:Starbucks") == 5
    assert report.after_by_group["competitor_brand:Starbucks"] == 2


def test_named_arm_bypass_is_reported_not_silent():
    report = apply_specs(_superset(), [normalize_spec({"op": "keep", "n": 5, "scope": "each"})])
    assert report.protected_kept.get("competitor_brand:Starbucks") == 2


# ── widening — impossible under the old append-only model ────────────────────


def test_actually_make_it_10_widens_back_out():
    superset = _superset()
    spec5 = normalize_spec({"op": "keep", "n": 5, "scope": "each"})
    spec10 = normalize_spec({"op": "keep", "n": 10, "scope": "each"})

    narrow = apply_specs(superset, [spec5])
    assert len(narrow.kept) == 12

    widened = apply_specs(superset, [spec5, spec10])
    assert len(widened.kept) == 18  # groups only had 8 each, so "10" == "all"
    assert widened.after_by_group == {
        "category:gym": 8, "category:restaurant": 8, "competitor_brand:Starbucks": 2,
    }


def test_a_persistent_drop_survives_a_later_widened_count():
    superset = _superset()
    specs = [
        normalize_spec({"op": "drop", "match": "gym"}),
        normalize_spec({"op": "keep", "n": 5, "scope": "each"}),
        normalize_spec({"op": "keep", "n": 10, "scope": "each"}),
    ]
    report = apply_specs(superset, specs)
    assert "category:gym" not in report.after_by_group  # the drop persists
    assert report.after_by_group == {"category:restaurant": 8, "competitor_brand:Starbucks": 2}


# ── match + count combos ──────────────────────────────────────────────────────


def test_only_3_gyms_sizes_the_named_subset():
    report = apply_specs(_superset(), [normalize_spec({"op": "keep", "n": 3, "match": "gym"})])
    assert report.after_by_group["category:gym"] == 3
    assert report.after_by_group["category:restaurant"] == 8  # untouched
    assert report.after_by_group["competitor_brand:Starbucks"] == 2  # untouched


def test_match_with_no_hits_is_a_deviation_not_a_wipe():
    report = apply_specs(_superset(), [normalize_spec({"op": "drop", "match": "does-not-exist-anywhere"})])
    assert len(report.kept) == 18
    assert any("does-not-exist-anywhere" in d for d in report.deviations)


def test_remove_the_tim_hortons_ones_style_predicate():
    report = apply_specs(_superset(), [normalize_spec("remove the Starbucks ones")])
    assert "competitor_brand:Starbucks" not in report.after_by_group
    assert len(report.kept) == 16


# ── unsupported clauses — the escape hatch, never silently approximated ──────


@pytest.mark.parametrize("spec_dict", [
    {"unsupported": "at least 2 in each category"},
    {"unsupported": "5 in each city"},
    {"unsupported": "cut it in half"},
])
def test_unsupported_clause_changes_nothing_and_is_reported(spec_dict):
    report = apply_specs(_superset(), [normalize_spec(spec_dict)])
    assert len(report.kept) == 18  # no-op on the pool
    assert report.unsupported == [spec_dict["unsupported"]]
    assert not report.applied


# ── ids (identity-pinned, how a map click becomes a spec) ────────────────────


def test_ids_drop_is_identity_pinned_and_survives_a_resize():
    superset = _superset()
    target = superset[0]  # "Gym 0"
    ident = [target["lat"], target["lng"], "gym 0"]
    specs = [
        {"op": "drop", "ids": [ident]},
        normalize_spec({"op": "keep", "n": 10, "scope": "each"}),
    ]
    report = apply_specs(superset, specs)
    assert not any(p["name"] == "Gym 0" for p in report.kept)
    assert report.after_by_group["category:gym"] == 7  # 8 - the one dropped by id


# ── empty / degenerate ────────────────────────────────────────────────────────


def test_no_specs_is_a_full_passthrough():
    report = apply_specs(_superset(), [])
    assert len(report.kept) == 18
    assert not report.applied and not report.deviations and not report.unsupported


def test_before_by_group_reflects_the_superset_not_the_result():
    report = apply_specs(_superset(), [normalize_spec({"op": "keep", "n": 5, "scope": "each"})])
    assert report.before_by_group == {
        "category:gym": 8, "category:restaurant": 8, "competitor_brand:Starbucks": 2,
    }
