"""
tests/test_builder_edits.py
───────────────────────────
The mid-build edit contract: every user statement about a field resolves to
exactly one of three outcomes — COMMIT, REFUSE, or REFRAME — and never a silent
fourth.

The bug this guards: the resume router classified an edit correctly, narrated
"Updated <field> → <value>", and then the builder dropped it. Punk asserted a
change it never made and published with the old value.

Also pins the two properties that make COMMIT safe to run automatically:
  * invalidation is a `filled`-layer rollback, never a checkpoint rewind
  * it never destroys the Meta OAuth connection
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.graph.builder.edits import (
    apply_pending_edits,
    current_edit_base,
    invalidate_from,
    resolve_edit_target,
    stash_edits,
)
from app.graph.field_owner_registry import edit_block_reason
from app.graph.resume_router import ExtraEdit, ResumeIntent, ResumeResult
from app.graph.wizard_helpers import _dispatch_edit_intent


def _built_bs() -> dict:
    """A run that has finished geo + maid + campaign and is sitting on media."""
    return {
        "ops_done": sorted([
            "connect_meta", "enrich_website", "geo_discover", "maid_query",
            "generate_brief", "resolve_meta", "generate_meta_json",
        ]),
        "stages_complete": ["campaign", "geo", "maid"],
        "filled": {
            "location_scope": "granular_local",
            "locations": "Montreal",
            "det_type": "category",
            "poi_types": "coffee shop",
            "poi_confirm": "yes",
            "poi_radius_m": "500",
            "lookback_days": "7",
            "maid_confirm": "yes",
            "publish_mode": "guide",
            "campaign_intake": "done",
            "business_name": "PunkBakery",
        },
        "geo_result": {"pois_found": 12},
        "geo_ws": {"_locations_synced": ["Montreal"]},
        "brief": {"headline": "old"},
        "marketing_plan": {"name": "C"},
        "media_ws": {"access_token": "SECRET", "ad_account_id": "act_1", "pixel_id": "9"},
        "iteration": 12,
    }


# ── COMMIT ────────────────────────────────────────────────────────────────────


def test_geo_edit_commits_and_invalidates_downstream():
    """'also target Laval' after discovery rewrites the slot AND drops the work
    derived from the old value, so the planner rebuilds instead of publishing a
    campaign whose POIs never included Laval."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("500", edits={"location": ["Montreal", "Laval"]}))

    ui_patch, rolled_back, note = apply_pending_edits(bs)

    assert bs["filled"]["locations"] == "Montreal, Laval"
    assert ui_patch == {"location": ["Montreal", "Laval"]}
    assert rolled_back == ["geo", "maid", "campaign", "media"]
    # The derived work is gone, so _next_step re-schedules it.
    assert "geo_discover" not in bs["ops_done"]
    assert "maid_query" not in bs["ops_done"]
    assert "generate_meta_json" not in bs["ops_done"]
    # Confirmation gates for the rolled-back stages must be re-asked.
    assert "poi_confirm" not in bs["filled"]
    assert "maid_confirm" not in bs["filled"]
    # Stale artifacts cleared — _builder_geo falls back to geo_result.
    assert "geo_result" not in bs and "marketing_plan" not in bs
    assert bs["stages_complete"] == []
    assert "Laval" in note


def test_commit_never_destroys_the_meta_connection():
    """A geo edit must not cost the user their OAuth. connect_meta is a pre-act
    and media_ws holds the token / account / pixel it resolved."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"location": "Toronto"}))
    apply_pending_edits(bs)

    assert bs["media_ws"] == {
        "access_token": "SECRET", "ad_account_id": "act_1", "pixel_id": "9",
    }
    assert "connect_meta" in bs["ops_done"]
    assert "enrich_website" in bs["ops_done"]


def test_commit_resets_the_iteration_budget():
    """_MAX_PLAN_ITERATIONS exists to stop a planner livelock. A livelock cannot
    happen across an edit (each costs a real user turn), and without the reset a
    user who changes their mind a few times kills the build permanently."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"location": "Toronto"}))
    apply_pending_edits(bs)
    assert bs["iteration"] == 0


def test_executor_edits_are_swept_from_ws():
    """Executors inside builder_act hold only a `ws`, which rides out to bs under
    geo_ws / maid_ws / media_ws. Sweeping those means no return path in
    builder_act has to know edits exist."""
    bs = _built_bs()
    bs["geo_ws"] = dict(bs["geo_ws"])
    stash_edits(bs["geo_ws"], ResumeResult("x", edits={"poi_types": "gym"}))

    _ui, rolled_back, note = apply_pending_edits(bs)

    assert bs["filled"]["poi_types"] == "gym"
    assert rolled_back and rolled_back[0] == "geo"
    assert note is not None


def test_ambiguous_alias_resolves_by_active_route():
    """search_radius_km is the prefill_key of BOTH radius_km and
    competitor_radius_km; only one applies in a given run."""
    assert resolve_edit_target(
        "search_radius_km", {"det_type": "competitor_nearby"}
    ) == "competitor_radius_km"
    assert resolve_edit_target(
        "search_radius_km", {"location_scope": "radius"}
    ) == "radius_km"


def test_commit_pushes_an_undo_snapshot():
    """`undo` pops this stack — a real commit must leave the PRE-edit filled
    behind, plus the unit it invalidated (v2: undo is an inverse edit that
    re-invalidates, never a restore of ops_done whose outputs were popped)."""
    bs = _built_bs()
    pre_filled = dict(bs["filled"])
    stash_edits(bs, ResumeResult("x", edits={"location": "Toronto"}))
    apply_pending_edits(bs)

    stack = bs.get("_undo_stack") or []
    assert len(stack) == 1
    assert stack[-1]["v"] == 2
    assert stack[-1]["filled"] == pre_filled
    assert stack[-1]["unit"] == "geocode"
    assert "ops_done" not in stack[-1]


def test_undo_stack_is_bounded():
    """A long, much-revised build must not grow this unboundedly."""
    from app.graph.builder.edits import _UNDO_STACK_MAX

    bs = _built_bs()
    for i in range(_UNDO_STACK_MAX + 5):
        stash_edits(bs, ResumeResult("x", edits={"location": f"City{i}"}))
        apply_pending_edits(bs)
    assert len(bs["_undo_stack"]) == _UNDO_STACK_MAX


def test_noop_pending_pushes_no_undo_snapshot():
    """A pending bucket that resolves to nothing applied (e.g. every field
    unknown) must not leave a fake undo point behind."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"totally_unknown_field": "x"}))
    apply_pending_edits(bs)
    assert not bs.get("_undo_stack")


def test_nothing_stashed_is_a_no_op():
    """The happy path must not allocate or invalidate."""
    bs = _built_bs()
    before = dict(bs)
    assert apply_pending_edits(bs) == ({}, [], None)
    assert bs["ops_done"] == before["ops_done"]
    assert bs["stages_complete"] == before["stages_complete"]


def test_invalidation_is_not_a_checkpoint_rewind():
    """The 2026-06 design forked the checkpoint and lost every slot filled after
    the target. This one rewrites `filled` in place, so answers the user already
    gave for OTHER slots survive."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"location": "Laval"}))
    apply_pending_edits(bs)

    for slot, value in (
        ("det_type", "category"), ("poi_types", "coffee shop"),
        ("poi_radius_m", "500"), ("lookback_days", "7"),
        ("publish_mode", "guide"), ("business_name", "PunkBakery"),
    ):
        assert bs["filled"][slot] == value, f"{slot} was discarded by the rollback"


