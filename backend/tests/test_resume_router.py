"""Tests for the resume-router intent classifier, registries, and decorator.

Covers:
- Sentinel short-circuit (no LLM call for yes/no/skip/numeric/JSON)
- Per-lane classifier mapping (mocked LLM)
- Cache hit on replay (second call invokes 0 LLMs)
- field_owner_registry resolves every STEP_PROMPTS field
- is_completed_owner matrix across empty / partial / full sets
- ResumeResult is a str subclass with .edits attribute
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.graph.field_owner_registry import (
    APPENDABLE_FIELDS,
    FIELD_OWNER,
    is_completed_owner,
    resolve_field_owner,
)
from app.graph.prompts_registry import STEP_PROMPTS
from app.graph.resume_router import (
    ExtraEdit,
    ResumeIntent,
    ResumeResult,
    _hash,
    _intent_cache,
    _classifier_prompt,
    classify_resume_intent,
    is_sentinel_resume,
)
from app.graph.wizard_exit import WizardExitRequested

# The prompt became a `@lru_cache`d generator (Step 4 — KNOWN EDITABLE FIELDS
# etc. are now derived from the registries, not hand-copied prose), so it's no
# longer a module-level constant. Resolve it once here rather than touching
# every one of this file's existing substring assertions below.
_CLASSIFIER_SYSTEM_PROMPT = _classifier_prompt()


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_resume_result_is_str_subclass_with_edits():
    r = ResumeResult("Montreal", edits={"business_name": "PunkBakery"})
    assert isinstance(r, str)
    assert r == "Montreal"
    assert r.lower() == "montreal"
    assert r.edits == {"business_name": "PunkBakery"}
    # Default edits = empty
    assert ResumeResult("x").edits == {}


def test_resume_result_parse_compat():
    """Existing wizard sub-nodes use str-typed operations on the return value."""
    assert float(ResumeResult("5.0")) == 5.0
    assert ResumeResult("Toronto").strip() == "Toronto"
    assert "yes" in ResumeResult("yes please")


def test_sentinel_resume_detection():
    assert is_sentinel_resume("yes")
    assert is_sentinel_resume("no")
    assert is_sentinel_resume("skip")
    assert is_sentinel_resume("500")
    assert is_sentinel_resume("5.5")
    assert is_sentinel_resume('{"a": 1}')
    assert is_sentinel_resume('{"confirm": true}')  # POI edit-delta payload
    assert is_sentinel_resume("[1, 2]")
    assert is_sentinel_resume("")
    assert is_sentinel_resume("   ")
    assert not is_sentinel_resume("Montreal")
    assert not is_sentinel_resume("change my location")
    assert not is_sentinel_resume("what's a POI?")


# ── Field owner registry ─────────────────────────────────────────────────────


def test_field_owner_resolves_every_step_prompts_field():
    """Every distinct STEP_PROMPTS[*]["field"] must map to an owner."""
    seen = set()
    unmapped = []
    for step_key, cfg in STEP_PROMPTS.items():
        field = cfg.get("field")
        if not field or field in seen:
            continue
        seen.add(field)
        if resolve_field_owner(field) is None:
            unmapped.append((step_key, field))
    assert not unmapped, f"unmapped fields in FIELD_OWNER: {unmapped}"


def test_appendable_fields_subset_of_field_owner():
    missing = [f for f in APPENDABLE_FIELDS if f not in FIELD_OWNER]
    assert not missing, f"APPENDABLE_FIELDS missing from FIELD_OWNER: {missing}"


def test_is_completed_owner_matrix():
    assert is_completed_owner("geo", {"wizards_completed": {"geo", "maid"}})
    assert not is_completed_owner("campaign", {"wizards_completed": {"geo"}})
    assert not is_completed_owner("geo", {"wizards_completed": set()})
    assert not is_completed_owner("geo", {})
    assert not is_completed_owner(None, {"wizards_completed": {"geo"}})
    # Tolerates missing key
    assert not is_completed_owner("geo", {"other_field": 1})


# ── Classifier ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_classifier_cache():
    _intent_cache.clear()
    yield
    _intent_cache.clear()


@pytest.mark.asyncio
async def test_classifier_sentinel_skips_llm():
    # Sentinel inputs should never invoke the LLM; we patch tracked_ainvoke
    # to fail if called, which would surface the bug as a test failure.
    with patch("app.graph.resume_router.tracked_ainvoke") as mock_invoke:
        intent = await classify_resume_intent("yes", "geo_collect_locations")
        assert intent.lane == "confirm"
        assert mock_invoke.call_count == 0


@pytest.mark.asyncio
async def test_classifier_timeout_falls_back_to_reject_not_confirm():
    """Two consecutive timeouts must land on 'reject', never 'confirm'.

    Regression: 'confirm' used to write the raw (unclassified) free text
    straight into the active gate, which for a non-yes/no gate (poi_confirm,
    maid_confirm) got silently popped and re-asked — the edit vanished while
    the narrator still told the user it landed.
    """
    async def _raise(*a, **k):
        raise TimeoutError()

    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(side_effect=_raise)) as mock_invoke:
        intent = await classify_resume_intent(
            "add brooklyn in there and also starbucks", "geo_pois_confirmation",
        )
    assert intent.lane == "reject"
    assert intent.confidence == 0.0
    assert mock_invoke.call_count == 2, "expected exactly one retry before falling back"


@pytest.mark.asyncio
async def test_classifier_retries_once_then_succeeds():
    """A single timeout is transparent — the retry's real answer survives."""
    payload = {"lane": "edit", "target_field": "location", "new_value": "Brooklyn",
               "is_append": True, "confidence": 0.9}
    calls = {"n": 0}

    async def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError()
        return AIMessage(content=json.dumps(payload)), None

    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(side_effect=_flaky)):
        intent = await classify_resume_intent("add brooklyn", "geo_pois_confirmation")
    assert intent.lane == "edit"
    assert intent.target_field == "location"
    assert calls["n"] == 2


