"""
tests/test_publish_failure_recovery.py
──────────────────────────────────────
Where a failed publish leaves the user, now that nothing asks first.

There is no publish gate at all: the plan editor's own Publish button is the
confirmation, publish only builds PAUSED objects, and ``go_live_confirm`` is the
only thing between the campaign and spend. So a failure cannot be answered by
re-asking a widget — it either reopens the plan editor, or (for the one failure
the editor has no control for) degrades itself and publishes again.

Also covers the compliance note the plan owes the user when placements get
narrowed.
"""
from __future__ import annotations

import pytest

from app.graph.builder.builder_node import (
    _PUBLISH_RETRY_LIMIT,
    _apply_publish_failure,
    _audience_notice,
    _next_step,
    _publish_is_terminal,
    _publish_terminal_message,
)
from app.graph.builder.executors.media import MetaPublishError
from app.services.meta_ads import MetaAdsError


# ── a failure that must stop offering a retry ────────────────────────────────
#
# A Meta #3 ("application does not have the capability to make this API call")
# on /adimages is not fixable by trying again, so it must not loop.


def _fail(step: str, code: int | None = None) -> MetaPublishError:
    exc = MetaPublishError("boom", step=step)
    if code is not None:
        exc.__cause__ = MetaAdsError("OAuthException: no capability", code=code)
    return exc


@pytest.mark.parametrize("code", [3, 10, 190, 200])
def test_permission_failures_are_terminal_on_the_first_try(code):
    terminal, permission = _publish_is_terminal(_fail("media_upload", code), {})
    assert terminal and permission


def test_a_transient_failure_retries_until_the_limit():
    """A flaky upload deserves another go; the same step failing forever does not."""
    fails: dict = {}
    exc = _fail("media_upload")  # no cause → not a permission problem
    outcomes = [_publish_is_terminal(exc, fails) for _ in range(_PUBLISH_RETRY_LIMIT)]
    assert [t for t, _ in outcomes[:-1]] == [False] * (_PUBLISH_RETRY_LIMIT - 1)
    assert outcomes[-1] == (True, False)


def test_custom_audience_is_never_terminal():
    """The next attempt is a genuinely different one — it drops the audience — so
    it must survive both the permission check and the retry cap."""
    fails: dict = {}
    for _ in range(_PUBLISH_RETRY_LIMIT + 2):
        assert _publish_is_terminal(_fail("custom_audience", 200), fails) == (False, False)


def test_a_plan_the_user_can_edit_does_not_burn_the_retry_allowance():
    """A rejection that reopens the editor with the offending control marked is
    answered by a DIFFERENT plan, not the same one again. Counting those spent
    the whole allowance on three typos and ended the session."""
    fails: dict = {}
    for step in ("preflight_adset", "ad_creative_rejected"):
        for _ in range(_PUBLISH_RETRY_LIMIT + 2):
            assert _publish_is_terminal(_fail(step), fails) == (False, False)


def test_a_permission_failure_is_still_terminal_on_a_plan_fixable_step():
    """No edit to the plan fixes a missing scope."""
    assert _publish_is_terminal(_fail("preflight_adset", 200), {}) == (True, True)


def test_the_terminal_message_never_invites_a_retry():
    msg = _publish_terminal_message(_fail("media_upload", 3), permission=True)
    assert "keep failing" in msg
    # The user's money is the first thing they will worry about.
    assert "PAUSED" in msg


# ── where a failed publish leaves the user ────────────────────────────────────


def _fail_state(step: str, code: int | None = None, **plan_errors):
    bs = {"stages_complete": ["campaign", "media", "geo"], "publish_fail_counts": {step: 2}}
    filled = {"plan_confirm": "{}"}
    exc = _fail(step, code)
    exc.plan_errors = plan_errors
    _apply_publish_failure(bs, filled, exc, "Meta said no.")
    return bs, filled


