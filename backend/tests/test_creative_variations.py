"""Variations on an ad — the wire shape and the fallback.

More than one headline, body, or image/video switches the creative from
``object_story_spec`` to ``asset_feed_spec`` — Ads Manager's "Add another option"
and its "select up to 10 media in a Single image or video ad". The two live in
different places on the request, and sending both is rejected, so the shape is
worth pinning: publishing five headlines as one concatenated string, or dropping
four of them silently, both look like a working publish.

Combining media into one ad is the alternative to fanning it out into separate
ads, not a replacement — the editor still offers both.
"""

from __future__ import annotations

import pytest

from app.graph.meta_spec.models import CreativeSpec
from app.services import meta_ads


def _creative(**kw) -> CreativeSpec:
    return CreativeSpec(
        title="Fresh Bread Daily",
        body="Baked at 5am, sold by noon.",
        call_to_action="LEARN_MORE",
        link="https://example.com",
        **kw,
    )


# ── which variations publish ─────────────────────────────────────────────────


def test_an_ad_without_alternates_publishes_one_of_each():
    assert _creative().text_variations() == (
        ["Fresh Bread Daily"], ["Baked at 5am, sold by noon."],
    )


def test_ai_suggestions_alone_publish_one_of_each():
    """The regression this split exists for. The plan builder fills
    ``*_suggestions`` with five ideas on every ad; they are the editor's dropdown,
    not an instruction to publish. Reading them here turned every ad the user
    never touched into a five-variation dynamic creative."""
    c = _creative(
        title_suggestions=[f"Headline {i}" for i in range(5)],
        body_suggestions=[f"Body {i}" for i in range(5)],
    )
    assert c.text_variations() == (
        ["Fresh Bread Daily"], ["Baked at 5am, sold by noon."],
    )


def test_variants_publish_with_the_primary_first_deduped():
    c = _creative(
        # The editor may leave the primary in the list, and it must not ship
        # twice. A blank is what an untouched "add another" row leaves behind.
        title_variants=["Fresh Bread Daily", "Still Warm at 9am", ""],
        body_variants=["Two ovens, no shortcuts."],
    )
    titles, bodies = c.text_variations()
    assert titles == ["Fresh Bread Daily", "Still Warm at 9am"]
    assert bodies == ["Baked at 5am, sold by noon.", "Two ovens, no shortcuts."]


def test_variations_capped_at_metas_five():
    """The field holds five and the primary may not be one of them — six would
    reach Meta without the cap in ``text_variations``."""
    c = _creative(title_variants=[f"Headline {i}" for i in range(5)])
    titles = c.text_variations()[0]
    assert len(titles) == 5
    assert titles[0] == "Fresh Bread Daily"


@pytest.mark.parametrize(
    "kw",
    [
        {"object_story_id": "1_2"},                      # boosted post
        {                                                # carousel
            "format": "CAROUSEL",
            "cards": [
                {"title": "A", "link": "https://a.com", "image_hash": "h1"},
                {"title": "B", "link": "https://b.com", "image_hash": "h2"},
            ],
        },
    ],
)
def test_variants_are_accepted_where_they_cannot_publish(kw):
    """A plan can reach these formats carrying variants — the user adds them on a
    single ad, then switches format. Rejecting it would make the plan
    unsubmittable over copy the ad was never going to use; publish drops the
    extras instead (see the wire tests below)."""
    assert _creative(title_variants=["A", "B"], **kw).text_variations()[0] == [
        "Fresh Bread Daily", "A", "B",
    ]


# ── which media may be combined ──────────────────────────────────────────────


