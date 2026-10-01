"""
tests/test_maid_failure_honesty.py
──────────────────────────────────
A failed query must never be narrated as an empty audience.

The live-test report's open issue H: a budget refusal reached the user as

    "we came up empty — zero devices were detected"

which is a confident statement about the world made when no query ran. The
correct copy existed but was emitted only as a stream `update`; the narrator
composes the visible message from the fact pack, where `maid_count == 0` is
indistinguishable from "nobody goes there".
"""
from __future__ import annotations

import pytest

from app.graph.narrator.grounding import _build_maid


def test_a_normal_extraction_reports_its_count():
    out = _build_maid({"maid_count": 3506}, {})
    assert out["count"] == 3506
    assert "query_failed" not in out


def test_a_genuine_empty_result_still_reports_zero():
    """"Nobody visited these spots" is a real, reportable answer — the point is
    only that a FAILURE must not look like it."""
    out = _build_maid({"maid_count": 0}, {})
    assert out["count"] == 0
    assert "query_failed" not in out


@pytest.mark.parametrize("kind", [
    "budget", "capacity", "ip_not_allowlisted", "circuit_open", "timeout",
    "rate_limited", "request_rejected", "vendor_error",
])
def test_a_failed_query_drops_the_count_entirely(kind):
    """The count is removed, not zeroed. Leaving a 0 in the pack is what let a
    composer state it as a finding."""
    out = _build_maid({"maid_count": 0, "maid_failure_kind": kind}, {})
    assert out["query_failed"] is True
    assert out["failure_kind"] == kind
    assert "count" not in out


def test_a_timeout_tells_the_composer_a_longer_lookback_is_slower():
    """Thread 77e403d3 was told to "widen to 60 days" after a timeout — the one
    change guaranteed to make it worse."""
    out = _build_maid({"maid_count": 0, "maid_failure_kind": "timeout"}, {})
    assert "longer lookback makes it slower" in out["failure_note"]
    assert "failure_note" not in _build_maid(
        {"maid_count": 0, "maid_failure_kind": "vendor_error"}, {}
    )


@pytest.mark.parametrize("kinds, expected", [
    ({"UnacastRequestTimeout"}, "timeout"),
    ({"UnacastBudgetExhausted", "UnacastRequestTimeout"}, "budget"),
    ({"UnacastCircuitOpen"}, "circuit_open"),
    ({"UnacastRateLimited"}, "rate_limited"),
    ({"UnacastRequestRejected"}, "request_rejected"),
    ({"ReadTimeout"}, "vendor_error"),
    ({None}, "vendor_error"),
    # UnacastExtractionTooLarge no longer exists — nothing is ever refused for
    # predicted size (see unacast_query.py's module docstring), so an unknown
    # exception name (including that now-deleted one, if it somehow reached
    # here from stale data) falls through to the generic kind.
    ({"UnacastExtractionTooLarge"}, "vendor_error"),
])
def test_exception_classes_map_to_a_failure_kind(kinds, expected):
    from app.graph.builder.executors.maid import _maid_failure_kind

    assert _maid_failure_kind(kinds) == expected


def test_a_failure_also_drops_a_stale_pre_filter_count():
    out = _build_maid(
        {
            "maid_count": 3506,
            "filtered_maid_count": 0,
            "audience_filter": {"min_visits": 2},
            "maid_failure_kind": "budget",
        },
        {},
    )
    assert "count" not in out and "count_before_filter" not in out
    assert out["query_failed"] is True


def test_filter_zeroed_is_a_different_thing_from_a_failure():
    """A real superset narrowed to nobody by the filter IS a finding, and must
    stay distinguishable from a query that never ran."""
    out = _build_maid(
        {
            "maid_count": 3506,
            "filtered_maid_count": 0,
            "audience_filter": {"min_visits": 9},
        },
        {},
    )
    assert out["filter_zeroed"] is True
    assert out["count"] == 0
    assert out["count_before_filter"] == 3506
    assert "query_failed" not in out


def test_an_unevaluable_filter_is_surfaced_without_hiding_the_audience():
    """The audience below is real — it just is not the one that was asked for,
    because the filter's history was never bought."""
    out = _build_maid(
        {
            "maid_count": 3506,
            "filtered_maid_count": 3506,
            "audience_filter": {"trend": "started"},
            "maid_filter_unevaluable": "needs 60 days, has 7",
        },
        {},
    )
    assert out["filter_unevaluable"] == "needs 60 days, has 7"
    assert out["count"] == 3506
    assert "query_failed" not in out


def test_a_partial_failure_keeps_the_count_and_says_so():
    """Some spots came back: the audience is real for those, so the count stays
    — but the composer must not present it as covering every spot."""
    out = _build_maid(
        {
            "maid_count": 120,
            "maid_partial_failure": {"failed_pois": 2, "total_pois": 10, "kind": "capacity"},
        },
        {},
    )
    assert out["count"] == 120
    assert out["partial_failure"]["failed_pois"] == 2
    assert "query_failed" not in out


def test_timeout_note_reflects_splitting_already_having_happened():
    """The "too_large" kind is gone — nothing is ever refused for predicted
    size. What's left is the terminal case: even the smallest possible
    request (one POI, one day, after unacast_query._split_request has halved
    it as far as it goes) still timed out."""
    out = _build_maid({"maid_count": 0, "maid_failure_kind": "timeout"}, {})
    assert out["query_failed"] is True and "count" not in out
    assert "split" in out["failure_note"]
