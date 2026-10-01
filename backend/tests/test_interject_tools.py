"""
Unit tests for builder/interject_tools.py — the Phase 2 `handoff` lane's
tool set. Exercises each @tool's underlying function directly (no LLM, no
network) via the same contextvar injection run_handoff_turn uses.
"""
import pytest

from app.graph.builder import interject_tools as it


def _with_state(state):
    token = it._ho_state.set(state)
    return token


def _clear(token):
    it._ho_state.reset(token)


def _state(bs):
    return {"campaign_builder_state": bs}


# ── read tools ───────────────────────────────────────────────────────────────

def test_get_build_state_reads_bs():
    bs = {"filled": {"business_name": "PunkBakery"}, "stages_complete": ["geo"], "ops_done": ["geo_discover"]}
    token = _with_state(_state(bs))
    try:
        out = it.get_build_state.func()
    finally:
        _clear(token)
    assert out == {
        "filled": {"business_name": "PunkBakery"},
        "stages_complete": ["geo"],
        "ops_done": ["geo_discover"],
    }


def test_get_build_state_empty_when_no_state():
    token = _with_state(None)
    try:
        out = it.get_build_state.func()
    finally:
        _clear(token)
    assert out == {"filled": {}, "stages_complete": [], "ops_done": []}


def test_get_pois_breakdown_and_sample_cap():
    pois = (
        [{"name": f"gym{i}", "source_angle": "category", "parent_poi_type": "gym", "parent_label": "Montreal"} for i in range(20)]
        + [{"name": "Boustan", "source_angle": "competitor_brand", "parent_poi_type": "restaurant", "parent_label": "Montreal"}]
    )
    bs = {"geo_result": {"targetable_pois": pois}}
    token = _with_state(_state(bs))
    try:
        out = it.get_pois.func()
    finally:
        _clear(token)
    assert out["total"] == 21
    assert out["by_angle"] == {"category": 20, "competitor_brand": 1}
    assert len(out["sample"]) == 15  # capped, never dumps the whole list


def test_get_pois_by_category_and_adjustable_cap():
    pois = (
        [{"name": f"gym{i}", "source_angle": "category", "parent_poi_type": "gym",
          "parent_label": "Montreal", "rating": 4.0, "user_ratings_total": 10,
          "audience_count": 5} for i in range(20)]
        + [{"name": "Boustan", "source_angle": "competitor_brand", "parent_poi_type": "restaurant",
            "brand": "Boustan", "parent_label": "Montreal"}]
    )
    bs = {"geo_result": {"targetable_pois": pois}}
    token = _with_state(_state(bs))
    try:
        out = it.get_pois.func(max_sample=3)
        out_all = it.get_pois.func(max_sample=100)
    finally:
        _clear(token)
    assert len(out["sample"]) == 3
    assert len(out_all["sample"]) == 21
    assert out["by_category"]["category:gym"] == {
        "count": 20, "rated": 20, "audience": 100, "avg_rating": 4.0,
    }
    # unrated named-arm POI: rated=0, avg_rating None, not a crash
    assert out["by_category"]["competitor_brand:restaurant"]["avg_rating"] is None
    assert out["has_reference_point"] is False
    assert "distance_km" not in out["sample"][0]  # never guessed with no ref point


def test_get_pois_distance_when_reference_point_available():
    pois = [
        {"name": "Near", "source_angle": "category", "parent_poi_type": "gym",
         "parent_label": "Montreal", "lat": 45.50, "lng": -73.55, "rating": 4.5, "user_ratings_total": 10},
        {"name": "Far", "source_angle": "category", "parent_poi_type": "gym",
         "parent_label": "Montreal", "lat": 46.00, "lng": -74.00, "rating": 4.5, "user_ratings_total": 10},
    ]
    bs = {
        "geo_result": {"targetable_pois": pois},
        "geo_ws": {"_det_center": {"latitude": 45.50, "longitude": -73.55}},
    }
    token = _with_state(_state(bs))
    try:
        out = it.get_pois.func()
    finally:
        _clear(token)
    assert out["has_reference_point"] is True
    by_name = {s["name"]: s["distance_km"] for s in out["sample"]}
    assert by_name["Near"] < by_name["Far"]
    assert by_name["Near"] < 1.0  # same coords as the ref point