def _mock_llm_returning(payload: dict):
    """Patch context that makes the classifier LLM return ``payload`` as JSON."""
    msg = AIMessage(content=json.dumps(payload))
    return patch(
        "app.graph.resume_router.tracked_ainvoke",
        new=AsyncMock(return_value=(msg, None)),
    )


@pytest.mark.asyncio
async def test_classifier_reads_a_gemini_3_block_list_reply():
    """Gemini 3.x returns content as a list of blocks (with thought signatures)
    even for a plain reply — 2.5 returned a str. The classifier must read both."""
    payload = {"lane": "edit", "target_field": "location", "new_value": "Brooklyn",
               "is_append": True, "confidence": 0.9}
    msg = AIMessage(content=[
        {"type": "thinking", "thinking": "the user wants Brooklyn"},
        {"type": "text", "text": json.dumps(payload), "extras": {"signature": "abc"}},
    ])
    with patch("app.graph.resume_router.tracked_ainvoke", new=AsyncMock(return_value=(msg, None))):
        intent = await classify_resume_intent("add brooklyn", "geo_pois_confirmation")
    assert (intent.lane, intent.target_field) == ("edit", "location")


@pytest.mark.asyncio
async def test_classifier_maps_remove_intent():
    payload = {
        "lane": "edit",
        "target_field": "location",
        "new_value": "Laval",
        "is_remove": True,
        "confidence": 0.95,
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("remove Laval", "geo_location_confirmation")
    assert intent.lane == "edit"
    assert intent.target_field == "location"
    assert intent.new_value == "Laval"
    assert intent.is_remove is True
    assert intent.is_append is False


@pytest.mark.asyncio
async def test_classifier_drops_remove_on_non_list_field():
    """is_remove on a non-appendable field collapses to a plain replace."""
    payload = {
        "lane": "edit",
        "target_field": "budget",
        "new_value": "$500",
        "is_remove": True,
        "confidence": 0.9,
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("drop the budget", "campaign_plan_confirm")
    assert intent.lane == "edit"
    assert intent.target_field == "budget"
    assert intent.is_remove is False


@pytest.mark.asyncio
async def test_classifier_replay_is_free():
    """A replayed turn must reuse the first decision and invoke ZERO LLMs.

    LangGraph re-executes a node from the top on resume, so a re-classification
    that landed on a different lane would diverge state.

    Rewritten from `test_classifier_caches_by_step_and_raw`, which hand-built the
    cache key as `(step_key, _hash(raw))`. The key now also covers the classifier
    context digest (the active question + already-filled slots), so warming it by
    hand silently missed — and the assertion then fell through to a REAL network
    call. Asserting the invocation count instead tests the contract that matters
    and cannot rot when the key shape changes again.
    """
    _intent_cache.clear()
    payload = {"lane": "reject", "confidence": 0.9}
    state = {"campaign_builder_state": {"filled": {"locations": "Montreal"}}}

    with _mock_llm_returning(payload) as spy:
        first = await classify_resume_intent("hmm", "geo_collect_locations", state)
        second = await classify_resume_intent("hmm", "geo_collect_locations", state)

    assert first.lane == "reject"
    assert second is first, "replay re-classified instead of reusing the decision"
    assert spy.call_count == 1, f"replay cost {spy.call_count} LLM call(s), expected 1"


# ── Remove (list-field) dispatch & backtrack ─────────────────────────────────


def test_list_remove_preserve_order():
    from app.graph.wizard_helpers import _list_remove_preserve_order

    assert _list_remove_preserve_order(["Montreal", "Laval", "Toronto"], ["laval"]) == [
        "Montreal",
        "Toronto",
    ]
    # Case-insensitive, no-op when absent, tolerates None members
    assert _list_remove_preserve_order(["Montreal"], ["Quebec"]) == ["Montreal"]
    assert _list_remove_preserve_order([None, "Montreal"], ["x"]) == ["Montreal"]


@pytest.mark.asyncio
async def test_dispatch_remove_shrinks_active_prefill():
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="location", new_value="Laval", is_remove=True,
        # The classifier always reports a confidence and _dispatch_edit_intent
        # will not COMMIT below settings.RESUME_EDIT_MIN_CONFIDENCE, so a
        # hand-built intent must carry one too or it takes the reframe path.
        confidence=0.95,
    )
    pending = {"prefill": ["Montreal", "Laval"]}
    edits: dict = {}
    await _dispatch_edit_intent(
        intent=intent,
        state={},
        writer=lambda _ev: None,
        pending=pending,
        cfg={"field": "location"},
        edits=edits,
    )
    assert pending["prefill"] == ["Montreal"]
    assert edits == {}


class _FakeTask:
    """StateSnapshot.tasks[] stub. ``state`` holds a nested subgraph snapshot
    (campaign_builder is a compiled subgraph, so its interrupt nests there)."""

    def __init__(self, interrupts=(), state=None):
        self.interrupts = interrupts
        self.state = state


class _FakeState:
    def __init__(self, values, tasks=()):
        self.values = values
        self.tasks = tasks


class _FakeGraph:
    """Minimal graph stub for run_preflight: only aget_state is exercised once
    the backtrack / locked-refusal lanes are gone."""

    def __init__(self, values, tasks=()):
        self._values = values
        self._tasks = tasks
        self.update_calls = 0
        self.update_diffs = []

    async def aget_state(self, config, subgraphs=False):
        return _FakeState(self._values, self._tasks)

    async def aupdate_state(self, config, diff):
        self.update_calls += 1
        self.update_diffs.append(diff)


@pytest.mark.asyncio
async def test_run_preflight_never_short_circuits_during_builder_interrupt():
    """Regression: a free-text reply mid-builder-collection must NOT rewind to
    an earlier step. The backtrack / locked-refusal lanes were removed, so
    run_preflight always falls through to the normal Command(resume=...) path
    (short_circuit False, no restored pending_action event)."""
    from app.services.resume_preflight import run_preflight

    # Active builder interrupt: pending_action carries a step_key (≠ the MAID
    # confirm step), so refresh_user_info skips extraction and maid re-emit is
    # a no-op. A free-text "actually go back to locations" must not rewind.
    graph = _FakeGraph({
        "pending_action": {"step_key": "geo_collect_business_desc"},
        "user_info": {"business_name": "PunkBakery"},
    })

    outcome = await run_preflight(graph, {}, "actually go back to locations")

    assert outcome.short_circuit is False
    assert not [e for e in outcome.sse_events if e["type"] == "pending_action"]
    assert graph.update_calls == 0   # no checkpoint rewind


@pytest.mark.asyncio
async def test_refresh_skips_extraction_during_subgraph_interrupt():
    """Reality check for the in_wizard_step guard on the builder path.

    A campaign_builder (subgraph) interrupt does NOT persist
    ``pending_action.step_key`` (chat/service.py), and it nests in
    ``tasks[].state.tasks[].interrupts`` — the parent-level ``tasks[].interrupts``
    is empty. So neither of the two cheap guard conditions catches it; only the
    recursive ``_has_pending_interrupt`` walk does. Extraction must be skipped so
    ``aupdate_state`` never restarts the subgraph from START.

    Fails against the pre-fix guard (extraction would fire mid-builder)."""
    from app.services import resume_preflight

    nested = _FakeState({}, tasks=(_FakeTask(interrupts=("geo_locations",)),))
    graph = _FakeGraph(
        {"pending_action": {}, "user_info": {"business_name": "PunkBakery"}},
        tasks=(_FakeTask(interrupts=(), state=nested),),
    )

    with patch(
        "app.graph.nodes.extract_user_info_from_text",
        new=AsyncMock(return_value={"business_name": "Changed"}),
    ) as mock_extract:
        outcome = await resume_preflight.run_preflight(
            graph, {}, "target coffee lovers in Montreal and Laval"
        )

    mock_extract.assert_not_awaited()   # guard skipped the extraction
    assert graph.update_calls == 0       # no subgraph-restart rewind
    assert outcome.short_circuit is False


@pytest.mark.asyncio
async def test_refresh_passes_last_ai_context():
    """When NOT inside an interrupt, resume extraction runs AND forwards the last
    AI turn (mirrors entry_node's extract arm) so reference answers resolve."""
    from langchain_core.messages import AIMessage, HumanMessage

    from app.services import resume_preflight

    graph = _FakeGraph({
        "pending_action": {},
        "user_info": {},
        "messages": [HumanMessage(content="hi"), AIMessage(content="Which city?")],
    })  # no tasks → no pending interrupt → extraction runs

    with patch(
        "app.graph.nodes.extract_user_info_from_text",
        new=AsyncMock(return_value={"location": ["Montreal"]}),
    ) as mock_extract:
        await resume_preflight.run_preflight(graph, {}, "Montreal")

    mock_extract.assert_awaited_once()
    _, kwargs = mock_extract.call_args
    assert kwargs.get("last_ai_response") == "Which city?"
    assert graph.update_calls == 1


# ── Composite replies: answer_value / question_text / extra_edits hardening ──


def test_classifier_prompt_declares_answer_value_and_extra_edits():
    """Regression for 1a: extra_edits was documented in prose but absent from
    the 'Return ONLY a JSON object with these keys' contract Flash is held to."""
    assert '"answer_value"' in _CLASSIFIER_SYSTEM_PROMPT
    assert '"extra_edits"' in _CLASSIFIER_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_classifier_drops_unknown_extra_edit_target():
    """Regression for 1b: extra_edits used to skip validation entirely, so a
    hallucinated field survived to be acked and then dropped downstream."""
    payload = {
        "lane": "edit",
        "target_field": "budget",
        "new_value": "500",
        "confidence": 0.9,
        "extra_edits": [{"target_field": "not_a_real_field", "new_value": "x"}],
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("bump budget, also frob the whatsit", "campaign_plan_confirm")
    assert intent.target_field == "budget"
    assert intent.extra_edits == []


@pytest.mark.asyncio
async def test_classifier_canonicalizes_slot_name_alias():
    """Regression: the `locations` slot is reachable by three aliases
    (`locations`, `location`, `geo_locations`) — `is_actionable_field` accepts
    all three, but `geo.py`'s confirm loop and `APPENDABLE_FIELDS` only know
    the registry name `location`. A classifier reply naming the bare slot
    alias `locations` used to survive validation unchanged, missing every
    `rerun_on_edit`/`stash_edits(exclude=...)` guard downstream and silently
    losing its `is_append` flag — see `edits.canonical_field`."""
    payload = {
        "lane": "edit",
        "target_field": "locations",
        "new_value": "Brooklyn",
        "is_append": True,
        "confidence": 0.9,
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent(
            "also add brooklyn", "geo_location_confirmation"
        )
    assert intent.target_field == "location"
    assert intent.is_append is True


@pytest.mark.asyncio
async def test_classifier_unknown_primary_promotes_valid_extra():
    """Regression for 1b: an unknown PRIMARY field used to collapse the whole
    intent to reject, discarding a perfectly valid extra_edits entry."""
    payload = {
        "lane": "edit",
        "target_field": "not_a_real_field",
        "new_value": "x",
        "confidence": 0.9,
        "extra_edits": [{"target_field": "budget", "new_value": "500"}],
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("frob the whatsit, also bump budget to 500", "campaign_plan_confirm")
    assert intent.lane == "edit"
    assert intent.target_field == "budget"
    assert intent.new_value == "500"
    assert intent.extra_edits == []


@pytest.mark.asyncio
async def test_dispatch_extra_edits_skipped_when_primary_refused():
    """Regression for 1d: extras used to be dispatched BEFORE the primary's own
    edit_block_reason check, so they landed even when the primary was refused."""
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="business_name", new_value="PunkBakery",
        confidence=0.95,
        extra_edits=[ExtraEdit(target_field="budget", new_value="500")],
    )
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()) as mock_narrate:
        reframe = await _dispatch_edit_intent(
            intent=intent,
            state={"meta_campaign_ids": ["123"]},  # published — hard block
            writer=lambda _ev: None,
            pending={},
            cfg={"field": "business_name"},
            edits=edits,
        )
    assert reframe is False  # the refusal itself is the response, not a reframe
    assert edits == {}  # extra never landed
    assert mock_narrate.await_count == 1  # exactly one refusal, not one per edit


@pytest.mark.asyncio
async def test_dispatch_extra_edits_skipped_below_confidence_floor():
    """Regression for 1c/1d: extras share the primary's confidence (ExtraEdit
    carries none of its own), so a reply below the floor must gate the WHOLE
    reply — extras must not sneak through ungated ahead of that check."""
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="business_name", new_value="PunkBakery",
        confidence=0.3,  # below settings.RESUME_EDIT_MIN_CONFIDENCE (0.7)
        extra_edits=[ExtraEdit(target_field="budget", new_value="500")],
    )
    edits: dict = {}
    reframe = await _dispatch_edit_intent(
        intent=intent, state={}, writer=lambda _ev: None,
        pending={}, cfg={"field": "business_name"}, edits=edits,
    )
    assert reframe is True
    assert edits == {}  # extra never dispatched


@pytest.mark.asyncio
async def test_dispatch_extra_edits_land_alongside_primary():
    """The everyday case still works after the reorder: primary + extra both
    apply when nothing blocks either."""
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="deterministic_subtype", new_value="event_based",
        confidence=0.9,
        extra_edits=[ExtraEdit(target_field="budget", new_value="500")],
    )
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state={}, writer=lambda _ev: None,
            pending={}, cfg={"field": "location"}, edits=edits,
        )
    assert reframe is False
    # `deterministic_subtype` is list-typed (APPENDABLE_FIELDS) — a pure
    # replace now wraps a bare scalar, same as append/remove already did.
    # See test_dispatch_replace_on_list_field_wraps_scalar for why.
    assert edits["deterministic_subtype"] == ["event_based"]
    assert edits["budget"] == "500"


