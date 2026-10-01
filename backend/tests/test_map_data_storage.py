"""The map_data payload is slimmed before it reaches langchain_data.

The MAID split-view map ships every observed device point — up to ~229k
{lat,lng,maid} entries, 24 MB on one payload — but WidgetMaidSplitView can never
draw more than 1500 of them (viewport-filtered, zoom > 14). Persisting the rest
put 722 MB of discarded points across 601 chat rows.

Covers: only map_data is touched, the sample spans the whole area rather than one
POI's cluster, sibling keys survive, and the live event is never mutated.
"""

from __future__ import annotations

import json

from app.modules.chat.service import _MAX_STORED_OBSERVATIONS, _slim_for_storage


def _obs(n: int) -> list[dict]:
    """n observations walking west→east, so a head slice is detectable."""
    return [{"lat": 40.7 + i * 1e-6, "lng": -74.0 + i * 1e-5, "maid": f"m{i}"} for i in range(n)]


def _payload(n: int) -> dict:
    return {
        "action_type": "maid_split_view",
        "pois": [{"name": "Regal Battery Park", "lat": 40.71, "lng": -74.01}],
        "maid_observations": _obs(n),
        "center": {"label": "New York, NY"},
        "maid_count": n,
        "visit_stats": {"basis": "sightings", "buckets": {"1x": 103189}},
        "lookback_days": 30,
        "editable": True,
    }


# ── only map_data is touched ──────────────────────────────────────────────────

def test_other_event_types_pass_through_untouched():
    pending = {"action_type": "permission", "options": ["yes", "no"]}
    assert _slim_for_storage("pending_action", pending) is pending
    assert _slim_for_storage("campaign_plan", {"a": 1}) == {"a": 1}
    assert _slim_for_storage(None, pending) is pending


def test_non_dict_content_is_safe():
    assert _slim_for_storage("map_data", None) is None
    assert _slim_for_storage("map_data", "not a dict") == "not a dict"


def test_short_list_is_returned_unchanged():
    small = _payload(10)
    assert _slim_for_storage("map_data", small) is small


def test_empty_and_missing_observations_are_safe():
    empty = {**_payload(0)}
    assert _slim_for_storage("map_data", empty) is empty
    missing = {"action_type": "maid_split_view", "pois": [], "maid_count": 0}
    assert _slim_for_storage("map_data", missing) is missing


# ── the cap ───────────────────────────────────────────────────────────────────

def test_large_list_is_capped():
    out = _slim_for_storage("map_data", _payload(229_021))
    assert len(out["maid_observations"]) <= _MAX_STORED_OBSERVATIONS


def test_sample_spans_the_whole_area_not_just_the_head():
    """A head slice (obs[:5000]) would keep one POI's cluster and leave the rest
    of the map bare — the observation list is grouped by POI."""
    total = 229_021
    out = _slim_for_storage("map_data", _payload(total))
    kept = out["maid_observations"]

    assert kept[0]["maid"] == "m0"                      # start retained
    last_index = int(kept[-1]["maid"][1:])
    assert last_index > total * 0.99                    # reaches the far end
    # …and it is genuinely spread, not a head slice with a tail bolted on.
    beyond_head = [o for o in kept if int(o["maid"][1:]) > _MAX_STORED_OBSERVATIONS]
    assert len(beyond_head) > len(kept) * 0.9


def test_sibling_keys_survive():
    src = _payload(229_021)
    out = _slim_for_storage("map_data", src)
    for key in ("action_type", "pois", "center", "maid_count", "visit_stats",
                "lookback_days", "editable"):
        assert out[key] == src[key], key


def test_input_is_not_mutated_so_the_live_stream_keeps_every_point():
    src = _payload(20_000)
    before = len(src["maid_observations"])
    out = _slim_for_storage("map_data", src)

    assert len(src["maid_observations"]) == before      # live payload untouched
    assert out is not src
    assert out["maid_observations"] is not src["maid_observations"]


def test_the_size_win_is_real():
    src = _payload(229_021)
    out = _slim_for_storage("map_data", src)
    big, small = len(json.dumps(src)), len(json.dumps(out))
    assert small < big * 0.05, f"{big} -> {small}"
