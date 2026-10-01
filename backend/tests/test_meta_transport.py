"""``meta_ads._request_once`` against real Graph-shaped responses.

Every other Meta test monkeypatches at or above ``_request``, so the layer that
actually builds the HTTP call and parses Meta's error body had no coverage at
all. That gap is why ``wait_for_video_ready`` shipped as a no-op: its status GET
was silently issued as a POST and nothing noticed.

Uses ``httpx.MockTransport`` so the requests are real httpx requests — the point
is to assert on the method and the query string that would go on the wire.
"""
import logging

import httpx
import pytest

from app.services import meta_ads


@pytest.fixture
def capture(monkeypatch):
    """Route every meta_ads HTTP call to a recorder, return the request list."""
    seen: list[httpx.Request] = []
    replies: dict = {"json": {"id": "1"}, "status": 200, "headers": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            replies["status"], json=replies["json"], headers=replies.get("headers") or {},
        )

    real_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_ads.httpx, "AsyncClient", _client)
    return seen, replies


# ── The dispatch bug ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_with_data_stays_a_get(capture):
    """A GET carrying ``data`` must be a GET.

    ``_request_once`` used to branch on ``data`` before it looked at the method,
    so this call went out as a form POST to /{video_id}. Meta rejected it,
    ``wait_for_video_ready`` caught the error, logged "proceeding without the
    gate" and returned — meaning every video creative was built against a
    possibly-still-transcoding asset.
    """
    seen, _ = capture

    await meta_ads._request(
        "GET", "video-123", "tok", data={"fields": "status"}
    )

    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert "fields=status" in str(seen[0].url)


@pytest.mark.asyncio
async def test_post_with_data_is_still_form_encoded(capture):
    """The URL-direct media upload path must keep its form-encoded POST."""
    seen, _ = capture

    await meta_ads._request(
        "POST", "act_1/advideos", "tok", data={"file_url": "https://x/y.mp4"}
    )

    assert seen[0].method == "POST"
    assert b"file_url" in seen[0].content
    assert seen[0].headers["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )


@pytest.mark.asyncio
async def test_post_without_data_sends_json(capture):
    seen, _ = capture

    await meta_ads._request("POST", "act_1/campaigns", "tok", json_data={"name": "n"})

    assert seen[0].method == "POST"
    assert seen[0].headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_video_ready_gate_actually_polls(capture):
    """The regression the dispatch fix exists for: a video Meta reports as
    errored must raise, not be waved through."""
    seen, replies = capture
    replies["json"] = {"status": {"video_status": "error"}}

    with pytest.raises(meta_ads.MetaAdsError, match="could not process video"):
        await meta_ads.wait_for_video_ready("video-123", "tok")

    assert seen[0].method == "GET"


# ── Error parsing ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_error_body_is_parsed(capture):
    seen, replies = capture
    replies["json"] = {
        "error": {
            "message": "Invalid parameter",
            "type": "OAuthException",
            "code": 100,
            "error_subcode": 1885204,
            "error_user_msg": "Pick another bid strategy.",
            "error_data": {"blame_field_specs": [["bid_strategy"]]},
            "fbtrace_id": "abc",
        }
    }

    with pytest.raises(meta_ads.MetaAdsError) as excinfo:
        await meta_ads._request("POST", "act_1/adsets", "tok", json_data={})

    exc = excinfo.value
    assert exc.code == 100
    assert exc.subcode == 1885204
    assert exc.user_msg == "Pick another bid strategy."
    # Flattened to the field names themselves — the specs are paths, and it is
    # the last segment the plan editor keys its form fields by.
    assert exc.blame_field == ["bid_strategy"]
    # Code 100 is a semantic rejection — retrying cannot make it valid.
    assert not exc.retryable
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_blame_fields_survive_error_data_arriving_as_a_string(capture):
    """Meta sends error_data as a JSON string far more often than as an object.
    The isinstance-dict read never once fired, so every rejection reached the
    plan editor as a banner with no field marked and nothing to fix."""
    _, replies = capture
    replies["json"] = {
        "error": {
            "message": "Invalid parameter",
            "type": "OAuthException",
            "code": 100,
            "error_subcode": 1885272,
            "error_user_msg": "Your ad set budget must be more than BDT3,700.00.",
            "error_data": '{"blame_field_specs":[["lifetime_budget"]]}',
        }
    }

    with pytest.raises(meta_ads.MetaAdsError) as excinfo:
        await meta_ads._request("POST", "act_1/adsets", "tok", json_data={})

    assert excinfo.value.blame_field == ["lifetime_budget"]


@pytest.mark.asyncio
async def test_unparseable_error_data_is_not_fatal(capture):
    """A rejection we cannot key onto a field is still a rejection to report."""
    _, replies = capture
    replies["json"] = {
        "error": {"message": "Invalid parameter", "code": 100, "error_data": "{not json"}
    }

    with pytest.raises(meta_ads.MetaAdsError) as excinfo:
        await meta_ads._request("POST", "act_1/adsets", "tok", json_data={})

    assert excinfo.value.blame_field == []


@pytest.mark.asyncio
async def test_non_json_response_raises_rather_than_crashing(monkeypatch):
    """A proxy returning an HTML error page must surface as MetaAdsError, not as
    a bare JSONDecodeError from inside the transport."""
    real_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(502, text="<html>bad gateway</html>")
        )
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_ads.httpx, "AsyncClient", _client)

    with pytest.raises(meta_ads.MetaAdsError, match="non-JSON response"):
        await meta_ads._request("GET", "act_1", "tok", retries=1)


