"""
tests/test_resume_payloads.py
──────────────────────────────
The resume transport contract, pinned per widget.

Every JSON-shaped widget payload short-circuits straight to the confirm lane —
``resume_router.is_sentinel_resume`` matches on "starts with { or [", ahead of
the classifier — so the ONLY thing standing between a widget's payload and it
being silently confirmed away unread is the slot handler actually parsing it.
Three separate comments in ``geo.py`` and ``builder_node.py`` record real
incidents of that: a delta was confirmed away because nothing parsed it. This
file is the regression guard for that whole bug class — one row per JSON
widget, walking `` _unwrap_qa -> is_sentinel_resume -> the handler `` exactly as
``wizard_interrupt`` does, on the LITERAL string each widget sends.

See ``WidgetPoiRadiusPicker.tsx``'s ``confirmMessage`` for the bug this class
of test would have caught: two `onConfirm` call sites passed a JSON payload as
a second argument that no caller of the widget ever forwarded, so the backend
silently fell back to an LLM extraction on every submission instead of using
the fast path.
"""

from __future__ import annotations

import json

import app.graph.builder.builder_node as bn
import app.graph.builder.executors.geo as geo_exec
from app.graph.builder.intake_form import parse_intake_submission
from app.graph.resume_router import is_sentinel_resume
from app.graph.wizard_helpers import _unwrap_qa