def test_extra_media_needs_a_primary():
    """Extras sit beside a primary. Without this, publish skips the ad for having
    no media while the editor shows several attached."""
    with pytest.raises(ValueError, match="primary image or video"):
        _creative(extra_media=[{"media_id": "m2"}])


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        # A boosted post IS the existing post — Meta ignores anything composed
        # beside object_story_id, so extras would silently do nothing.
        ({"object_story_id": "1_2"}, "boosted post"),
        (
            {
                "format": "CAROUSEL",
                "cards": [
                    {"title": "A", "link": "https://a.com", "image_hash": "h1"},
                    {"title": "B", "link": "https://b.com", "image_hash": "h2"},
                ],
            },
            "each card",
        ),
    ],
)
def test_extra_media_rejected_where_it_cannot_publish(kw, match):
    """Unlike text variants, which a plan may carry into these formats, extra
    media is rejected outright — the editor clears it on a format switch, so
    reaching here means the spec is wrong, not merely stale."""
    with pytest.raises(ValueError, match=match):
        _creative(image_hash="h0", extra_media=[{"media_id": "m2"}], **kw)


def test_extra_media_kind_follows_a_post_upload_reference():
    c = _creative(image_hash="h0", extra_media=[{"image_hash": "h1"}])
    assert c.extra_media[0].media_kind == "image"


@pytest.mark.parametrize(
    ("primary", "extra"),
    [
        ({"image_hash": "h0"}, {"video_id": "v1"}),
        ({"video_id": "v0"}, {"image_hash": "h1"}),
        ({"video_id": "v0"}, {"video_id": "v1"}),
        ({"media_id": "m0", "media_kind": "image"}, {"media_id": "m1", "media_kind": "video"}),
    ],
)
def test_combining_media_on_one_ad_is_images_only(primary, extra):
    """Measured against a live ad account (scripts/probe_mixed_feed.py): Meta
    strips ``videos`` out of an asset_feed_spec every time — every ad_formats
    value, every thumbnail shape, a "ready" video, even a feed carrying nothing
    else. The ad publishes looking correct and runs one asset.

    So a video gets an ad to itself. Rejected here, where the plan is editable.
    """
    with pytest.raises(ValueError, match="images only"):
        _creative(**primary, extra_media=[extra])


def test_several_images_on_one_ad_stay_allowed():
    c = _creative(image_hash="h0", extra_media=[{"image_hash": "h1"}, {"image_hash": "h2"}])
    assert len(c.extra_media) == 2


# ── a media-only feed borrows a headline so Meta keeps it ────────────────────
# Measured: 3 images + 1 headline + 1 body => Meta discards the whole
# asset_feed_spec and the ad runs one image. 3 images + 2 headlines => all kept.


def test_combined_media_borrows_a_second_headline_from_the_suggestions():
    c = _creative(
        image_hash="h0",
        extra_media=[{"image_hash": "h1"}],
        title_suggestions=["Runner up", "Third"],
    )
    titles, bodies = c.text_variations()
    assert titles == ["Fresh Bread Daily", "Runner up"]
    # Only one is borrowed — enough to keep the feed, without republishing copy
    # the user never picked as if it were four separate ads.
    assert bodies == ["Baked at 5am, sold by noon."]


def test_it_falls_back_to_the_body_when_no_headline_suggestion_fits():
    c = _creative(
        image_hash="h0",
        extra_media=[{"image_hash": "h1"}],
        # The only suggestion repeats the primary, so it de-dupes away.
        title_suggestions=["Fresh Bread Daily"],
        body_suggestions=["Another body"],
    )
    titles, bodies = c.text_variations()
    assert titles == ["Fresh Bread Daily"]
    assert bodies == ["Baked at 5am, sold by noon.", "Another body"]


def test_an_ad_the_user_already_varied_borrows_nothing():
    c = _creative(
        image_hash="h0",
        extra_media=[{"image_hash": "h1"}],
        title_variants=["Mine"],
        title_suggestions=["Not mine"],
    )
    assert c.text_variations()[0] == ["Fresh Bread Daily", "Mine"]


def test_a_single_media_ad_borrows_nothing():
    """No extra media, no feed, nothing to rescue — the suggestions stay a
    picklist, which is the rule everywhere else."""
    c = _creative(title_suggestions=["Runner up"], body_suggestions=["Other body"])
    assert c.text_variations() == (["Fresh Bread Daily"], ["Baked at 5am, sold by noon."])