# ── Dead-token invalidation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_code_190_invalidates_the_acting_users_token(capture, monkeypatch):
    """A revoked connection has to stop reading as connected.

    Nothing used to clear ``is_valid`` when Meta rejected a token, so a user who
    revoked Punk in Business Settings kept a row saying "connected" while every
    publish failed on 190.
    """
    _, replies = capture
    replies["json"] = {
        "error": {"message": "Session expired", "type": "OAuthException", "code": 190}
    }

    invalidated: list[str] = []

    async def _mark(user_id, reason=""):
        invalidated.append(user_id)

    monkeypatch.setattr("app.services.oauth.mark_meta_token_invalid", _mark)

    with meta_ads.acting_user("user-42"):
        with pytest.raises(meta_ads.MetaAdsError):
            await meta_ads._request("GET", "act_1", "tok", retries=1)

    assert invalidated == ["user-42"]


@pytest.mark.asyncio
async def test_permission_error_does_not_invalidate(capture, monkeypatch):
    """Codes 10/200 mean the token is alive but lacks a scope. Marking it dead
    would disconnect a working account over a missing permission."""
    _, replies = capture
    replies["json"] = {
        "error": {"message": "no permission", "type": "OAuthException", "code": 200}
    }

    invalidated: list[str] = []

    async def _mark(user_id, reason=""):
        invalidated.append(user_id)

    monkeypatch.setattr("app.services.oauth.mark_meta_token_invalid", _mark)

    with meta_ads.acting_user("user-42"):
        with pytest.raises(meta_ads.MetaAdsError):
            await meta_ads._request("GET", "act_1", "tok", retries=1)

    assert invalidated == []


@pytest.mark.asyncio
async def test_wrong_token_type_190_does_not_invalidate(capture, monkeypatch):
    """"Must be called with a Page Access Token" is a 190, but the user token is
    alive — it is the wrong kind of token for that edge. Invalidating it sent the
    advertiser round a reconnect loop that could never fix anything."""
    _, replies = capture
    replies["json"] = {
        "error": {
            "message": "(#190) This method must be called with a Page Access Token",
            "type": "OAuthException",
            "code": 190,
        }
    }

    invalidated: list[str] = []

    async def _mark(user_id, reason=""):
        invalidated.append(user_id)

    monkeypatch.setattr("app.services.oauth.mark_meta_token_invalid", _mark)

    with meta_ads.acting_user("user-42"):
        with pytest.raises(meta_ads.MetaAdsError):
            await meta_ads._request("GET", "page_1/leadgen_forms", "tok", retries=1)

    assert invalidated == []


@pytest.mark.asyncio
async def test_acting_user_does_not_leak_out_of_its_block():
    assert meta_ads._ACTING_USER_ID.get() is None
    with meta_ads.acting_user("a"):
        assert meta_ads._ACTING_USER_ID.get() == "a"
    assert meta_ads._ACTING_USER_ID.get() is None


# ── Rate-limit header capture ───────────────────────────────────────────────
# Every response header used to be discarded — X-Business-Use-Case-Usage (Meta's
# own per-ad-account throttle headroom) was never read, so Punk had no signal
# before hitting the account's throttle and no data toward the Marketing API
# Access Tier's own error-rate assessment. Asserted on logger.log calls, not
# caplog: app logging goes through structlog, which does not propagate to
# pytest's capture handler.


def _fake_logger(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        meta_ads.logger, "log",
        lambda level, msg, *args, **kw: calls.append((level, msg % args)),
    )
    return calls


def test_missing_usage_header_logs_nothing(monkeypatch):
    calls = _fake_logger(monkeypatch)
    resp = httpx.Response(200, json={"id": "1"})

    meta_ads._log_usage_header(resp, "act_1/campaigns")

    assert calls == []


def test_malformed_usage_header_is_not_fatal(monkeypatch):
    calls = _fake_logger(monkeypatch)
    resp = httpx.Response(
        200, json={"id": "1"},
        headers={"X-Business-Use-Case-Usage": "not json"},
    )

    meta_ads._log_usage_header(resp, "act_1/campaigns")  # must not raise

    assert calls == []