def test_get_audience_not_run_yet_is_honest_not_zero():
    """No extraction id on record -> `ran: False`, not a silent 0 that reads
    as 'nobody found', so the composer can say 'haven't pulled that yet'."""
    bs = {"geo_result": {}}
    token = _with_state(_state(bs))
    try:
        out = it.get_audience.func()
    finally:
        _clear(token)
    assert out["ran"] is False
    assert out["total"] == 0 and out["filtered"] == 0
    assert out["visit_stats"] == {} and out["by_category"] == {}


def test_get_audience_reads_maid_fields():
    pois = [
        {"name": "Gym A", "source_angle": "category", "parent_poi_type": "gym", "audience_count": 80},
        {"name": "Gym B", "source_angle": "category", "parent_poi_type": "gym", "audience_count": 40},
        {"name": "Boustan", "source_angle": "competitor_brand", "parent_poi_type": "restaurant", "brand": "Boustan", "audience_count": 30},
    ]
    bs = {"geo_result": {
        "maid_extraction_id": "abc123",
        "targetable_pois": pois,
        "maid_count": 500, "filtered_maid_count": 120,
        "audience_filter": {"min_visits": 2},
        "maid_visit_stats": {"total_devices": 120, "repeat_visitor_count": 30, "repeat_visitor_pct": 25.0},
        "lookback_days": 90, "poi_radius_km": 0.5,
    }}
    token = _with_state(_state(bs))
    try:
        out = it.get_audience.func()
    finally:
        _clear(token)
    assert out["ran"] is True
    assert out["total"] == 500 and out["filtered"] == 120
    assert out["filter_raw"] == {"min_visits": 2}
    assert out["filter_chips"] == ["2+ visits"]
    assert out["visit_stats"]["repeat_visitor_pct"] == 25.0
    # by_category sums the already-stamped per-POI audience_count, no new query
    assert out["by_category"] == {"category:gym": 120, "competitor_brand:restaurant": 30}
    assert out["lookback_days"] == 90 and out["radius_km"] == 0.5


def test_get_audience_total_and_filtered_can_genuinely_differ():
    """Regression: total/filtered used to be mirrored to the same value
    everywhere, making 'how many did the filter cut' unanswerable from this
    tool. They must be independently readable."""
    bs = {"geo_result": {
        "maid_extraction_id": "x", "targetable_pois": [],
        "maid_count": 500, "filtered_maid_count": 120,
    }}
    token = _with_state(_state(bs))
    try:
        out = it.get_audience.func()
    finally:
        _clear(token)
    assert out["total"] != out["filtered"]


def test_get_audience_after_a_failed_retry_never_states_the_stale_count():
    """Reproduces the mechanism traced in executors/maid.py: a total query
    failure after a prior SUCCESSFUL extraction leaves `maid_count` at its
    stale pre-edit value (the zero-or-keep-prior-nonzero guard never
    overwrites it on total failure) while `filtered_maid_count` IS
    unconditionally reset to the failed attempt's empty 0 — and
    `maid_failure_kind` is set alongside both. Asking "how big is my
    audience" right after such a retry must never state either number as
    fact — that is the same false-acknowledgment narrator/grounding.py's
    `_build_maid` already refuses to make for the user-facing reveal."""
    bs = {"geo_result": {
        "maid_extraction_id": "abc123",       # extraction row still exists
        "targetable_pois": [],
        "maid_count": 3506,                   # STALE — from before the edit
        "filtered_maid_count": 0,              # fresh, but from THIS failure
        "maid_failure_kind": "budget",
    }}
    token = _with_state(_state(bs))
    try:
        out = it.get_audience.func()
    finally:
        _clear(token)
    assert out["ran"] is True
    assert out["query_failed"] is True
    assert out["failure_kind"] == "budget"
    # Neither number is trustworthy right now — must not leak the stale 3506.
    assert out["total"] == 0
    assert out["filtered"] == 0