def test_an_unknown_extra_kind_is_left_to_publish():
    """A bare media_id says nothing about the file, so the spec cannot judge it.
    ``media.py`` re-checks against MediaFile.media_type, which is the first point
    that actually knows."""
    c = _creative(image_hash="h0", extra_media=[{"media_id": "m1"}])
    assert c.extra_media[0].media_kind is None


# ── the wire shape ───────────────────────────────────────────────────────────


def _capture(monkeypatch, *, fail_first: bool = False) -> list[dict]:
    """Record the ad-creative POSTs only.

    ``create_ad_creative`` also reads a video's poster frame (Meta rejects a
    video creative that names none), so the creative is not necessarily the
    first request any more. Filtering by endpoint keeps these assertions about
    the creative payload rather than about call ordering.
    """
    calls: list[dict] = []

    async def _fake_request(method, path, token, json_data=None, **kw):
        if not str(path).endswith("/adcreatives"):
            return {}                      # thumbnail lookup and friends
        calls.append(json_data or {})
        if fail_first and len(calls) == 1:
            raise meta_ads.MetaAdsError("Invalid parameter", code=100)
        return {"id": f"creative-{len(calls)}"}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    return calls


_ARGS = dict(
    name="Ad 1 Creative",
    page_id="pg_1",
    media_type="image",
    media_ref="img-hash",
    title="Fresh Bread Daily",
    body="Baked at 5am, sold by noon.",
    cta_type="LEARN_MORE",
    link_url="https://example.com",
    ad_account_id="act_1",
    access_token="tok",
)


@pytest.mark.asyncio
async def test_one_headline_keeps_the_story_spec(monkeypatch):
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(**_ARGS, titles=["Fresh Bread Daily"])
    body = calls[0]
    assert "asset_feed_spec" not in body
    assert body["object_story_spec"]["link_data"]["name"] == "Fresh Bread Daily"


@pytest.mark.asyncio
async def test_multiple_titles_build_an_asset_feed(monkeypatch):
    calls = _capture(monkeypatch)
    creative_id = await meta_ads.create_ad_creative(
        **_ARGS,
        description="Free delivery",
        titles=["Fresh Bread Daily", "Still Warm at 9am"],
        bodies=["Baked at 5am, sold by noon.", "Two ovens, no shortcuts."],
    )
    assert creative_id == "creative-1"
    feed = calls[0]["asset_feed_spec"]
    assert [t["text"] for t in feed["titles"]] == [
        "Fresh Bread Daily", "Still Warm at 9am",
    ]
    assert len(feed["bodies"]) == 2
    assert feed["images"] == [{"hash": "img-hash"}]
    assert feed["ad_formats"] == ["SINGLE_IMAGE"]
    assert feed["link_urls"] == [{"website_url": "https://example.com"}]
    assert feed["descriptions"] == [{"text": "Free delivery"}]
    # The story spec keeps the full creative. Stripping it to the page id makes
    # this a Dynamic Creative ad, which Meta only accepts in a Dynamic Creative ad
    # set (subcode 1885998) — the feed rides ALONGSIDE the ad that runs.
    assert calls[0]["object_story_spec"]["link_data"]["link"] == "https://example.com"
    assert calls[0]["object_story_spec"]["link_data"]["image_hash"] == "img-hash"


@pytest.mark.asyncio
async def test_a_video_ads_feed_carries_copy_only(monkeypatch):
    """A video ad's video rides ``object_story_spec.video_data`` — the feed exists
    only to hold the copy variations.

    It must NOT also list the video: Meta never stores ``videos`` in an asset feed
    (scripts/probe_mixed_feed.py --mode videotext), so sending the key made the
    read-back see "0 of 1 videos" and warn the user their extras had not run — on
    every video ad with a second headline, none of which was true.
    """
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(
        **{**_ARGS, "media_type": "video", "media_ref": "vid-1"},
        titles=["One", "Two"],
    )
    feed = calls[0]["asset_feed_spec"]
    assert feed["ad_formats"] == ["SINGLE_VIDEO"]
    assert "videos" not in feed
    assert "images" not in feed
    assert [t["text"] for t in feed["titles"]] == ["One", "Two"]
    # The video still runs — it is on the story spec, where it always was.
    assert calls[0]["object_story_spec"]["video_data"]["video_id"] == "vid-1"