@pytest.mark.asyncio
async def test_dispatch_replace_on_list_field_wraps_scalar():
    """Regression: a pure-replace edit on a list-typed field ("location") used
    to stash the classifier's bare string straight into `edits`, unwrapped —
    unlike the append/remove branches a few lines up, which already guard
    this. geo.py's confirm-loop consumers (`_apply_location_edit`, the store
    equivalent) iterate `edits[target_field]` as a collection, so an
    unwrapped string like "New York, NY, USA" split into characters and each
    one got geocoded as its own bogus location."""
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="location", new_value="New York, NY, USA",
        confidence=0.9,
    )
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state={}, writer=lambda _ev: None,
            pending={}, cfg={"field": "something_else"}, edits=edits,
        )
    assert reframe is False
    assert edits["location"] == ["New York, NY, USA"]


# ── wizard_interrupt loop: composite (answer + edit / question) replies ─────


@contextmanager
def _loop_harness(classify_results, interrupt_values):
    """Patch everything wizard_interrupt touches around a resolved interrupt()
    call, so the loop's own dispatch logic runs for real against canned
    classifier output. ``classify_results`` / ``interrupt_values`` are consumed
    one per loop iteration (iteration 0, 1, 2, ...)."""
    with ExitStack() as stack:
        # Pin the lane-JSON backend regardless of the ambient
        # RESUME_ROUTER_TOOLCALLING setting (a local .env can flip this) —
        # this harness mocks classify_resume_intent specifically, and if the
        # toolcalling backend is actually selected at runtime that mock is
        # never consulted, `classify_resume_intent_tools` runs unmocked and
        # errors, and the loop re-prompts for a 2nd `interrupt()` this
        # harness's single canned value can't satisfy — a StopIteration that
        # has nothing to do with the lane being tested.
        stack.enter_context(patch("app.graph.wizard_helpers.settings.RESUME_ROUTER_TOOLCALLING", False))
        stack.enter_context(patch(
            "app.graph.wizard_helpers.interrupt",
            side_effect=list(interrupt_values),
        ))
        stack.enter_context(patch(
            "app.graph.wizard_helpers.classify_resume_intent",
            new=AsyncMock(side_effect=list(classify_results)),
        ))
        mock_narrate = stack.enter_context(
            patch("app.graph.wizard_helpers.narrate", new=AsyncMock())
        )
        stack.enter_context(patch("app.graph.wizard_helpers.wizard_ask", new=AsyncMock()))
        stack.enter_context(patch("app.graph.wizard_helpers.generate_chips", new=AsyncMock(return_value=[])))
        stack.enter_context(patch("app.graph.wizard_helpers.flush_narration", new=AsyncMock()))
        stack.enter_context(patch("app.graph.wizard_helpers._narrator_peek", return_value=False))
        stack.enter_context(patch("app.graph.wizard_helpers._narrator_drain", return_value=[]))
        yield mock_narrate