@pytest.mark.parametrize("step", ["ad", "ad_rejected", "media_upload", "activation"])
def test_any_publish_failure_reopens_the_plan_editor(step):
    bs, filled = _fail_state(step)
    # Un-completing the stages is what actually reopens the editor — the client
    # unmounts it on submit and never re-renders it from the transcript.
    assert "campaign" not in bs["stages_complete"]
    assert "media" not in bs["stages_complete"]
    assert "plan_confirm" not in filled
    assert bs["plan_errors"]["__root__"] == "Meta said no."


def test_a_permission_failure_lands_in_the_editor_too():
    """It cannot be fixed by editing the plan, but exiting to the chatbot left the
    user with nowhere to go. The message says what to fix; the editor is where
    they are while they fix it."""
    bs, _ = _fail_state("media_upload", 200)
    assert "campaign" not in bs["stages_complete"]
    assert bs["plan_errors"]["__root__"] == "Meta said no."


def test_the_field_meta_named_survives_alongside_the_banner():
    bs, _ = _fail_state("ad_rejected", **{"adsets[0].ads[0].creative.link": "Bad link."})
    assert bs["plan_errors"] == {
        "adsets[0].ads[0].creative.link": "Bad link.",
        "__root__": "Meta said no.",
    }


def test_a_blocked_audience_degrades_instead_of_asking():
    """Meta refuses a customer-list audience on an ad account outside a Business.
    Nothing in the plan editor fixes that and there is no gate to ask at, so the
    next attempt drops the audience by itself."""
    bs, filled = _fail_state("custom_audience")
    assert bs["publish_audience_blocked"] is True
    assert bs["publish_without_audience"] is True
    assert bs["stages_complete"] == ["campaign", "media", "geo"]   # editor NOT reopened
    assert "plan_errors" not in bs
    assert "plan_confirm" in filled


def test_the_degraded_retry_is_an_act_not_an_ask():
    """The whole point of removing the gate: after the audience failure the next
    step is publishing again, not a question."""
    bs, filled = _fail_state("custom_audience")
    filled["publish_mode"] = "guide"   # already normalized on write, as builder_ask stores it
    bs["filled"] = filled
    assert _next_step(bs, "media") == {"kind": "act", "operation": "publish"}


def test_reopening_the_editor_keeps_the_failure_counters():
    """Every failure reopens the editor now, so clearing the counters here would
    make the retry cap unreachable and the terminal wording would never fire.
    Only a resubmitted plan is a genuinely fresh attempt."""
    bs, _ = _fail_state("media_upload")
    assert bs["publish_fail_counts"] == {"media_upload": 2}


# ── the user has to be told the audience was dropped ─────────────────────────


def test_the_notice_fires_when_a_built_audience_was_not_attached():
    notice = _audience_notice(
        {"publish_without_audience": True, "audience_blocked_reason": "No Business."},
        {"maid_extraction_id": "ext_1"},
    )
    assert notice["dropped"] is True
    assert notice["reason"] == "No Business."
    assert "Business Manager" in notice["fix"]


def test_no_notice_without_an_audience_to_lose():
    """A plan that never built a visitor audience has nothing to disclose — the
    banner would be claiming a loss that never happened."""
    assert _audience_notice({"publish_without_audience": True}, {}) is None
    assert _audience_notice({}, {"maid_extraction_id": "ext_1"}) is None


def test_the_notice_still_explains_itself_without_a_stored_reason():
    """The reason comes from the connect-time check; a publish-time rejection sets
    the flag with no prose behind it, and the banner still has to say why."""
    notice = _audience_notice(
        {"publish_without_audience": True}, {"maid_extraction_id": "ext_1"},
    )
    assert "Business" in notice["reason"]


# ── the plan has to disclose what it changed ──────────────────────────────────


def test_restricted_placements_are_reported_in_compliance_notes():
    """Naming a platform switches delivery off everywhere else. It is inferred
    from LLM prose, so the plan says so rather than letting the user find out
    from where the ads did not appear."""
    from app.graph.meta_spec.builder import build_campaign_tree

    tree = build_campaign_tree(
        user_info={
            "business_name": "Acme", "budget": "100", "campaign_objective": "TRAFFIC",
            "website_url": "https://acme.example", "meta_page_id": "pg_1",
        },
        geo_data={},
        brief={"placement_strategy": "Facebook Feed only — that is where they are"},
        seed_targeting={"geo_locations": {"countries": ["US"]}},
        broad_targeting={"geo_locations": {"countries": ["US"]}},
    )
    notes = " ".join(tree.get("compliance_notes") or [])
    assert "Placements limited to" in notes
    assert "Facebook" in notes
    assert tree["adsets"][0]["targeting"]["publisher_platforms"] == ["facebook"]


