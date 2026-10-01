"""Meta's Data Deletion Request Callback and Deauthorize Callback —
POST /ads/data-deletion/meta and POST /ads/deauthorize/meta.

Unauthenticated in the ordinary sense (no login, no API key): the
signed_request's HMAC-SHA256 signature IS the authentication, same shape as
the leadgen webhook's X-Hub-Signature-256 but travelling inside the body
instead of a header (Meta's older signed_request convention).

Neither callback can identify which Punk account made the request (see
``_record_meta_signed_request``'s docstring) — both just record it durably,
keyed by a confirmation code, and GET /ads/data-deletion/meta/status reports
what was actually recorded for that code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.modules.ads import router as ads_router
from app.modules.ads.service import parse_meta_signed_request
from app.modules.subscription.models import UserSubscription

SECRET = "test-app-secret"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _signed_request(payload: dict, secret: str = SECRET) -> str:
    payload_b64 = _b64url(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{_b64url(sig)}.{payload_b64}"


def _payload(**overrides) -> dict:
    base = {"algorithm": "HMAC-SHA256", "expires": 0, "issued_at": 0, "user_id": "meta-user-1"}
    base.update(overrides)
    return base


# ── parse_meta_signed_request ───────────────────────────────────────────────


def test_a_correctly_signed_request_decodes():
    out = parse_meta_signed_request(_signed_request(_payload()), SECRET)
    assert out == _payload()


def test_wrong_secret_is_refused():
    assert parse_meta_signed_request(_signed_request(_payload()), "wrong-secret") is None


def test_tampered_payload_is_refused():
    """Change one byte of the payload after signing — the signature must not
    still verify."""
    sr = _signed_request(_payload())
    sig_part, payload_part = sr.split(".", 1)
    tampered = payload_part[:-1] + ("A" if payload_part[-1] != "A" else "B")
    assert parse_meta_signed_request(f"{sig_part}.{tampered}", SECRET) is None


def test_missing_dot_is_refused():
    assert parse_meta_signed_request("not-a-signed-request", SECRET) is None


def test_empty_string_is_refused():
    assert parse_meta_signed_request("", SECRET) is None


def test_unparseable_base64_is_refused():
    assert parse_meta_signed_request("not-valid-base64!!.also-not-valid!!", SECRET) is None


def test_non_dict_payload_is_refused():
    payload_b64 = _b64url(json.dumps([1, 2, 3]).encode())
    sig = hmac.new(SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sr = f"{_b64url(sig)}.{payload_b64}"
    assert parse_meta_signed_request(sr, SECRET) is None


def test_wrong_algorithm_field_is_refused():
    """Meta has only ever sent HMAC-SHA256 here — a payload claiming
    something else must not be trusted just because the signature covers it."""
    out = parse_meta_signed_request(_signed_request(_payload(algorithm="MD5")), SECRET)
    assert out is None


def test_no_app_secret_configured_refuses_everything():
    assert parse_meta_signed_request(_signed_request(_payload()), "") is None


# ── the callbacks ────────────────────────────────────────────────────────────


class _FormRequest:
    """Just enough of a Starlette request for the handler."""

    def __init__(self, form: dict):
        self._form = form

    async def form(self):
        return self._form


def _mock_audit_writes(monkeypatch) -> AsyncMock:
    """Capture every AuditLogRequest the handler builds, returning a truthy
    row so the handler treats the write as having landed."""
    calls = AsyncMock(return_value=object())
    monkeypatch.setattr(
        "app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs",
        calls,
    )
    return calls


@pytest.mark.asyncio
async def test_an_unsigned_deletion_callback_is_refused():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await ads_router.meta_data_deletion_callback.__wrapped__(
            _FormRequest({"signed_request": "garbage"}),
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_an_unsigned_deauthorize_callback_is_refused():
    """One verification path serves both callbacks — prove it applies to
    deauthorize too, not just deletion."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await ads_router.meta_deauthorize_callback.__wrapped__(
            _FormRequest({"signed_request": "garbage"}),
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_a_valid_deletion_callback_records_the_request_and_deletes_nothing(monkeypatch):
    """No Punk account can ever be identified from this payload (see the
    handler's docstring) — this is the regression pin against reintroducing a
    lookup that can only miss or mismatch: nothing gets disconnected, and
    what gets recorded is the request itself, not a deletion outcome."""
    audit_calls = _mock_audit_writes(monkeypatch)
    disconnect = AsyncMock()
    monkeypatch.setattr(ads_router.service, "disconnect_meta", disconnect)

    sr = _signed_request(_payload(), secret=settings.META_APP_SECRET)
    out = await ads_router.meta_data_deletion_callback.__wrapped__(
        _FormRequest({"signed_request": sr}),
    )

    assert "confirmation_code" in out
    assert out["url"].endswith(f"code={out['confirmation_code']}")
    disconnect.assert_not_awaited()

    request = audit_calls.await_args.args[1]
    assert request.action == "meta.data_deletion_processed"
    assert request.resource_id == out["confirmation_code"]
    assert request.new_data["meta_user_id"] == "meta-user-1"