# ── REFUSE ────────────────────────────────────────────────────────────────────


_SPEC_BUILT = {"campaign_builder_state": {"ops_done": ["generate_meta_json"]}}


@pytest.mark.parametrize("field,state,expected", [
    # (A) a real control exists in the plan editor
    ("target_age_min", _SPEC_BUILT, "plan_editor"),
    ("pixel_id", _SPEC_BUILT, "plan_editor"),
    ("campaign_start_date", _SPEC_BUILT, "plan_editor"),
    # (B) no control, and no writeback if there were — saying "change it in the
    # editor" sends the user to look for a field that is not there.
    # budget IS adjustable, just as a real amount per ad set rather than the
    # free-text figure from intake — so it gets its own copy, not "I can't".
    ("budget", _SPEC_BUILT, "budget_in_plan"),
    ("pixel_status", _SPEC_BUILT, "not_in_editor"),
    ("campaign_objective", _SPEC_BUILT, "plan_editor"),   # real control in the editor
    # The campaign exists in Meta but builder_finalize has not copied the ids
    # up yet — the go_live_confirm gate pauses in exactly this window.
    ("location",
     {"campaign_builder_state": {"ops_done": ["publish"],
                                 "meta_campaign_ids": {"campaign_id": "1"}}},
     "published"),
    ("campaign_publish_mode", _SPEC_BUILT, "mode_locked"),
    # (C) prompt-only inputs that shaped the copy → commit + redraft
    ("target_audience", _SPEC_BUILT, "redraft"),
    ("business_description", _SPEC_BUILT, "redraft"),
    # before the spec exists everything commits normally
    ("budget", {"campaign_builder_state": {"ops_done": ["generate_brief"]}}, None),
    ("target_audience", {"campaign_builder_state": {"ops_done": []}}, None),
    ("meta_page_id", {"campaign_builder_state": {"ops_done": []}}, "meta_account"),
    ("location", {"meta_campaign_ids": {"campaign_id": "1"}}, "published"),
    ("location", {"wizards_completed": {"geo"}}, "locked"),
    ("location", {"campaign_builder_state": {"ops_done": ["geo_discover"]}}, None),
    ("not_a_field", {}, None),
])
def test_edit_admissibility(field, state, expected):
    assert edit_block_reason(field, state) == expected


def test_every_post_spec_route_has_a_message():
    """A route with no copy would surface as a KeyError mid-conversation."""
    from app.graph.field_owner_registry import (
        EDIT_BLOCK_MESSAGES, _POST_SPEC_ROUTE,
    )
    for field, route in _POST_SPEC_ROUTE.items():
        if route == "redraft":
            continue          # redraft acts, it does not print a refusal
        assert route in EDIT_BLOCK_MESSAGES, f"{field} → {route} has no message"


def test_mid_build_edit_is_admissible_even_though_stage_is_complete():
    """Regression: is_completed_owner reads wizards_completed, which only
    builder_finalize writes. Mid-build it is empty, so the old locked-refusal
    branch was unreachable AND the edit was dropped — no apply, no refusal."""
    state = {"campaign_builder_state": {"ops_done": ["geo_discover", "maid_query"]},
             "wizards_completed": set()}
    assert edit_block_reason("location", state) is None


@pytest.mark.asyncio
async def test_refused_edit_never_acknowledges_and_never_mutates():
    """The core lie: an ack for a change that will not happen."""
    events: list[dict] = []
    state = {"campaign_builder_state": {"ops_done": ["generate_meta_json"]}}
    pending: dict = {"prefill": None}
    edits: dict = {}

    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="target_age_min",
                            new_value="30", confidence=0.99),
        state=state, writer=events.append, pending=pending,
        cfg={"field": "maid_poi_radius"}, edits=edits,
    )

    assert reframe is False           # the refusal copy steers back on its own
    assert edits == {"_reopen_plan": True}
    assert "target_age_min" not in edits
    assert any("REFUSED (plan_editor)" in str(e.get("content", "")) for e in events)


# ── REFRAME ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_edit_reframes_instead_of_rebuilding():
    """A COMMIT re-runs a POI search and a warehouse query. The 2026-06 router
    had no confidence floor and auto-rewound on any is_append, which is what got
    it removed."""
    events: list[dict] = []
    pending: dict = {"prefill": "Montreal"}
    edits: dict = {}

    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="location",
                            new_value="catering", is_append=True, confidence=0.2),
        state={"campaign_builder_state": {"ops_done": ["geo_discover"]}},
        writer=events.append, pending=pending,
        cfg={"field": "maid_poi_radius"}, edits=edits,
    )

    assert reframe is True            # caller must not re-ask silently
    assert edits == {}                # nothing to commit
    assert any("below confidence floor" in str(e.get("content", "")) for e in events)


@pytest.mark.asyncio
async def test_cost_bearing_field_needs_a_higher_floor_than_the_global_default():
    """poi_radius_m re-buys live Unacast vendor data on commit — a confidence
    that clears the plain global floor (0.7) but not the field's raised one
    must still reframe, not spend shared monthly call budget on a guess."""
    events: list[dict] = []
    edits: dict = {}

    assert 0.7 < 0.72 < settings.RESUME_EDIT_MIN_CONFIDENCE + 0.1

    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="poi_radius_m",
                            new_value="1000", confidence=0.72),
        state={"campaign_builder_state": {"ops_done": ["geo_discover", "maid_query"]}},
        writer=events.append, pending={"prefill": "500"},
        cfg={"field": "maid_poi_radius"}, edits=edits,
    )

    assert reframe is True
    assert edits == {}
    assert any("below confidence floor" in str(e.get("content", "")) for e in events)


@pytest.mark.asyncio
async def test_non_cost_bearing_field_keeps_the_plain_global_floor():
    """The same confidence that reframes poi_radius_m above must still commit
    a field the raised floor does not apply to — the margin is additive to
    specific fields, not a global tightening."""
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="business_name",
                            new_value="PunkBakery", confidence=0.72),
        state={"campaign_builder_state": {"ops_done": []}},
        writer=lambda _e: None, pending={}, cfg={"field": "maid_poi_radius"},
        edits=edits,
    )
    assert reframe is False
    assert edits.get("business_name") == "PunkBakery"


# ── backtrack ("go back to X") ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_target_step_key_becomes_a_restart_directive():
    """ResumeIntent.target_step_key has existed since 2026-05 and nothing ever
    consumed it, so an explicit backtrack request did nothing."""
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="geo_locations",
                            target_step_key="geo_collect_locations", confidence=0.9),
        state={"campaign_builder_state": {"ops_done": ["geo_discover"]}},
        writer=lambda _e: None, pending={}, cfg={"field": "maid_poi_radius"},
        edits=edits,
    )
    assert reframe is False
    assert edits["_restart_step"] == "geo_collect_locations"


