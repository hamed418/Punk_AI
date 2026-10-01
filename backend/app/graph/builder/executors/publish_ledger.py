"""
graph/builder/executors/publish_ledger.py
─────────────────────────────────────────
Idempotency ledger for the Meta publish.

Publishing a campaign is a multi-step remote transaction — campaign, then per ad
set: media upload, ad creative, ad set, ad — and Meta has no rollback past
deleting objects one at a time. Before this ledger existed, a failure at ad set 3
left ad sets 1 and 2 orphaned in the account, and the retry created a **second**
campaign because nothing recorded what had already succeeded.

The ledger records every created object id keyed by ad set index, and is
committed to the ``campaigns.publish_state`` column immediately after each
creation. A retry then skips anything already present and resumes where it
stopped.

It degrades safely: with no ``campaign_id`` (no draft row, no user id) it behaves
as a pure in-memory dict, so publish still works — just without cross-process
resume. That keeps unit tests and any DB-less path running unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class PublishLedger:
    """Records what publish has already created, and persists it eagerly."""

    def __init__(self, state: Optional[dict] = None, draft_id: Optional[UUID] = None) -> None:
        state = dict(state or {})
        self._draft_id = draft_id
        # One entry per campaign, keyed by campaign index as a string. Normally
        # a single "0"; an App-promotion plan with both store links publishes as
        # two campaigns (Meta puts the promoted app on the campaign, and iOS
        # installs need their own SKAdNetwork campaign), so this cannot be the
        # scalar it used to be — a second create would have overwritten the
        # first id and orphaned that campaign on every retry.
        #
        # A ledger persisted before this existed carries only "campaign_id", so
        # it is folded in here and resumes unchanged.
        self.campaigns: dict[str, str] = dict(state.get("campaigns") or {})
        if not self.campaigns and state.get("campaign_id"):
            self.campaigns["0"] = str(state["campaign_id"])
        self.custom_audience_id: Optional[str] = state.get("custom_audience_id")
        self.lookalike_audience_id: Optional[str] = state.get("lookalike_audience_id")
        # An instant form we created on the Page. Recorded so a retry reuses it
        # rather than leaving a second identical form behind on the Page.
        self.lead_form_id: Optional[str] = state.get("lead_form_id")
        # Per-ad-set maps. JSON keys are strings, so indices are stored as str.
        # Media keys are "aidx:jdx" for an ad's own image, "aidx:jdx:cidx" for a
        # carousel card's, and "aidx:jdx:mN" for the extra media combined into a
        # single-image-or-video ad. The "m" prefix is what keeps that last one
        # from colliding with a carousel card's index.
        #
        # ``aidx`` is the ad set's index in the WHOLE plan, not within its
        # campaign. A campaign split partitions ad sets across campaigns and
        # never duplicates one, so plan-wide indices stay unique and these maps
        # need no campaign dimension — which is also why an older ledger keeps
        # resuming and no media is re-uploaded per campaign.
        self.media: dict[str, str] = dict(state.get("media") or {})
        # "image" | "video" per media key. Recorded because the ref alone does not
        # say which endpoint produced it, and a cached video read back as an image
        # is built into the creative as an image_hash — an ad Meta rejects. Absent
        # for a ledger written before this map existed; the caller falls back to
        # the spec in that case.
        self.media_kinds: dict[str, str] = dict(state.get("media_kinds") or {})
        self.creatives: dict[str, str] = dict(state.get("creatives") or {})
        # What each recorded creative was BUILT FROM — a hash of the ad's copy and
        # resolved media. The draft keeps its ledger when an edited plan is
        # re-approved (repository.upsert_draft), which is right for campaigns, ad
        # sets and uploaded media, and wrong for creatives: without this the retry
        # reuses the creative id and republishes the copy the user just replaced.
        # Absent for ledgers written before this existed — treated as a match, so
        # those sessions keep resuming instead of rebuilding every creative.
        self.creative_specs: dict[str, str] = dict(state.get("creative_specs") or {})
        self.adsets: dict[str, str] = dict(state.get("adsets") or {})
        self.ads: dict[str, str] = dict(state.get("ads") or {})
        self.activated: bool = bool(state.get("activated"))
        # Individual ad set / ad ids already flipped ACTIVE. Activation is a serial
        # loop with no transaction, so a failure part-way leaves some objects live
        # and some paused; without this the retry re-POSTs every one of them and,
        # worse, cannot tell a half-activated campaign from an untouched one.
        self.activated_ids: set[str] = set(state.get("activated_ids") or [])

    # ── reads ────────────────────────────────────────────────────────────────

    @property
    def campaign_id(self) -> Optional[str]:
        """The primary campaign — the one every scalar reader downstream means.

        Kept as a property so ``resuming``, ``to_dict`` and the existing callers
        that only ever knew about one campaign keep working untouched.
        """
        return self.campaigns.get("0")

    @property
    def campaign_ids(self) -> list[str]:
        """Every campaign created, in campaign order."""
        return [self.campaigns[k] for k in sorted(self.campaigns, key=int)]

    def campaign_for(self, cidx: int) -> Optional[str]:
        return self.campaigns.get(str(cidx))

    @property
    def resuming(self) -> bool:
        """True when a previous attempt got far enough to create a campaign."""
        return bool(self.campaigns)

    def media_for(self, key: "int | str") -> Optional[str]:
        return self.media.get(str(key))

    def media_kind_for(self, key: "int | str") -> Optional[str]:
        return self.media_kinds.get(str(key))

    def creative_for(self, key: "int | str", fingerprint: Optional[str] = None) -> Optional[str]:
        """The creative already built for this ad, or None if it must be rebuilt.

        ``fingerprint`` is what the ad looks like *now*. A recorded creative whose
        fingerprint differs was built from copy or media the user has since
        changed, so it is not reusable — returning it is how an edited ad
        republished its old headline.
        """
        creative_id = self.creatives.get(str(key))
        if creative_id is None or fingerprint is None:
            return creative_id
        recorded = self.creative_specs.get(str(key))
        return creative_id if recorded in (None, fingerprint) else None

    def adset_for(self, idx: int) -> Optional[str]:
        return self.adsets.get(str(idx))

    def ad_for(self, key: "int | str") -> Optional[str]:
        return self.ads.get(str(key))

    def to_dict(self) -> dict[str, Any]:
        return {
            # Both: "campaign_id" is what repository.save_publish_state and every
            # existing reader look for; "campaigns" is the full map.
            "campaign_id": self.campaign_id,
            "campaigns": self.campaigns,
            "custom_audience_id": self.custom_audience_id,
            "lookalike_audience_id": self.lookalike_audience_id,
            "lead_form_id": self.lead_form_id,
            "media": self.media,
            "media_kinds": self.media_kinds,
            "creatives": self.creatives,
            "creative_specs": self.creative_specs,
            "adsets": self.adsets,
            "ads": self.ads,
            "activated": self.activated,
            # Sorted for a stable JSON column: a set's iteration order is not.
            "activated_ids": sorted(self.activated_ids),
        }

    @property
    def adset_ids(self) -> list[str]:
        """Ad set ids in ad-set order, not dict-insertion order."""
        return [self.adsets[k] for k in sorted(self.adsets, key=int)]

    @property
    def ad_ids(self) -> list[str]:
        """Ad ids ordered by (adset index, ad index). Keys are ``"aidx:jdx"``
        (nested ads) or a bare ``"aidx"`` (legacy single-ad ledger)."""
        def _sort_key(k: str) -> tuple[int, int]:
            parts = k.split(":")
            aidx = int(parts[0])
            jdx = int(parts[1]) if len(parts) > 1 else 0
            return (aidx, jdx)
        return [self.ads[k] for k in sorted(self.ads, key=_sort_key)]

    # ── writes ───────────────────────────────────────────────────────────────

    async def record_campaign(self, campaign_id: str, cidx: int = 0) -> None:
        self.campaigns[str(cidx)] = campaign_id
        await self._persist()

    async def forget_campaigns(self, campaign_ids: "list[str]") -> None:
        """Drop the named campaigns after they have been deleted at Meta.

        Used when preflight fails: the campaigns created by that attempt exist
        but are empty and get removed, so the ledger must not claim them next
        time. Only the ids passed in are dropped — a campaign resumed from an
        earlier attempt is still standing, with its ad sets, and forgetting it
        would orphan it and build a duplicate on the retry.
        """
        dropped = set(campaign_ids)
        self.campaigns = {k: v for k, v in self.campaigns.items() if v not in dropped}
        await self._persist()

    async def forget_campaign_tree(self) -> None:
        """Drop every id that belongs to a campaign, after the campaigns are gone.

        ``forget_campaigns`` is not enough once ad sets exist: the adset / ad /
        creative maps still point at objects that were deleted along with their
        campaign, and the retry would hand Meta those dead ids instead of
        rebuilding. Used when a plan rejected at ad-creation time is rolled back
        so the user can edit it — the one path where a standing campaign is
        deliberately torn down.

        Media, audiences and the instant form are deliberately KEPT. All three
        live on the ad account or the Page, not inside the campaign, so deleting
        the campaign leaves them valid — and re-uploading a video the user
        already waited on is the slowest possible way to be careful.
        """
        self.campaigns = {}
        self.adsets = {}
        self.ads = {}
        self.creatives = {}
        self.creative_specs = {}
        self.activated = False
        self.activated_ids = set()
        await self._persist()

    async def record_audiences(
        self, *, custom_audience_id: Optional[str], lookalike_audience_id: Optional[str]
    ) -> None:
        self.custom_audience_id = custom_audience_id
        self.lookalike_audience_id = lookalike_audience_id
        await self._persist()

    async def record_lead_form(self, form_id: str) -> None:
        self.lead_form_id = form_id
        await self._persist()

    async def record_media(
        self, key: "int | str", media_ref: str, kind: Optional[str] = None
    ) -> None:
        self.media[str(key)] = media_ref
        if kind:
            self.media_kinds[str(key)] = kind
        await self._persist()

    async def record_creative(
        self, key: "int | str", creative_id: str, fingerprint: Optional[str] = None
    ) -> None:
        self.creatives[str(key)] = creative_id
        if fingerprint:
            self.creative_specs[str(key)] = fingerprint
        await self._persist()

    async def record_adset(self, idx: int, adset_id: str) -> None:
        self.adsets[str(idx)] = adset_id
        await self._persist()

    async def record_ad(self, key: "int | str", ad_id: str) -> None:
        self.ads[str(key)] = ad_id
        await self._persist()

    async def record_activated_id(self, obj_id: str) -> None:
        """One ad set or ad is now ACTIVE. Called per object, mid-loop."""
        self.activated_ids.add(str(obj_id))
        await self._persist()

    def needs_activation(self, ids: "list[str]") -> list[str]:
        """``ids`` minus the ones already flipped ACTIVE in an earlier attempt."""
        return [i for i in ids if i not in self.activated_ids]

    async def record_activated(self) -> None:
        self.activated = True
        await self._persist()

    # ── persistence ──────────────────────────────────────────────────────────

    async def _persist(self) -> None:
        """Commit the ledger. Never raises.

        A DB problem here must not abort a publish that is succeeding against
        Meta — losing resume capability is far better than failing a campaign
        that is already half-created. The failure is logged loudly because it
        means a subsequent retry could duplicate.
        """
        if self._draft_id is None:
            return
        try:
            from app.db.database import AsyncSessionLocal
            from app.modules.campaigns.repository import CampaignsRepository

            async with AsyncSessionLocal() as db:
                await CampaignsRepository().save_publish_state(db, self._draft_id, self.to_dict())
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.error(
                "publish ledger: could not persist state for draft %s — %s. "
                "A retry may create duplicate Meta objects.",
                self._draft_id, exc,
            )