def _resumed_state(step_key: str) -> dict:
    """A state dict wizard_interrupt reads as 'already paused at step_key' —
    triggers the resume-detection skip so iteration 0 never emits a fresh
    pending_action / wizard_ask call."""
    return {"pending_action": {"step_key": step_key}, "campaign_builder_state": {}}


@pytest.mark.asyncio
async def test_wizard_interrupt_answer_plus_edit_resolves_and_stashes_edit():
    """'yes 2km, and bump my budget to 500' — the active step (locations) is
    answered AND budget is edited, in one reply. Both must land; the answer
    must not be lost to the edit lane re-looping."""
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="budget", new_value="500",
        answer_value="Toronto", confidence=0.9,
    )
    with _loop_harness([intent], ["yes 2km, and bump my budget to 500"]):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_collect_locations",
            context="test",
            state=_resumed_state("geo_collect_locations"),
        )
    assert result == "Toronto"
    assert result.edits.get("budget") == "500"


@pytest.mark.asyncio
async def test_wizard_interrupt_answer_on_active_field_drops_redundant_edit():
    """An edit naming the field the user just answered is redundant — answer
    wins, no double-write."""
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="geo_locations", new_value="Montreal",
        answer_value="Toronto", confidence=0.9,
    )
    with _loop_harness([intent], ["Toronto, not Montreal"]):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_collect_locations",
            context="test",
            state=_resumed_state("geo_collect_locations"),
        )
    assert result == "Toronto"
    assert result.edits == {}


