"""
nodes._validate_audience_filter_clause — value-sanity for an extracted
`audience_filter`. Previously `_validate_extracted_field` had NO case for
this field at all, so whatever the LLM emitted (a negative cadence, an
inverted hours range, an empty groups list) passed straight through into
targeting unchecked. Pure function, no LLM.
"""
from __future__ import annotations

from app.graph.nodes import _validate_audience_filter_clause, _validate_extracted_field


def test_valid_clause_passes_through_unchanged():
    clause = {"min_visits": 3, "window_days": 14, "days_of_week": [5, 6]}
    assert _validate_audience_filter_clause(clause) == clause


def test_non_positive_counts_are_dropped():
    clause = {"min_visits": 0, "cadence_days": -30, "window_days": 14}
    assert _validate_audience_filter_clause(clause) == {"window_days": 14}


def test_inverted_or_out_of_range_hours_are_dropped():
    assert _validate_audience_filter_clause({"hours": [22, 6]}) is None       # lo >= hi
    assert _validate_audience_filter_clause({"hours": [0, 30]}) is None       # hi > 24
    assert _validate_audience_filter_clause({"hours": [9, 17]}) == {"hours": [9, 17]}


def test_out_of_range_days_of_week_are_filtered_not_rejected_wholesale():
    # 9 isn't a valid weekday token — drop just that one, keep the rest.
    assert _validate_audience_filter_clause({"days_of_week": [1, 9, 5]}) == {
        "days_of_week": [1, 5]
    }


def test_bogus_op_and_trend_enums_are_dropped():
    clause = {"op": "xor", "trend": "forever", "groups": ["gym"]}
    assert _validate_audience_filter_clause(clause) == {"groups": ["gym"]}


def test_empty_or_blank_group_labels_are_stripped():
    clause = {"groups": ["", "  ", "gym"]}
    assert _validate_audience_filter_clause(clause) == {"groups": ["gym"]}


def test_unknown_keys_are_dropped():
    clause = {"min_visits": 2, "not_a_real_field": "whatever"}
    assert _validate_audience_filter_clause(clause) == {"min_visits": 2}


def test_fully_empty_clause_becomes_none_not_an_empty_dict():
    assert _validate_audience_filter_clause({"min_visits": 0, "cadence_days": -1}) is None
    assert _validate_audience_filter_clause({}) is None
    assert _validate_audience_filter_clause("not a dict") is None


def test_any_of_branches_are_each_validated_and_empty_branches_dropped():
    clause = {
        "any_of": [
            {"min_visits": 2},
            {"min_visits": -5},  # invalid — should be dropped, not the whole any_of
        ]
    }
    assert _validate_audience_filter_clause(clause) == {"any_of": [{"min_visits": 2}]}


def test_any_of_with_every_branch_invalid_drops_the_whole_field():
    clause = {"any_of": [{"min_visits": 0}, {"cadence_days": -1}]}
    assert _validate_audience_filter_clause(clause) is None


def test_unsupported_verbatim_note_survives_alone():
    # A clause the user named but nothing else expresses ("cut it in half")
    # is still meaningful on its own — never dropped just because no
    # structured field could carry it.
    clause = {"unsupported": "cut it in half"}
    assert _validate_audience_filter_clause(clause) == clause


def test_wired_into_validate_extracted_field():
    assert _validate_extracted_field(
        "audience_filter", {"min_visits": -1, "groups": ["gym"]}
    ) == {"groups": ["gym"]}
    assert _validate_extracted_field("audience_filter", {"min_visits": 0}) is None
