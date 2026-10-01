"""``builder_node._record_go_live_consent`` — durable proof that a launch was
recorded, not just gated. The gate itself (go_live_confirm) was always real;
this is the "and the request is recorded" half of the App Review submission's
activation claim, which was not true until this existed.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.builder import builder_node as bn


@pytest.mark.asyncio
async def test_records_the_go_live_answer_with_the_right_fields():
    captured = {}

    async def fake_create(self, db, payload):
        captured["payload"] = payload
        return object()

    with patch("app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs", fake_create):
        await bn._record_go_live_consent(
            user_id="u1", campaign_id="camp-1", campaign_ids=["camp-1"],
            ad_account_id="act_123", go_live_answer="Set it live — start delivering this campaign now",
        )

    payload = captured["payload"]
    assert payload.action == "meta.go_live_confirmed"
    assert payload.user_id == "u1"
    assert payload.resource_type == "campaign"
    assert payload.resource_id == "camp-1"
    assert payload.new_data["go_live_answer"] == "Set it live — start delivering this campaign now"
    assert payload.new_data["campaign_ids"] == ["camp-1"]
    assert payload.new_data["ad_account_id"] == "act_123"


@pytest.mark.asyncio
async def test_a_write_failure_never_undoes_the_activation():
    """This runs AFTER activate_published_tree already succeeded — a logging
    outage here must never surface as an error to the user whose campaign is
    now live."""
    with patch(
        "app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs",
        AsyncMock(side_effect=RuntimeError("db is down")),
    ):
        await bn._record_go_live_consent(
            user_id="u1", campaign_id="camp-1", campaign_ids=["camp-1"],
            ad_account_id="act_123", go_live_answer="Set it live",
        )  # must not raise


@pytest.mark.asyncio
async def test_a_none_row_is_logged_not_raised():
    warnings = []
    with patch(
        "app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs",
        AsyncMock(return_value=None),
    ), patch.object(bn.logger, "warning", lambda msg, *a, **kw: warnings.append(msg % a if a else msg)):
        await bn._record_go_live_consent(
            user_id="u1", campaign_id="camp-1", campaign_ids=["camp-1"],
            ad_account_id="act_123", go_live_answer="Set it live",
        )
    assert any("go-live consent" in w for w in warnings)
