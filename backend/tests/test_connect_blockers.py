"""
tests/test_connect_blockers.py
──────────────────────────────
What Punk says in chat the moment Meta connects, for things that are not publish
blockers: no Pixel, a Pixel that never fired, and Custom Audience Terms it cannot
read. ``connect_meta`` itself is a branch of a very large function, so the beat
logic lives in ``_connect_extra_beats`` and is tested through the real beat buffer
(conftest resets it around every test).

The case that matters most is the healthy account: a false constraint on a good
account is worse than the silence these beats replace.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.graph.builder import builder_node as bn
from app.graph.narrator import beats
from app.graph.narrator.composer import _max_chars
from app.services import meta_remediation as rem

_WARM = {"id": "1", "name": "px", "last_fired_time": "2026-09-01T00:00:00+0000"}
_COLD = {"id": "2", "name": "px", "last_fired_time": ""}
_AUDIENCE = {"id": "a1", "subtype": "CUSTOM"}


def _run(*, pixels, audiences=(), blockers=(), **bs_extra):
    bs = {"media_ws": {"pixel_candidates": list(pixels),
                       "audience_candidates": list(audiences)}, **bs_extra}
    bn._connect_extra_beats({}, bs, list(blockers), "act_9")
    return [b.facts.get("constraint") for b in beats.peek({})]


def test_a_healthy_account_gets_no_beat():
    assert _run(pixels=[_WARM], audiences=[_AUDIENCE]) == []


def test_no_pixel_is_said():
    got = _run(pixels=[], audiences=[_AUDIENCE])
    assert got == ["No Pixel on this ad account"]


def test_a_pixel_that_never_fired_is_said_with_a_connect_time_effect():
    _run(pixels=[_COLD], audiences=[_AUDIENCE])
    (beat,) = beats.peek({})

    assert beat.facts["constraint"] == "Your Pixel has never fired"
    # The catalog effect talks about a campaign that does not exist yet.
    assert "The campaign can still run" not in beat.facts["effect"]
    assert "steer" in beat.facts["effect"]
    # dataset_id filled, so the Events Manager deep link survives render().
    assert "/2/" in beat.facts["url"]


def test_one_warm_pixel_among_cold_ones_is_enough():
    assert _run(pixels=[_COLD, _WARM], audiences=[_AUDIENCE]) == []


def test_unread_terms_are_asked_not_claimed():
    got = _run(pixels=[_WARM])
    assert len(got) == 1 and got[0].startswith("Confirm")


def test_terms_are_not_raised_when_the_account_already_holds_an_audience():
    assert _run(pixels=[_WARM], audiences=[_AUDIENCE]) == []


def test_terms_are_not_raised_when_the_audience_is_off_the_table():
    assert _run(pixels=[_WARM], publish_without_audience=True) == []


def test_terms_are_not_repeated_when_a_real_blocker_already_says_it():
    real = rem.CATALOG["custom_audience_tos"]
    assert _run(pixels=[_WARM], blockers=[real]) == []


def test_a_bare_account_gets_exactly_no_pixel_and_terms():
    assert len(_run(pixels=[])) == 2


# ── room for all of it ───────────────────────────────────────────────────────


def _failures(n):
    return [SimpleNamespace(kind="failure") for _ in range(n)]


def test_one_failure_keeps_the_flat_budget():
    assert _max_chars(None, _failures(1)) == _max_chars(None, [])


def test_each_extra_failure_buys_room_up_to_a_ceiling():
    flat = _max_chars(None, [])
    assert _max_chars(None, _failures(3)) == flat + 2 * 220
    assert _max_chars(None, _failures(50)) == flat + 4 * 220


def test_other_beat_kinds_do_not_inflate_the_budget():
    others = [SimpleNamespace(kind="reveal") for _ in range(6)]
    assert _max_chars(None, others) == _max_chars(None, [])


# -- the Terms answer --


def test_terms_a_read_proved_accepted_are_not_asked_about():
    bs = {"media_ws": {"pixel_candidates": [_WARM]}}
    bn._connect_extra_beats({}, bs, [], "act_9", tos_accepted=True)
    assert beats.peek({}) == []


def test_terms_a_read_proved_missing_are_left_to_the_real_card():
    """False becomes a plain blocker upstream; the unverified beat must not double it."""
    bs = {"media_ws": {"pixel_candidates": [_WARM]}}
    bn._connect_extra_beats({}, bs, [], "act_9", tos_accepted=False)
    assert beats.peek({}) == []


# -- Page gaps --


def _pages(flag, field, *others):
    return {"media_ws": {flag: True, "page_candidates": [{"id": "p1", field: False}, *others]}}


def test_an_unpublished_only_page_blocks():
    (card,) = bn._page_blockers(_pages("page_unpublished", "is_published"))
    assert card.key == "page_unpublished" and card.severity == "blocks"


def test_an_unpublished_page_with_a_published_sibling_only_warns():
    (card,) = bn._page_blockers(
        _pages("page_unpublished", "is_published", {"id": "p2", "is_published": True})
    )
    assert card.severity == "warns" and "other published Pages" in card.effect


def test_a_missing_role_with_an_advertisable_sibling_only_warns():
    (card,) = bn._page_blockers(
        _pages("page_role_missing", "can_advertise", {"id": "p2", "can_advertise": True})
    )
    assert card.key == "page_role_missing" and card.severity == "warns"


def test_an_unknown_sibling_does_not_soften_a_blocker():
    """A sibling whose flag is absent might be unpublished too; only True softens."""
    (card,) = bn._page_blockers(_pages("page_unpublished", "is_published", {"id": "p2"}))
    assert card.severity == "blocks"


def test_no_page_still_reports_no_page():
    assert [c.key for c in bn._page_blockers({"media_ws": {"no_facebook_page": True}})] == [
        "no_facebook_page"
    ]


def test_a_healthy_connection_has_no_page_gaps():
    assert bn._page_blockers({"media_ws": {"page_candidates": [{"id": "p1"}]}}) == []
