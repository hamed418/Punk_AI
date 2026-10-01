"""
Unit test for narrator/grounding.py's _build_maid — the composer's reference
count must reflect an active audience_filter, not the raw pre-filter
maid_count. Round 2 of thread 0b3b050c-7873-42f1-8732-79273520fc38's fix:
without this, a filter applied on one turn ("at least twice") reads back as
forgotten on any later turn whose own beat doesn't carry the count.
"""
from app.graph.narrator.grounding import _build_geo, _build_maid, build_pack


def test_filtered_count_wins_over_raw_when_filter_active():
    geo_data = {
        "maid_count": 6732,
        "filtered_maid_count": 4020,
        "audience_filter": {"min_visits": 2},
    }
    out = _build_maid(geo_data, {})
    assert out["count"] == 4020
    assert out["count_before_filter"] == 6732
    assert out["active_filter"]  # non-empty chip list


def test_raw_count_used_when_no_filter():
    geo_data = {"maid_count": 6732, "filtered_maid_count": None, "audience_filter": None}
    out = _build_maid(geo_data, {})
    assert out["count"] == 6732
    assert "count_before_filter" not in out
    assert "active_filter" not in out


# ── Q2/Q3: surfacing the funnel when it explains a big drop ────────────────

def test_funnel_facts_surface_when_the_filter_drops_more_than_half():
    """geo["maid_funnel"] (executors/maid.py) already has the breakdown — the
    composer had no way to reach it before this. Only worth surfacing past a
    real drop, not on every filtered result."""
    geo_data = {
        "maid_count": 1000,
        "filtered_maid_count": 300,
        "audience_filter": {"min_confidence": "confirmed", "min_dwell_min": 10},
        "maid_funnel": {"unconfirmed_visit_pct": 55, "dwell_measurable_pct": 40},
    }
    out = _build_maid(geo_data, {})
    assert out["funnel_dropped_pct"] == 70
    assert out["funnel_unconfirmed_pct"] == 55
    assert out["evidence_timed_visit_pct"] == 40


def test_evidence_timed_visit_pct_absent_without_a_stated_dwell_predicate():
    """dwell_measurable_pct is data quality, not an audience criterion — it
    must not surface (and read as a dwell filter Punk applied) unless the
    user's own filter actually stated a min_dwell_min. Regression for thread
    f7ad8978-5e21-4746-b47c-474a3439eb4a, where the composer told the user it
    "filtered for only those who spent at least 10 minutes" though nothing in
    state ever set a dwell threshold."""
    geo_data = {
        "maid_count": 1000,
        "filtered_maid_count": 300,
        "audience_filter": {"min_confidence": "confirmed"},
        "maid_funnel": {"unconfirmed_visit_pct": 55, "dwell_measurable_pct": 40},
    }
    out = _build_maid(geo_data, {})
    assert "evidence_timed_visit_pct" not in out


def test_derived_filter_never_presented_as_the_users_choice():
    """executors/maid.py stamps a system-default window as
    {"window_days": N, "_derived": True} when the user asked for no
    narrowing at all — it must still drive `count`, but never surface as
    `active_filter` or trip the funnel explanation, both of which read as
    'here's the narrowing you chose'."""
    geo_data = {
        "maid_count": 3600,
        "filtered_maid_count": 710,
        "audience_filter": {"window_days": 15, "_derived": True},
        "maid_funnel": {"unconfirmed_visit_pct": 55, "dwell_measurable_pct": 40},
    }
    out = _build_maid(geo_data, {})
    assert out["count"] == 710
    assert out["count_before_filter"] == 3600
    assert "active_filter" not in out
    assert "funnel_dropped_pct" not in out
    assert "evidence_timed_visit_pct" not in out


def test_explicit_user_filter_still_surfaces_alongside_a_derived_window():
    """A real user narrowing must keep working even when it happens to share
    shape with the derived default — only the `_derived` stamp itself gates
    presentation, not the mere presence of `window_days`."""
    geo_data = {
        "maid_count": 3600,
        "filtered_maid_count": 710,
        "audience_filter": {"window_days": 15},
        "maid_funnel": {"unconfirmed_visit_pct": 55},
    }
    out = _build_maid(geo_data, {})
    assert out["active_filter"]
    assert out["funnel_dropped_pct"] == 80


def test_funnel_facts_absent_when_the_drop_is_small():
    geo_data = {
        "maid_count": 1000,
        "filtered_maid_count": 800,
        "audience_filter": {"min_visits": 2},
        "maid_funnel": {"unconfirmed_visit_pct": 10},
    }
    out = _build_maid(geo_data, {})
    assert "funnel_dropped_pct" not in out


def test_witness_rejection_surfaces_when_the_intersection_rejected_someone():
    """'vet AND PetSmart AND dog park' — a co-located-geofence rejection is
    correct but invisible without this."""
    geo_data = {
        "maid_count": 500,
        "filtered_maid_count": 450,
        "audience_filter": {"groups": ["a", "b"], "op": "intersection"},
        "maid_funnel": {"intersection_raw": 12, "intersection_after_witness_test": 9},
    }
    out = _build_maid(geo_data, {})
    assert out["funnel_witness_rejected"] == 3