# ── write / process-control tools ───────────────────────────────────────────

def test_undo_pops_the_snapshot_and_restores():
    import asyncio

    bs = {
        "filled": {"business_name": "NewName"},
        "ops_done": ["geo_discover", "generate_brief"],
        "_undo_stack": [{"filled": {"business_name": "OldName"}, "ops_done": ["geo_discover"]}],
    }
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert "reverted" in result
    assert bs["filled"] == {"business_name": "OldName"}
    assert bs["ops_done"] == ["geo_discover"]
    assert bs["_undo_stack"] == []


def test_undo_empty_stack_is_honest():
    import asyncio

    bs = {"filled": {}, "ops_done": []}
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert "nothing to undo" in result
    # Must not fabricate a change when there was nothing to revert.
    assert bs["filled"] == {}


def test_undo_restores_poi_selection_specs_and_refolds_the_superset():
    """The docstring's "a POI trim" claim used to be a lie for the common
    case: a turn that only trims POIs pushes a snapshot carrying
    `_poi_selection_specs`, but undo only restored `filled`/`ops_done` —
    the trimmed `targetable_pois` stayed trimmed. Undo now restores the spec
    LIST and re-folds it over the persisted superset (`apply_specs`), the
    same recompute `_apply_geo_poi_selection_edit` does going forward.
    """
    import asyncio

    superset = [
        {"name": f"gym{i}", "lat": 45.0, "lng": -73.0 + i * 0.01,
         "source_angle": "category", "parent_poi_type": "gym",
         "parent_label": "Montreal", "types": ["gym"]}
        for i in range(10)
    ]
    bs = {
        "filled": {"business_name": "NewName"},
        "ops_done": ["geo_discover"],
        "geo_ws": {"_all_pois_cache": superset},
        # Post-edit state: a SECOND trim (top 3) already landed on top of the
        # snapshotted first trim (top 5) — undo must land back on the FIRST.
        "_poi_selection_specs": [{"op": "keep", "n": 3, "scope": "all"}],
        "geo_result": {"targetable_pois": superset[:3], "pois_found": 3},
        "_undo_stack": [{
            "filled": {"business_name": "OldName"},
            "ops_done": ["geo_discover"],
            "_poi_selection_specs": [{"op": "keep", "n": 5, "scope": "all"}],
        }],
    }
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert "reverted" in result
    assert bs["_poi_selection_specs"] == [{"op": "keep", "n": 5, "scope": "all"}]
    # Re-folded against the superset, not left at the still-3-trimmed value.
    assert bs["geo_result"]["pois_found"] == 5
    assert len(bs["geo_result"]["targetable_pois"]) == 5
    assert bs.get("_geo_recommit") is True


