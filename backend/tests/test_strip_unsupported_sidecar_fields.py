"""
tests/test_strip_unsupported_sidecar_fields.py
──────────────────────────────────────────────────
`nodes._strip_unsupported_sidecar_fields` — the deterministic backstop that
drops a sidecar field whose own required evidence is absent from the text.

The regression this guards: "at least 2 of a gym, a spa, or a salon" (a
min_distinct_groups phrase, no role/certainty/trend language at all) was
observed stacking min_confidence="confirmed" + the presence-pattern role
trio + trend_recent_days onto an otherwise-correct extraction, with the
model's own rationale admitting it was "inferring... not explicitly
stated" — a real narrowing bug, not cosmetic noise: min_confidence silently
drops unconfirmed visits, and the role trio silently narrows a plain
"visited 3 of 5 kinds of place" audience down to a staff-only one.
Pure function, no LLM.
"""
from __future__ import annotations

from app.graph.nodes import _strip_unsupported_sidecar_fields


def test_strips_min_confidence_with_no_certainty_language():
    extracted = {"audience_filter": {"groups": ["gym"], "min_confidence": "confirmed"}}
    result = _strip_unsupported_sidecar_fields("visited a gym at least twice", extracted)
    assert result == {"groups": ["gym"]}


def test_keeps_min_confidence_with_certainty_language():
    extracted = {"audience_filter": {"groups": ["gym"], "min_confidence": "confirmed"}}
    assert _strip_unsupported_sidecar_fields(
        "people who definitely went inside the gym, not just passing by", extracted
    ) is None


def test_strips_trend_windows_with_no_trend():
    extracted = {
        "audience_filter": {"groups": ["gym"], "trend_recent_days": 14, "trend_prior_days": 60}
    }
    result = _strip_unsupported_sidecar_fields("visited a gym", extracted)
    assert result == {"groups": ["gym"]}


def test_keeps_trend_windows_when_trend_set():
    extracted = {
        "audience_filter": {
            "groups": ["gym"], "trend": "lapsed",
            "trend_recent_days": 14, "trend_prior_days": 60,
        }
    }
    assert _strip_unsupported_sidecar_fields("used to go but stopped", extracted) is None


def test_strips_exclude_window_days_with_no_exclude_groups():
    extracted = {"audience_filter": {"groups": ["gym"], "exclude_window_days": 0}}
    result = _strip_unsupported_sidecar_fields("visited a gym", extracted)
    assert result == {"groups": ["gym"]}


def test_keeps_exclude_window_days_with_exclude_groups():
    extracted = {
        "audience_filter": {
            "groups": ["gym"], "exclude_groups": ["my store"], "exclude_window_days": 0,
        }
    }
    assert _strip_unsupported_sidecar_fields("gym-goers who never came to my store", extracted) is None


def test_strips_role_trio_with_no_role_language():
    extracted = {
        "audience_filter": {
            "groups": ["gym", "cafe", "salon"], "min_distinct_groups": 2,
            "min_open_day_share": 0.5, "min_intraday_span_min": 240, "min_days_present": 1,
        }
    }
    result = _strip_unsupported_sidecar_fields(
        "visited at least 2 of a gym, a cafe, or a salon in the last month", extracted,
    )
    assert result == {"groups": ["gym", "cafe", "salon"], "min_distinct_groups": 2}


def test_keeps_role_trio_with_role_language():
    extracted = {
        "audience_filter": {
            "groups": ["barbershop"],
            "min_open_day_share": 0.5, "min_intraday_span_min": 240, "min_days_present": 2,
        }
    }
    assert _strip_unsupported_sidecar_fields(
        "find me the barbers who spend all day inside, not customers", extracted,
    ) is None


def test_keeps_role_trio_on_own_language():
    extracted = {"audience_filter": {"groups": ["cafe"], "min_open_day_share": 0.5}}
    assert _strip_unsupported_sidecar_fields("people who own cafes in Chicago", extracted) is None


def test_clean_spec_returns_none():
    extracted = {"audience_filter": {"groups": ["gym"], "min_distinct_groups": 2}}
    assert _strip_unsupported_sidecar_fields("at least 2 of gym or spa", extracted) is None


def test_no_audience_filter_returns_none():
    assert _strip_unsupported_sidecar_fields("anything", {}) is None
    assert _strip_unsupported_sidecar_fields("anything", {"audience_filter": None}) is None


def test_strips_multiple_at_once():
    extracted = {
        "audience_filter": {
            "groups": ["gym", "cafe", "salon"], "min_distinct_groups": 2,
            "min_confidence": "confirmed", "trend_recent_days": 30,
            "min_open_day_share": 0.5, "exclude_window_days": 0,
        }
    }
    result = _strip_unsupported_sidecar_fields(
        "visited at least 2 of a gym, a cafe, or a salon", extracted,
    )
    assert result == {"groups": ["gym", "cafe", "salon"], "min_distinct_groups": 2}
