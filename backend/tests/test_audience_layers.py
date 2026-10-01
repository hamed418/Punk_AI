"""
tests/test_audience_layers.py
─────────────────────────────
The layer builder's backend: the read-only per-layer recount, the group-label
resolver it shares with the chat edit path, and the structured panel commit that
must reach the edit lane instead of being read as a "yes".
"""
from __future__ import annotations

import json

from app.graph.maid_query import attribute_audience
from app.graph.resume_router import audience_panel_intent, is_sentinel_resume
from app.graph.unacast_query import poi_key
from app.services.maid_store import (
    MAX_PREVIEW_LAYERS,
    preview_audience_layers,
    resolve_audience_filter_specs,
    resolve_group_labels,
)

GYM = {"name": "Gold's Gym", "lat": 45.51, "lng": -73.58, "radius_km": 0.5,
       "source_angle": "category", "parent_poi_type": "gym"}
CAFE = {"name": "Tim Hortons", "lat": 45.52, "lng": -73.59, "radius_km": 0.5,
        "source_angle": "category", "parent_poi_type": "coffee shop"}
SALON = {"name": "Snip", "lat": 45.53, "lng": -73.60, "radius_km": 0.5,
         "source_angle": "category", "parent_poi_type": "salon"}
POIS = [GYM, CAFE, SALON]


def _row(maid: str, poi: dict, day: str, hour: int = 12) -> dict:
    return {
        "lat": poi["lat"], "lng": poi["lng"], "maid": maid, "count": 1,
        "poi_key": poi_key(poi), "days": [day],
        "visits": [{"ts": f"{day}T{hour:02d}:00:00+00:00", "dwell_min": 10,
                    "dwell_lower_s": 600, "n_pings": 2}],
    }


def _stamped() -> list[dict]:
    """all3 → gym, cafe, salon on separate days; two → gym + cafe; one → gym."""
    raw = [
        _row("all3", GYM, "2026-08-01"), _row("all3", CAFE, "2026-08-02"), _row("all3", SALON, "2026-08-03"),
        _row("two", GYM, "2026-08-01"), _row("two", CAFE, "2026-08-02"),
        _row("one", GYM, "2026-08-01"),
    ]
    _, rows = attribute_audience(raw, [dict(p) for p in POIS], stamp_stats=False)
    return rows


def _preview(layers: list[dict], **kw) -> list[dict]:
    return preview_audience_layers(_stamped(), [dict(p) for p in POIS], layers, **kw)


def test_each_layer_is_counted_over_the_stored_rows_and_the_count_falls():
    layers = _preview([
        {"label": "Gym", "patches": [{"groups": ["gym"]}]},
        {"label": "+ cafe", "patches": [{"groups": ["gym", "coffee shop"], "op": "intersection"}]},
        {"label": "+ salon", "patches": [{"groups": ["gym", "coffee shop", "salon"], "op": "intersection"}]},
    ])
    assert [l["count"] for l in layers] == [3, 2, 1]
    assert [l["label"] for l in layers] == ["Gym", "+ cafe", "+ salon"]


def test_any_n_of_m_is_the_rescue_rung_between_all_and_nothing():
    groups = ["gym", "coffee shop", "salon"]
    layers = _preview([
        {"label": "all", "patches": [{"groups": groups, "op": "intersection"}]},
        {"label": "any 2", "patches": [{"groups": groups, "min_distinct_groups": 2}]},
    ])
    assert [l["count"] for l in layers] == [1, 2]
    assert layers[1]["chips"] == ["any 2+ of these groups"]


def test_a_later_patch_overrides_an_earlier_one_and_none_clears_a_key():
    """The layer's patches replay through the same fold the chat edit uses."""
    [layer] = _preview([{"label": "x", "patches": [
        {"groups": ["gym", "coffee shop"], "op": "intersection"},
        {"op": None},
    ]}])
    # op cleared → a plain union of the two groups: all3, two, one all touch the gym
    assert layer["count"] == 3
    assert "op" not in layer["filter"]


def test_group_ids_resolve_verbatim_and_labels_still_work():
    assert resolve_group_labels(["category:gym"], POIS) == ["category:gym"]
    assert resolve_group_labels(["gym"], POIS) == ["category:gym"]


