"""
tests/test_edit_ack_invariant.py
─────────────────────────────────
Two structural invariants the ack/apply mismatch bug (see edits.py's
`is_actionable_field` and resume_router's `_validate_edit_target` docstrings)
used to violate silently:

  1. ACK GATE ≡ APPLY GATE — the predicate resume_router uses to decide
     "is this field even worth acking" must exactly match the predicate
     builder/edits.apply_pending_edits uses to decide "can I actually commit
     this field". Before `is_actionable_field` unified them, the ack gate was
     `FIELD_OWNER` (79 keys) and the apply gate was `EDIT_ALIASES` + campaign
     + control fields (a much smaller set) — 7 fields lived in the gap.

  2. NO BEAT CLAIMS AN UNAPPLIED CHANGE — `_dispatch_edit_intent` records a
     `heard` ledger entry at ack time; `apply_pending_edits` (and the two
     overlay appliers) record `applied` when the write actually lands. For
     every field this predicate says IS actionable, driving a real edit
     through the full ack→commit path must leave nothing stranded in
     `heard_not_applied`. The negative case (a field the predicate correctly
     refuses) must never reach `_dispatch_edit_intent` as an edit at all —
     it's caught upstream and routed to the `unhandled` lane instead.

Neither test drives an LLM or the graph — both go straight at the pure
functions the mechanism is built from.
"""

from __future__ import annotations

import pytest

from app.graph.builder.edits import apply_pending_edits, is_actionable_field, stash_edits
from app.graph.field_owner_registry import FIELD_OWNER
from app.graph.narrator.beats import drain_changes
from app.graph.resume_router import ResumeIntent, ResumeResult, _post_validate_edit_lane, _validate_edit_target
from app.graph.wizard_helpers import _dispatch_edit_intent


# ── 1. ack gate ≡ apply gate ────────────────────────────────────────────────


@pytest.mark.parametrize("field", sorted(FIELD_OWNER))
def test_actionable_iff_commits(field: str):
    """For every field the registry names, is_actionable_field's verdict must
    match what apply_pending_edits actually does with a stashed edit for it —
    the SAME two-sided check `_validate_edit_target`'s docstring promises.

    `poi_selection` / `audience_filter` (the two `_CONTROL_FIELDS`) are
    excluded on purpose: is_actionable_field counts them actionable, but they
    never reach apply_pending_edits's generic field loop at all — production
    code stashes them under their OWN underscore-prefixed control keys
    (`_poi_selection`, `_audience_filter_patch`, both in `_CONTROL_KEYS`) and
    commits them through their dedicated overlay appliers in `builder_plan`,
    called BEFORE apply_pending_edits — already covered by
    test_poi_selection_corpus.py and test_audience_filter.py. Stashing the
    bare classifier field name here (as `_dispatch_edit_intent` never does
    for these two) would just prove apply_pending_edits correctly refuses to
    guess at a control key it doesn't own — a different, uninteresting fact.
    `note` alone is the right signal for "did anything commit" — checking
    `field in bs["filled"]` is wrong whenever the field is an ALIAS that
    resolves to a differently-named slot (e.g. `maid_poi_radius` ->
    `poi_radius_m`); `apply_pending_edits` returns `note=None` iff nothing in
    `applied` was populated, regardless of what key it landed under.
    """
    if field in {"poi_selection", "audience_filter", "location_ring", "location_center", "map_pins", "excluded_areas"}:
        pytest.skip("control field — committed via its own overlay applier, not this loop")
    bs: dict = {"filled": {}, "ops_done": [], "geo_ws": {}}
    # The search-circle radius is parsed to a number before it can land on a
    # location (edits._apply_search_ring); a non-numeric value is correctly
    # dropped, which says nothing about whether the FIELD is routable.
    value = {
        "search_radius_km": "5", "geo_radius_km": "5",
        # An unreadable scope is reported as unsupported (never written as a
        # blank), so this field needs a value the normalizer recognises.
        "geo_scope": "admin_areas", "geo_location_type": "admin_areas",
    }.get(field, "test-value")
    stash_edits(bs, ResumeResult("x", edits={field: value}))
    _ui_patch, _rolled_back, note = apply_pending_edits(bs)

    committed = bool(note)
    assert is_actionable_field(field) == committed, (
        f"{field!r}: is_actionable_field={is_actionable_field(field)} but "
        f"apply_pending_edits commit={committed} (note={note!r})"
    )


