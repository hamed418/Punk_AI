"""``media._record_audience_source_disclosure`` — the durable half of the
Custom Audience source-disclosure requirement. The TEXT lives in the
campaign_plan_confirm prompt (prompts_registry.py, the last screen before
publish); this is proof a publish that used licensed location data actually
happened after that screen, for a specific ad account and extraction.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.builder.executors import media


@pytest.mark.asyncio
async def test_records_a_disclosure_ack_with_the_right_fields():
    captured = {}

    async def fake_create(self, db, payload):
        captured["payload"] = payload
        return object()  # anything non-None reads as success

    with patch("app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs", fake_create):
        await media._record_audience_source_disclosure(
            user_id="u1", ad_account_id="act_123",
            maid_extraction_id="ext-1", maid_count=250,
        )

    payload = captured["payload"]
    assert payload.action == "meta.audience_source_disclosure_ack"
    assert payload.user_id == "u1"
    assert payload.resource_type == "ad_account"
    assert payload.resource_id == "act_123"
    assert payload.new_data["maid_extraction_id"] == "ext-1"
    assert payload.new_data["maid_count"] == 250


@pytest.mark.asyncio
async def test_a_write_failure_is_swallowed_not_raised():
    """This runs inside publish_campaign_to_meta, right before the audience
    upload — a logging outage here must never block a real publish."""
    with patch(
        "app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs",
        AsyncMock(side_effect=RuntimeError("db is down")),
    ):
        await media._record_audience_source_disclosure(
            user_id="u1", ad_account_id="act_123",
            maid_extraction_id="ext-1", maid_count=10,
        )  # must not raise


@pytest.mark.asyncio
async def test_a_none_row_is_logged_not_raised(caplog):
    """create_audit_logs returns None on its own internal failure (see
    test_audit_logs.py) rather than raising — this caller must notice and log,
    not treat None as success silently."""
    warnings = []
    with patch(
        "app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs",
        AsyncMock(return_value=None),
    ), patch.object(media.logger, "warning", lambda msg, *a, **kw: warnings.append(msg % a if a else msg)):
        await media._record_audience_source_disclosure(
            user_id="u1", ad_account_id="act_123",
            maid_extraction_id="ext-1", maid_count=10,
        )
    assert any("disclosure" in w for w in warnings)
