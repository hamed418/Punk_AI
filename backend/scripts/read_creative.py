"""
scripts/read_creative.py
────────────────────────
Dump what Meta actually stored on a campaign's ad creatives. Read-only.

``create_ad_creative`` composes an ``asset_feed_spec`` for a multi-media ad and
Meta may keep it, trim it, or discard it with a 200 and no warning. Nothing in a
publish log distinguishes those from the outside. This reads a creative back and
prints Meta's own JSON, so an ad built BY HAND in Ads Manager can be used as the
reference shape our payload has to match.

    .venv/Scripts/python.exe scripts/read_creative.py --email user@example.com
    .venv/Scripts/python.exe scripts/read_creative.py --email x@y.com --campaign-id 123
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import model_registry  # noqa: F401,E402  — registers every ORM model
from app.db.database import AsyncSessionLocal  # noqa: E402
from app.modules.user.models import User  # noqa: E402
from app.services import meta_ads  # noqa: E402
from app.services.oauth import get_meta_credentials  # noqa: E402

# The fields _TEMPLATE_AD_FIELDS deliberately leaves out. That constant feeds the
# campaign-template importer, which reads it on every template pick — diagnostics
# do not belong there, so they are asked for separately here.
# asset_feed_spec is asked for AGAIN here, directly on the creative, even though
# fetch_campaign_tree already requests it nested under ``creative{...}``. Graph's
# nested expansion returns it inconsistently; a direct GET on the creative id does
# not. Reading it twice costs one call and is the difference between "this ad has
# one image" and "we asked the wrong way".
# (asset_customization_rules is not a creative field — it lives inside
# asset_feed_spec.)
_EXTRA_CREATIVE_FIELDS = (
    "id,name,asset_feed_spec,object_story_spec,degrees_of_freedom_spec,"
    "instagram_user_id,effective_object_story_id"
)


async def main(email: str, campaign_id: str) -> int:
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

    tree = await meta_ads.fetch_campaign_tree(campaign_id, token)

    # fetch_campaign_tree already returns creative{object_story_spec, ...,
    # asset_feed_spec}; only the diagnostic fields above need a second call.
    for adset in tree.get("adsets") or []:
        for ad in adset.get("ads") or []:
            creative = ad.get("creative") or {}
            if not creative.get("id"):
                continue
            extra = await meta_ads._request(
                "GET", creative["id"], token,
                json_data={"fields": _EXTRA_CREATIVE_FIELDS},
            )
            creative.update(extra)

    print(json.dumps(tree, indent=2, default=str))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    p.add_argument("--email", required=True, help="account the campaign belongs to")
    p.add_argument("--campaign-id", default="52534883922333")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.email, args.campaign_id)))