def test_no_field_is_actionable_without_a_real_landing_spot():
    """Cross-check in the other direction, over the WHOLE registry at once —
    is_actionable_field's true set must never outrun what apply_pending_edits
    can actually commit in one pass (deliberately excludes the geo/maid
    confirmation-gate quartet, which commit through a DIFFERENT path — a
    widget answer landing on a Slot, not an NL edit — see slots.py)."""
    from app.graph.builder.edits import EDIT_ALIASES

    gates = {"poi_confirm", "maid_confirm", "plan_confirm", "go_live_confirm"}
    control = {"poi_selection", "audience_filter", "location_ring", "location_center", "map_pins", "excluded_areas"}
    actionable = {f for f in FIELD_OWNER if is_actionable_field(f)} - gates
    for field in actionable:
        assert (
            field in EDIT_ALIASES
            or FIELD_OWNER.get(field) == "campaign"
            or field in control
        ), f"{field!r} is actionable but has no EDIT_ALIASES/campaign/control landing spot"


# ── 2. no beat claims an unapplied change ───────────────────────────────────


@pytest.mark.asyncio
async def test_a_landed_cross_step_edit_leaves_nothing_heard_not_applied():
    """Drive a real edit through the SAME two calls production code makes —
    _dispatch_edit_intent (records `heard`), then stash_edits +
    apply_pending_edits(bs, state) (records `applied`) — and confirm the
    ledger closes: nothing acked is left dangling."""
    state = {"campaign_builder_state": {}}
    bs: dict = {
        "ops_done": ["geo_discover"],
        "filled": {"business_name": "PunkBakery"},
    }
    state["campaign_builder_state"] = bs
    edits: dict = {}

    reframe = await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_field="budget", new_value="750", confidence=0.95,
        ),
        state=state, writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "maid_lookback"}, edits=edits,
    )
    assert reframe is False

    stash_edits(bs, ResumeResult("x", edits=edits))
    apply_pending_edits(bs, state)

    changes = drain_changes(state)
    assert changes["heard_not_applied"] == []
    assert any("budget" in a for a in changes["applied"])


@pytest.mark.asyncio
async def test_a_refused_field_never_reaches_the_heard_ledger():
    """geo_disambiguate_location is in FIELD_OWNER (a real geo-owned name)
    but is neither an edit target nor a backtrack target — mid-loop, a
    per-name disambiguation step. It must be caught BEFORE
    _dispatch_edit_intent ever sees it (at classification), never acked,
    never land in the heard ledger, and never resolve as an ordinary edit."""
    assert is_actionable_field("geo_disambiguate_location") is False

    # The exact gate resume_router's classifier runs before dispatch — must
    # refuse this field outright rather than pass it through as an edit.
    assert _validate_edit_target("geo_disambiguate_location", False, False, "x", "step") is None

    intent = ResumeIntent(
        lane="edit", target_field="geo_disambiguate_location", new_value="x", confidence=0.95,
    )
    resolved = _post_validate_edit_lane(intent, "geo_disambiguate_location")
    assert resolved.lane == "unhandled"

    # And if it somehow reached _dispatch_edit_intent anyway, nothing must be
    # acked or committed for it — belt-and-suspenders on the same invariant.
    state = {"campaign_builder_state": {}}
    bs: dict = {"ops_done": [], "filled": {}}
    state["campaign_builder_state"] = bs
    edits: dict = {}
    await _dispatch_edit_intent(
        intent=ResumeIntent(
            lane="edit", target_field="geo_disambiguate_location", new_value="x",
            confidence=0.95,
        ),
        state=state, writer=lambda _e: None, pending={"prefill": None},
        cfg={"field": "geo_disambiguate_location"}, edits=edits,
    )
    stash_edits(bs, ResumeResult("x", edits=edits))
    apply_pending_edits(bs, state)
    changes = drain_changes(state)
    assert changes["heard_not_applied"] == []
    assert changes["applied"] == []