@pytest.mark.asyncio
async def test_wizard_interrupt_answer_below_confidence_floor_reasks():
    """An answer_value below the confidence floor must not fill the slot —
    the loop re-asks instead of committing a hallucinated answer."""
    from app.graph.wizard_helpers import wizard_interrupt

    low_confidence = ResumeIntent(
        lane="reject", answer_value="Toronto", confidence=0.4,
    )
    second_turn = ResumeIntent(lane="confirm", confidence=1.0)
    with _loop_harness([low_confidence, second_turn], ["hmm maybe toronto?", "Toronto"]):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_collect_locations",
            context="test",
            state=_resumed_state("geo_collect_locations"),
        )
    assert result == "Toronto"  # resolved on the SECOND turn, not the first


@pytest.mark.asyncio
async def test_wizard_interrupt_question_plus_edit_both_land():
    """'what's a POI? also add Toronto' — the question is answered inline AND
    the edit is applied; neither is dropped for the other."""
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="budget", new_value="500",
        question_text="what is a POI", confidence=0.9,
    )
    second_turn = ResumeIntent(lane="confirm", confidence=1.0)
    with _loop_harness([intent, second_turn], ["what's a POI? also bump budget to 500", "Toronto"]) as mock_narrate:
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_collect_locations",
            context="test",
            state=_resumed_state("geo_collect_locations"),
        )
    assert result == "Toronto"


@pytest.mark.asyncio
async def test_wizard_interrupt_rerun_on_edit_sees_extra_edits_target():
    """Regression: 'just manhattan' landing as an EXTRA (not the primary target)
    must still trigger rerun_on_edit and return to the caller immediately —
    not sit in the loop-local `edits` dict re-showing a stale widget until some
    later turn finally applies it (the observed bug: the geo edit only applied
    on the NEXT turn, rolling back geo+maid+campaign+media all at once).
    """
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="business_name", new_value="ok",
        confidence=0.9,
        extra_edits=[ExtraEdit(target_field="location", new_value="Manhattan")],
    )
    with _loop_harness([intent], ["rename to ok, just manhattan"]):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_pois_confirmation",
            context="test",
            state=_resumed_state("geo_pois_confirmation"),
            rerun_on_edit={"location"},
        )
    # Returned to the caller on THIS turn (raw reply, not a re-ask) — the
    # extra's target landed in edits for the caller to apply. `location` is
    # list-typed (APPENDABLE_FIELDS) — a pure replace wraps the bare scalar,
    # same as append/remove already did (test_dispatch_replace_on_list_field_
    # wraps_scalar): geo.py's confirm-loop consumers iterate this as a
    # collection, and an unwrapped string used to split into characters.
    assert result == "rename to ok, just manhattan"
    assert result.edits.get("location") == ["Manhattan"]
    assert result.edits.get("business_name") == "ok"


@pytest.mark.asyncio
async def test_wizard_interrupt_maid_confirm_edit_returns_immediately():
    """Regression: at maid_confirm_results, an edit ('target coffee lovers and
    also health conscious people, and pilates and gym' -> poi_types append,
    paired with deterministic_subtype += category) must return to the caller
    on THIS turn with every appended item intact — not sit in the loop-local
    `edits` dict re-showing the stale audience widget (the observed bug: the
    narrator announced the edit as applied, then the graph re-interrupted on
    the SAME maid_confirm_results gate with the unchanged audience).

    `_loop_harness` supplies exactly ONE interrupt() value; if wizard_interrupt
    fails to return here and loops back to interrupt() a second time, the
    patched side_effect list is exhausted and this test errors — which is
    itself the regression signal for the missing rerun_on_edit wiring at
    builder_node.py's maid_confirm branch.
    """
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="poi_types",
        new_value=["coffee shop", "health food store", "pilates studio", "gym"],
        is_append=True, confidence=0.9,
        extra_edits=[ExtraEdit(
            target_field="deterministic_subtype", new_value="category", is_append=True,
        )],
    )
    rerun_on_edit = {f for f, owner in FIELD_OWNER.items() if owner in ("geo", "maid")}
    with _loop_harness(
        [intent],
        ["target coffee lovers and also the people who are health conscious, "
         "and also pilates and gym"],
    ):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="maid_confirm_results",
            context="test",
            state=_resumed_state("maid_confirm_results"),
            rerun_on_edit=rerun_on_edit,
        )
    assert result.edits.get("poi_types") == [
        "coffee shop", "health food store", "pilates studio", "gym",
    ]
    assert result.edits.get("deterministic_subtype") == ["category"]


