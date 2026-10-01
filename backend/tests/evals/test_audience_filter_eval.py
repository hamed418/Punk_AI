"""
tests/evals/test_audience_filter_eval.py
──────────────────────────────────────────
Real-Gemini accuracy eval for the audience_filter extraction prompts — the
`audience_filter` entry inside EXTRACTION_FIELDS_SPEC (prompts.py, the entry/
first-mention path) AND the AUDIENCE LAYERING section of the resume-router
classifier prompt (resume_router.py, the mid-build EDIT path). Hits the live
model — gated behind `pytest -m eval` (pytest.ini's `addopts = -m "not eval"`),
never runs per-commit, costs real API calls.

This closes the real gap the role-inference feature exposed: there was no
live-model eval for audience_filter extraction AT ALL before this file —
test_ceo_prompts.py explicitly does not call the LLM (it hardcodes the spec
each prompt SHOULD produce and only exercises the evaluator downstream). The
prompt text deciding whether "barbershop owners, inside 40+ hrs/week" resolves
to the right AudienceFilter was untested.

Asserts the resolved SPEC's field family, never exact numeric values (a model
answering min_weekly_hours=32 vs 30, or min_open_day_share=0.55 vs 0.5, is not
a regression — see the ~75%-of-stated-hours note in AUDIENCE_FILTER_ROLE_GUARD
for why an exact number is not even the right target). A regression here means
a role-targeting prompt that used to resolve to a real predicate now resolves
to nothing, or to the wrong FIELD FAMILY (dwell vs presence-pattern vs
cross-location) — silently narrowing to zero, or to the wrong audience shape,
is what this corpus exists to catch before it ships.

Both extraction paths are covered because they diverged once already: the
edit path lacked the entry path's role guard entirely (see
AUDIENCE_FILTER_ROLE_GUARD's docstring in prompts.py) until this feature
closed it structurally — this file is what re-proves they stay in sync.

Run: `cd backend && PYTHONIOENCODING=utf-8 pytest -m eval tests/evals -v`
"""
from __future__ import annotations

import pytest

from app.graph.nodes import extract_user_info_from_text
from app.graph.resume_router import classify_resume_intent, classify_resume_intent_tools

pytestmark = pytest.mark.eval

_STEP = "maid_confirm_results"


def _edit_state() -> dict:
    """Minimal state for the edit-path classifier — an audience is already on
    screen, matching every AUDIENCE LAYERING worked example's own framing."""
    return {"campaign_builder_state": {"geo_data": {"maid_count": 500}}}


# ── Assertions: field FAMILY, never exact values ────────────────────────────

def _has_presence_field(spec: dict) -> bool:
    return any(
        spec.get(k) is not None
        for k in ("min_open_day_share", "min_intraday_span_min", "min_days_present")
    )


def _assert_role_no_duration(spec: dict) -> None:
    """"owners"/"staff"/"managers, not customers" with NO stated duration ->
    a presence-pattern field, NOT min_weekly_hours (that needs a real
    stated duration and the phrase alone isn't one — the whole point of
    AUDIENCE_FILTER_ROLE_GUARD)."""
    assert _has_presence_field(spec), f"expected a presence-pattern field, got {spec}"
    assert spec.get("min_weekly_hours") is None, (
        f"min_weekly_hours set with no stated duration: {spec}"
    )
    assert spec.get("min_dwell_min") is None, f"min_dwell_min set with no stated duration: {spec}"


def _assert_role_with_duration(spec: dict) -> None:
    """A REAL stated duration ("40+ hrs/week") -> min_weekly_hours. The
    presence-pattern fields are for when NO duration was stated — this is
    the other half of the contrast, and must not regress the other way."""
    assert spec.get("min_weekly_hours"), f"expected min_weekly_hours, got {spec}"


def _assert_cross_location_recurrence(spec: dict) -> None:
    """"multiple locations of the same chain every week" -> min_distinct_pois
    + cadence_days — a THIRD signal, not dwell and not single-location
    presence (no single-location claim was made at all)."""
    assert (spec.get("min_distinct_pois") or 0) >= 2, f"expected min_distinct_pois>=2, got {spec}"
    assert spec.get("cadence_days"), f"expected cadence_days, got {spec}"
    assert spec.get("min_weekly_hours") is None, f"min_weekly_hours set: {spec}"
    assert not _has_presence_field(spec), f"a presence-pattern field set: {spec}"