def test_restart_clears_only_its_own_slot():
    """A backtrack must re-ask ONE step. The 2026-06 rewind forked the checkpoint
    and lost every slot filled after the target, so the builder re-asked them
    all — the loop-back that got it removed."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"_restart_step": "geo_collect_locations"}))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert "locations" not in bs["filled"]        # re-asked
    assert bs["filled"]["det_type"] == "category"  # survives
    assert bs["filled"]["poi_radius_m"] == "500"   # survives
    assert bs["filled"]["publish_mode"] == "guide"  # survives
    assert rolled_back == ["geo", "maid", "campaign", "media"]


# ── escape menu ───────────────────────────────────────────────────────────────


def test_escape_menu_matches_exactly_only():
    """The menu is attached to pending at iteration >= 2 but nothing read it back:
    the short-circuit above it checks pending["options"] only, so pressing
    "exit wizard" just burned another iteration toward the budget it escapes.

    Matching must stay exact — "explain" is a plausible free-text answer and
    hijacking it would be worse than missing the shortcut, since the query lane
    already handles that phrasing."""
    from app.graph.wizard_helpers import _match_escape

    menu = ["use default", "explain", "exit wizard"]
    assert _match_escape("exit wizard", menu) == "exit wizard"
    assert _match_escape("  Exit Wizard  ", menu) == "exit wizard"
    assert _match_escape("use default", menu) == "use default"
    # Not exact → falls through to the classifier, as before.
    assert _match_escape("please exit the wizard", menu) is None
    assert _match_escape("explain this to me", menu) is None
    assert _match_escape("Montreal", menu) is None
    assert _match_escape("exit wizard", None) is None


@pytest.mark.asyncio
async def test_confident_edit_above_the_floor_still_commits():
    """The floor must cost a genuine edit nothing."""
    assert settings.RESUME_EDIT_MIN_CONFIDENCE <= 0.95
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="location",
                            new_value="Laval", is_append=True, confidence=0.95),
        state={"campaign_builder_state": {"ops_done": ["geo_discover"]}},
        writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "maid_poi_radius"}, edits=edits,
        edit_base={"location": ["Montreal"]},
    )
    assert reframe is False
    assert edits["location"] == ["Montreal", "Laval"]


# ── the build must survive a confused user ────────────────────────────────────


@pytest.mark.asyncio
async def test_off_path_exit_preserves_the_whole_build(monkeypatch):
    """_MAX_NONANSWER_LOOPS off-path replies raised WizardExitRequested and
    builder_ask returned campaign_builder_state=None. `_bs` is a shallow copy,
    so that diff was the only thing persisting the scratch: every answered slot,
    the discovered POIs, the audience, the brief and the plan were destroyed
    because the user got confused eight times."""
    from app.graph.builder import builder_node as bn
    from app.graph.wizard_exit import WizardExitRequested

    bs = _built_bs()
    bs["next_action"] = {"kind": "ask", "slot": "poi_radius_m"}
    state = {"campaign_builder_state": bs, "user_info": {}, "pending_action": None}

    async def _boom(*_a, **_k):
        raise WizardExitRequested()

    monkeypatch.setattr(bn, "wizard_interrupt", _boom)
    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _e: None))
    monkeypatch.setattr(bn, "_enrich_slot_ask", lambda *_a, **_k: _async_empty())

    out = await bn.builder_ask(state)

    assert out["wizard_failure"] == "user_exit"
    assert out["next_nodes"] == ["chatbot"]
    kept = out["campaign_builder_state"]
    assert kept is not None, "the entire build was thrown away"
    assert kept["filled"]["locations"] == "Montreal"
    assert kept["filled"]["business_name"] == "PunkBakery"
    assert "geo_discover" in kept["ops_done"]
    assert kept["marketing_plan"] == {"name": "C"}
    assert kept["media_ws"]["access_token"] == "SECRET"
    # Cleared so the planner re-plans instead of re-entering the same ask.
    assert kept["next_action"] is None


async def _async_empty() -> dict:
    return {}


def test_escape_beats_the_fuzzy_option_matcher():
    """Ordering matters: resolve_option is fuzzy and runs on every reply. If it
    got first look it could match "exit wizard" onto a real option and swallow
    the escape. The escape check is exact, so it goes first."""
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "graph" / "wizard_helpers.py"
    ).read_text(encoding="utf-8")
    assert src.index("# Escape-menu short-circuit") < src.index("# Option-click short-circuit")


def test_stuck_user_has_a_complete_way_out():
    """The recovery loop must be closed end to end. Each link was individually
    broken before: the menu rendered nowhere, "exit wizard" was wired to nothing,
    the exit destroyed the build, the failure code had no message, and entry
    could not route back in."""
    from app.graph.field_owner_registry import EDIT_BLOCK_MESSAGES  # noqa: F401
    from app.graph.nodes import EntryRouting
    from app.graph.wizard_helpers import _ESCAPE_MENU_THRESHOLD, _match_escape

    # 1. the menu appears while there is still loop budget left to use it
    from app.graph.wizard_helpers import _MAX_NONANSWER_LOOPS
    assert _ESCAPE_MENU_THRESHOLD < _MAX_NONANSWER_LOOPS

    # 2. pressing it is recognised
    assert _match_escape("exit wizard", ["use default", "explain", "exit wizard"])

    # 3. the failure code the exit sets has real copy, not an improvised token
    src = (Path(__file__).resolve().parents[1] / "app" / "graph" / "nodes.py").read_text(
        encoding="utf-8"
    )
    assert '"user_exit": (' in src

    # 4. entry can route back into the paused build
    assert "campaign_builder" in EntryRouting.model_fields["route"].annotation.__args__



# ── Round 2: appends must not truncate ────────────────────────────────────────


def test_current_edit_base_reads_the_list_not_the_joined_string():
    """`filled` stores ", ".join(...), which is already ambiguous — "New York, NY"
    cannot be told apart from two places. user_info keeps the real list, and
    _slot_user_info_patch deliberately never stomps it."""
    state = {"user_info": {"location": ["New York, NY", "Boston"]}}
    bs = {"filled": {"locations": "New York, NY, Boston"}}
    assert current_edit_base(state, bs)["location"] == ["New York, NY", "Boston"]


@pytest.mark.asyncio
async def test_append_keeps_what_was_already_there():
    """REGRESSION (round 1): edit_base was only passed by the two geo confirm
    sites, so at a builder_ask interrupt the merge ran [] + ["Toronto"] and
    "also add Toronto" REPLACED Montreal. Inert before the commit path existed;
    destructive after it."""
    state = {"user_info": {"location": ["Montreal"]},
             "campaign_builder_state": {"ops_done": ["geo_discover"]}}
    bs = {"filled": {"locations": "Montreal", "det_type": "category"}}
    edits: dict = {}

    await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="location",
                            new_value="Toronto", is_append=True, confidence=0.95),
        state=state, writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "maid_poi_radius"}, edits=edits,
        edit_base=current_edit_base(state, bs),
    )
    assert edits["location"] == ["Montreal", "Toronto"]


# ── Round 2: combining targeting angles ───────────────────────────────────────


def test_angle_tokens_union_rather_than_replace():
    from app.graph.builder.slots import merge_angle_tokens

    assert merge_angle_tokens("category", ["competitor_brand"]) == "category,competitor_brand"
    assert merge_angle_tokens("category,event_based", "category") == "category,event_based"
    assert merge_angle_tokens(["", None]) == ""          # str(None) must not become "none"


def test_angles_are_appendable():
    """Without this resume_router force-collapses is_append→False and "also target
    near Starbucks" SWAPS the angle instead of adding it."""
    from app.graph.field_owner_registry import APPENDABLE_FIELDS

    assert "deterministic_subtype" in APPENDABLE_FIELDS
    assert "geo_deterministic_type" in APPENDABLE_FIELDS


