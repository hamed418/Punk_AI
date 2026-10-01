"""
tests/test_publish_mode_routing.py
──────────────────────────────────
The three publish modes, as a routing contract.

``publish_mode`` is asked right after Meta is connected and decides how much of
the campaign Punk builds:

  self    → export the audience into the user's ad account, then stop.
  guide   → the full campaign editor. No intake form: business name/what-you-
            sell come from the entry gate upstream, and generate_brief infers
            the objective when the user never states one.
  express → the same acts, plus the intake form up front — its editor locks
            the campaign/ad-set panes, so budget/flight/Page/objective have
            nowhere else to be asked.

The sequencing lives in ``_next_step``/``_stage_acts``, not in the planner
prompt, so it is asserted here as an exact op/ask ordering per mode. The thing
most worth pinning: `self` must never reach the media stage (there is no
campaign to publish), and `activate` must never run without the go_live_confirm
preview gate in front of it.
"""

from __future__ import annotations

import pytest

import app.graph.builder.builder_node as bn
from app.graph.builder.slots import GATE_SLOTS, SLOTS


def _walk(mode: str, limit: int = 30) -> list[str]:
    """Drive _next_step to exhaustion, answering every ask and running every act.

    Starts with geo+maid already complete — this contract is only about what
    happens after the audience exists.
    """
    filled: dict = {}
    if mode:
        filled["publish_mode"] = mode
    bs: dict = {"filled": filled, "ops_done": [], "stages_complete": ["geo", "maid"]}
    steps: list[str] = []
    for _ in range(limit):
        stage = bn._current_stage(bs, {})
        if stage == "done":
            return steps
        step = bn._next_step(bs, stage)
        if step is None:
            bs["stages_complete"] = sorted({*bs["stages_complete"], stage})
            continue
        if step["kind"] == "act":
            steps.append(f"act:{step['operation']}")
            bs["ops_done"] = sorted({*bs["ops_done"], step["operation"]})
        else:
            steps.append(f"ask:{step['slot']}")
            filled[step["slot"]] = "answered"
    raise AssertionError(f"{mode!r} did not finish in {limit} steps: {steps}")


# No publish_confirm ask: the plan editor's own Publish button is the
# confirmation, and publish only builds PAUSED objects — go_live_confirm is the
# gate that matters. See test_publish_has_no_gate_at_all.
_AFTER_INTAKE = [
    "act:generate_brief",
    "act:resolve_meta",
    "act:generate_meta_json",
    "ask:plan_confirm",
    "act:publish",
    "ask:go_live_confirm",
    "act:activate",
]


def test_self_publish_exports_the_audience_and_stops():
    assert _walk("self") == ["act:connect_meta", "act:export_audience"]


def test_express_asks_the_intake_form_guide_does_not():
    """Both modes run the exact same acts from generate_brief on — the only
    routing difference between them is whether campaign_intake is asked at
    all (skipped for guide, see slots.py's not_when on that slot)."""
    assert _walk("express") == ["act:connect_meta", "ask:campaign_intake", *_AFTER_INTAKE]
    assert _walk("guide") == ["act:connect_meta", *_AFTER_INTAKE]


def test_mode_is_asked_before_anything_is_built():
    """With no mode chosen yet the very next ask is the mode itself — nothing
    downstream may run first, because `self` would throw that work away."""
    bs = {"filled": {}, "ops_done": ["connect_meta"], "stages_complete": ["geo", "maid"]}
    assert bn._next_step(bs, "campaign") == {"kind": "ask", "slot": "publish_mode"}


def test_publish_has_no_gate_at_all():
    """"Ready to publish?" was the same click the editor's Publish button already
    was, and publish only builds PAUSED objects. Even the audience-refused case is
    answered without asking now — see test_publish_failure_recovery."""
    from app.graph.builder.slots import GATE_SLOTS, SLOTS

    assert "publish" not in bn._OP_GATE
    assert "publish_confirm" not in SLOTS and "publish_confirm" not in GATE_SLOTS
    # go_live_confirm is the gate that survived — it is the one before spend.
    assert bn._gate_pending("go_live_confirm", {"publish_mode": "guide"}) is True


def test_activate_is_gated_behind_the_preview():
    """The campaign is already in Meta and PAUSED at this point, so this gate is
    the last thing between it and live spend."""
    assert bn._OP_GATE["activate"] == "go_live_confirm"
    assert bn._GATE_PREREQ_OP["go_live_confirm"] == "publish"
    assert "go_live_confirm" in GATE_SLOTS
    assert SLOTS["go_live_confirm"].required is False