def _assert_invert_role(spec: dict) -> None:
    """"drop the staff"/"not the owners" with no duration -> invert + a
    presence-pattern field, not invert + min_weekly_hours."""
    assert spec.get("invert") is True, f"expected invert=true, got {spec}"
    assert _has_presence_field(spec), f"expected a presence-pattern field alongside invert, got {spec}"


def _assert_no_role_field(spec: dict) -> None:
    """A control with no role language at all must not pick up a role field
    just because the corpus is about role targeting."""
    assert not _has_presence_field(spec), f"unexpected presence-pattern field: {spec}"
    assert spec.get("min_weekly_hours") is None, f"unexpected min_weekly_hours: {spec}"


# ── The four role-targeting prompts from the brief, plus controls ──────────

ENTRY_CASES = [
    pytest.param(
        "I created scheduling software for barbershops. Target people who are "
        "inside a barbershop 40+ hours a week — those are the owners and "
        "managers, not the customers.",
        _assert_role_with_duration, id="barbershop-owners-stated-hours",
    ),
    pytest.param(
        "I made a booking tool for barbershops. My users are barbers, not "
        "people getting their hair cut. Find me people who spend all day "
        "inside barbershops.",
        _assert_role_no_duration, id="barbershop-barbers-no-duration",
    ),
    pytest.param(
        "I sell franchise management software. Target people who show up at "
        "multiple locations of the same restaurant chain every week — those "
        "are the managers, not the customers.",
        _assert_cross_location_recurrence, id="franchise-managers-cross-location",
    ),
    pytest.param(
        "I run a wholesale coffee roasting company. Target people who own "
        "cafés in Chicago.",
        _assert_role_no_duration, id="cafe-owners-no-duration",
    ),
    # Control: a plain frequency ask should not pick up any role field.
    pytest.param(
        "people who show up 3+ times in the last two weeks",
        _assert_no_role_field, id="control-plain-frequency",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("message,check", ENTRY_CASES)
async def test_entry_extraction_resolves_role_spec(message, check):
    """The FIRST-MENTION path — prompts.py's EXTRACTION_FIELDS_SPEC."""
    result = await extract_user_info_from_text(message)
    spec = result.get("audience_filter")
    assert isinstance(spec, dict), f"{message!r} -> audience_filter={spec!r} (expected a spec dict)"
    check(spec)


EDIT_CASES = [
    pytest.param(
        "keep the ones who are inside 40+ hours a week, those are the owners",
        _assert_role_with_duration, id="edit-owners-stated-hours",
    ),
    pytest.param(
        "just the barbers who spend all day in there, not customers",
        _assert_role_no_duration, id="edit-barbers-no-duration",
    ),
    pytest.param(
        "only people who hit multiple locations of the chain every week — the managers",
        _assert_cross_location_recurrence, id="edit-managers-cross-location",
    ),
    pytest.param(
        "drop the staff, just keep the actual customers",
        _assert_invert_role, id="edit-drop-staff-invert",
    ),
    pytest.param(
        "just the regulars — 3 or more visits in the last two weeks",
        _assert_no_role_field, id="edit-control-plain-frequency",
    ),
    pytest.param(
        "only people who go twice a week",
        lambda spec: _assert_twice(spec), id="edit-twice-a-week",
    ),
]


def _assert_twice(spec: dict) -> None:
    """"twice a week" is a visit COUNT (min_visits=2 over a window), which is what
    the prompt teaches. The tools backend once answered with cadence_days=3.5 — a
    spacing rule that silently changes who qualifies."""
    assert spec.get("min_visits") == 2, f"expected min_visits=2, got {spec}"
    assert not spec.get("cadence_days"), f"spacing rule where a count was asked: {spec}"


@pytest.mark.asyncio
@pytest.mark.parametrize("message,check", EDIT_CASES)
async def test_edit_extraction_resolves_role_spec(message, check):
    """The MID-BUILD EDIT path — resume_router.py's AUDIENCE LAYERING
    section. Must resolve the SAME field family the entry path does for the
    same underlying ask — this is what proves the two prompts stay in sync
    now that they share AUDIENCE_FILTER_ROLE_GUARD."""
    intent = await classify_resume_intent(message, _STEP, _edit_state())
    assert intent.lane == "edit", f"{message!r} -> lane={intent.lane!r} (expected edit)"
    assert intent.target_field == "audience_filter", (
        f"{message!r} -> target_field={intent.target_field!r}"
    )
    spec = intent.new_value
    assert isinstance(spec, dict), f"{message!r} -> new_value={spec!r} (expected a spec dict)"
    check(spec)


@pytest.mark.asyncio
@pytest.mark.parametrize("message,check", EDIT_CASES)
async def test_edit_extraction_resolves_role_spec_tools_backend(message, check):
    """The same corpus through `classify_resume_intent_tools` — the two backends
    must resolve the same ask to the same field family, or flipping
    RESUME_ROUTER_TOOLCALLING on silently changes who an audience contains."""
    intent = await classify_resume_intent_tools(message, _STEP, _edit_state())
    assert intent.lane == "edit", f"{message!r} -> lane={intent.lane!r} (expected edit)"
    assert intent.target_field == "audience_filter", (
        f"{message!r} -> target_field={intent.target_field!r}"
    )
    spec = intent.new_value
    assert isinstance(spec, dict), f"{message!r} -> new_value={spec!r} (expected a spec dict)"
    check(spec)


# ── "and"-list: singular items = intersection, all-plural = union ───────────
# Threads 23f83f99 (bridal) / 0aa5fa49 (dog gear): "visited a X, a Y, and a Z"
# means one visit to EACH, while "gyms, cafes and pilates studios" sweeps a TYPE
# of place (union). The rule is taught in the prompt (no code backstop); these
# cases prove it on the entry path AND both edit backends. Field family only —
# op — never window_days/min_visits, which other cases already cover.

def _assert_intersection(spec: dict) -> None:
    assert spec.get("op") == "intersection", f"expected op=intersection, got {spec}"
    assert len(spec.get("groups") or []) >= 2, f"expected >=2 groups, got {spec}"


def _assert_union(spec: dict) -> None:
    assert spec.get("op") in (None, "union"), f"expected union (no op), got {spec}"


_ENTRY_LIST_CASES = [
    pytest.param(
        "I run a bridal boutique in Nashville. Target women 24-38 who visited a "
        "wedding venue, a jeweler, and a bridal show in the last 30 days.",
        _assert_intersection, id="bridal-singular-list",
    ),
    pytest.param(
        "I sell custom dog gear online. Target people who visited a vet clinic, "
        "PetSmart, and a dog park within the last 15 days in Denver.",
        _assert_intersection, id="dog-gear-no-all-word",
    ),
    pytest.param(
        "Target people who visited Starbucks, Nike and Adidas in Chicago.",
        _assert_intersection, id="brand-list",
    ),
    pytest.param(
        "Target people who visited a vet clinic and dog parks in Denver.",
        _assert_intersection, id="mixed-singular-plural",
    ),
    pytest.param(
        "Target people who visited both a gym and a spa in Austin.",
        _assert_intersection, id="explicit-both-control",
    ),
    pytest.param(
        "Target people who visited gyms, cafes and pilates studios in Austin.",
        _assert_union, id="all-plural-list",
    ),
    pytest.param(
        "Target people who visited a gym or a cafe in Austin.",
        _assert_union, id="or-list",
    ),
    pytest.param(
        "Target people who visited any of a gym, a spa or a salon in Austin.",
        _assert_union, id="any-of-list",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("message,check", _ENTRY_LIST_CASES)
async def test_entry_and_list_op(message, check):
    result = await extract_user_info_from_text(message)
    spec = result.get("audience_filter") or {}
    check(spec)


# Edit path: a narrowing reply, so groups must be named in the reply itself.
_EDIT_LIST_CASES = [
    pytest.param(
        "only people who went to a gym, a coffee shop, and a bookstore",
        _assert_intersection, id="edit-singular-list",
    ),
    pytest.param(
        "only people who went to gyms, cafes and bookstores",
        _assert_union, id="edit-all-plural-list",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("message,check", _EDIT_LIST_CASES)
async def test_edit_and_list_op(message, check):
    intent = await classify_resume_intent(message, _STEP, _edit_state())
    assert intent.target_field == "audience_filter", f"{message!r} -> {intent.target_field!r}"
    check(intent.new_value or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("message,check", _EDIT_LIST_CASES)
async def test_edit_and_list_op_tools_backend(message, check):
    intent = await classify_resume_intent_tools(message, _STEP, _edit_state())
    assert intent.target_field == "audience_filter", f"{message!r} -> {intent.target_field!r}"
    check(intent.new_value or {})