def test_adding_an_angle_activates_its_slots_and_reruns_discovery():
    """The whole point: a combined set must actually RUN the new arm. Before this,
    brand_names was written, geo rebuilt, and the brands ignored because det_type
    was still `category`."""
    bs = _built_bs()
    bs["filled"]["det_type"] = "category"
    stash_edits(bs, ResumeResult("x", edits={
        "deterministic_subtype": ["category", "competitor_brand"],
    }))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert bs["filled"]["det_type"] == "category,competitor_brand"
    # the new angle's collection slot is now scheduled...
    from app.graph.builder.slots import missing_required_slots
    assert [s.name for s in missing_required_slots("geo", bs["filled"])] == ["brand_names"]
    # ...and discovery re-runs, so the arm is actually executed
    assert "geo_discover" not in bs["ops_done"]
    assert rolled_back[0] == "geo"


def test_det_type_edit_never_amputates_an_angle_already_running():
    """Regression for thread b1e1fd10-24c7-439b-92ea-ee3a68bce94f: "also target
    pet stores" paired an extra_edit of {"deterministic_subtype":"category"} —
    just the ONE new token, not unioned against what's already running (the
    wizard_helpers append-merge that's SUPPOSED to do that union depends on
    edit_base/is_append landing correctly, which is exactly what broke live).
    Before this fix, apply_pending_edits took that bare value at face value and
    det_type silently lost "competitor_brand" — the PetSmart brand arm stopped
    running with no error anywhere."""
    bs = _built_bs()
    bs["filled"]["det_type"] = "category,competitor_brand"
    stash_edits(bs, ResumeResult("x", edits={"deterministic_subtype": "category"}))

    apply_pending_edits(bs)

    assert "competitor_brand" in bs["filled"]["det_type"].split(",")
    assert "category" in bs["filled"]["det_type"].split(",")


def test_naming_a_leaf_value_activates_its_own_angle():
    """'target Boustan, Sparta' at the POI-confirm gate — the classifier's most
    natural reading names the LEAF field (competitor_brands), not the angle
    token. Before this, resolve_edit_target's `return candidates[0]` fallback
    wrote brand_names anyway while det_type stayed unchanged, geo rebuilt on
    byte-identical inputs (the competitor_brand arm never reads brand_names_list
    unless it's in subtype_set), and the names sat in `filled` forever because
    missing_required_slots also skips an inapplicable slot."""
    bs = _built_bs()
    assert bs["filled"]["det_type"] == "category"       # no competitor_brand yet
    stash_edits(bs, ResumeResult("x", edits={
        "competitor_brands": ["Boustan", "Sparta"],
    }))

    ui_patch, rolled_back, _note = apply_pending_edits(bs)

    assert bs["filled"]["det_type"] == "category,competitor_brand"
    assert bs["filled"]["brand_names"] == "Boustan, Sparta"
    assert ui_patch["deterministic_subtype"] == ["category", "competitor_brand"]
    # the leaf is committed in the SAME pass — no re-ask
    from app.graph.builder.slots import missing_required_slots
    assert "brand_names" not in [s.name for s in missing_required_slots("geo", bs["filled"])]
    assert "geo_discover" not in bs["ops_done"]
    assert rolled_back[0] == "geo"


@pytest.mark.parametrize("field,slot_name,angle", [
    ("named_places", "named_places", "named_places"),
    ("poi_types", "poi_types", "category"),
])
def test_naming_other_leaf_fields_also_activates_their_angle(field, slot_name, angle):
    bs = _built_bs()
    bs["filled"]["det_type"] = "event_based"            # neither angle active
    stash_edits(bs, ResumeResult("x", edits={field: "Fight Club"}))

    apply_pending_edits(bs)

    assert angle in bs["filled"]["det_type"].split(",")
    assert bs["filled"][slot_name] == "Fight Club"


def test_ambiguous_alias_does_not_guess_an_angle():
    """search_radius_km aliases to BOTH radius_km and competitor_radius_km —
    inferring competitor_nearby from a bare radius change would be a guess this
    mechanism has no business making."""
    bs = _built_bs()
    bs["filled"]["det_type"] = "category"
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "2"}))

    apply_pending_edits(bs)

    assert bs["filled"]["det_type"] == "category"        # unchanged


def test_event_based_check_is_set_aware():
    """`== "event_based"` failed for "event_based,named_places" and only worked by
    accident, via a substring test on targeting_type."""
    import inspect
    from app.graph.builder import builder_node as bn

    src = inspect.getsource(bn.builder_act)
    assert '== "event_based"' not in src
    assert '"event_based" in _det_tokens' in src


# ── Round 2: redraft keeps the user's plan ────────────────────────────────────


def test_redraft_reruns_the_brief_without_deleting_the_plan():
    """target_audience has no editor control and never reaches the Meta spec, so a
    post-spec change must redraft the copy. It must NOT go through
    invalidate_from("campaign"), which pops marketing_plan and would delete the
    user's whole editor tree over a wording change."""
    from app.graph.builder.edits import refresh_copy

    bs = _built_bs()
    filled = bs["filled"]
    refresh_copy(bs, filled)

    assert "generate_brief" not in bs["ops_done"]      # brief re-runs
    assert "generate_meta_json" in bs["ops_done"]      # spec is NOT rebuilt
    assert bs["marketing_plan"] == {"name": "C"}       # the user's tree survives
    assert bs["_copy_refresh"] is True                 # one-shot suggestion refresh
    assert "plan_confirm" not in filled                # editor reopens
    assert "campaign" not in bs["stages_complete"]


@pytest.mark.asyncio
async def test_redraft_signal_carries_the_new_value():
    """The value must land in user_info — generate_campaign_brief reads nothing
    else, so without it the re-run would redraft from the OLD audience."""
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="target_audience",
                            new_value="young professionals", confidence=0.95),
        state=_SPEC_BUILT, writer=lambda _e: None, pending={},
        cfg={"field": "maid_poi_radius"}, edits=edits,
    )
    assert reframe is False
    assert edits["_redraft"] == {"target_audience": "young professionals"}
    assert "_reopen_plan" not in edits


# ── Round 3: gaps found by auditing the round-2 fix ───────────────────────────


def test_published_guard_covers_the_pre_finalize_window():
    """`publish` writes bs["meta_campaign_ids"]; only builder_finalize copies it
    to AgentState — and the go_live_confirm gate INTERRUPTS in between. At that
    pause the campaign exists in Meta (paused) while AgentState looks unpublished,
    so an edit sailed past the guard, invalidate_from dropped publish+activate,
    and the builder would publish a SECOND campaign."""
    mid_publish = {"campaign_builder_state": {
        "ops_done": ["publish"], "meta_campaign_ids": {"campaign_id": "120x"}}}
    assert edit_block_reason("location", mid_publish) == "published"
    assert edit_block_reason("poi_radius_m", mid_publish) == "published"