def test_an_unknown_group_is_reported_not_silently_dropped():
    [layer] = _preview([{"label": "x", "patches": [{"groups": ["gym", "spaceport"]}]}])
    assert layer["deviations"] == ["1 named group didn't match any category on screen"]
    _, named, matched = resolve_audience_filter_specs([{"groups": ["gym", "spaceport"]}], POIS)
    assert (named, matched) == (2, 1)


def test_an_unevaluable_layer_reports_why_instead_of_a_confident_zero():
    [layer] = _preview(
        [{"label": "lapsed", "patches": [{"trend": "lapsed", "window_days": 30}]}],
        history_days_bought=7,
    )
    assert layer["count"] is None
    assert layer["unevaluable"]


def test_preview_leaves_the_stored_rows_untouched():
    rows = _stamped()
    before = json.dumps(rows, sort_keys=True, default=str)
    preview_audience_layers(rows, [dict(p) for p in POIS], [{"label": "x", "patches": [{"groups": ["gym"]}]}])
    assert json.dumps(rows, sort_keys=True, default=str) == before


def test_layers_beyond_the_cost_cap_are_not_evaluated():
    layers = [{"label": str(i), "patches": [{"groups": ["gym"]}]} for i in range(MAX_PREVIEW_LAYERS + 3)]
    assert len(_preview(layers)) == MAX_PREVIEW_LAYERS


# ── the panel's structured commit ────────────────────────────────────────────

def _commit(patch: dict) -> str:
    return json.dumps({"action": "audience_filter_patch", "patch": patch})


def test_a_panel_commit_reaches_the_edit_lane_not_the_confirm_lane():
    raw = _commit({"groups": ["gym", "coffee shop"], "min_distinct_groups": 2})
    assert is_sentinel_resume(raw)  # the generic check WOULD read this as "confirm"
    intent = audience_panel_intent(raw)
    assert intent is not None
    assert (intent.lane, intent.target_field, intent.confidence) == ("edit", "audience_filter", 1.0)
    assert intent.new_value == {"groups": ["gym", "coffee shop"], "min_distinct_groups": 2}


def test_null_keys_survive_so_removing_a_layer_actually_clears_it():
    intent = audience_panel_intent(_commit({"op": None, "exclude_groups": None, "min_visits": 3}))
    assert intent.new_value == {"op": None, "exclude_groups": None, "min_visits": 3}


def test_invalid_values_are_dropped_and_unknown_keys_ignored():
    intent = audience_panel_intent(_commit({"min_visits": -2, "bogus": 1, "window_days": 30}))
    assert intent.new_value == {"window_days": 30}


def test_other_replies_are_not_panel_commits():
    for raw in ("yes", "only weekends", '{"confirm": true}', '{"action": "other"}',
                json.dumps({"action": "audience_filter_patch", "patch": "x"}),
                _commit({"bogus": 1}), _commit({})):
        assert audience_panel_intent(raw) is None, raw


# ── the panel can only say what it owns; everything else rides the base ──────

def test_a_panel_patch_sets_owned_keys_and_may_only_remove_the_rest():
    """Two closed lanes. The panel SETS what it has a control for (dwell, trend
    and cadence included); for a setting it merely lists as 'also applied' it can
    say only 'remove' — never a new value."""
    from app.graph.resume_router import sanitize_panel_patch

    cleaned = sanitize_panel_patch({
        "groups": ["gym"], "min_visits": 3, "window_days": None,
        "trend": "lapsed", "trend_recent_days": 14, "cadence_days": 7, "min_dwell_min": 60,
        "invert": True, "hours": [6, 9],                     # carried: cannot be SET
        "min_weekly_hours": None, "dwell_bound": None,       # carried: can be REMOVED
        "any_of": None, "_resolved": None, "unsupported": "x", "not_a_key": None,  # never
    })
    assert cleaned == {
        "groups": ["gym"], "min_visits": 3, "window_days": None,
        "trend": "lapsed", "trend_recent_days": 14, "cadence_days": 7, "min_dwell_min": 60,
        "min_weekly_hours": None, "dwell_bound": None,
    }