@pytest.mark.asyncio
async def test_extra_media_builds_an_asset_feed_on_its_own(monkeypatch):
    """One headline, several images: the media alone is enough to need the feed.
    Before, extra media had nowhere to go and only the primary published."""
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(
        **_ARGS,
        titles=["Fresh Bread Daily"],
        extra_media=[("img-2", "image"), ("img-3", "image")],
    )
    feed = calls[0]["asset_feed_spec"]
    assert feed["images"] == [
        {"hash": "img-hash"}, {"hash": "img-2"}, {"hash": "img-3"},
    ]
    assert feed["ad_formats"] == ["SINGLE_IMAGE"]
    assert "videos" not in feed
    # One headline still ships as one — combining media must not invent copy.
    assert len(feed["titles"]) == 1


@pytest.mark.asyncio
async def test_the_feed_names_the_one_kind_the_ad_carries(monkeypatch):
    """"An asset feed can have exactly one ad format" (subcode 1885374).

    One kind per ad — enforced by ``CreativeSpec`` and re-checked at publish —
    means there is only ever one to name, so this never has to guess.
    """
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(
        **_ARGS, extra_media=[("img-2", "image"), ("img-3", "image")],
    )
    assert calls[0]["asset_feed_spec"]["ad_formats"] == ["SINGLE_IMAGE"]


@pytest.mark.asyncio
async def test_feed_rides_beside_the_creative_as_degrees_of_freedom(monkeypatch):
    """The two halves of the shape Meta actually accepts, asserted together.

    They only work as a pair: DEGREES_OF_FREEDOM without the full story spec is
    "The link field is required" (subcode 2061015), and the full story spec
    without it is "Object story spec is ill formed" (subcode 1443048). Sending
    neither — a feed on a page-only story spec — builds a Dynamic Creative ad
    that no ordinary ad set will take (subcode 1885998). All three shapes were
    tried against a live ad account; this is the one that published.
    """
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(**_ARGS, titles=["A", "B"], bodies=["one", "two"])
    assert calls[0]["asset_feed_spec"]["optimization_type"] == "DEGREES_OF_FREEDOM"
    assert calls[0]["object_story_spec"]["link_data"]["name"] == _ARGS["title"]


@pytest.mark.asyncio
async def test_rejected_media_feed_falls_back_to_the_primary_media(monkeypatch):
    """Same deal as the text fallback: a refused feed costs the extra media, not
    the campaign. The primary is what the story spec keeps."""
    calls = _capture(monkeypatch, fail_first=True)
    reasons: list[str] = []
    creative_id = await meta_ads.create_ad_creative(
        **_ARGS, extra_media=[("img-2", "image")], on_fallback=reasons.append,
    )
    assert creative_id == "creative-2"
    assert "asset_feed_spec" not in calls[1]
    assert calls[1]["object_story_spec"]["link_data"]["image_hash"] == "img-hash"
    assert reasons


def _capture_with_readback(monkeypatch, stored: dict | None) -> list[dict]:
    """Like ``_capture``, but the creative reads back as ``stored``.

    Meta answers a trimmed feed with a plain 200 — the loss is only visible in
    what the creative says afterwards, which is what this lets the tests set.
    """
    calls: list[dict] = []

    async def _fake_request(method, path, token, json_data=None, **kw):
        if method == "GET" and (json_data or {}).get("fields") == "asset_feed_spec":
            return {"asset_feed_spec": stored} if stored else {}
        if not str(path).endswith("/adcreatives"):
            return {}
        calls.append(json_data or {})
        return {"id": f"creative-{len(calls)}"}

    monkeypatch.setattr(meta_ads, "_request", _fake_request)
    return calls


@pytest.mark.asyncio
async def test_a_feed_stored_intact_reports_nothing(monkeypatch):
    _capture_with_readback(monkeypatch, {
        "titles": [{"text": "A"}, {"text": "B"}],
        "bodies": [{"text": "one"}],
        "images": [{"hash": "img-hash"}, {"hash": "img-2"}],
    })
    reasons: list[str] = []
    await meta_ads.create_ad_creative(
        **_ARGS, titles=["A", "B"], extra_media=[("img-2", "image")],
        on_fallback=reasons.append,
    )
    assert reasons == []


