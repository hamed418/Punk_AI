"""``auditLogs`` — regression coverage for the write path's two bugs, found
while wiring the first real callers (Custom Audience source-disclosure
acknowledgement, go-live consent).

Both bugs were unreachable in practice: nothing in the codebase called
``create_audit_logs`` before now, so neither had ever actually run.

1. ``AuditLogService.create_audit_logs`` called
   ``self.repository.create_audit_logs(self, db, payloadRequest)`` — passing
   the *service* instance as the repository method's ``db`` argument.
2. ``AuditLogRepository.create_audit_logs``'s except-clause called
   ``logger.error(...)`` with no ``logger`` ever imported in that module —
   a write failure raised NameError instead of being logged, replacing the
   original exception with a misleading one.
"""
from unittest.mock import AsyncMock

import pytest

from app.modules.auditLogs.repository import AuditLogRepository
from app.modules.auditLogs.schemas import AuditLogRequest
from app.modules.auditLogs.service import AuditLogService


def _payload(**overrides) -> AuditLogRequest:
    base = dict(user_id="u1", action="meta.go_live_confirmed", resource_id="camp-1")
    base.update(overrides)
    return AuditLogRequest(**base)


@pytest.mark.asyncio
async def test_service_passes_db_to_the_repository_not_itself():
    """The stray `self` argument shifted every positional param by one —
    db.add would have been called on the AuditLogService instance."""
    repo = AuditLogRepository()
    repo.create_audit_logs = AsyncMock(return_value="ok")
    service = AuditLogService(repo)
    db = object()  # a real AsyncSession is not needed — we only check what's passed
    payload = _payload()

    await service.create_audit_logs(db, payload)

    repo.create_audit_logs.assert_awaited_once_with(db, payload)


@pytest.mark.asyncio
async def test_a_write_failure_is_logged_not_a_nameerror(monkeypatch, caplog):
    """Force db.commit to raise, and confirm the except branch logs cleanly
    instead of dying on the missing `logger` name."""
    from app.modules.auditLogs import repository as repo_module

    class _BoomDB:
        def add(self, _obj):
            pass

        async def commit(self):
            raise RuntimeError("db is down")

    logged = []
    monkeypatch.setattr(
        repo_module.logger, "error",
        lambda msg, *a, **kw: logged.append(msg % a if a else msg),
    )

    result = await AuditLogRepository().create_audit_logs(_BoomDB(), _payload())

    assert result is None
    assert logged and "db is down" in logged[0]


@pytest.mark.asyncio
async def test_a_successful_write_returns_the_row():
    class _Db:
        def __init__(self):
            self.added = None

        def add(self, obj):
            self.added = obj

        async def commit(self):
            pass

    db = _Db()
    row = await AuditLogRepository().create_audit_logs(db, _payload(action="meta.audience_disclosure_ack"))

    assert row is db.added
    assert row.action == "meta.audience_disclosure_ack"
    assert row.user_id == "u1"
