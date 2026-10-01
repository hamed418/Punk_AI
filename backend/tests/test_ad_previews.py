"""
tests/test_ad_previews.py
─────────────────────────
Meta's own rendering of a published ad, per placement — what the Preview &
Publish gate shows before the user sets the campaign live.

Two things are worth pinning. Meta hands back a full ``<iframe …>`` string and
we keep only the src, so the client never injects Meta's markup into the app
document. And not every placement is valid for every creative (a single-image ad
has no Reels rendering), which Meta answers with an error rather than an empty
preview — so a partial answer is the normal case, not a failure.
"""
from __future__ import annotations

import pytest

from app.services import meta_ads


def _iframe(token: str) -> dict:
    return {"data": [{"body": (
        f'<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d={token}&amp;t=x" '
        'width="320" height="568" scrolling="yes" style="border: none;"></iframe>'
    )}]}


@pytest.mark.asyncio
async def test_previews_keep_only_the_src_and_unescape_it(monkeypatch):
    async def _fake_request(method, path, access_token, **kwargs):
        assert method == "GET"
        assert path.startswith("ad-1/previews?ad_format=")
        return _iframe("AQ1")

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    previews = await meta_ads.generate_ad_previews("ad-1", "tok")

    assert len(previews) == len(meta_ads._PREVIEW_FORMATS)
    assert previews[0]["format"] == "MOBILE_FEED_STANDARD"
    assert previews[0]["label"] == "Facebook Feed"
    # &amp; came back HTML-escaped inside the iframe attribute; an escaped src
    # loads a different URL than the one Meta signed.
    assert previews[0]["src"] == (
        "https://www.facebook.com/ads/api/preview_iframe.php?d=AQ1&t=x"
    )
    assert all("<iframe" not in p["src"] for p in previews)


@pytest.mark.asyncio
async def test_unsupported_placements_are_dropped_not_fatal(monkeypatch):
    """One rejected format must not cost the user every other preview."""
    async def _fake_request(method, path, access_token, **kwargs):
        if "INSTAGRAM_STANDARD" not in path:
            raise meta_ads.MetaAdsError("unsupported ad format", code=100)
        return _iframe("AQ2")

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    previews = await meta_ads.generate_ad_previews("ad-1", "tok")

    assert [p["format"] for p in previews] == ["INSTAGRAM_STANDARD"]


@pytest.mark.asyncio
async def test_no_previews_at_all_is_an_empty_list(monkeypatch):
    """A brand-new ad can take a moment before Meta will render anything. The
    caller shows the campaign summary without previews rather than failing."""
    async def _fake_request(method, path, access_token, **kwargs):
        raise meta_ads.MetaAdsError("not ready", code=100)

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    assert await meta_ads.generate_ad_previews("ad-1", "tok") == []


@pytest.mark.asyncio
async def test_a_body_without_an_iframe_is_skipped(monkeypatch):
    async def _fake_request(method, path, access_token, **kwargs):
        return {"data": [{"body": "preview unavailable"}]}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    assert await meta_ads.generate_ad_previews("ad-1", "tok") == []


# The tests above stub `_request`, so they pin the shape of the call and nothing
# about what leaves the process. These two go one layer down, where the bug was:
# httpx replaces a URL's query string outright when a `params` dict is passed, so
# a query written into the endpoint path never reached Meta — every preview came
# back "(#100) For field 'previews': The parameter ad_format is required".
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint, expected",
    [
        ("ad-1/previews?ad_format=INSTAGRAM_STANDARD",
         {"ad_format": "INSTAGRAM_STANDARD"}),
        # list_account_campaigns — without `fields` Meta omits effective_status,
        # and the DELETED/ARCHIVED filter then keeps every campaign.
        ("act_1/campaigns?fields=id,name&limit=25",
         {"fields": "id,name", "limit": "25"}),
    ],
)
async def test_an_endpoints_own_query_survives_to_the_wire(
    monkeypatch, endpoint, expected
):
    seen: dict = {}

    async def _fake_once(method, url, params, ep, *args, **kwargs):
        seen["url"] = url
        seen["params"] = params
        return {}

    monkeypatch.setattr(meta_ads, "_request_once", _fake_once)
    # The proof is what makes `params` non-empty in production; without it there
    # is nothing for httpx to overwrite the query with and the bug hides.
    monkeypatch.setattr(meta_ads, "_appsecret_proof", lambda _tok: "proof")

    await meta_ads._request("GET", endpoint, "tok")

    assert "?" not in seen["url"]
    assert seen["params"] == {**expected, "appsecret_proof": "proof"}