@pytest.mark.asyncio
async def test_a_valid_deauthorize_callback_records_a_different_action(monkeypatch):
    audit_calls = _mock_audit_writes(monkeypatch)

    sr = _signed_request(_payload(), secret=settings.META_APP_SECRET)
    out = await ads_router.meta_deauthorize_callback.__wrapped__(
        _FormRequest({"signed_request": sr}),
    )

    assert "confirmation_code" in out
    request = audit_calls.await_args.args[1]
    assert request.action == "meta.deauthorized"
    assert request.resource_id == out["confirmation_code"]


@pytest.mark.asyncio
async def test_an_audit_write_failure_never_breaks_the_response(monkeypatch):
    monkeypatch.setattr(
        "app.modules.auditLogs.repository.AuditLogRepository.create_audit_logs",
        AsyncMock(side_effect=RuntimeError("db is down")),
    )

    sr = _signed_request(_payload(), secret=settings.META_APP_SECRET)
    out = await ads_router.meta_data_deletion_callback.__wrapped__(
        _FormRequest({"signed_request": sr}),
    )
    assert "confirmation_code" in out  # must not raise
    assert out["url"].endswith(f"code={out['confirmation_code']}")


# ── the status endpoint ──────────────────────────────────────────────────────


class _Row:
    def __init__(self, resource_id: str, new_data: dict, created_at=None):
        self.resource_id = resource_id
        self.new_data = new_data
        self.created_at = created_at


class _ScalarsResult:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _StatusDb:
    def __init__(self, row=None):
        self._row = row

    async def execute(self, _stmt):
        return _ScalarsResult(self._row)


@pytest.mark.asyncio
async def test_status_reports_the_recorded_outcome():
    row = _Row("abc123", {"meta_user_id": "meta-user-1", "connection_deleted": False})
    out = await ads_router.meta_data_deletion_status.__wrapped__(
        request=None, code="abc123", db=_StatusDb(row),
    )
    assert out["confirmation_code"] == "abc123"
    assert out["status"] == "completed"
    assert "nothing further to delete" in out["detail"]


@pytest.mark.asyncio
async def test_status_of_an_unissued_code_is_unknown():
    """This is what the old hardcoded '"completed" for any code' behavior
    was papering over — a code nobody issued must not read as done."""
    out = await ads_router.meta_data_deletion_status.__wrapped__(
        request=None, code="never-issued", db=_StatusDb(None),
    )
    assert out["confirmation_code"] == "never-issued"
    assert out["status"] == "unknown"


# ── the subscription cascade ─────────────────────────────────────────────────


def test_meta_disconnect_does_not_cascade_into_subscriptions():
    """A Meta disconnect must clear the pointer, not delete the row carrying
    the user's Stripe linkage."""
    fk = next(iter(UserSubscription.__table__.c.meta_ads_id.foreign_keys))
    assert fk.ondelete == "SET NULL"

    # Every mapped class must be importable for SQLAlchemy to resolve the
    # string-named relationship targets below — this test is otherwise the
    # first thing in the suite to force full mapper configuration.
    import app.db.model_registry  # noqa: F401
    from app.modules.ads.models import OAuthToken

    assert OAuthToken.ads_accounts.property.passive_deletes is True
    assert OAuthToken.meta_account_subscriptions.property.passive_deletes is True