def test_self_publish_skips_every_campaign_and_media_step():
    filled = {"publish_mode": "self"}
    assert bn._stage_acts("campaign", filled) == ("export_audience",)
    assert bn._stage_acts("media", filled) == ()
    # No plan to approve, so the campaign stage closes on the export alone.
    assert bn._stage_exit_gate("campaign", filled) is None


def test_unanswered_mode_does_not_filter_earlier_stages():
    """_stage_acts is consulted for every stage, including the ones that run
    before the question is asked — an empty mode must not empty them."""
    assert bn._stage_acts("geo", {}) == ("geo_discover",)
    assert bn._stage_acts("maid", {}) == ("maid_query",)


@pytest.mark.asyncio
async def test_a_failed_export_leaves_the_builder_instead_of_retrying_forever(monkeypatch):
    """`export_audience` has no confirmation gate in front of it, so returning to
    builder_plan on failure handed the same act straight back and re-ran the failing
    Meta call every iteration. The failure code is what ends the turn."""
    from app.graph.builder.executors import media as media_exec

    async def _fail(*a, **k):
        raise media_exec.MetaPublishError("Meta said no.", step="custom_audience")

    monkeypatch.setattr(bn, "get_writer", lambda: (lambda _event: None))
    monkeypatch.setattr(media_exec, "export_audience_only", _fail)

    state = {
        "user_id": None,
        "user_info": {"meta_access_token": "tok", "meta_ad_account_id": "act_1"},
        "campaign_builder_state": {
            "filled": {"publish_mode": "self"},
            "ops_done": ["connect_meta"],
            "stages_complete": ["geo", "maid"],
            "next_action": {"kind": "act", "operation": "export_audience"},
        },
    }
    out = await bn.builder_act(state, {})

    assert out["wizard_failure"] == "campaign_audience_export_failed"
    # Undone, so a user-driven retry re-runs it — but only when the user asks.
    assert "export_audience" not in (out["campaign_builder_state"].get("ops_done") or [])


def test_the_mode_question_warns_when_the_account_cannot_hold_an_audience():
    """`self` is the one mode that cannot work on an ad account outside a Business.
    Say so at the question — but keep all three options: the widget answers by
    index, so removing one would remap every numeric pick."""
    import asyncio

    slot = SLOTS["publish_mode"]

    blocked = asyncio.run(bn._enrich_slot_ask(
        slot, {"audience_blocked_reason": "no Business"}, {}, None,
    ))
    assert "Business Manager" in blocked["prompt_override"]
    assert "options_override" not in blocked

    assert asyncio.run(bn._enrich_slot_ask(slot, {}, {}, None)) == {}


@pytest.mark.parametrize(
    "answer,expected",
    [
        # Current labels (prompts_registry.PUBLISH_MODE_OPTIONS).
        ("Export audience to Meta — Finish setting up the campaign in Meta Ads Manager", "self"),
        ("Set up campaign manually in Punk — Set campaign type, budget, optimization and other parameters through Punk", "guide"),
        # A client that rewrites the em-dash must still land on the right branch.
        ("Let Punk setup the campaign - Let Punk's expert agents create and optimize your entire campaign", "express"),
        # Pre-rename labels — a session checkpointed before the copy change is
        # still paused on the old option list and answers with its text.
        ("Publish It Myself — Build the audience only. I'll finish the campaign setup in Meta.", "self"),
        ("Guide Me — Punk pre-fills your campaign settings", "guide"),
        ("Do It For Me - Punk configures your campaign", "express"),
        # Numeric picks come back from the option widget.
        ("1", "self"),
        ("3", "express"),
        ("something else entirely", ""),
    ],
)
def test_mode_answer_normalization(answer, expected):
    assert bn._normalize_publish_mode(answer) == expected


def test_publish_mode_options_are_well_formed():
    """Each label has exactly one em-dash — WidgetOptionSelection splits on a
    bare '—' and would silently drop everything after a second one."""
    from app.graph.prompts_registry import PUBLISH_MODE_OPTIONS

    assert len(PUBLISH_MODE_OPTIONS) == 3
    for option in PUBLISH_MODE_OPTIONS:
        assert option.count("—") == 1
        assert " — " in option