def test_the_clear_lane_is_every_user_facing_key_and_nothing_internal():
    from app.services.maid_store import CLEARABLE_FILTER_KEYS, LAYER_BUILDER_KEYS

    assert LAYER_BUILDER_KEYS <= CLEARABLE_FILTER_KEYS
    assert "any_of" not in CLEARABLE_FILTER_KEYS  # replaces the whole filter; not a removal
    assert not any(k.startswith("_") for k in CLEARABLE_FILTER_KEYS)


def test_every_setting_the_panel_cannot_edit_shows_up_as_something_removable():
    """A carried key the user cannot see cannot be removed. This pins the set:
    add a filter key and this fails until it has a sample — i.e. a label."""
    from app.services.maid_store import CLEARABLE_FILTER_KEYS, LAYER_BUILDER_KEYS, carried_filter_parts

    samples = {
        "min_distinct_pois": 2, "hours": [6, 9], "min_weekly_hours": 30, "invert": True,
        "min_share_in_scope": 0.5, "min_confidence": "confirmed", "exclude_flags": 4,
        "dwell_bound": "upper", "min_open_day_share": 0.5, "min_intraday_span_min": 120,
        "min_days_present": 3,
    }
    assert set(samples) == CLEARABLE_FILTER_KEYS - LAYER_BUILDER_KEYS
    for key, value in samples.items():
        [part] = carried_filter_parts({key: value})
        assert part["key"] == key and part["label"], key


def test_carried_parts_are_one_per_key_and_skip_owned_and_internal_keys():
    from app.services.maid_store import carried_filter_parts

    parts = carried_filter_parts({
        "groups": ["category:gym"], "trend": "lapsed", "min_dwell_min": 30,   # owned by the panel
        "min_weekly_hours": 30, "invert": True, "dwell_bound": "upper", "hours": [6, 9],
        "_resolved": True, "_history_days_bought": 60, "made_up_key": 1,       # not user-facing
    })
    assert parts == [
        {"key": "min_weekly_hours", "label": "30+ hrs/week"},
        {"key": "invert", "label": "flipped — excludes the people who match"},
        {"key": "dwell_bound", "label": "dwell counted at its upper bound"},
        {"key": "hours", "label": "6:00–9:00"},
    ]
    assert carried_filter_parts(None) == []
    assert carried_filter_parts({"window_days": 7, "_derived": True}) == []


def test_removing_a_carried_setting_changes_the_count_and_only_that_one():
    layers = _preview(
        [
            {"label": "kept", "patches": [{}]},
            {"label": "removed", "patches": [{"min_distinct_pois": None}]},
        ],
        base={"min_distinct_pois": 2, "hours": [0, 24]},
    )
    kept, removed = layers
    assert kept["count"] == 2      # all3 + two visited 2+ places
    assert removed["count"] == 3   # the requirement is gone; everyone is back
    assert removed["filter"] == {"hours": [0, 24]}


def test_dwell_trend_and_cadence_are_real_filters_the_panel_can_set():
    """They reach the engine through the same overlay as everything else."""
    dwell_ok, dwell_too_long = _preview([
        {"label": "5", "patches": [{"groups": ["gym"], "min_dwell_min": 5}]},
        {"label": "30", "patches": [{"groups": ["gym"], "min_dwell_min": 30}]},
    ])
    assert (dwell_ok["count"], dwell_too_long["count"]) == (3, 0)   # every visit is 10 min

    [lapsed] = _preview(
        [{"label": "l", "patches": [{"trend": "lapsed", "window_days": 30}]}], history_days_bought=90,
    )
    assert lapsed["count"] is not None and lapsed["unevaluable"] is None


