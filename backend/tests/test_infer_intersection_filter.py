"""
tests/test_infer_intersection_filter.py
─────────────────────────────────────────
`nodes._infer_intersection_filter` — the deterministic backstop for "who
went to both X and Y" phrasing.

The regression this guards: the one-shot `ExtractedUserInfo` structured-output
call sometimes drops `audience_filter` entirely even when the user's text
plainly asked for an intersection ("both SneakerCon and Flight Club") — the
LLM never emits the field at all, so it passes through as `None` regardless
of validation, and the audience defaults to a plain union of every spot
found. Pure function, no LLM. (Separately, `_validate_extracted_field` DOES
now sanity-check an `audience_filter` the LLM did produce — see
`_validate_audience_filter_clause` and test_audience_filter_validation.py —
but that only helps when the field is present with bad values, not when
it's missing entirely, which is this module's problem.)
"""
from __future__ import annotations

from app.graph.nodes import _infer_intersection_filter


def test_both_phrasing_infers_intersection_from_extracted_labels():
    extracted = {"named_places": ["Flight Club"], "event_queries": ["SneakerCon"]}
    result = _infer_intersection_filter(
        "Target users who went to both SneakerCon and Flight Club in New York.",
        extracted,
    )
    assert result == {"groups": ["Flight Club", "SneakerCon"], "op": "intersection"}


def test_all_of_phrasing_also_infers():
    extracted = {"competitor_brands": ["Nike", "Adidas"]}
    result = _infer_intersection_filter("Reach shoppers at all of Nike and Adidas.", extracted)
    assert result == {"groups": ["Nike", "Adidas"], "op": "intersection"}


def test_does_not_override_explicit_extraction():
    extracted = {
        "named_places": ["Flight Club"],
        "event_queries": ["SneakerCon"],
        "audience_filter": {"op": "union"},
    }
    assert _infer_intersection_filter("both SneakerCon and Flight Club", extracted) is None


def test_needs_at_least_two_labels():
    extracted = {"named_places": ["Flight Club"]}
    assert _infer_intersection_filter("both places", extracted) is None


def test_no_both_phrasing_does_nothing():
    extracted = {"named_places": ["Flight Club"], "event_queries": ["SneakerCon"]}
    assert _infer_intersection_filter("Flight Club and SneakerCon visitors", extracted) is None


def test_no_text_does_nothing():
    assert _infer_intersection_filter(None, {"named_places": ["A"], "event_queries": ["B"]}) is None