def test_undo_resyncs_the_persisted_extraction_when_one_exists(monkeypatch):
    """Regression: undo() recomputed the POI restore against LOCAL state
    (geo_result/geo_ws) but never touched the persisted MAID extraction —
    so undoing a trim left Postgres (the map's tabs, the audience count, the
    MAID list Meta uploads) at the still-trimmed set. Mocks the delegation
    itself (the real DB round trip is covered by
    test_poi_selection_after_extraction.py's fake_extraction_db + production
    use) to prove undo() calls it, with both halves of the delta, whenever
    an extraction is on record."""
    import asyncio

    import app.graph.builder.builder_node as bn

    calls: list[dict] = []

    async def _fake_apply_maid_poi_edits(bs_arg, state_arg, edits, *, narrate=True):
        calls.append(edits)
        return "ok"

    monkeypatch.setattr(bn, "_apply_maid_poi_edits", _fake_apply_maid_poi_edits)

    superset = [
        {"name": f"gym{i}", "lat": 45.0, "lng": -73.0 + i * 0.01,
         "source_angle": "category", "parent_poi_type": "gym",
         "parent_label": "Montreal", "types": ["gym"]}
        for i in range(10)
    ]
    bs = {
        "filled": {}, "ops_done": ["geo_discover"],
        "geo_ws": {"_all_pois_cache": superset},
        "_poi_selection_specs": [{"op": "keep", "n": 3, "scope": "all"}],
        "geo_result": {
            "targetable_pois": superset[:3], "pois_found": 3,
            "maid_extraction_id": "extraction-1",
        },
        "_undo_stack": [{
            "filled": {}, "ops_done": ["geo_discover"],
            "_poi_selection_specs": [{"op": "keep", "n": 5, "scope": "all"}],
        }],
    }
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert "reverted" in result
    assert bs["geo_result"]["pois_found"] == 5  # local restore still happened
    assert len(calls) == 1
    # Both halves of the delta — report.kept ("added", the restored 5) and
    # report.dropped ("removed", the other 5 not in this fold) — same shape
    # _apply_geo_poi_selection_edit passes on the forward path; dedup inside
    # apply_poi_edits makes re-"adding" an already-present POI a no-op.
    assert len(calls[0]["added"]) == 5
    assert len(calls[0]["removed"]) == 5


def test_undo_skips_the_maid_resync_with_no_extraction_on_record(monkeypatch):
    import asyncio

    import app.graph.builder.builder_node as bn

    calls = []
    monkeypatch.setattr(
        bn, "_apply_maid_poi_edits",
        lambda *a, **k: calls.append(1) or "ok",
    )

    superset = [
        {"name": f"gym{i}", "lat": 45.0, "lng": -73.0 + i * 0.01,
         "source_angle": "category", "parent_poi_type": "gym",
         "parent_label": "Montreal", "types": ["gym"]}
        for i in range(10)
    ]
    bs = {
        "filled": {}, "ops_done": ["geo_discover"],
        "geo_ws": {"_all_pois_cache": superset},
        "_poi_selection_specs": [{"op": "keep", "n": 3, "scope": "all"}],
        "geo_result": {"targetable_pois": superset[:3], "pois_found": 3},
        "_undo_stack": [{
            "filled": {}, "ops_done": ["geo_discover"],
            "_poi_selection_specs": [{"op": "keep", "n": 5, "scope": "all"}],
        }],
    }
    token = _with_state(_state(bs))
    try:
        asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert calls == []


def test_narrow_pois_narrows_mid_turn_and_undo_puts_it_back():
    """The handoff lane's write tool: delegates to the same
    _apply_geo_poi_selection_edit resolver the edit-lane uses, so a mid-turn
    "just the top 3" narrows the LIVE geo_result, pushes an undo snapshot, and
    sets _geo_recommit for the next pause — then undo() (above) reverses it."""
    import asyncio

    superset = [
        {"name": f"gym{i}", "lat": 45.0, "lng": -73.0 + i * 0.01,
         "source_angle": "category", "parent_poi_type": "gym",
         "parent_label": "Montreal", "types": ["gym"]}
        for i in range(10)
    ]
    bs = {
        "filled": {}, "ops_done": ["geo_discover"],
        "geo_ws": {"_all_pois_cache": superset},
        "geo_result": {"targetable_pois": list(superset), "pois_found": 10},
    }
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.narrow_pois.ainvoke({"spec": {"op": "keep", "n": 3, "scope": "all"}}))
    finally:
        _clear(token)
    # narrate=False: the tool's return IS the human-facing message, not a log
    # string — the handoff compose LLM speaks it directly.
    assert "3" in result
    assert bs["_poi_selection_specs"] == [{"op": "keep", "n": 3, "scope": "all"}]
    assert bs["geo_result"]["pois_found"] == 3
    assert bs.get("_geo_recommit") is True
    assert bs.get("_undo_stack"), "narrow_pois must push an undo snapshot like the edit-lane path"


