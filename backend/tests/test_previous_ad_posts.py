"""
tests/test_previous_ad_posts.py
───────────────────────────────
"Reuse a post from an older ad" — the intake form's third ad-creative answer.

The picker offers POSTS, not ads: an account that ran the same post four times
has one thing to reuse, and an ad whose copy was composed in the editor has
nothing behind it at all. Both of those, plus which creative field an Instagram
pick lands on, are decided by the mapping in ``list_account_ads`` — so they are
what this pins.
"""
from __future__ import annotations

import pytest

from app.services import meta_ads


def _ad(ad_id: str, name: str, creative: dict, status: str = "ACTIVE") -> dict:
    return {
        "id": ad_id, "name": name, "effective_status": status,
        "created_time": "2026-08-01T00:00:00+0000", "creative": creative,
    }


@pytest.mark.asyncio
async def test_the_picker_lists_posts_not_ads(monkeypatch):
    captured: dict = {}

    async def _fake_request(method, path, access_token, **kwargs):
        captured["path"] = path
        return {"data": [
            # Two ads, one post — the picker offers it once.
            _ad("1", "Spring ad", {"effective_object_story_id": "page_1"}),
            _ad("2", "Spring ad (copy)", {"effective_object_story_id": "page_1"}),
            # An unpublished inline post: object_story_id is null, which is why
            # effective_object_story_id is the field asked for.
            _ad("3", "Dark post ad", {
                "object_story_id": None, "effective_object_story_id": "page_2",
                "thumbnail_url": "https://img/2.jpg",
            }),
            # Composed in the editor — no post to reuse.
            _ad("4", "Written ad", {"object_story_spec": {"link_data": {}}}),
            # Archived: gone from the advertiser's own view already.
            _ad("5", "Old ad", {"effective_object_story_id": "page_9"}, status="ARCHIVED"),
            # Instagram-sourced: names its media instead of a story id.
            _ad("6", "IG ad", {"source_instagram_media_id": "ig_7"}),
        ]}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    posts = await meta_ads.list_account_ads("act_1", "tok", limit=25)

    # A GET body silently drops effective_status — see list_account_campaigns.
    assert captured["path"].startswith("act_1/ads?fields=")
    assert "effective_status" in captured["path"]

    assert [p["id"] for p in posts] == ["page_1", "page_2", "ig_7"]
    assert posts[0]["label"] == "Spring ad"
    assert posts[1]["image"] == "https://img/2.jpg"
    # Which creative field the pick lands on — an ad promotes one post, and the
    # two fields are mutually exclusive.
    assert [p["source"] for p in posts] == ["facebook", "facebook", "instagram"]


@pytest.mark.asyncio
async def test_a_lookup_failure_is_an_empty_picker_not_a_broken_editor(monkeypatch):
    async def _fake_request(method, path, access_token, **kwargs):
        raise meta_ads.MetaAdsError("no permission", code=200)

    monkeypatch.setattr(meta_ads, "_request", _fake_request)

    assert await meta_ads.list_account_ads("act_1", "tok") == []