# ── N-way extraction: guard fix + clauses scratch field + 3/4-clause shapes ──


def test_classifier_guard_no_longer_blocks_not_yet_set_fields():
    """Regression for the Starbucks-drop bug: the old wording forbade editing
    ANY field absent from 'Already set', even a real KNOWN EDITABLE FIELDS
    entry the user named outright — just because its slot hasn't come up yet
    in this build. Assert the blanket-forbid sentence is gone and the
    scoped-to-real-fields replacement is in."""
    assert "not in \"Already set\" and is not the" not in _CLASSIFIER_SYSTEM_PROMPT
    assert "REGARDLESS of whether it is" in _CLASSIFIER_SYSTEM_PROMPT
    assert "KNOWN EDITABLE FIELDS at" in _CLASSIFIER_SYSTEM_PROMPT


def test_classifier_prompt_has_enumerate_map_audit_method():
    """The N-way extraction method (clauses → map → audit) must be present —
    this is what's meant to generalize past the 2-item examples."""
    assert '"clauses"' in _CLASSIFIER_SYSTEM_PROMPT
    assert "ENUMERATE first" in _CLASSIFIER_SYSTEM_PROMPT
    assert "AUDIT before you output" in _CLASSIFIER_SYSTEM_PROMPT


def test_classifier_prompt_has_3_and_4_clause_examples():
    assert "manhattan is fine but also add brooklyn" in _CLASSIFIER_SYSTEM_PROMPT
    assert "bump my budget to 500, and add events too" in _CLASSIFIER_SYSTEM_PROMPT


def test_classifier_prompt_puts_maid_settings_under_maid_not_geo():
    """poi_radius_m / lookback_days are maid Slots (slots.py) owned by "maid"
    (field_owner_registry.py) — the prompt used to list them under `geo:`,
    so an edit to either resolved to a geo slot and rolled back the whole geo
    stage (a fresh Places search) for a maid-only change."""
    geo_block = _CLASSIFIER_SYSTEM_PROMPT[
        _CLASSIFIER_SYSTEM_PROMPT.index("geo:"):_CLASSIFIER_SYSTEM_PROMPT.index("maid:")
    ]
    maid_block = _CLASSIFIER_SYSTEM_PROMPT[
        _CLASSIFIER_SYSTEM_PROMPT.index("maid:"):_CLASSIFIER_SYSTEM_PROMPT.index("campaign:")
    ]
    assert "poi_radius_m" not in geo_block and "lookback_days" not in geo_block
    assert "poi_radius_m" in maid_block and "lookback_days" in maid_block


def test_classifier_prompt_distinguishes_audience_narrowing_from_a_new_poi_type():
    """The leaf-value pairing rule ("coffee lovers" -> poi_types + an angle)
    used to be the closest few-shot to "only people who go twice a week" at
    maid_confirm_results, so a pure frequency/day narrowing over an audience
    that already exists got mapped to a NEW geo poi_types entry — which rolled
    back geo (a fresh Places search) and re-asked poi_confirm for a reply that
    named no place at all."""
    assert "only people who go twice a week" in _CLASSIFIER_SYSTEM_PROMPT
    assert "just the weekend crowd" in _CLASSIFIER_SYSTEM_PROMPT
    for phrase in ("only people who go twice a week", "just the weekend crowd"):
        # rindex, not index: both phrases are named twice — once in the rule's
        # own prose, once as the few-shot's user reply — and it's the latter
        # (later in the prompt) whose following JSON this test checks.
        start = _CLASSIFIER_SYSTEM_PROMPT.rindex(phrase)
        example = _CLASSIFIER_SYSTEM_PROMPT[start:start + 250]
        assert '"target_field":"audience_filter"' in example
        assert "poi_types" not in example
        assert "deterministic_subtype" not in example


@pytest.mark.asyncio
async def test_classifier_audience_narrowing_payload_carries_no_geo_extras():
    """Post-validation must not invent anything the model didn't emit: given
    the payload shape the new prompt asks for (audience_filter alone, no
    poi_types/deterministic_subtype extras), the result stays exactly that —
    the classifier layer is not what would re-introduce the geo rollback."""
    payload = {
        "lane": "edit", "target_field": "audience_filter",
        "new_value": {"min_visits": 2}, "confidence": 0.9,
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent(
            "only people who go twice a week", "maid_confirm_results")
    assert intent.target_field == "audience_filter"
    assert intent.new_value == {"min_visits": 2}
    assert intent.extra_edits == []


@pytest.mark.asyncio
async def test_classifier_ignores_clauses_scratch_key():
    """The whole `clauses` mechanism depends on Pydantic v2's default
    extra='ignore' silently dropping an unknown JSON key. Regression: if a
    future `model_config` change starts forbidding extra keys, every
    classifier response breaks — this test would catch it directly."""
    payload = {
        "clauses": ["manhattan is fine", "add brooklyn", "add starbucks"],
        "lane": "edit", "target_field": "location", "new_value": "Brooklyn",
        "is_append": True, "answer_value": "Manhattan is fine", "confidence": 0.9,
        "extra_edits": [{"target_field": "deterministic_subtype",
                          "new_value": "competitor_brand", "is_append": True}],
    }
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent(
            "manhattan is fine but also add brooklyn and also add starbucks in those areas",
            "geo_location_confirmation",
        )
    assert not hasattr(intent, "clauses")
    assert intent.answer_value == "Manhattan is fine"
    assert intent.target_field == "location"
    assert intent.extra_edits[0].target_field == "deterministic_subtype"


@pytest.mark.asyncio
async def test_wizard_interrupt_three_clause_reply_all_land():
    """The exact repro: answer + primary edit + one extra_edits entry on a
    field never before filled (deterministic_subtype, not in 'Already set').
    All three must land — this is what the guard fix + example teach."""
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="location", new_value="Brooklyn", is_append=True,
        answer_value="Manhattan is fine", confidence=0.9,
        extra_edits=[ExtraEdit(target_field="deterministic_subtype",
                                new_value="competitor_brand", is_append=True)],
    )
    with _loop_harness(
        [intent],
        ["manhattan is fine but also add brooklyn and also add starbucks in those areas"],
    ):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_location_confirmation",
            context="test",
            state=_resumed_state("geo_location_confirmation"),
        )
    assert result == "Manhattan is fine"
    # Cross-step append on a list-typed field union-merges into a list, even
    # for a single item — see _union_merge_preserve_order.
    assert result.edits.get("deterministic_subtype") == ["competitor_brand"]