def test_narrow_pois_no_pois_yet():
    import asyncio

    bs = {"filled": {}, "ops_done": []}
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.narrow_pois.ainvoke({"spec": {"op": "keep", "n": 5}}))
    finally:
        _clear(token)
    assert "nothing to trim" in result


def test_undo_restores_audience_filter_specs_and_recomputes(monkeypatch):
    """The mirror of test_undo_restores_poi_selection_specs_and_refolds_the_
    superset, for audience: undo()'s docstring claimed "an audience-filter
    change" was already reverted and it was not — bs["_audience_filter_specs"]
    was never in the snapshot at all. Mocks the recompute step itself (the
    real DB round trip is covered by fold_audience_filter_specs's own tests
    plus production use) to prove undo() restores the RIGHT (popped) history
    and actually calls the recompute with it, not just the raw list."""
    import asyncio

    import app.graph.builder.builder_node as bn

    calls: list[list[dict]] = []

    async def _fake_recompute(bs_arg, state_arg, specs):
        calls.append(list(specs))
        bs_arg["geo_result"]["audience_filter"] = (
            {"min_visits": 2} if specs == [{"min_visits": 2}] else {"min_visits": 5}
        )
        return None

    monkeypatch.setattr(bn, "_recompute_audience_filter", _fake_recompute)

    bs = {
        "filled": {}, "ops_done": [],
        # Post-edit state: a SECOND, narrower patch (min_visits 5) already
        # landed on top of the snapshotted first patch (min_visits 2) —
        # undo must land back on the FIRST, same shape as the POI case.
        "_audience_filter_specs": [{"min_visits": 2}, {"min_visits": 5}],
        "geo_result": {"maid_extraction_id": "extraction-123", "audience_filter": {"min_visits": 5}},
        "_undo_stack": [{
            "filled": {}, "ops_done": [],
            "_audience_filter_specs": [{"min_visits": 2}],
        }],
    }
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert "reverted" in result
    assert bs["_audience_filter_specs"] == [{"min_visits": 2}]
    assert calls == [[{"min_visits": 2}]]
    assert bs["geo_result"]["audience_filter"] == {"min_visits": 2}


def test_undo_skips_audience_recompute_when_no_extraction_on_record():
    """No maid_extraction_id -> nothing to recompute against; the spec list
    still restores (so a LATER extraction sees the right history) but no
    recompute call is attempted."""
    import asyncio

    bs = {
        "filled": {}, "ops_done": [],
        "_audience_filter_specs": [{"min_visits": 2}, {"min_visits": 5}],
        "geo_result": {},
        "_undo_stack": [{"filled": {}, "ops_done": [], "_audience_filter_specs": [{"min_visits": 2}]}],
    }
    token = _with_state(_state(bs))
    try:
        result = asyncio.run(it.undo.ainvoke({}))
    finally:
        _clear(token)
    assert "reverted" in result
    assert bs["_audience_filter_specs"] == [{"min_visits": 2}]


def test_delegate_rest_sets_the_flag():
    bs = {}
    token = _with_state(_state(bs))
    try:
        result = it.delegate_rest.func()
    finally:
        _clear(token)
    assert bs["_auto_default_remaining"] is True
    # The safety guarantee leads; nothing implies it is ready to publish.
    assert result.startswith("nothing publishes until")
    assert "approves the final plan" in result
    assert "ready to publish" not in result.replace("Do not describe this as ready to publish.", "")


def test_abort_returns_sentinel_without_raising():
    # abort must NOT raise inside the tool call — the orchestrator (not the
    # tool) decides when to unwind the interrupt loop. See the module
    # docstring / run_handoff_turn.
    token = _with_state(_state({}))
    try:
        result = it.abort.func()
    finally:
        _clear(token)
    assert result == "__ABORT__"


def test_all_tools_registered():
    names = {t.name for t in it.HANDOFF_ALL_TOOLS}
    assert names == {
        "get_build_state", "get_pois", "get_audience",
        "retrieve_marketing_knowledge", "undo", "delegate_rest", "abort",
        "narrow_pois", "list_changeable",
    }


