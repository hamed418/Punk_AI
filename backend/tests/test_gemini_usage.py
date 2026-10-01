"""
tests/test_gemini_usage.py
──────────────────────────
Unit tests for Gemini token pricing, model normalization, grounding usage
tracking, and creative generation kill-switch.
"""

from unittest.mock import MagicMock
import pytest

from app.core.config import settings
from app.graph.state import _counter_add
from app.graph.usage import (
    MODEL_PRICING,
    aggregate_grounding_usage,
    api_call_callback,
    compute_cost,
    grounding_usage_callback,
    normalize_model_name,
    record_api_call,
    record_grounding_usage,
)
from app.services.creative_gen import CreativeGenError, _client


def test_normalize_model_name_keeps_the_real_model_id():
    """Prefixes and @version are stripped; the model is never collapsed onto another."""
    assert normalize_model_name("gemini-3.5-flash") == "gemini-3.5-flash"
    assert normalize_model_name("models/gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"
    assert normalize_model_name("publishers/google/models/gemini-3.1-pro-preview@001") == "gemini-3.1-pro-preview"
    assert normalize_model_name("Gemini-2.5-PRO") == "gemini-2.5-pro"
    # No longer mapped onto a "tier": what ran is what is recorded.
    assert normalize_model_name("gemini-2.0-flash") == "gemini-2.0-flash"

    # No model given = the configured default fast model.
    assert normalize_model_name(None) == settings.GEMINI_MODEL
    assert normalize_model_name("") == settings.GEMINI_MODEL


@pytest.mark.parametrize("model, one_m_in_out", [
    # Vertex standard tier, global, <=200k prompts: 1M input + 1M output tokens.
    ("gemini-2.5-flash", 0.30 + 2.50),
    ("gemini-2.5-pro", 1.25 + 10.00),
    ("gemini-3.5-flash", 1.50 + 9.00),
    ("gemini-3.5-flash-lite", 0.30 + 2.50),
    ("gemini-3.1-flash-lite", 0.25 + 1.50),
    ("models/gemini-3.1-pro-preview", 2.00 + 12.00),
])
def test_compute_cost_uses_the_real_price_of_each_model(model, one_m_in_out):
    cost = compute_cost(input_tokens=1_000_000, output_tokens=1_000_000, thinking_tokens=0, model=model)
    assert pytest.approx(cost, rel=1e-6) == one_m_in_out


def test_unknown_model_is_charged_the_priciest_rate_and_logged(caplog):
    """A model missing from the table must over-report, never be priced as Flash."""
    with caplog.at_level("ERROR", logger="app.graph.usage"):
        cost = compute_cost(input_tokens=1_000_000, output_tokens=1_000_000, model="claude-sonnet-5")
    assert pytest.approx(cost, rel=1e-6) == 2.00 + 12.00  # gemini-3.1-pro-preview is the priciest row
    assert "no pricing for model 'claude-sonnet-5'" in caplog.text


def test_compute_cost_thinking_tokens():
    """Reasoning/thinking tokens calculation."""
    # 500k input, 300k output (of which 100k is thinking)
    cost = compute_cost(
        input_tokens=500_000,
        output_tokens=300_000,
        thinking_tokens=100_000,
        model="gemini-2.5-flash",
    )
    pricing = MODEL_PRICING["gemini-2.5-flash"]
    expected = (
        0.5 * pricing["input_per_million"]
        + 0.2 * pricing["output_per_million"]
        + 0.1 * pricing["thinking_per_million"]
    )
    assert pytest.approx(cost, rel=1e-6) == expected


def test_grounding_usage_outside_turn_is_noop():
    """Outside a turn context, record_grounding_usage is a safe no-op."""
    mock_meta = MagicMock()
    mock_meta.prompt_token_count = 100
    mock_meta.candidates_token_count = 50
    record_grounding_usage("gemini-2.5-flash", mock_meta)

    total_tokens, total_cost = aggregate_grounding_usage(None)
    assert total_tokens == 0
    assert total_cost == 0.0


def test_grounding_usage_inside_turn():
    """Inside a turn context, record_grounding_usage records and aggregates tokens."""
    with grounding_usage_callback() as acc:
        mock_meta = MagicMock()
        mock_meta.prompt_token_count = 200
        mock_meta.tool_use_prompt_token_count = 50
        mock_meta.candidates_token_count = 100
        mock_meta.thoughts_token_count = 30
        mock_meta.total_token_count = 380

        record_grounding_usage("models/gemini-2.5-flash", mock_meta)

        total_tokens, total_cost = aggregate_grounding_usage(acc)
        assert total_tokens == 380
        assert total_cost > 0


def test_api_call_outside_turn_is_noop():
    """Outside a turn context, record_api_call is a safe no-op."""
    record_api_call("places_text_search")  # must not raise with no context open


def test_api_call_inside_turn_accumulates():
    """Inside a turn context, record_api_call sums repeated keys."""
    with api_call_callback() as acc:
        record_api_call("places_text_search")
        record_api_call("places_text_search")
        record_api_call("geocoding", 3)
        assert acc == {"places_text_search": 2, "geocoding": 3}


def test_counter_add_reducer():
    """AgentState.google_api_calls reducer: sums per key, treats None/{} as identity."""
    assert _counter_add(None, None) == {}
    assert _counter_add({"geocoding": 2}, None) == {"geocoding": 2}
    assert _counter_add(None, {"geocoding": 2}) == {"geocoding": 2}
    a = {"geocoding": 2}
    b = {"geocoding": 3, "places_text_search": 5}
    result = _counter_add(a, b)
    assert result == {"geocoding": 5, "places_text_search": 5}
    # inputs not mutated
    assert a == {"geocoding": 2}
    assert b == {"geocoding": 3, "places_text_search": 5}


def test_creative_gen_disabled_in_v1(monkeypatch):
    """Verifies that creative generation is disabled for Version 1 and raises appropriately."""
    monkeypatch.setattr(settings, "CREATIVE_GEN_ENABLED", False)
    with pytest.raises(CreativeGenError) as exc_info:
        _client()
    assert "disabled in Version 1" in str(exc_info.value)
