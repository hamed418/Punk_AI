"""
scripts/probe_mixed_feed.py
───────────────────────────
Does Meta keep an asset feed carrying BOTH images and videos?

A live matrix run showed one mixed shape accepted with a 200 and then stored with
``0 of 1 videos`` — but that was a single payload (``AUTOMATIC_FORMAT``, image
primary). This tries the plausible shapes side by side and prints what Meta
actually stored for each, so the "one kind per ad or not" question is answered by
the API rather than by inference.

Creates **ad creatives only** — no campaign, no ad set, no ad. A creative is an
inert object: it cannot deliver and cannot spend. Every one is deleted again
before the script exits, and the ids are printed either way.

    .venv/Scripts/python.exe scripts/probe_mixed_feed.py --email user@example.com
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import model_registry  # noqa: F401,E402  — registers every ORM model
from app.db.database import AsyncSessionLocal  # noqa: E402
from app.modules.user.models import User  # noqa: E402
from app.services import meta_ads  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402

_LINK = "https://example.com"


def _feed(
    images: list[str], videos: list[dict], ad_formats: list[str], titles: int = 2
) -> dict:
    feed: dict = {
        "ad_formats": ad_formats,
        "titles": [{"text": "Probe headline"}, {"text": "Second headline"}][:titles],
        "bodies": [{"text": "Probe body copy."}],
        "call_to_action_types": ["LEARN_MORE"],
        "link_urls": [{"website_url": _LINK}],
        "optimization_type": "DEGREES_OF_FREEDOM",
    }
    if images:
        feed["images"] = [{"hash": h} for h in images]
    if videos:
        feed["videos"] = videos
    return feed


async def main(email: str, mode: str) -> int:
    logging.disable(logging.INFO)
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
    if user is None:
        print(f"no user with email {email}", file=sys.stderr)
        return 1
    creds = await get_meta_credentials(str(user.id))
    if not creds:
        print(f"{email} has no valid Meta connection", file=sys.stderr)
        return 1
    token = creds["access_token"]
    act = meta_ads._act(creds["ad_account_id"])
    page_id = creds.get("page_id")

    # Reuse assets the account already holds — uploading fresh ones would prove
    # nothing extra and costs quota on an account that throttles hard.
    imgs = await meta_ads._request(
        "GET", f"{act}/adimages", token, json_data={"fields": "hash", "limit": 3},
    )
    vids = await meta_ads._request(
        "GET", f"{act}/advideos", token, json_data={"fields": "id", "limit": 1},
    )
    hashes = [i["hash"] for i in (imgs.get("data") or []) if i.get("hash")]
    video_ids = [v["id"] for v in (vids.get("data") or []) if v.get("id")]
    if not hashes or not video_ids:
        print(
            f"account needs at least 1 image and 1 video: got {len(hashes)} image(s), "
            f"{len(video_ids)} video(s)",
            file=sys.stderr,
        )
        return 1
    print(f"using image={hashes[0]} video={video_ids[0]} page={page_id}\n")

    thumb = await meta_ads.fetch_video_thumbnail(video_ids[0], token)
    video_entry: dict = {"video_id": video_ids[0]}
    if thumb:
        video_entry["thumbnail_url"] = thumb

    story = {
        "page_id": page_id,
        "link_data": {
            "image_hash": hashes[0],
            "name": "Probe headline",
            "message": "Probe body copy.",
            "link": _LINK,
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": _LINK}},
        },
    }
    video_story = {
        "page_id": page_id,
        "video_data": {
            "video_id": video_ids[0],
            "title": "Probe headline",
            "message": "Probe body copy.",
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": _LINK}},
            **({"image_url": thumb} if thumb else {}),
        },
    }

    # Round 1 said every feed carrying a video comes back without it — including
    # a videos-ONLY feed, which no mixing rule can explain. Round 2 asks why:
    # is the video simply not usable, or is the entry shape wrong?
    status = await meta_ads._request(
        "GET", video_ids[0], token, json_data={"fields": "id,status,published"},
    )
    print(f"video status: {json.dumps(status, default=str)}\n")

    video_variants: list[tuple[str, dict]] = [
        ("videos only, thumbnail_url", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed([], [video_entry], ["SINGLE_VIDEO"]),
        }),
        ("videos only, no thumbnail at all", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed([], [{"video_id": video_ids[0]}], ["SINGLE_VIDEO"]),
        }),
        ("videos only, thumbnail_hash instead of url", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed(
                [], [{"video_id": video_ids[0], "thumbnail_hash": hashes[0]}],
                ["SINGLE_VIDEO"],
            ),
        }),
        ("videos only, AUTOMATIC_FORMAT", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed([], [video_entry], ["AUTOMATIC_FORMAT"]),
        }),
    ]

    # The reported case, and the one cell no run had ever covered: several images
    # on an ad that has ONE headline and ONE body. The code assumes Meta discards
    # such a feed whole ("it only combines media when the copy varies too"); this
    # is what actually decides whether that assumption is real.
    solo_variants: list[tuple[str, dict]] = [
        ("3 images, ONE headline, ONE body  [THE REPORTED CASE]", {
            "object_story_spec": story,
            "asset_feed_spec": _feed(hashes[:3], [], ["SINGLE_IMAGE"], titles=1),
        }),
        ("3 images, TWO headlines (known-good control)", {
            "object_story_spec": story,
            "asset_feed_spec": _feed(hashes[:3], [], ["SINGLE_IMAGE"], titles=2),
        }),
        # The lever the user's hand-built Ads Manager ad actually carried. If this
        # is what makes a one-headline feed stick, it is the whole fix.
        ("3 images, ONE headline + standard_enhancements OPT_IN", {
            "object_story_spec": story,
            "asset_feed_spec": _feed(hashes[:3], [], ["SINGLE_IMAGE"], titles=1),
            "degrees_of_freedom_spec": {
                "creative_features_spec": {
                    "standard_enhancements": {"enroll_status": "OPT_IN"},
                    "advantage_plus_creative": {"enroll_status": "OPT_IN"},
                }
            },
        }),
        ("3 images, ONE headline, no optimization_type", {
            "object_story_spec": story,
            "asset_feed_spec": {
                k: v
                for k, v in _feed(hashes[:3], [], ["SINGLE_IMAGE"], titles=1).items()
                if k != "optimization_type"
            },
        }),
    ]

    # A VIDEO ad that also carries text variations. The video itself rides the
    # object_story_spec, so the feed only has to keep the copy — but publish sends
    # the video in the feed too, which Meta always discards, and the discard is
    # then reported to the user as "your extras didn't run". Does dropping the
    # videos key keep the copy variations working?
    videotext_variants: list[tuple[str, dict]] = [
        ("video ad, 2 headlines, videos key sent (what we ship today)", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed([], [video_entry], ["SINGLE_VIDEO"]),
        }),
        ("video ad, 2 headlines, NO videos key", {
            "object_story_spec": video_story,
            "asset_feed_spec": {
                k: v
                for k, v in _feed([], [], ["SINGLE_VIDEO"]).items()
                if k != "videos"
            },
        }),
    ]

    # Each variant is one hypothesis about why the video was dropped.
    variants: list[tuple[str, dict]] = [
        ("image primary + AUTOMATIC_FORMAT (what we ship today)", {
            "object_story_spec": story,
            "asset_feed_spec": _feed([hashes[0]], [video_entry], ["AUTOMATIC_FORMAT"]),
        }),
        ("image primary + SINGLE_VIDEO", {
            "object_story_spec": story,
            "asset_feed_spec": _feed([hashes[0]], [video_entry], ["SINGLE_VIDEO"]),
        }),
        ("video primary + AUTOMATIC_FORMAT", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed([hashes[0]], [video_entry], ["AUTOMATIC_FORMAT"]),
        }),
        ("video primary, videos only (control)", {
            "object_story_spec": video_story,
            "asset_feed_spec": _feed([], [video_entry], ["SINGLE_VIDEO"]),
        }),
        ("image primary, images only (control)", {
            "object_story_spec": story,
            "asset_feed_spec": _feed(hashes[:2], [], ["SINGLE_IMAGE"]),
        }),
    ]

    created: list[str] = []
    try:
        for label, body in {"videos": video_variants, "solo": solo_variants, "videotext": videotext_variants}.get(mode, variants):
            sent = body["asset_feed_spec"]
            want = (len(sent.get("images") or []), len(sent.get("videos") or []))
            try:
                res = await meta_ads._request(
                    "POST", f"{act}/adcreatives", token,
                    json_data={"name": f"[probe] {label}", **body},
                )
            except meta_ads.MetaAdsError as exc:
                print(f"REJECTED  {label}\n          {exc}\n")
                continue
            cid = str(res["id"])
            created.append(cid)
            back = await meta_ads._request(
                "GET", cid, token, json_data={"fields": "asset_feed_spec"},
            )
            stored = back.get("asset_feed_spec") or {}
            got = (len(stored.get("images") or []), len(stored.get("videos") or []))
            verdict = "KEPT ALL" if got == want else "TRIMMED"
            if not stored:
                verdict = "FEED DISCARDED WHOLE"
            print(
                f"{verdict}  {label}\n"
                f"          sent images/videos={want}  stored={got}  creative={cid}\n"
            )
    finally:
        for cid in created:
            try:
                await meta_ads._request("DELETE", cid, token)
            except meta_ads.MetaAdsError as exc:
                print(f"could not delete probe creative {cid}: {exc}", file=sys.stderr)
        print(f"cleaned up {len(created)} probe creative(s)")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    p.add_argument("--email", required=True)
    p.add_argument("--mode", choices=("mixed", "videos", "solo", "videotext"), default="mixed")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.email, args.mode)))