def test_a_cadence_over_too_short_a_purchase_is_refused_not_answered_with_nobody():
    """`assert_filter_evaluable` only guarded a trend. A cadence over a purchase
    too short to observe it finds nobody — which reads as a real 'no one repeats'."""
    import pytest

    from app.services.maid_store import AudienceFilterUnevaluable, apply_audience_filter

    rows, pois = _stamped(), [dict(p) for p in POIS]
    with pytest.raises(AudienceFilterUnevaluable) as exc:
        apply_audience_filter(rows, {"cadence_days": 14, "_history_days_bought": 7}, pois=pois)
    assert exc.value.needed_days > 7 and "repeating visit pattern" in str(exc.value)
    apply_audience_filter(rows, {"cadence_days": 7, "_history_days_bought": 60}, pois=pois)  # enough history
    apply_audience_filter(rows, {"cadence_days": 14}, pois=pois)  # legacy row, no stamp: unchanged

    [layer] = _preview([{"label": "c", "patches": [{"cadence_days": 14}]}], history_days_bought=7)
    assert layer["count"] is None and layer["unevaluable"]


def test_a_sidecar_never_outlives_its_owner_in_the_fold():
    """"Drop the trend" clears `trend` alone; the windows left behind would
    silently re-attach to the next 'lapsed' anyone asks for."""
    from app.services.maid_store import fold_audience_filter_specs

    def pub(specs):
        return {k: v for k, v in fold_audience_filter_specs(specs).items() if not k.startswith("_")}

    windows = {"trend": "lapsed", "trend_recent_days": 14, "trend_prior_days": 60}
    assert pub([windows]) == windows
    assert pub([windows, {"trend": None}]) == {}
    assert pub([{"cadence_days": 7, "cadence_tolerance_days": 1}, {"cadence_days": None}]) == {}
    # the owner still present: nothing is stripped
    assert pub([{"cadence_days": 7, "cadence_tolerance_days": 1}, {"min_visits": 3}]) == {
        "cadence_days": 7, "cadence_tolerance_days": 1, "min_visits": 3,
    }


def test_preview_and_commit_clean_a_patch_with_the_same_function():
    """Both go through `sanitize_panel_patch`, so a patch means the same thing
    in each — including what happens to an invalid value."""
    from app.graph.resume_router import audience_panel_intent, sanitize_panel_patch

    patch = {"min_visits": -2, "window_days": 30, "days_of_week": [9], "op": None}
    intent = audience_panel_intent(_commit(patch))
    assert intent.new_value == sanitize_panel_patch(patch)


def test_layer_builder_keys_match_the_frontends_panel_keys():
    """`LAYER_BUILDER_KEYS` (server) and `PANEL_KEYS` (audienceLayers.ts) are one
    list in two languages. If they drift, the panel either edits a key the
    server drops or shows a key as 'also applied' that it is actually editing."""
    import re
    from pathlib import Path

    from app.services.maid_store import LAYER_BUILDER_KEYS

    ts = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/app/(main)/chat/components/widgets/maid-split-view/audienceLayers.ts"
    ).read_text(encoding="utf-8")
    block = re.search(r"export const PANEL_KEYS = \[(.*?)\] as const", ts, re.S)
    assert block, "PANEL_KEYS not found in audienceLayers.ts"
    assert set(re.findall(r"'([a-z_]+)'", block.group(1))) == set(LAYER_BUILDER_KEYS)


def test_public_filter_hides_internals_and_the_system_default():
    from app.services.maid_store import public_audience_filter

    assert public_audience_filter(None) == {}
    assert public_audience_filter({"window_days": 7, "_derived": True}) == {}
    assert public_audience_filter(
        {"groups": ["category:gym"], "trend": "lapsed", "_resolved": True, "_history_days_bought": 60}
    ) == {"groups": ["category:gym"], "trend": "lapsed"}


# ── the endpoint ─────────────────────────────────────────────────────────────

class _Repo:
    def __init__(self, owns: bool = True):
        self.owns = owns

    async def find_specific_user_chat(self, db, session_id, user_id):
        return object() if self.owns else None


def _service(owns: bool = True):
    from app.modules.chat.service import ChatService

    return ChatService(_Repo(owns))


def _request(*layers: dict):
    from app.modules.chat.schemas import AudiencePreviewRequest

    return AudiencePreviewRequest(layers=list(layers))


def _run_preview(monkeypatch, extraction, request, *, owns: bool = True):
    import asyncio

    async def fake(_session_id):
        return extraction

    monkeypatch.setattr("app.services.maid_store.fetch_maid_extraction_by_session", fake)

    class _User:
        id = "u1"

    return asyncio.run(_service(owns).preview_audience("s1", request, _User(), None))