def test_every_interrupt_site_stashes_its_edits():
    """The round-1 bug was 'the caller never reads .edits'. Round 2 fixed only
    builder_ask, leaving 7 executor sites still acking and dropping."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "graph"
    files = [
        root / "builder" / "builder_node.py",
        root / "builder" / "executors" / "geo.py",
        root / "builder" / "executors" / "media.py",
    ]
    calls = stashes = 0
    for f in files:
        src = f.read_text(encoding="utf-8")
        calls += len(re.findall(r"await wizard_interrupt\(", src))
        stashes += len(re.findall(r"stash_edits\(", src)) - src.count("def stash_edits")
    # 9: the ninth is media_check_meta_auth's "connected but no ad account" re-ask.
    assert calls == 9, f"expected 9 interrupt sites, found {calls}"
    assert stashes >= calls, f"{calls} interrupt sites but only {stashes} stash their edits"


@pytest.mark.asyncio
async def test_compound_edit_applies_every_field():
    """A single target_field meant 'change my budget AND add Toronto' silently
    dropped one of the two — squarely the confuse-Punk case."""
    from app.graph.resume_router import ExtraEdit

    edits: dict = {}
    await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_field="poi_radius_m", new_value="1000", confidence=0.95,
            extra_edits=[
                ExtraEdit(target_field="location", new_value="Toronto", is_append=True),
                ExtraEdit(target_field="lookback_days", new_value="30"),
            ],
        ),
        state={"campaign_builder_state": {"ops_done": ["geo_discover"]}},
        writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "maid_lookback"}, edits=edits,
        edit_base={"location": ["Montreal"]},
    )
    assert edits["poi_radius_m"] == "1000"
    assert edits["location"] == ["Montreal", "Toronto"]
    assert edits["lookback_days"] == "30"


@pytest.mark.asyncio
async def test_compound_edit_still_refuses_the_inadmissible_half():
    """Each extra edit goes through the SAME admissibility check — a compound
    reply must not smuggle a refused field in beside an allowed one."""
    from app.graph.resume_router import ExtraEdit

    edits: dict = {}
    await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_field="poi_radius_m", new_value="1000", confidence=0.95,
            extra_edits=[ExtraEdit(target_field="meta_page_id", new_value="999")],
        ),
        state={"campaign_builder_state": {"ops_done": ["geo_discover"]}},
        writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "maid_lookback"}, edits=edits,
    )
    assert edits["poi_radius_m"] == "1000"
    assert "meta_page_id" not in edits      # refused as meta_account


def test_every_advertised_classifier_field_resolves_or_is_refused():
    """A field the prompt offers but nothing can act on collapses to the reject
    lane, so "change my targeting method" reads as a refusal to answer.

    Two-directional, both halves load-bearing:
      1. every field named in the generated KNOWN EDITABLE FIELDS block must
         satisfy `is_actionable_field` — the SAME predicate the router's own
         admissibility gate uses (resume_router._validate_edit_target), so
         this is now near-tautological BY CONSTRUCTION (the block is derived
         from the registries, not hand-copied prose) and tests the generator,
         not a human's diligence keeping two lists in sync.
      2. the reverse: no worked example may hand the model a non-actionable
         field as a `target_field` to EMIT — catches a human writing an
         orphan field (e.g. a deleted `geo_map_selection`) into a worked
         example's output by hand, which the derived-block check alone can't
         see. Scoped to `"target_field":"X"` occurrences specifically, not
         any bare mention of the name — a step_key is legitimately named in
         scene-setting prose ("Step: geo_location_confirmation (...)") and in
         the STEPS YOU CAN GO BACK TO list without ever being an edit target.
    """
    import re
    from app.graph.builder.edits import is_actionable_field
    from app.graph.resume_router import _classifier_prompt

    prompt = _classifier_prompt()
    block = prompt.split("KNOWN EDITABLE FIELDS")[1].split("APPEND-ABLE")[0]
    noise = {"geo", "campaign", "media", "maid", "use", "these", "exact", "names", "as",
             "target_field"}
    advertised = {f for f in re.findall(r"[a-z_]{4,}", block)} - noise
    orphans = [f for f in sorted(advertised) if not is_actionable_field(f)]
    assert not orphans, f"classifier advertises unusable fields: {orphans}"

    emitted = set(re.findall(r'"target_field"\s*:\s*"([a-z_]+)"', prompt))
    leaked = sorted(f for f in emitted if f and not is_actionable_field(f))
    assert not leaked, f"a worked example emits a non-actionable target_field: {leaked}"


# ── Regressions: the three holes the mechanism review found ───────────────────


@pytest.mark.asyncio
async def test_backtrack_is_judged_by_the_same_guard_as_an_edit():
    """A backtrack carries `target_step_key` and NO `target_field`, and
    `edit_block_reason(None, ...)` is None — so "take me back to where I picked
    locations" at the go_live gate sailed past the `published` guard,
    invalidate_from dropped publish + activate, and the builder published a
    SECOND campaign into Meta. The step resolves to the field it collects."""
    published = {"campaign_builder_state": {
        "ops_done": ["publish"], "meta_campaign_ids": {"campaign_id": "120x"}}}
    edits: dict = {}
    said: list = []

    intent = ResumeIntent(
        lane="edit", target_step_key="geo_collect_locations", confidence=0.99,
    )
    await _dispatch_edit_intent(
        intent=intent, state=published, writer=lambda e: said.append(e),
        pending={}, cfg={"field": "meta_go_live_confirm"}, edits=edits,
    )
    assert "_restart_step" not in edits, "a published build must not be rewound"
    assert any("REFUSED (published)" in str(e.get("content", "")) for e in said)


@pytest.mark.asyncio
async def test_backtrack_still_works_while_the_build_is_live():
    """The guard must not swallow the legitimate case it was added around."""
    mid_build = {"campaign_builder_state": {"ops_done": ["geo_discover"]}}
    edits: dict = {}
    await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_step_key="geo_collect_locations", confidence=0.99),
        state=mid_build, writer=lambda _e: None,
        pending={}, cfg={"field": "geo_poi_types"}, edits=edits,
    )
    assert edits["_restart_step"] == "geo_collect_locations"


def test_control_keys_survive_a_stash_onto_an_executor_ws():
    """7 of the 8 interrupt sites live inside builder_act and stash onto a `ws`.
    builder_plan read control keys off bs["_pending_edits"] only, so a refused
    campaign edit typed at the pixel picker was acked ("I've reopened the editor
    below") and then skipped by the field loop as a _CONTROL_KEY — dropped."""
    from app.graph.builder.edits import collect_pending

    bs = _built_bs()
    bs["media_ws"] = dict(bs["media_ws"])
    stash_edits(bs["media_ws"], ResumeResult("x", edits={"_reopen_plan": True}))

    pending = collect_pending(bs)
    assert pending.get("_reopen_plan") is True, "control key lost between ws and plan"
    assert bs["media_ws"].get("_pending_edits") is None, "ws bucket not cleared"

    # What builder_plan does with it, then the ordinary commit drain.
    pending.pop("_reopen_plan")
    assert apply_pending_edits(bs) == ({}, [], None)


def test_collect_pending_keeps_a_restart_and_a_field_together():
    """_drain pops the restart key out of the bucket; collect_pending has to put
    it back or a backtrack raised at an executor site is lost the same way."""
    from app.graph.builder.edits import collect_pending

    bs = _built_bs()
    bs["geo_ws"] = dict(bs["geo_ws"])
    stash_edits(bs["geo_ws"], ResumeResult(
        "x", edits={"_restart_step": "geo_collect_locations", "poi_types": "gyms"}))

    pending = collect_pending(bs)
    assert pending["_restart_step"] == "geo_collect_locations"
    assert pending["poi_types"] == "gyms"

    _ui, rolled_back, note = apply_pending_edits(bs)
    assert "locations" not in bs["filled"]          # restart cleared its slot
    assert bs["filled"]["poi_types"] == "gyms"      # and the field still landed
    assert rolled_back and rolled_back[0] == "geo"


def test_builder_plan_reads_the_consolidated_bucket():
    """The unit tests above cover `collect_pending`; this pins the WIRING, which
    is where the bug actually lived — builder_plan reached into
    bs["_pending_edits"] directly and so never saw a ws-stashed control key."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "graph" / "builder"
           / "builder_node.py").read_text(encoding="utf-8")
    assert "collect_pending(bs)" in src, "builder_plan must sweep the ws buckets"
    assert 'bs.get("_pending_edits")' not in src, (
        "reading the bs bucket directly misses every executor-site stash"
    )


# ── Round 4: gaps found by the second unhappy-path review ─────────────────────


@pytest.mark.asyncio
async def test_redraft_merges_two_fields_in_one_reply():
    """'rename the business and tweak the offer' redrafts TWO prompt-only fields.
    A plain `edits["_redraft"] = {...}` assignment (rather than a merge) kept only
    the second — the extra_edits recursion applies each independently, so the dict
    they write into has to accumulate, not clobber."""
    from app.graph.resume_router import ExtraEdit

    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_field="target_audience", new_value="young professionals",
            confidence=0.95,
            extra_edits=[ExtraEdit(target_field="business_description",
                                    new_value="artisan bakery")],
        ),
        state=_SPEC_BUILT, writer=lambda _e: None, pending={}, cfg={"field": "maid_poi_radius"},
        edits=edits,
    )
    assert reframe is False
    assert edits["_redraft"] == {
        "target_audience": "young professionals",
        "business_description": "artisan bakery",
    }


@pytest.mark.asyncio
async def test_backtrack_with_a_co_emitted_value_commits_instead_of_restarting():
    """'go back to locations, use Toronto' names a step AND gives a value — that
    is an edit, not a bare backtrack. Restarting on target_step_key alone would
    ack 'Toronto' and then blank the slot instead of writing it."""
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="business_name",
                            new_value="Toronto", target_step_key="geo_collect_locations",
                            confidence=0.9),
        state={"campaign_builder_state": {"ops_done": ["geo_discover"]}},
        writer=lambda _e: None, pending={}, cfg={"field": "maid_poi_radius"},
        edits=edits,
    )
    assert reframe is False
    assert edits.get("business_name") == "Toronto"
    assert "_restart_step" not in edits


def test_anchor_confirm_stash_excludes_only_the_anchor_fields():
    """The anchor-confirm branch applies store_addresses / competitor_anchor
    itself via a targeted re-geocode; every OTHER field must still reach
    apply_pending_edits, or a co-emitted edit ('add this store AND change my
    budget') is acked for the budget half and then silently dropped."""
    from app.graph.builder.builder_node import _ANCHOR_OWNED_FIELDS
    from app.graph.builder.edits import collect_pending

    bs = _built_bs()
    result = ResumeResult("x", edits={
        "competitor_anchor": "400 Rue Wellington",   # owned — branch applies this itself
        "budget": "$500/day",                        # not owned — must reach the commit path
    })
    stash_edits(bs, result, exclude=_ANCHOR_OWNED_FIELDS)

    pending = collect_pending(bs)
    assert pending.get("budget") == "$500/day"
    assert "competitor_anchor" not in pending


@pytest.mark.asyncio
async def test_redraft_below_confidence_floor_reframes_without_committing():
    """The floor used to sit below the block-reason branch, so a low-confidence
    reply classified as a redraft skipped it entirely and committed anyway."""
    events: list[dict] = []
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(lane="edit", target_field="target_audience",
                            new_value="young professionals", confidence=0.3),
        state=_SPEC_BUILT, writer=events.append, pending={"prefill": "old"},
        cfg={"field": "maid_poi_radius"}, edits=edits,
    )
    assert reframe is True
    assert edits == {}                 # _redraft never set — floor ran first
    assert any("below confidence floor" in str(e.get("content", "")) for e in events)


# ── Round 5: gaps found by the third unhappy-path review ──────────────────────


def test_builder_act_never_shadows_its_pending_edit_registry():
    """builder_act's scratch registry is bound `_live: dict[str, dict] = {}` and
    read back via `bs.update(_live)` in the exit/error handlers. Two branches
    used to rebind that SAME name to activate_published_tree's return value and
    then a bool — the second rebind turned a recoverable publish-adjacent
    exception into a crash (`bs.update(True_or_False)`), and both silently
    dropped whatever pending-edit scratch the registry was holding."""
    src = (Path(__file__).resolve().parents[1] / "app" / "graph" / "builder"
           / "builder_node.py").read_text(encoding="utf-8")
    assert "_live = bool(" not in src
    assert "_live = await activate_published_tree" not in src
    # The registry declaration itself must still be exactly this shape.
    assert "_live: dict[str, dict] = {}" in src


def test_media_stash_survives_when_the_node_never_returns():
    """_run_media_overlay seeds `live["media_ws"]` onto the SAME object handed to
    the executor as `state["media_wizard_state"]` before the node runs, not only
    after. A stash the executor parks on that shared object — media.py's fix —
    must be visible to `collect_pending` even when the node then pauses or
    raises WizardExit and never returns to the `await node_fn(view)` line at all;
    stashing onto the executor's own private `_ws()` copy could not survive that,
    since nothing ever read the copy back out."""
    from app.graph.builder.edits import collect_pending

    bs = _built_bs()
    live: dict = {}
    shared_media_ws = dict(bs["media_ws"])
    live["media_ws"] = shared_media_ws           # pre-loop seed in _run_media_overlay

    # The executor stashes onto the object it was handed, not a copy.
    stash_edits(shared_media_ws, ResumeResult("x", edits={"budget": "$500/day"}))

    # Node never returns — builder_act's WizardExit/error handler runs next.
    bs.update(live)

    pending = collect_pending(bs)
    assert pending.get("budget") == "$500/day"


def test_redraft_narration_defers_to_the_rollback_it_would_contradict():
    """Same source-order guard as test_builder_plan_reads_the_consolidated_bucket
    above: refresh_copy must run AFTER apply_pending_edits and be skipped once
    the same turn already rolled back the campaign stage — otherwise a same-turn
    'rename the business AND add Toronto' announces 'plan kept' one thinking-line
    before the rollback beat announces the opposite."""
    src = (Path(__file__).resolve().parents[1] / "app" / "graph" / "builder"
           / "builder_node.py").read_text(encoding="utf-8")
    plan_body = src[src.index("async def builder_plan("):]
    apply_idx = plan_body.index("_report = apply_edits(bs, state)")
    refresh_idx = plan_body.index('refresh_copy(bs, bs.setdefault(')
    assert refresh_idx > apply_idx, "refresh_copy must run after the rollback is known"
    assert '"campaign" in _rolled_back' in plan_body[apply_idx:refresh_idx + 300]


# ── unit-grain invalidation ─────────────────────────────────────────────────
#
# `invalidate_from` used to take a STAGE, and the "geo" stage bundled two
# independent jobs behind one op (geo_discover): geocoding (location confirm)
# and the Places search (POI confirm). A POI-only edit rolled back both, and
# re-asked a location confirmation the user never touched. These pin the fix:
# a POI-side edit invalidates the search but leaves the settled location
# answer (and its geo_ws memory) alone.


def test_poi_only_edit_preserves_the_location_confirmation():
    bs = _built_bs()
    bs["geo_ws"] = {
        "_locations_synced": ["Montreal"],
        "_location_confirmed": True,
        "_geocoded_locations": [{"name": "Montreal"}],
        "_loc_picks": {"Montreal": 0},
        "_all_pois_cache": [{"name": "old spot"}],
        "_poi_cache_key": "stale",
    }
    stash_edits(bs, ResumeResult("x", edits={"poi_types": "gym"}))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert bs["filled"]["poi_types"] == "gym"
    assert rolled_back == ["geo", "maid", "campaign", "media"]
    assert "geo_discover" not in bs["ops_done"]
    assert "poi_confirm" not in bs["filled"]           # POI gate re-asks
    # Location-side memory survives untouched.
    ws = bs["geo_ws"]
    assert ws["_location_confirmed"] is True
    assert ws["_geocoded_locations"] == [{"name": "Montreal"}]
    assert ws["_loc_picks"] == {"Montreal": 0}
    # POI-side memory is gone — the search actually reruns.
    assert "_all_pois_cache" not in ws
    assert "_poi_cache_key" not in ws
    assert "geo_result" not in bs


def test_maid_field_edit_leaves_geo_and_poi_confirm_untouched():
    """poi_radius_m / lookback_days are maid inputs (KNOWN EDITABLE FIELDS
    used to list them under `geo:`, matching neither FIELD_OWNER nor their
    Slot's stage). An edit to either must roll back ONLY maid — not geo, not
    the POI confirm gate that already reflects the unchanged search."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"lookback_days": "14"}))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert bs["filled"]["lookback_days"] == "14"
    assert rolled_back == ["maid", "campaign", "media"]
    assert "geo_discover" in bs["ops_done"]
    assert "poi_confirm" in bs["filled"]               # untouched, survives
    assert "maid_query" not in bs["ops_done"]
    assert "maid_confirm" not in bs["filled"]
    assert "geo_result" in bs and bs["geo_ws"] == {"_locations_synced": ["Montreal"]}


def test_campaign_field_edit_leaves_every_geo_and_maid_gate_answered():
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"business_name": "PunkCo"}))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert bs["filled"]["business_name"] == "PunkCo"
    assert rolled_back == ["campaign", "media"]
    assert "geo_discover" in bs["ops_done"] and "maid_query" in bs["ops_done"]
    assert "poi_confirm" in bs["filled"] and "maid_confirm" in bs["filled"]
    assert bs["geo_ws"] == {"_locations_synced": ["Montreal"]}


@pytest.mark.asyncio
async def test_audience_filter_co_emitted_with_a_second_field_applies_both():
    """The `audience_filter` branch used to `return False` BEFORE the
    extra_edits loop, so a co-emitted field ("only weekends AND bump the
    radius") was acked as one reply and silently dropped as two — the
    audience patch landed, the radius change never did."""
    edits: dict = {}
    intent = ResumeIntent(
        lane="edit", target_field="audience_filter",
        new_value={"days_of_week": [5, 6]}, confidence=0.9,
        extra_edits=[ExtraEdit(target_field="poi_radius_m", new_value="750")],
    )
    reframe = await _dispatch_edit_intent(
        intent=intent, state={}, writer=lambda _e: None,
        pending={}, cfg={"field": "maid_confirm_results"}, edits=edits,
    )
    assert reframe is False
    assert edits["_audience_filter_patch"] == {"days_of_week": [5, 6]}
    assert edits["poi_radius_m"] == "750"


# ── backtrack: gate-slots vs ws-flags vs inapplicable slots ─────────────────


@pytest.mark.parametrize("step_key", [
    "geo_disambiguate_location", "geo_disambiguate_named_place",
    "maid_collect_poi_radius", "media_check_meta_auth",
    "media_select_ad_account", "media_select_pixel",
    "geo_context_confirm_location_type", "geo_context_confirm_det_type",
    "geo_wizard_plan_review",
])
def test_backtrack_to_an_unmapped_step_is_refused_never_acked(step_key):
    """11 of 33 STEP_PROMPTS keys map to no Slot and no ws-flag. Applying one
    used to log a warning and do nothing — AFTER the narrator had already told
    the user "Sure — taking you back to that step." Refusing here is what
    keeps that promise honest; the classifier-level guard (same function,
    `edits.resolve_backtrack_target`) is exercised in test_resume_router.py."""
    from app.graph.builder.edits import resolve_backtrack_target

    assert resolve_backtrack_target(step_key) == ("none", None)

    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"_restart_step": step_key}))
    ui_patch, rolled_back, note = apply_pending_edits(bs)
    assert (ui_patch, rolled_back, note) == ({}, [], None)
    assert bs["filled"] == _built_bs()["filled"]      # nothing touched


def test_backtrack_to_the_location_confirmation_reruns_geocode_only():
    bs = _built_bs()
    bs["geo_ws"] = {
        "_location_confirmed": True, "_geocoded_locations": [{"name": "Montreal"}],
        "_all_pois_cache": [{"name": "spot"}],
    }
    stash_edits(bs, ResumeResult(
        "x", edits={"_restart_step": "geo_location_confirmation"}))

    _ui, rolled_back, note = apply_pending_edits(bs)

    assert rolled_back == ["geo", "maid", "campaign", "media"]
    assert "geo_discover" not in bs["ops_done"]
    assert "poi_confirm" not in bs["filled"]           # downstream, re-asks too
    assert "_location_confirmed" not in bs["geo_ws"]   # the flag actually clears
    assert note is not None


def test_backtrack_to_the_poi_confirm_gate_invalidates_nothing():
    """A gate-slot backtrack re-shows the existing artifact — it must not
    re-run the Places search or the location confirm just to look at the map
    again."""
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"_restart_step": "geo_pois_confirmation"}))

    _ui, rolled_back, note = apply_pending_edits(bs)

    assert "poi_confirm" not in bs["filled"]           # re-asks
    assert rolled_back == []                           # nothing invalidated
    assert "geo_discover" in bs["ops_done"]
    assert bs["geo_result"] == {"pois_found": 12}
    assert bs["geo_ws"] == {"_locations_synced": ["Montreal"]}
    assert note is not None


def test_backtrack_to_the_maid_confirm_gate_skips_the_warehouse_requery():
    bs = _built_bs()
    stash_edits(bs, ResumeResult("x", edits={"_restart_step": "maid_confirm_results"}))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert "maid_confirm" not in bs["filled"]
    assert rolled_back == []
    assert "maid_query" in bs["ops_done"]


def test_backtrack_to_an_inapplicable_slot_activates_its_angle():
    """Restarting `geo_collect_brands` while det_type="category" (no
    competitor_brand angle active) must not be a silent no-op: without
    activating the angle, missing_required_slots skips the cleared slot
    forever and the planner never re-asks it."""
    bs = _built_bs()
    assert bs["filled"]["det_type"] == "category"
    stash_edits(bs, ResumeResult("x", edits={"_restart_step": "geo_collect_brands"}))

    apply_pending_edits(bs)

    assert bs["filled"]["det_type"] == "category,competitor_brand"
    assert "brand_names" not in bs["filled"]
    from app.graph.builder.slots import missing_required_slots
    assert "brand_names" in [s.name for s in missing_required_slots("geo", bs["filled"])]


def test_edit_naming_a_confirm_gate_does_not_roll_the_build_back():
    """A reply naming a gate step (poi_confirm, maid_confirm, ...) is an answer
    to a confirm screen. It has no _SLOT_UNIT entry, so it used to fall back to
    the stage's first unit and wipe the whole build — re-running the POI search
    and re-buying Unacast data for a "looks good"."""
    from app.graph.builder import edits

    bs = {
        "filled": {"locations": "LA", "det_type": "category", "poi_types": "comics", "poi_confirm": "yes"},
        "ops_done": ["geo_discover", "maid_query", "generate_brief"],
        "stages_complete": ["geo", "maid"],
        "_pending_edits": {"geo_pois_confirmation": "looks good"},
    }
    _ui, rolled_back, _note = edits.apply_pending_edits(bs)
    assert rolled_back == []
    assert bs["ops_done"] == ["geo_discover", "maid_query", "generate_brief"]
    assert bs["filled"]["poi_confirm"] == "looks good"
    assert bs["filled"]["locations"] == "LA"


def test_connection_owned_fields_are_named_to_the_classifier_and_all_refused():
    """The prompt names the media fields nobody can edit from chat so a request to
    change the ad account gets the specific refusal instead of being mapped onto a
    look-alike field (it used to land on custom_conversion_id). The list is derived
    from the registry, and every name in it must be genuinely refused downstream."""
    from app.graph.builder.edits import is_actionable_field
    from app.graph.field_owner_registry import FIELD_OWNER, edit_block_reason
    from app.graph.resume_router import _classifier_prompt, _connection_owned_fields

    named = set(_connection_owned_fields().split(", "))
    assert {"meta_ad_account_id", "meta_page_id", "meta_pixel_id"} <= named
    assert named == {f for f, o in FIELD_OWNER.items() if o == "media" and not is_actionable_field(f)}
    assert all(edit_block_reason(f, {}) for f in named)  # none can ever reach the apply gate
    assert "NOT CHANGEABLE FROM CHAT" in _classifier_prompt()


# ── Two radii: search circle vs per-POI visit ring ────────────────────────────


def _ring_bs(*, boundary_only: bool = False) -> dict:
    """A granular-local build past geocode: one city circle on the confirm map."""
    bs = _built_bs()
    loc = (
        {"location_name": "Quebec", "ui_mode": "boundary"}
        if boundary_only else
        {"location_name": "Montreal", "formatted_address": "Montreal, QC", "ui_mode": "pin_radius",
         "latitude": 45.5, "longitude": -73.6, "search_radius_km": 12.0,
         "_source_name": "Montreal"}
    )
    bs["geo_ws"] = {"_geocoded_locations": [loc], "_location_confirmed": True,
                    "_loc_radius_overrides": {"montreal": {"radius_km": 7.0, "lat": 1.0}}}
    return bs


def test_typed_search_radius_resizes_the_circle_not_the_visit_ring():
    """'change the radius to 5 km' on a city run resolved to the radius_km slot,
    which only a radius-scope run reads — acked, then lost on re-geocode."""
    bs = _ring_bs()
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "5"}))

    _ui, rolled_back, note = apply_pending_edits(bs)

    assert bs["geo_ws"]["_geocoded_locations"][0]["search_radius_km"] == 5.0
    assert bs["geo_ws"]["_search_ring_km"] == 5.0
    assert "radius_km" not in bs["geo_ws"]["_loc_radius_overrides"]["montreal"]   # drag replaced
    assert bs["geo_ws"]["_loc_radius_overrides"]["montreal"]["lat"] == 1.0       # centre kept
    assert "radius_km" not in bs["filled"]                                        # no dead slot write
    assert bs["filled"]["poi_radius_m"] == "500"                                  # visit ring untouched
    # Places re-runs inside the new circle; the location confirm is not re-asked.
    assert "geo_discover" not in bs["ops_done"]
    assert bs["geo_ws"]["_location_confirmed"] is True
    assert rolled_back and rolled_back[0] == "geo"
    assert "search_radius_km" in note


def test_typed_search_radius_on_boundary_only_run_is_dropped_not_acked():
    bs = _ring_bs(boundary_only=True)
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "5"}))

    ui_patch, rolled_back, note = apply_pending_edits(bs)

    assert (ui_patch, rolled_back, note) == ({}, [], None)
    assert "_search_ring_km" not in bs["geo_ws"]
    assert "geo_discover" in bs["ops_done"]


def test_typed_search_radius_before_geocode_is_stored_without_invalidating():
    bs = _built_bs()
    bs["geo_ws"] = {}
    stash_edits(bs, ResumeResult("x", edits={"geo_radius_km": "3 km"}))

    _ui, rolled_back, _note = apply_pending_edits(bs)

    assert bs["geo_ws"]["_search_ring_km"] == 3.0
    assert rolled_back == []
    assert "geo_discover" in bs["ops_done"]


def test_radius_scope_run_keeps_the_slot_path():
    bs = _built_bs()
    bs["filled"].update({"location_scope": "radius", "radius_km": "10"})
    stash_edits(bs, ResumeResult("x", edits={"search_radius_km": "4"}))

    apply_pending_edits(bs)

    assert float(bs["filled"]["radius_km"]) == 4.0
    assert "_search_ring_km" not in (bs.get("geo_ws") or {})


def test_typed_ring_survives_regeocode_and_a_drag_still_wins():
    from app.graph.builder.executors import geo

    ws = {"_search_ring_km": 5.0}
    loc = {"place_type": "locality", "location_name": "Laval", "_source_name": "Laval"}
    geo._stamp_location_radius_mode(loc, ws)
    assert loc["search_radius_km"] == 5.0

    ws["_loc_radius_overrides"] = {"laval": {"radius_km": 9.0}}
    loc2 = {"place_type": "locality", "location_name": "Laval", "_source_name": "Laval"}
    geo._stamp_location_radius_mode(loc2, ws)
    assert loc2["search_radius_km"] == 9.0


def test_classifier_context_lists_both_rings():
    from app.graph.resume_router import _classifier_context

    bs = _ring_bs()
    bs["filled"]["poi_radius_m"] = "100"
    ctx = _classifier_context("maid_confirm", {"campaign_builder_state": bs})

    assert "Rings:" in ctx
    assert "search_radius_km" in ctx and "Montreal, QC" not in ctx.split("Rings:")[0]
    assert "Montreal 12.0 km" in ctx
    assert "poi_radius_m) — 100 m around each spot" in ctx


def test_classifier_context_has_no_rings_line_when_none_exist():
    from app.graph.resume_router import _rings_digest

    assert _rings_digest({"campaign_builder_state": {"filled": {}}}) == ""
    assert _rings_digest(None) == ""