@pytest.mark.asyncio
async def test_wizard_interrupt_four_clause_reply_all_four_channels_land():
    """Stress case: answer + question + primary edit + extra edit, all at
    once, none of them colliding with the active field. Proves the
    composite machinery isn't capped at 3 either."""
    from app.graph.wizard_helpers import wizard_interrupt

    intent = ResumeIntent(
        lane="edit", target_field="budget", new_value="500", is_append=False,
        answer_value="chicago works", question_text="what is a POI", confidence=0.9,
        extra_edits=[ExtraEdit(target_field="deterministic_subtype", new_value="event_based", is_append=True)],
    )
    with _loop_harness(
        [intent],
        ["chicago works, what's a POI, also bump my budget to 500, and add events too"],
    ) as mock_narrate:
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="geo_collect_locations",
            context="test",
            state=_resumed_state("geo_collect_locations"),
        )
    assert result == "chicago works"
    assert result.edits.get("budget") == "500"
    assert result.edits.get("deterministic_subtype") == ["event_based"]
    roles = [c.args[0].role for c in mock_narrate.await_args_list]
    assert "sidebar_answer" in roles


@pytest.mark.asyncio
async def test_wizard_interrupt_audience_panel_commit_is_an_edit_not_a_confirm():
    """The layer-builder's structured commit is JSON, which `is_sentinel_resume`
    reads as "confirm" — so without the panel hook a filter edit would be taken
    as a yes and the audience never narrowed. It must land in the edit lane with
    NO classifier call (the mock has no canned result, so a call would raise),
    and — in LEGACY loop mode too (``_single_interrupt`` False/absent, this
    test's default via ``_resumed_state``) — return to the caller on the
    control-key edit alone, with no second reply needed.

    That "returns immediately" part matters more than it looks: before the fix
    a control-key edit with no matching `rerun_on_edit` field (audience_filter
    is a control key, never a slot) fell through to the loop tail's `continue`,
    which called `interrupt()` a SECOND time within the same node execution. In
    real LangGraph that pauses the graph again before this function ever
    returns, discarding the stashed `_audience_filter_patch` entirely — a
    mocked `interrupt()` that just returns canned values back-to-back hides
    this (it never actually re-pauses), so the old code looked fine under test
    while silently dropping the edit in production. Only ONE
    `interrupt_values` entry is supplied below — a regression back to the old
    behaviour would raise `StopIteration` reaching for a second one instead of
    returning here.
    """
    import json

    from app.graph.wizard_helpers import wizard_interrupt

    commit = json.dumps({"action": "audience_filter_patch", "patch": {
        "groups": ["gym", "coffee shop"], "min_distinct_groups": 2, "op": None,
    }})
    with _loop_harness([], [commit]):
        result = await wizard_interrupt(
            writer=lambda _ev: None,
            step_key="maid_confirm_results",
            context="test",
            state=_resumed_state("maid_confirm_results"),
        )
    assert result.answered is False  # a stashed edit, not the step's real answer
    assert result.edits["_audience_filter_patch"] == {
        "groups": ["gym", "coffee shop"], "min_distinct_groups": 2, "op": None,
    }


@pytest.mark.asyncio
async def test_dispatch_audience_patch_is_validated_like_a_panel_patch():
    """A classifier/tool audience patch used to be merged into the stash raw: a
    negative count or a hallucinated key reached `_audience_filter_specs` and was
    evaluated as a silent no-op. Values are checked and unknown keys dropped, but
    a key set to None survives — that is how a patch clears a filter part."""
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="audience_filter", confidence=0.95,
        new_value={"min_visits": 3, "cadence_days": -7, "made_up_key": "x", "days_of_week": None},
    )
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state={}, writer=lambda _ev: None,
            pending={}, cfg={"field": "audience_filter"}, edits=edits,
        )
    assert reframe is False
    assert edits["_audience_filter_patch"] == {"min_visits": 3, "days_of_week": None}


@pytest.mark.asyncio
async def test_dispatch_audience_patch_with_nothing_valid_reframes():
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(
        lane="edit", target_field="audience_filter", confidence=0.95,
        new_value={"made_up_key": "x", "cadence_days": -7},
    )
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state={}, writer=lambda _ev: None,
            pending={}, cfg={"field": "audience_filter"}, edits=edits,
        )
    assert reframe is True
    assert "_audience_filter_patch" not in edits