def test_automatic_placements_say_nothing():
    """Advantage+ placements is the default and the good answer — no note."""
    from app.graph.meta_spec.builder import build_campaign_tree

    tree = build_campaign_tree(
        user_info={
            "business_name": "Acme", "budget": "100", "campaign_objective": "TRAFFIC",
            "website_url": "https://acme.example", "meta_page_id": "pg_1",
        },
        geo_data={},
        brief={},
        seed_targeting={"geo_locations": {"countries": ["US"]}},
        broad_targeting={"geo_locations": {"countries": ["US"]}},
    )
    notes = " ".join(tree.get("compliance_notes") or [])
    assert "Placements limited to" not in notes
    assert "publisher_platforms" not in tree["adsets"][0]["targeting"]


# ── refusals Punk cannot fix at all ───────────────────────────────────────────
#
# A Terms of Service nobody has accepted, an ad account with no card on it: the
# plan is fine and no control in the editor can touch the problem. Sending the
# user to the editor with a marked field is two wrong moves at once — but the
# editor still has to open, because its Publish button is the only retry there
# is. Leaving the publish op un-done with no gate in front of it re-runs the
# failing Meta call every iteration until the plan budget is gone.


def _fix(key: str) -> dict:
    from app.services import meta_remediation

    return meta_remediation.render(meta_remediation.CATALOG[key], ad_account_id="act_1")


def _remediated_state(step: str, key: str):
    bs = {"stages_complete": ["campaign", "media", "geo"], "publish_fail_counts": {step: 1}}
    filled = {"plan_confirm": "{}"}
    exc = _fail(step)
    exc.plan_errors = {"adsets[0].name": "Meta said no."}
    exc.remediation = _fix(key)
    _apply_publish_failure(bs, filled, exc, "Meta said no.")
    return bs, filled


def test_a_blocking_prerequisite_opens_the_editor_but_marks_nothing():
    bs, filled = _remediated_state("adset", "ad_account_no_payment")

    # The editor reopens — it is the only screen with a retry on it.
    assert "campaign" not in bs["stages_complete"]
    assert "plan_confirm" not in filled
    # ...and nothing on the form is marked, because nothing on it is wrong.
    assert not bs.get("plan_errors")
    assert bs["publish_remediation"][0]["key"] == "ad_account_no_payment"


def test_a_degrading_prerequisite_publishes_with_less_instead():
    """The audience case: Meta will not hold a customer-list audience here, so the
    next attempt drops it and publishes on Advantage+ inside the same locations."""
    bs, filled = _remediated_state("custom_audience", "custom_audience_tos")

    assert bs["publish_without_audience"] is True
    assert bs["publish_audience_blocked"] is True
    # The editor is NOT reopened: there is nothing to edit and the retry is
    # immediate.
    assert "campaign" in bs["stages_complete"]


def test_an_unrecognised_rejection_still_reopens_the_editor_with_the_field_marked():
    """The ordinary path, unchanged. Most rejections ARE the plan's fault."""
    bs, filled = _fail_state("adset", **{"adsets[0].name": "too long"})

    assert bs["plan_errors"]["adsets[0].name"] == "too long"
    assert bs["plan_errors"]["__root__"] == "Meta said no."
    assert not bs.get("publish_remediation")


def test_the_same_prerequisite_is_not_stacked_on_every_retry():
    bs = {"stages_complete": ["campaign"], "publish_remediation": [_fix("ad_account_no_payment")]}
    filled = {}
    exc = _fail("adset")
    exc.remediation = _fix("ad_account_no_payment")
    _apply_publish_failure(bs, filled, exc, "again")

    assert [r["key"] for r in bs["publish_remediation"]] == ["ad_account_no_payment"]