def _extraction(audience_filter=None, **over):
    return {
        "maid_count": 3, "observations": _stamped(), "pois": [dict(p) for p in POIS],
        "audience_filter": audience_filter, "purged_at": None, **over,
    }


def test_endpoint_overlays_the_patch_on_the_stored_filter_and_names_what_it_carries(monkeypatch):
    out = _run_preview(
        monkeypatch,
        _extraction({"groups": ["category:gym"], "min_visits": 1, "min_distinct_pois": 1, "_resolved": True}),
        _request({"label": "x", "patches": [{"window_days": 30}]}),
    )
    [layer] = out["layers"]
    # the carried `min_distinct_pois` is in the previewed filter, and the response names it
    assert layer["filter"]["min_distinct_pois"] == 1
    assert layer["filter"]["groups"] == ["category:gym"]
    assert out["carried"] == [{"key": "min_distinct_pois", "label": "1+ locations"}]
    assert out["min_deliverable"] == 1000


def test_endpoint_refuses_an_either_or_filter_instead_of_showing_a_different_audience(monkeypatch):
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc:
        _run_preview(
            monkeypatch,
            _extraction({"any_of": [{"groups": ["category:gym"]}, {"min_visits": 3}], "_resolved": True}),
            _request({"label": "x", "patches": [{"window_days": 30}]}),
        )
    assert exc.value.status_code == 409


def test_endpoint_status_codes(monkeypatch):
    from fastapi import HTTPException
    import pytest

    req = _request({"label": "x", "patches": [{}]})
    for extraction, owns, status in [
        (_extraction(), False, 404),                       # not this user's conversation
        (None, True, 404),                                 # nothing extracted yet
        (_extraction(purged_at="2026-01-01"), True, 409),  # already published, rows cleared
    ]:
        with pytest.raises(HTTPException) as exc:
            _run_preview(monkeypatch, extraction, req, owns=owns)
        assert exc.value.status_code == status


def test_endpoint_lets_a_patch_remove_a_carried_key_but_never_change_it(monkeypatch):
    """Removal is the only thing the panel can say about a setting it has no
    control for: a new value for it is dropped by preview and commit alike."""
    base = {"groups": ["category:gym"], "min_share_in_scope": 0.5, "hours": [0, 24], "_resolved": True}
    out = _run_preview(
        monkeypatch, _extraction(base),
        _request(
            {"label": "set", "patches": [{"min_share_in_scope": 0.9, "min_visits": 1}]},
            {"label": "removed", "patches": [{"hours": None}]},
        ),
    )
    changed, removed = out["layers"]
    assert changed["filter"]["min_share_in_scope"] == 0.5      # the new value never landed
    assert "hours" not in removed["filter"] and removed["filter"]["min_share_in_scope"] == 0.5


def test_the_widget_payload_carries_the_users_filter_but_not_internals_or_the_default_window():
    """The panel seeds its draft from this. A system-default window (`_derived`)
    shown as if the user chose it would make the panel preselect — and Apply —
    a window nobody asked for."""
    from app.graph.maid_query import build_maid_split_view

    def payload(spec):
        return build_maid_split_view(
            pois=[dict(p) for p in POIS], observations=_stamped(), audience_filter=spec,
            center={}, visit_stats=None, search_radius_km=None, lookback_days=7, event_date_ranges=[],
        )["audience_filter"]

    assert payload(None) is None
    assert payload({"window_days": 7, "_derived": True}) is None
    assert payload({"groups": ["category:gym"], "trend": "started", "_resolved": True, "_history_days_bought": 60}) == {
        "groups": ["category:gym"], "trend": "started",
    }


def test_a_panel_commit_that_only_removes_settings_still_reaches_the_edit_lane():
    raw = _commit({"trend": None, "hours": None})
    intent = audience_panel_intent(raw)
    assert intent is not None and intent.new_value == {"trend": None, "hours": None}
    assert audience_panel_intent(_commit({"hours": [6, 9]})) is None   # a value for a carried key: nothing left