def _resume_as_sent(prompt: str, payload: dict | str) -> str:
    """The exact string ``ChatContext.tsx`` posts to /resume for a Q:/A:-wrapped
    widget — matches every widget in this table except CampaignEditor, which
    sends the bare value with no wrapper (see its own case below)."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return f"Q: {prompt}\nA: {body}"


def test_location_map_confirm_delta_is_parsed_not_confirmed_away():
    sent = _resume_as_sent(
        "Confirm your locations",
        {"confirm": True, "added": [{"name": "Laval, QC"}], "removed": []},
    )
    unwrapped = _unwrap_qa(sent)
    assert is_sentinel_resume(unwrapped) is True  # confirm lane, $0 — no classifier call

    parsed = bn._parse_json_value(unwrapped, "{")
    assert parsed == {"confirm": True, "added": [{"name": "Laval, QC"}], "removed": []}


def test_maid_split_view_confirm_delta_is_parsed():
    sent = _resume_as_sent(
        "Confirm your audience",
        {"confirm": True, "added": [], "removed": [{"id": "abc", "name": "Store 1"}]},
    )
    unwrapped = _unwrap_qa(sent)
    assert is_sentinel_resume(unwrapped) is True

    parsed = bn._parse_json_value(unwrapped, "{")
    assert parsed["removed"] == [{"id": "abc", "name": "Store 1"}]


def test_map_interaction_pin_is_parsed():
    # WidgetMapInteraction hardcodes its own prompt rather than echoing
    # content.prompt — see the frontend map_interaction call site.
    sent = _resume_as_sent(
        "Pin your target location on the map",
        {"lat": 45.5, "lng": -73.6, "place": "Montreal, QC"},
    )
    unwrapped = _unwrap_qa(sent)
    assert is_sentinel_resume(unwrapped) is True

    parsed = bn._parse_json_value(unwrapped, "{")
    assert parsed == {"lat": 45.5, "lng": -73.6, "place": "Montreal, QC"}


def test_competitor_anchor_and_store_confirm_delta_is_parsed():
    """geo.py's own confirm widgets — mirrors builder_node._parse_json_value
    with a duplicate implementation because of the import cycle (see
    _parse_location_delta's docstring)."""
    sent = _resume_as_sent(
        "Confirm competitor locations",
        {"confirm": True, "added": [{"name": "Starbucks Downtown"}], "removed": []},
    )
    unwrapped = _unwrap_qa(sent)
    assert is_sentinel_resume(unwrapped) is True

    parsed = geo_exec._parse_location_delta(unwrapped)
    assert parsed is not None
    assert parsed["added"] == [{"name": "Starbucks Downtown"}]

    # A plain confirmation is NOT a delta — must fall through to the normal
    # confirm lane instead of being (mis)parsed as an empty delta.
    assert geo_exec._parse_location_delta(_unwrap_qa(_resume_as_sent("Confirm?", "yes"))) is None


def test_file_upload_payload_is_parsed():
    sent = _resume_as_sent(
        "Upload your creative",
        {"fileUploaded": True, "id": "media_1", "name": "hero.jpg", "file_path": "/media/hero.jpg"},
    )
    unwrapped = _unwrap_qa(sent)
    assert is_sentinel_resume(unwrapped) is True

    parsed = bn._parse_json_value(unwrapped, "{")
    assert parsed["file_path"] == "/media/hero.jpg"
    assert parsed["fileUploaded"] is True


def test_campaign_intake_form_values_are_parsed():
    sent = _resume_as_sent(
        "Let's set up your campaign",
        {"values": {
            "business_name": "Acme",
            "business_context": "We sell handmade candles.",
            "objective": "OUTCOME_SALES",
            "budget_amount": 5000,
        }},
    )
    unwrapped = _unwrap_qa(sent)
    assert is_sentinel_resume(unwrapped) is True

    values, errors = parse_intake_submission(unwrapped)
    assert errors == {}
    assert values["business_name"] == "Acme"
    assert values["budget_amount"] == 5000


def test_campaign_intake_form_bad_json_is_rejected_not_silently_dropped():
    values, errors = parse_intake_submission("not json")
    assert values == {}
    assert "__root__" in errors


def test_campaign_editor_sends_bare_value_no_qa_wrapper():
    """CampaignEditor is one of the three widgets that do NOT wrap the answer
    in Q:/A: (WidgetFileUpload and WidgetOauthConnect are the other two) —
    _unwrap_qa must be a no-op on it, not swallow part of the spec."""
    raw = json.dumps({"action": "publish", "spec": {"name": "My Campaign"}, "tracking_method": "pixel"})
    unwrapped = _unwrap_qa(raw)
    assert unwrapped == raw  # unchanged — no Q:/A: prefix to strip
    assert is_sentinel_resume(unwrapped) is True

    submission = bn._parse_json_value(unwrapped, "{")
    assert submission["action"] == "publish"
    assert submission["spec"]["name"] == "My Campaign"


def test_campaign_editor_unlocked_flag_round_trips_both_ways():
    """submit() must send `unlocked` unconditionally (not only when true) for
    the backend's `"unlocked" in submission` re-lock check to ever fire."""
    for unlocked in (True, False):
        raw = json.dumps({"action": "save", "spec": {}, "unlocked": unlocked})
        submission = bn._parse_json_value(_unwrap_qa(raw), "{")
        assert submission["unlocked"] is unlocked


def test_poi_radius_picker_sends_bare_json_no_qa_wrapper():
    """WidgetPoiRadiusPicker's Generate Audience / Confirm Settings buttons send
    ``confirmPayload`` — bare JSON, no Q:/A: wrap (like CampaignEditor above) —
    fixing the bug this file's module docstring names: the widget used to send
    a prose ``confirmMessage`` instead, so ``poi_radius_m``/``lookback_days``
    only ever reached ``builder_node``'s fast JSON path (:4263-4306) via a live
    LLM re-extraction of that prose, with no deterministic fallback if it
    misfired. This pins the fast path directly."""
    raw = json.dumps({"poi_radius_m": 250, "lookback_days": 14})
    unwrapped = _unwrap_qa(raw)
    assert unwrapped == raw  # unchanged — no Q:/A: prefix to strip
    assert is_sentinel_resume(unwrapped) is True  # confirm lane, $0 — no classifier call

    parsed = bn._parse_json_value(unwrapped, "{")
    assert parsed == {"poi_radius_m": 250, "lookback_days": 14}


def test_poi_radius_picker_radius_only_variant_is_parsed():
    """The radius-only re-ask (lookback already known) omits the second key —
    builder_node's write branch must read poi_radius_m alone without choking
    on lookback_days being absent."""
    raw = json.dumps({"poi_radius_m": 300})
    unwrapped = _unwrap_qa(raw)
    assert is_sentinel_resume(unwrapped) is True

    parsed = bn._parse_json_value(unwrapped, "{")
    assert parsed == {"poi_radius_m": 300}
    assert "lookback_days" not in parsed


def test_narrow_pois_and_trim_pois_stay_distinct_names():
    """interject_tools.narrow_pois (handoff lane, executes mid-turn) and
    resume_router.trim_pois (edit lane, only classifies intent) are the SAME
    conceptual operation under two names ON PURPOSE — see narrow_pois's own
    docstring. resume_router._handoff_tool_names() matches by tool NAME alone
    to route a resume answer to the handoff lane; if a future rename ever made
    the two share a name, every "top 10" at a confirm gate would silently
    misroute from the edit lane to the handoff lane instead of failing loudly.
    """
    from app.graph.builder.interject_tools import narrow_pois
    from app.graph.resume_router import _handoff_tool_names, trim_pois

    assert narrow_pois.name == "narrow_pois"
    assert trim_pois.name == "trim_pois"
    assert narrow_pois.name != trim_pois.name

    handoff_names = _handoff_tool_names()
    assert "narrow_pois" in handoff_names
    assert "trim_pois" not in handoff_names