@pytest.mark.parametrize("value,det,expect", [
    ("12 Main St, Toronto", "store_set", "store_addresses"),
    (["12 Main St, Toronto", "9 King St W, Toronto"], "store_set", "store_addresses"),
    ("12 Main St, Toronto", "competitor_nearby", "competitor_address"),
    ("Toronto", "store_set", None),                        # a bare city stays the market hint
    ("90210", "store_set", None),
    (["12 Main St, Toronto", "Laval"], "store_set", None),  # mixed -> never guess
    ("12 Main St, Toronto", "store_set,category", None),    # a market angle is running: location is real
    ("12 Main St, Toronto", "category", None),
    ("12 Main St, Toronto", "", None),
])
def test_location_address_edit_on_store_run_is_a_store_address_edit(value, det, expect):
    from app.graph.builder.slots import store_anchor_field_for_location

    assert store_anchor_field_for_location(value, det) == expect


@pytest.mark.asyncio
async def test_dispatch_retargets_location_address_on_store_run():
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(lane="edit", target_field="location", new_value=["12 Main St, Toronto"],
                          is_append=True, confidence=0.99)
    state = {"campaign_builder_state": {"filled": {"det_type": "store_set"}}}
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _ev: None,
            pending={}, cfg={"field": "geo_poi_types"}, edits=edits,
            edit_base={"store_addresses": ["1 Old Rd, Montreal"]},
        )
    assert reframe is False
    assert "location" not in edits
    assert edits["store_addresses"] == ["1 Old Rd, Montreal", "12 Main St, Toronto"]


@pytest.mark.asyncio
async def test_dispatch_keeps_location_edit_when_it_is_a_real_market():
    from app.graph.wizard_helpers import _dispatch_edit_intent

    intent = ResumeIntent(lane="edit", target_field="location", new_value="Toronto", confidence=0.99)
    state = {"campaign_builder_state": {"filled": {"det_type": "store_set"}}}
    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        await _dispatch_edit_intent(
            intent=intent, state=state, writer=lambda _ev: None,
            pending={}, cfg={"field": "geo_poi_types"}, edits=edits, edit_base={},
        )
    assert "location" in edits and "store_addresses" not in edits


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "meta_ad_account_id", "meta_pixel_id", "meta_page_id", "creative_upload", "meta_access_token",
])
async def test_media_field_edit_gets_the_specific_meta_account_refusal(field):
    """Ad account / Page / pixel come from the OAuth connection. These used to be
    dropped at the ack gate and labelled `unhandled` ("I can't act on that yet"),
    so the written `meta_account` copy was unreachable."""
    from app.graph.field_owner_registry import EDIT_BLOCK_MESSAGES
    from app.graph.wizard_helpers import _dispatch_edit_intent

    payload = {"lane": "edit", "target_field": field, "new_value": "act_123", "confidence": 0.95}
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("use ad account act_123", "geo_pois_confirmation")
    assert intent.lane == "edit" and intent.target_field == field

    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()) as mock_narrate:
        reframe = await _dispatch_edit_intent(
            intent=intent, state={}, writer=lambda _ev: None,
            pending={}, cfg={"field": "geo_pois_confirmation"}, edits=edits,
        )
    assert reframe is False
    assert edits == {}  # refused: nothing stashed, so nothing can reach the apply gate
    assert mock_narrate.await_count == 1
    utterance = mock_narrate.await_args.args[0]
    assert utterance.fallback == EDIT_BLOCK_MESSAGES["meta_account"]


# ── a stated confidence of exactly 0.0 on an otherwise complete edit ─────────

@pytest.mark.asyncio
async def test_edit_stated_at_zero_confidence_is_treated_as_unstated_not_as_no_trust():
    """The model sometimes writes "confidence":0.0 on a reply it classified
    correctly, and the edit was then refused as low-confidence."""
    from app.graph.resume_router import _UNSTATED_CONFIDENCE
    from app.graph.wizard_helpers import _dispatch_edit_intent
    from app.core.config import settings

    payload = {"lane": "edit", "target_field": "poi_selection",
               "new_value": {"op": "keep", "n": 10, "scope": "all"}, "confidence": 0.0}
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("just the top 10", "geo_pois_confirmation")
    assert intent.confidence == _UNSTATED_CONFIDENCE >= settings.RESUME_EDIT_MIN_CONFIDENCE

    edits: dict = {}
    with patch("app.graph.wizard_helpers.narrate", new=AsyncMock()):
        reframe = await _dispatch_edit_intent(
            intent=intent, state={}, writer=lambda _ev: None,
            pending={}, cfg={"field": "geo_pois_confirmation"}, edits=edits,
        )
    assert reframe is False and edits["_poi_selection"]


@pytest.mark.asyncio
async def test_zero_confidence_never_clears_the_cost_bearing_floor():
    """A re-buy of vendor data (location, radius, lookback) needs a real, stated
    confidence — an unreliable 0.0 must still be refused there."""
    from app.graph.builder.edits import edit_confidence_floor
    from app.graph.resume_router import _UNSTATED_CONFIDENCE
    from app.core.config import settings

    for field in ("location", "geo_locations", "poi_radius_m", "lookback_days", "store_addresses"):
        assert _UNSTATED_CONFIDENCE < edit_confidence_floor(field, settings.RESUME_EDIT_MIN_CONFIDENCE), field


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"lane": "handoff", "question_text": "undo that", "confidence": 0.0},   # can undo/abort: stays strict
    {"lane": "reject", "confidence": 0.0},
    {"lane": "query", "question_text": "what's a POI", "confidence": 0.0},
    {"lane": "edit", "confidence": 0.0},                                    # names no target
])
async def test_zero_confidence_elsewhere_still_means_zero(payload):
    with _mock_llm_returning(payload):
        intent = await classify_resume_intent("whatever", "geo_pois_confirmation")
    assert intent.confidence == 0.0