@pytest.mark.asyncio
async def test_a_silently_trimmed_feed_is_reported(monkeypatch):
    """Meta takes the feed with a 200 and stores less than it was sent.

    Live behaviour, on a real ad account: a feed whose only multi-valued field
    is media comes back with no ``asset_feed_spec`` at all, and ``videos`` are
    dropped beside images. The ad publishes either way, so nothing but reading
    the creative back tells the user their extras are not running.
    """
    _capture_with_readback(monkeypatch, {
        "titles": [{"text": "A"}, {"text": "B"}],
        "bodies": [{"text": "one"}],
        "images": [{"hash": "img-hash"}],          # the second image did not stick
    })
    reasons: list[str] = []
    await meta_ads.create_ad_creative(
        **_ARGS, titles=["A", "B"], extra_media=[("img-2", "image")],
        on_fallback=reasons.append,
    )
    assert reasons == ["Meta kept 1 of 2 images"]


@pytest.mark.asyncio
async def test_a_feed_dropped_whole_is_reported(monkeypatch):
    _capture_with_readback(monkeypatch, None)
    reasons: list[str] = []
    await meta_ads.create_ad_creative(
        **_ARGS, extra_media=[("img-2", "image"), ("img-3", "image")],
        on_fallback=reasons.append,
    )
    assert reasons and "more than one headline or body" in reasons[0]


@pytest.mark.asyncio
async def test_instant_form_ad_never_uses_an_asset_feed(monkeypatch):
    """The button opens a form, not a link_url, and the feed has nowhere to put
    the form id — so a lead ad keeps the single-text creative."""
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(
        **_ARGS, lead_gen_form_id="form-1", titles=["One", "Two"],
    )
    assert "asset_feed_spec" not in calls[0]
    cta = calls[0]["object_story_spec"]["link_data"]["call_to_action"]
    assert cta["value"] == {"lead_gen_form_id": "form-1"}


@pytest.mark.asyncio
async def test_carousel_ignores_the_extra_headlines(monkeypatch):
    """A carousel's copy lives on its cards. The asset feed would replace the
    child_attachments the cards build, so the extras are dropped, not sent."""
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(
        **{**_ARGS, "ad_format": "CAROUSEL"},
        cards=[
            {"title": "A", "link": "https://a.com", "image_hash": "h1"},
            {"title": "B", "link": "https://b.com", "image_hash": "h2"},
        ],
        titles=["One", "Two"],
    )
    assert "asset_feed_spec" not in calls[0]
    assert len(calls[0]["object_story_spec"]["link_data"]["child_attachments"]) == 2


@pytest.mark.asyncio
async def test_boosted_post_ignores_the_extra_headlines(monkeypatch):
    """The ad IS the existing post — its own caption runs, and Meta ignores
    anything composed alongside object_story_id."""
    calls = _capture(monkeypatch)
    await meta_ads.create_ad_creative(
        **_ARGS, object_story_id="pg_1_9", titles=["One", "Two"],
    )
    assert calls[0] == {"name": "Ad 1 Creative", "object_story_id": "pg_1_9"}


@pytest.mark.asyncio
async def test_rejected_asset_feed_falls_back_to_single_text(monkeypatch):
    """Whether an account may vary text on an ordinary ad set is an account-level
    rule. A rejection must cost the variations, not the campaign."""
    calls = _capture(monkeypatch, fail_first=True)
    reasons: list[str] = []
    creative_id = await meta_ads.create_ad_creative(
        **_ARGS,
        titles=["Fresh Bread Daily", "Still Warm at 9am"],
        on_fallback=reasons.append,
    )
    assert creative_id == "creative-2"
    assert "asset_feed_spec" in calls[0]
    assert "asset_feed_spec" not in calls[1]
    assert calls[1]["object_story_spec"]["link_data"]["name"] == "Fresh Bread Daily"
    assert reasons and "Invalid parameter" in reasons[0]