def test_per_account_usage_logged_at_debug_below_threshold(monkeypatch):
    calls = _fake_logger(monkeypatch)
    resp = httpx.Response(
        200, json={"id": "1"},
        headers={
            "X-Business-Use-Case-Usage": (
                '{"act_1": [{"type": "ads_management", "call_count": 40, '
                '"total_time": 10, "total_cputime": 5}]}'
            )
        },
    )

    meta_ads._log_usage_header(resp, "act_1/campaigns")

    assert len(calls) == 1
    level, msg = calls[0]
    assert level == logging.DEBUG
    assert "40%" in msg and "act_1" in msg


def test_per_account_usage_logged_at_warning_over_threshold(monkeypatch):
    calls = _fake_logger(monkeypatch)
    resp = httpx.Response(
        200, json={"id": "1"},
        headers={
            "X-Business-Use-Case-Usage": (
                '{"act_1": [{"type": "ads_management", "call_count": 92, '
                '"total_time": 10, "total_cputime": 5}]}'
            )
        },
    )

    meta_ads._log_usage_header(resp, "act_1/campaigns")

    assert len(calls) == 1
    level, msg = calls[0]
    assert level == logging.WARNING
    assert "92%" in msg


def test_app_level_usage_header_has_no_account_id(monkeypatch):
    calls = _fake_logger(monkeypatch)
    resp = httpx.Response(
        200, json={"id": "1"},
        headers={
            "X-App-Usage": '{"call_count": 10, "total_time": 5, "total_cputime": 5}'
        },
    )

    meta_ads._log_usage_header(resp, "act_1/campaigns")

    assert len(calls) == 1
    level, msg = calls[0]
    assert level == logging.DEBUG
    assert "X-App-Usage" in msg
    assert " for " not in msg  # no account id to name


@pytest.mark.asyncio
async def test_request_still_works_when_the_usage_header_is_present(capture):
    """The capture point must not disturb a normal successful call."""
    seen, replies = capture
    replies["headers"] = {
        "X-Business-Use-Case-Usage": '{"act_1": [{"call_count": 5}]}'
    }

    result = await meta_ads._request("GET", "act_1/campaigns", "tok")

    assert result == {"id": "1"}
    assert seen[0].method == "GET"


# ── fetch_delivery_estimate ─────────────────────────────────────────────────
# The ads_read justification promises a delivery estimate on the plan screen;
# nothing in the codebase called this endpoint before now.


@pytest.mark.asyncio
async def test_fetch_delivery_estimate_sends_a_get_with_json_encoded_targeting(capture):
    seen, replies = capture
    replies["json"] = {
        "data": [{
            "estimate_mau_lower_bound": 10_000,
            "estimate_mau_upper_bound": 50_000,
            "estimate_ready": True,
        }]
    }

    out = await meta_ads.fetch_delivery_estimate(
        "act_1", "tok",
        optimization_goal="REACH",
        targeting_spec={"geo_locations": {"countries": ["US"]}},
    )

    assert out == {
        "estimate_mau_lower_bound": 10_000,
        "estimate_mau_upper_bound": 50_000,
        "estimate_ready": True,
    }
    req = seen[0]
    assert req.method == "GET"
    assert "act_1/delivery_estimate" in str(req.url)
    assert "optimization_goal=REACH" in str(req.url)
    # targeting_spec rides as a JSON string, the documented shape for this
    # endpoint's complex params.
    import json as _json
    import urllib.parse as _url
    qs = dict(_url.parse_qsl(str(req.url).split("?", 1)[1]))
    assert _json.loads(qs["targeting_spec"]) == {"geo_locations": {"countries": ["US"]}}


@pytest.mark.asyncio
async def test_fetch_delivery_estimate_returns_none_without_an_ad_account():
    out = await meta_ads.fetch_delivery_estimate(
        "", "tok", optimization_goal="REACH", targeting_spec={"a": 1},
    )
    assert out is None


@pytest.mark.asyncio
async def test_fetch_delivery_estimate_returns_none_on_empty_data(capture):
    _, replies = capture
    replies["json"] = {"data": []}

    out = await meta_ads.fetch_delivery_estimate(
        "act_1", "tok", optimization_goal="REACH", targeting_spec={"a": 1},
    )
    assert out is None


@pytest.mark.asyncio
async def test_fetch_delivery_estimate_degrades_to_none_on_metas_deprecation_error(capture):
    """Meta's own docs warn this edge can answer with a deprecated-version
    error (code 2635) rather than data — this must never surface as a broken
    plan screen."""
    _, replies = capture
    replies["json"] = {
        "error": {"message": "deprecated version of the Ads API", "type": "OAuthException", "code": 2635}
    }

    out = await meta_ads.fetch_delivery_estimate(
        "act_1", "tok", optimization_goal="REACH", targeting_spec={"a": 1},
    )
    assert out is None