# ── run_handoff_turn (orchestration; the LLM passes are mocked) ─────────────

from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402


def _ai(content="", tool_calls=None):
    return SimpleNamespace(content=content, text=content, tool_calls=tool_calls or [])


def _handoff_llm(*replies):
    """Patch both LLM passes: `replies` are consumed in order by tracked_ainvoke
    (an Exception instance is raised instead of returned)."""
    effects = [r if isinstance(r, Exception) else (r, None) for r in replies]
    return (
        patch.object(it, "_make_handoff_llm", return_value=MagicMock(bind_tools=lambda _t: MagicMock())),
        patch.object(it, "tracked_ainvoke", new=AsyncMock(side_effect=effects)),
    )


async def _run(*replies):
    llm_patch, invoke_patch = _handoff_llm(*replies)
    with llm_patch, invoke_patch as invoke:
        result = await it.run_handoff_turn("what's a POI?", "geo_pois_confirmation", _state({"filled": {}}))
    return result, invoke


@pytest.mark.asyncio
async def test_handoff_no_tool_call_keeps_the_models_answer():
    # "what's a POI?" needs no tool — the prompt says so. Its answer used to be
    # discarded, leaving the user with silence and the same widget.
    result, invoke = await _run(_ai("A POI is a place worth targeting, like a gym."))
    assert result.text == "A POI is a place worth targeting, like a gym."
    assert not result.abort
    assert invoke.await_count == 1  # no compose pass without tools


@pytest.mark.asyncio
async def test_handoff_no_tool_call_and_no_text_stays_quiet():
    result, _ = await _run(_ai(""))
    assert result.text is None and not result.abort


@pytest.mark.asyncio
async def test_handoff_select_pass_timeout_is_not_silent():
    result, _ = await _run(TimeoutError())
    assert result.text == it._HANDOFF_FAILED_TEXT and not result.abort


@pytest.mark.asyncio
async def test_handoff_compose_pass_timeout_is_not_silent():
    call = {"name": "get_build_state", "args": {}, "id": "c1"}
    result, _ = await _run(_ai(tool_calls=[call]), TimeoutError())
    assert result.text == it._HANDOFF_FAILED_TEXT


@pytest.mark.asyncio
async def test_handoff_tool_error_still_reaches_compose():
    call = {"name": "get_build_state", "args": {}, "id": "c1"}
    broken = SimpleNamespace(name="get_build_state", ainvoke=AsyncMock(side_effect=RuntimeError("boom")))
    with patch.object(it, "HANDOFF_ALL_TOOLS", [broken]):
        result, invoke = await _run(_ai(tool_calls=[call]), _ai("Nothing built yet."))
    assert result.text == "Nothing built yet."
    tool_msgs = [m for m in invoke.await_args_list[1].args[1] if type(m).__name__ == "ToolMessage"]
    assert tool_msgs and tool_msgs[0].content.startswith("tool error:")


@pytest.mark.asyncio
async def test_handoff_compose_gets_the_raw_select_reply_not_a_rebuilt_one():
    # Gemini 3.x signs its function calls; a rebuilt AIMessage(tool_calls=...) drops
    # the signature and gemini-3.5-flash-lite answers 400 INVALID_ARGUMENT.
    call = {"name": "get_build_state", "args": {}, "id": "c1"}
    select = _ai(tool_calls=[call])
    result, invoke = await _run(select, _ai("Nothing built yet."))
    assert result.text == "Nothing built yet."
    assert any(m is select for m in invoke.await_args_list[1].args[1])


@pytest.mark.asyncio
async def test_handoff_abort_skips_compose_and_flags_abort():
    call = {"name": "abort", "args": {}, "id": "c1"}
    result, invoke = await _run(_ai(tool_calls=[call]))
    assert result.abort and result.text is None
    assert invoke.await_count == 1