def test_witness_rejection_absent_when_nothing_was_rejected():
    geo_data = {
        "maid_count": 500,
        "filtered_maid_count": 450,
        "audience_filter": {"groups": ["a", "b"], "op": "intersection"},
        "maid_funnel": {"intersection_raw": 12, "intersection_after_witness_test": 12},
    }
    out = _build_maid(geo_data, {})
    assert "funnel_witness_rejected" not in out


def test_no_funnel_data_at_all_is_not_fatal():
    geo_data = {"maid_count": 1000, "filtered_maid_count": 300, "audience_filter": {"min_visits": 2}}
    out = _build_maid(geo_data, {})
    assert out["funnel_dropped_pct"] == 70
    assert out.get("funnel_unconfirmed_pct") is None


def test_not_found_labels_excluded_from_poi_types():
    # Regression: "SneakerCon" was searched (an event query) but found zero
    # venues — it still landed in geo_data["poi_types"] (geo.py unions in
    # every REQUESTED term, hit or miss), so the composer read it next to
    # highlights.top_brands as if it were an actual confirmed spot and
    # narrated "ring around SneakerCon" for a POI that was really Flight
    # Club. _build_geo must keep a not-found term out of poi_types and
    # surface it separately instead.
    geo_data = {
        "poi_types": ["SneakerCon", "Flight Club"],
        "not_found_labels": ["SneakerCon"],
    }
    out = _build_geo(geo_data, {})
    assert out["poi_types"] == ["Flight Club"]
    assert out["not_found_labels"] == ["SneakerCon"]


def test_no_not_found_labels_leaves_poi_types_untouched():
    geo_data = {"poi_types": ["Flight Club"]}
    out = _build_geo(geo_data, {})
    assert out["poi_types"] == ["Flight Club"]
    assert "not_found_labels" not in out


def test_poi_types_drops_category_a_poi_selection_trim_emptied():
    # Regression (thread db46217e-0762-4f3d-ad5d-f2468e63ea96): a
    # poi_selection drop-by-category ("remove the longevity clinics") only
    # ever touches targetable_pois — it never prunes poi_types. Left
    # unfiltered, the composer kept naming a category the map no longer has
    # a single spot for ("the single best-rated longevity clinic") for a
    # survivor whose real parent_poi_type was "IV therapy lounge".
    geo_data = {
        "poi_types": ["longevity clinic", "IV therapy lounge", "hormone clinic", "yoga studio"],
        "targetable_pois": [{"name": "Next Health", "parent_poi_type": "IV therapy lounge"}],
    }
    out = _build_geo(geo_data, {})
    assert out["poi_types"] == ["IV therapy lounge"]


def test_poi_types_untouched_before_any_poi_materialized():
    # During discovery, before targetable_pois exists at all, poi_types
    # describes what's being searched — must not be filtered down to nothing.
    geo_data = {"poi_types": ["gym", "yoga studio"]}
    out = _build_geo(geo_data, {})
    assert out["poi_types"] == ["gym", "yoga studio"]


# ── build_pack reads the LIVE bs["geo_result"], not just the committed mirror ──

def test_build_pack_reflects_live_geo_result_without_geo_recommit():
    """state["geo_data"] is only refreshed when builder_plan runs and pops
    bs["_geo_recommit"] — but the maid_confirm widget re-fetches straight
    from bs["geo_result"] on EVERY pause, with no such gate. An edit applied
    inside wizard_interrupt's loop that re-asks the same gate without a
    builder_plan round trip (the handoff lane, a no-op edit, a plain reject)
    must not leave the narrator quoting the pre-edit count while the widget
    it sits next to already shows the new one."""
    state = {
        "geo_data": {"maid_count": 6732, "filtered_maid_count": 6732},
        "campaign_builder_state": {
            "geo_result": {"maid_count": 4020, "filtered_maid_count": 4020},
        },
    }
    pack = build_pack(state)
    assert pack.maid["count"] == 4020


def test_build_pack_keeps_committed_keys_the_live_dict_does_not_carry():
    """bs["geo_result"] wins per-key, but a key it doesn't carry must fall
    back to the committed mirror instead of vanishing — the live dict is not
    guaranteed to be a superset of everything geo_data has ever accumulated."""
    state = {
        "geo_data": {
            "maid_count": 6732, "filtered_maid_count": 6732,
            "maid_count_confidence": 91,
        },
        "campaign_builder_state": {
            "geo_result": {"maid_count": 4020, "filtered_maid_count": 4020},
        },
    }
    pack = build_pack(state)
    assert pack.maid["count"] == 4020
    assert pack.maid["confidence"] == 91


def test_build_pack_falls_back_to_geo_data_with_no_builder_state():
    """Outside the campaign builder (or before it's started), there is no
    bs["geo_result"] at all — must fall back to state["geo_data"] cleanly,
    not raise or silently produce an empty pack."""
    state = {"geo_data": {"maid_count": 6732, "filtered_maid_count": 6732}}
    pack = build_pack(state)
    assert pack.maid["count"] == 6732
