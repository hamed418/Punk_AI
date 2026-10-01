"""
tests/test_publish_idempotency.py
─────────────────────────────────
Publish hardening: Meta preflight, rollback, retries, and the resume ledger.

The behaviours under test are the ones that used to fail expensively:

  * an invalid plan created a campaign and some ad sets before Meta rejected the
    rest, leaving orphans in the account;
  * a retry after any mid-publish failure created a SECOND campaign, because
    nothing recorded what had already succeeded;
  * a throttled request failed the whole publish instead of backing off;
  * an activation failure was swallowed, so a campaign could be reported as
    published and never actually run.
"""
from __future__ import annotations

import pytest

import app.graph.builder.executors.media as media_exec
from app.graph.builder.executors.media import MetaPublishError, publish_campaign_to_meta
from app.graph.builder.executors.publish_ledger import PublishLedger
from app.graph.meta_spec import CampaignSpec
from app.services import meta_ads


# ── fixtures ──────────────────────────────────────────────────────────────────


def _plan(adsets=("Seed", "Prospecting"), media_id: str | None = "m1") -> dict:
    plan = {
        "name": "C",
        "objective": "OUTCOME_TRAFFIC",
        "adsets": [
            {
                "name": n,
                "audience_role": "seed" if i == 0 else "broad",
                "optimization_goal": "LINK_CLICKS",
                "billing_event": "IMPRESSIONS",
                "destination_type": "WEBSITE",
                "daily_budget": 5000,
                "targeting": {"geo_locations": {"countries": ["US"]}},
                "start_time": "2026-07-01T00:00:00+00:00",
                # One ad per ad set, each carrying its own image (media_id).
                "ads": [
                    {
                        "name": f"{n} Ad",
                        "creative": {
                            "title": "t", "body": "b",
                            "call_to_action": "LEARN_MORE", "link": "https://x.example",
                            "media_id": media_id,
                        },
                    }
                ],
            }
            for i, n in enumerate(adsets)
        ],
    }
    CampaignSpec.model_validate(plan)
    return plan


_USER = {
    "meta_access_token": "tok", "meta_ad_account_id": "act_1",
    "meta_page_id": "pg_1", "business_name": "Acme",
}


def _writer():
    events: list[dict] = []
    return events, events.append


class _Recorder:
    """Stands in for the whole Meta client, recording every create call."""

    def __init__(
        self,
        *,
        fail_adset_at: int | None = None,
        fail_validate_at: int | None = None,
        campaign_prefix: str = "camp",
    ):
        # A retry installs a FRESH recorder, so without a distinct prefix its
        # first campaign would be handed the same id as the one still in the
        # ledger — and a test could not tell a resumed campaign from a new one.
        self._campaign_prefix = campaign_prefix
        self.campaigns: list[str] = []
        self.campaign_specs: list = []
        self.adsets: list[str] = []
        self.ads: list[str] = []
        self.creatives: list[str] = []
        self.deleted: list[str] = []
        self.validated_campaign = 0
        self.validated_adsets = 0
        self.activated = False
        self._fail_adset_at = fail_adset_at
        self._fail_validate_at = fail_validate_at

    def install(self, monkeypatch, *, ledger: PublishLedger | None = None):
        async def _noop(*a, **k):
            return None

        async def _validate_campaign(spec, **k):
            self.validated_campaign += 1

        async def _validate_adset(adset, **k):
            i = self.validated_adsets
            self.validated_adsets += 1
            if self._fail_validate_at == i:
                raise meta_ads.MetaAdsError("Invalid optimization goal for objective")

        async def _create_campaign(spec, **k):
            # Distinct ids per call: an App-promotion plan covering both stores
            # publishes one campaign per store, and a single canned id would hide
            # a second create entirely.
            camp_id = f"{self._campaign_prefix}-{len(self.campaigns) + 1}"
            self.campaigns.append(camp_id)
            self.campaign_specs.append(spec)
            return camp_id

        async def _create_adset(adset, **k):
            i = len(self.adsets)
            if self._fail_adset_at == i:
                raise meta_ads.MetaAdsError("budget too low")
            self.adsets.append(f"adset-{i}")
            return f"adset-{i}"

        async def _create_ad(**k):
            self.ads.append(f"ad-{len(self.ads)}")
            return f"ad-{len(self.ads) - 1}"

        async def _create_creative(**k):
            self.creatives.append(f"creative-{len(self.creatives)}")
            return f"creative-{len(self.creatives) - 1}"

        async def _delete(campaign_id, access_token):
            self.deleted.append(campaign_id)

        async def _activate(*a, **k):
            self.activated = True

        async def _resolve_ad_media(marketing_plan, user_id):
            # Every ad's media_id resolves to a public URL → handed straight to
            # Meta's upload (no download/materialize step).
            return {"m1": {"file_path": "https://cdn.example/x.jpg",
                           "media_type": "image", "original_filename": "x.jpg"}}

        async def _upload(*a, **k):
            return "img-hash"

        monkeypatch.setattr(media_exec, "_resolve_ad_media", _resolve_ad_media)
        monkeypatch.setattr(meta_ads, "upload_image", _upload)
        monkeypatch.setattr(meta_ads, "build_targeting", _ret({}))
        monkeypatch.setattr(meta_ads, "validate_campaign_payload", _validate_campaign)
        monkeypatch.setattr(meta_ads, "validate_adset_payload", _validate_adset)
        monkeypatch.setattr(meta_ads, "create_campaign_from_spec", _create_campaign)
        monkeypatch.setattr(meta_ads, "create_adset_from_spec", _create_adset)
        monkeypatch.setattr(meta_ads, "create_ad", _create_ad)
        monkeypatch.setattr(meta_ads, "create_ad_creative", _create_creative)
        monkeypatch.setattr(meta_ads, "delete_campaign", _delete)
        monkeypatch.setattr(meta_ads, "activate_campaign", _activate)
        monkeypatch.setattr(meta_ads, "activate_adsets", _activate)
        monkeypatch.setattr(meta_ads, "activate_ads", _activate)

        # No DB in unit tests: hand publish whichever ledger the test wants.
        async def _ledger(*a, **k):
            return ledger if ledger is not None else PublishLedger()

        monkeypatch.setattr(media_exec, "_load_ledger", _ledger)


def _ret(value):
    async def _inner(*a, **k):
        return value
    return _inner


async def _publish(plan=None, brief=None, **kw):
    _, writer = _writer()
    return await publish_campaign_to_meta(
        _USER, {"targeting_method": "deterministic"}, plan or _plan(),
        brief or {}, writer, **kw,
    )


async def _publish_then_activate(plan=None, brief=None, **kw):
    """Publish, then run the separate activation step over what it built.

    Activation left ``publish_campaign_to_meta`` when the go_live_confirm preview
    gate was added: publishing now always ends PAUSED, and the user's answer at
    that gate is what starts delivery. These are still one story for the
    idempotency tests, so this drives both halves.
    """
    ids = await _publish(plan=plan, brief=brief, **kw)
    _, writer = _writer()
    ids["activated"] = await media_exec.activate_published_tree(
        ids, _USER, plan or _plan(), writer,
    )
    return ids


# ── preflight ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_campaign_preflight_runs_before_any_create(monkeypatch):
    rec = _Recorder()
    rec.install(monkeypatch)
    await _publish()
    assert rec.validated_campaign == 1
    assert rec.validated_adsets == 2       # every ad set checked before any created
    assert rec.campaigns == ["camp-1"]


@pytest.mark.asyncio
async def test_campaign_preflight_failure_creates_nothing(monkeypatch):
    rec = _Recorder()
    rec.install(monkeypatch)

    async def _boom(spec, **k):
        raise meta_ads.MetaAdsError("special ad category required")

    monkeypatch.setattr(meta_ads, "validate_campaign_payload", _boom)

    with pytest.raises(MetaPublishError) as exc:
        await _publish()
    assert exc.value.step == "preflight_campaign"
    assert rec.campaigns == []
    assert rec.adsets == []


@pytest.mark.asyncio
async def test_adset_preflight_failure_rolls_back_the_campaign(monkeypatch):
    """The campaign has to exist to validate ad sets against it, so a rejected
    ad set means deleting the campaign we just made — the account ends up
    exactly as it started."""
    rec = _Recorder(fail_validate_at=1)
    rec.install(monkeypatch)

    with pytest.raises(MetaPublishError) as exc:
        await _publish()
    assert exc.value.step == "preflight_adset"
    assert rec.deleted == ["camp-1"]       # rolled back
    assert rec.adsets == []                # nothing partially created


@pytest.mark.asyncio
async def test_preflight_surfaces_metas_own_wording(monkeypatch):
    rec = _Recorder()
    rec.install(monkeypatch)

    async def _boom(spec, **k):
        raise meta_ads.MetaAdsError(
            "GraphAPIError: bad", code=100,
            user_msg="Your ad account is not authorized to run housing ads.",
        )

    monkeypatch.setattr(meta_ads, "validate_campaign_payload", _boom)

    with pytest.raises(MetaPublishError) as exc:
        await _publish()
    assert "not authorized to run housing ads" in exc.value.user_message


# ── idempotent resume ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failure_records_progress_in_the_ledger(monkeypatch):
    ledger = PublishLedger()
    rec = _Recorder(fail_adset_at=1)
    rec.install(monkeypatch, ledger=ledger)

    with pytest.raises(MetaPublishError):
        await _publish()

    assert ledger.campaign_id == "camp-1"
    assert ledger.adset_for(0) == "adset-0"      # first one survived
    assert ledger.adset_for(1) is None


@pytest.mark.asyncio
async def test_retry_reuses_the_campaign_instead_of_duplicating(monkeypatch):
    """The core regression: before the ledger, this second call created a
    completely separate campaign and the user paid for both."""
    ledger = PublishLedger()

    rec1 = _Recorder(fail_adset_at=1)
    rec1.install(monkeypatch, ledger=ledger)
    with pytest.raises(MetaPublishError):
        await _publish()

    rec2 = _Recorder()
    rec2.install(monkeypatch, ledger=ledger)
    result = await _publish()

    assert rec2.campaigns == []                   # no second campaign
    assert result["campaign_id"] == "camp-1"      # continued the first one
    assert len(result["adset_ids"]) == 2


@pytest.mark.asyncio
async def test_retry_skips_the_adset_that_already_succeeded(monkeypatch):
    ledger = PublishLedger()

    rec1 = _Recorder(fail_adset_at=1)
    rec1.install(monkeypatch, ledger=ledger)
    with pytest.raises(MetaPublishError):
        await _publish()

    rec2 = _Recorder()
    rec2.install(monkeypatch, ledger=ledger)
    await _publish()

    # Only the ad set that had not been created is created on the retry.
    assert len(rec2.adsets) == 1


@pytest.mark.asyncio
async def test_retry_skips_preflight_when_resuming(monkeypatch):
    """Meta already accepted this payload on the first attempt; re-validating
    costs API quota for no new information."""
    ledger = PublishLedger()

    rec1 = _Recorder(fail_adset_at=1)
    rec1.install(monkeypatch, ledger=ledger)
    with pytest.raises(MetaPublishError):
        await _publish()

    rec2 = _Recorder()
    rec2.install(monkeypatch, ledger=ledger)
    await _publish()
    assert rec2.validated_campaign == 0
    assert rec2.validated_adsets == 0


@pytest.mark.asyncio
async def test_ledger_reuses_uploaded_media(monkeypatch):
    """Meta media ids are permanent — re-uploading the same asset wastes time
    and quota. Media is keyed per (adset:ad) as "aidx:jdx"."""
    ledger = PublishLedger({"campaign_id": "camp-1", "media": {"0:0": "img-hash"}})
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    uploads: list = []

    async def _spy_upload(*a, **k):
        uploads.append(a)
        return "new-hash"

    monkeypatch.setattr(meta_ads, "upload_image", _spy_upload)

    # Single ad set / ad whose media the ledger already has → no upload.
    await _publish(plan=_plan(adsets=("Seed",)))
    assert uploads == []


def test_ledger_orders_ids_by_adset_index_not_insertion():
    """JSON dict keys are strings; sorting them lexically would put "10" before
    "2" and mis-pair ad sets with their ads."""
    ledger = PublishLedger({"adsets": {"2": "c", "10": "d", "0": "a", "1": "b"}})
    assert ledger.adset_ids == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_retry_reuses_the_ledgers_extra_media(monkeypatch):
    """Meta media ids are permanent, so a retry must re-upload nothing — including
    the extra media combined into an ad, which is keyed "aidx:jdx:mN" so it cannot
    collide with a carousel card's "aidx:jdx:cidx"."""
    plan = _plan(adsets=("Seed",))
    plan["adsets"][0]["ads"][0]["creative"]["extra_media"] = [{"media_id": "m1"}]
    CampaignSpec.model_validate(plan)

    ledger = PublishLedger({
        "media": {"0:0": "img-primary", "0:0:m0": "img-extra"},
        "media_kinds": {"0:0": "image", "0:0:m0": "image"},
    })
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    uploads: list = []
    monkeypatch.setattr(
        meta_ads, "upload_image",
        lambda *a, **k: uploads.append(a) or _ret("img-new")(),
    )

    captured: list[dict] = []

    async def _cap_creative(**kw):
        captured.append(kw)
        return "creative-0"

    monkeypatch.setattr(meta_ads, "create_ad_creative", _cap_creative)

    _, writer = _writer()
    await publish_campaign_to_meta(_USER, {"targeting_method": "deterministic"}, plan, {}, writer)

    assert uploads == [], "a cached asset was uploaded again"
    assert captured[0]["media_ref"] == "img-primary"
    assert captured[0]["extra_media"] == [("img-extra", "image")]


@pytest.mark.asyncio
async def test_republishing_an_unchanged_plan_reuses_the_creative(monkeypatch):
    """The whole point of the ledger: nothing is rebuilt when nothing changed."""
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    await _publish(plan=_plan(adsets=("Seed",)))
    await _publish(plan=_plan(adsets=("Seed",)))
    assert rec.creatives == ["creative-0"]


@pytest.mark.asyncio
async def test_edited_copy_rebuilds_the_creative_and_repoints_the_ad(monkeypatch):
    """An edited ad must not republish the creative built from the old copy.

    The draft keeps its publish ledger when a re-approved plan is saved, so
    without the fingerprint the second publish reused ``creatives["0:0"]`` and the
    user's edit — new headline, added variations, added media — reached Meta
    nowhere. The existing ad is re-pointed rather than duplicated.
    """
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    repointed: list[tuple] = []

    async def _update_ad_creative(ad_id, creative_id, access_token):
        repointed.append((ad_id, creative_id))

    monkeypatch.setattr(meta_ads, "update_ad_creative", _update_ad_creative)

    await _publish(plan=_plan(adsets=("Seed",)))
    assert rec.creatives == ["creative-0"]

    edited = _plan(adsets=("Seed",))
    edited["adsets"][0]["ads"][0]["creative"]["title_variants"] = ["Second headline"]
    CampaignSpec.model_validate(edited)
    await _publish(plan=edited)

    assert rec.creatives == ["creative-0", "creative-1"]
    assert repointed == [("ad-0", "creative-1")]
    assert rec.ads == ["ad-0"], "the ad was duplicated instead of re-pointed"


def test_ledger_without_a_draft_id_is_a_noop_not_an_error():
    """No user/conversation → in-memory ledger. Publish still works, it just
    cannot resume across processes."""
    ledger = PublishLedger()
    assert ledger.resuming is False
    assert ledger.to_dict()["campaign_id"] is None


# ── activation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activation_failure_is_surfaced_not_swallowed(monkeypatch):
    """Previously logged and ignored, so a campaign could be fully built,
    reported as published, and never actually run."""
    rec = _Recorder()
    rec.install(monkeypatch)

    async def _boom(*a, **k):
        raise meta_ads.MetaAdsError("account has no payment method")

    monkeypatch.setattr(meta_ads, "activate_campaign", _boom)
    monkeypatch.setattr(meta_ads, "upload_image", _ret("img-hash"))

    with pytest.raises(MetaPublishError) as exc:
        await _publish_then_activate()
    assert exc.value.step == "activation"
    assert "Nothing is spending" in exc.value.user_message


# ── retries ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_retries_throttling_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def _flaky(method, url, params, endpoint, json_data, files, data, timeout, headers=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise meta_ads.MetaAdsError("rate limited", code=17)
        return {"id": "ok"}

    monkeypatch.setattr(meta_ads, "_request_once", _flaky)
    monkeypatch.setattr(meta_ads.asyncio, "sleep", _ret(None))

    out = await meta_ads._request("POST", "act_1/campaigns", "tok")
    assert out == {"id": "ok"}
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_request_does_not_retry_validation_errors(monkeypatch):
    """Retrying a rejected payload cannot make it valid — it just burns quota
    and delays the real error."""
    calls = {"n": 0}

    async def _invalid(*a, **k):
        calls["n"] += 1
        raise meta_ads.MetaAdsError("Invalid parameter", code=100)

    monkeypatch.setattr(meta_ads, "_request_once", _invalid)
    monkeypatch.setattr(meta_ads.asyncio, "sleep", _ret(None))

    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads._request("POST", "act_1/campaigns", "tok")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_request_gives_up_after_max_attempts(monkeypatch):
    calls = {"n": 0}

    async def _always_throttled(*a, **k):
        calls["n"] += 1
        raise meta_ads.MetaAdsError("rate limited", code=4)

    monkeypatch.setattr(meta_ads, "_request_once", _always_throttled)
    monkeypatch.setattr(meta_ads.asyncio, "sleep", _ret(None))

    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads._request("POST", "act_1/campaigns", "tok", retries=3)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_validate_only_sets_execution_options(monkeypatch):
    captured: dict = {}

    async def _capture(method, url, params, endpoint, json_data, files, data, timeout, headers=None):
        captured.update(json_data or {})
        return {}

    monkeypatch.setattr(meta_ads, "_request_once", _capture)
    await meta_ads._request("POST", "act_1/campaigns", "tok",
                            json_data={"name": "C"}, validate_only=True)
    assert captured["execution_options"] == ["validate_only"]
    assert captured["name"] == "C"


# ── app promotion: one campaign per store ────────────────────────────────────
# Meta carries the promoted app on the CAMPAIGN, and an iOS 14.5+ install
# campaign is a dedicated SKAdNetwork type that cannot hold Android ad sets. We
# used to publish both platforms as ad sets inside ONE campaign — a shape Meta
# accepts and then silently denies SKAdNetwork attribution on.


def _app_plan() -> dict:
    def _adset(name, user_os, store_url):
        return {
            "name": name,
            "audience_role": "seed" if "Seed" in name else "broad",
            "optimization_goal": "APP_INSTALLS",
            "billing_event": "IMPRESSIONS",
            "destination_type": "APP",
            "daily_budget": 5000,
            "targeting": {"geo_locations": {"countries": ["US"]}, "user_os": [user_os]},
            "start_time": "2026-07-01T00:00:00+00:00",
            "promoted_object": {"application_id": "555", "object_store_url": store_url},
            "ads": [{
                "name": f"{name} Ad",
                "creative": {
                    "title": "t", "body": "b", "call_to_action": "INSTALL_MOBILE_APP",
                    "link": store_url, "media_id": "m1",
                },
            }],
        }

    ios_url = "https://apps.apple.com/app/id1"
    play_url = "https://play.google.com/store/apps/details?id=x"
    plan = {
        "name": "C",
        "objective": "OUTCOME_APP_PROMOTION",
        # Interleaved on purpose: the ledger keys by plan-wide ad set index, so
        # a split that re-enumerated per campaign would collide these.
        "adsets": [
            _adset("Seed iOS", "iOS", ios_url),
            _adset("Seed Android", "Android", play_url),
            _adset("Prospecting iOS", "iOS", ios_url),
            _adset("Prospecting Android", "Android", play_url),
        ],
    }
    CampaignSpec.model_validate(plan)
    return plan


@pytest.mark.asyncio
async def test_both_stores_publish_as_two_campaigns(monkeypatch):
    rec = _Recorder()
    rec.install(monkeypatch)

    result = await _publish(plan=_app_plan())

    assert rec.campaigns == ["camp-1", "camp-2"]
    assert result["campaign_ids"] == ["camp-1", "camp-2"]
    # The scalar key every downstream reader uses still resolves, to the first.
    assert result["campaign_id"] == "camp-1"
    assert len(result["adset_ids"]) == 4

    ios, android = rec.campaign_specs
    assert ios.is_skadnetwork_attribution is True
    assert android.is_skadnetwork_attribution is False
    assert {tuple(a.targeting["user_os"]) for a in ios.adsets} == {("iOS",)}
    assert {tuple(a.targeting["user_os"]) for a in android.adsets} == {("Android",)}


@pytest.mark.asyncio
async def test_split_publish_keys_the_ledger_by_plan_wide_adset_index(monkeypatch):
    """The ad sets are interleaved across the two campaigns, so plan-wide indices
    are the only keys that stay unique — and they are what a resume looks up."""
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    await _publish(plan=_app_plan())

    assert sorted(ledger.adsets, key=int) == ["0", "1", "2", "3"]
    assert ledger.campaigns == {"0": "camp-1", "1": "camp-2"}


@pytest.mark.asyncio
async def test_retry_of_a_split_publish_creates_no_duplicate_campaign(monkeypatch):
    """Campaign A succeeded, an ad set under B failed. The retry must resume both
    rather than create a third and fourth campaign."""
    ledger = PublishLedger()
    rec1 = _Recorder(fail_adset_at=3)
    rec1.install(monkeypatch, ledger=ledger)
    with pytest.raises(MetaPublishError):
        await _publish(plan=_app_plan())
    assert rec1.campaigns == ["camp-1", "camp-2"]

    rec2 = _Recorder()
    rec2.install(monkeypatch, ledger=ledger)
    result = await _publish(plan=_app_plan())

    assert rec2.campaigns == []                       # neither was recreated
    assert result["campaign_ids"] == ["camp-1", "camp-2"]
    assert len(result["adset_ids"]) == 4


@pytest.mark.asyncio
async def test_campaign_preflight_failure_rolls_back_every_campaign(monkeypatch):
    """The second campaign's ad set preflight fails. Both campaigns are empty and
    PAUSED, so both must be deleted — leaving one behind is an orphan the user
    pays nothing for but still sees in Ads Manager."""
    ledger = PublishLedger()
    rec = _Recorder(fail_validate_at=2)
    rec.install(monkeypatch, ledger=ledger)

    with pytest.raises(MetaPublishError):
        await _publish(plan=_app_plan())

    assert rec.deleted == ["camp-1", "camp-2"]
    assert ledger.campaigns == {}


def test_a_ledger_written_before_the_split_still_resumes():
    """Persisted publish_state from the single-campaign era has only
    "campaign_id". It must keep resuming, not start a duplicate campaign."""
    ledger = PublishLedger({"campaign_id": "camp-1", "media": {"0:0": "img-hash"}})

    assert ledger.resuming is True
    assert ledger.campaign_id == "camp-1"
    assert ledger.campaign_for(0) == "camp-1"
    assert ledger.campaign_ids == ["camp-1"]
    assert ledger.media_for("0:0") == "img-hash"
    # And it round-trips into the new shape without losing the old key.
    assert ledger.to_dict()["campaign_id"] == "camp-1"
    assert ledger.to_dict()["campaigns"] == {"0": "camp-1"}


@pytest.mark.asyncio
async def test_resumed_campaign_is_not_rolled_back_when_a_later_one_fails(monkeypatch):
    """Campaign A finished in an earlier attempt and already carries ad sets and
    ads. If campaign B fails preflight on the retry, deleting A would throw that
    finished work away — only campaigns created in THIS attempt may be removed."""
    ledger = PublishLedger()

    # Attempt 1: both campaigns created, A's ad sets land, B's first ad set fails.
    rec1 = _Recorder(fail_adset_at=2)
    rec1.install(monkeypatch, ledger=ledger)
    with pytest.raises(MetaPublishError):
        await _publish(plan=_app_plan())
    assert ledger.campaigns == {"0": "camp-1", "1": "camp-2"}

    # Attempt 2: A resumes from the ledger; B has to be re-created and its ad set
    # preflight fails this time.
    ledger.campaigns.pop("1")
    rec2 = _Recorder(fail_validate_at=0, campaign_prefix="retry")
    rec2.install(monkeypatch, ledger=ledger)
    with pytest.raises(MetaPublishError):
        await _publish(plan=_app_plan())

    # Only what attempt 2 created is deleted. The resumed campaign survives.
    assert rec2.deleted == ["retry-1"]
    assert ledger.campaign_for(0) == "camp-1"


# ── activation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activation_resumes_from_where_it_failed(monkeypatch):
    """A failure mid-activation must not re-activate what is already live.

    ``activate_adsets``/``activate_ads`` are serial loops with no transaction, so
    before the ledger recorded each id a retry re-POSTed every object and could
    not tell a half-activated campaign from an untouched one.
    """
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    activated: list[str] = []
    # Meta gives up on the second ad set, once.
    fail_once = {"adset-1"}

    async def _activate_campaign(cid, token):
        activated.append(cid)

    async def _activate_many(ids, token, on_activated=None):
        for i in ids:
            if i in fail_once:
                fail_once.discard(i)
                raise meta_ads.MetaAdsError("temporarily unavailable")
            activated.append(i)
            if on_activated is not None:
                await on_activated(i)

    monkeypatch.setattr(meta_ads, "activate_campaign", _activate_campaign)
    monkeypatch.setattr(meta_ads, "activate_adsets", _activate_many)
    monkeypatch.setattr(meta_ads, "activate_ads", _activate_many)

    with pytest.raises(MetaPublishError):
        await _publish_then_activate()

    # The campaign and the first ad set are live and recorded; the rest is not.
    assert "camp-1" in ledger.activated_ids
    assert "adset-0" in ledger.activated_ids
    assert "adset-1" not in ledger.activated_ids
    assert not ledger.activated

    # Retry: nothing already ACTIVE is touched again.
    activated.clear()
    rec2 = _Recorder(campaign_prefix="camp")
    rec2.install(monkeypatch, ledger=ledger)
    monkeypatch.setattr(meta_ads, "activate_campaign", _activate_campaign)
    monkeypatch.setattr(meta_ads, "activate_adsets", _activate_many)
    monkeypatch.setattr(meta_ads, "activate_ads", _activate_many)
    await _publish_then_activate()

    assert "camp-1" not in activated       # already live, skipped
    assert "adset-0" not in activated      # already live, skipped
    assert "adset-1" in activated          # resumed here
    assert ledger.activated


@pytest.mark.asyncio
async def test_activation_switch_off_leaves_everything_paused(monkeypatch):
    """META_PUBLISH_ACTIVATE=false publishes end-to-end without going live.

    Every object Punk creates is PAUSED by default, so this flag is the only
    thing standing between a published campaign and real spend — which is what
    makes an end-to-end test against a real ad account safe.
    """
    from app.core.config import settings

    rec = _Recorder()
    rec.install(monkeypatch)

    async def _boom(*a, **k):
        raise AssertionError("activation must not run when the switch is off")

    monkeypatch.setattr(meta_ads, "activate_campaign", _boom)
    monkeypatch.setattr(meta_ads, "activate_adsets", _boom)
    monkeypatch.setattr(meta_ads, "activate_ads", _boom)
    monkeypatch.setattr(settings, "META_PUBLISH_ACTIVATE", False)

    result = await _publish_then_activate()

    assert result["ad_ids"]            # ads were created
    assert result["activated"] is False   # but nothing is live


@pytest.mark.asyncio
async def test_publish_leaves_everything_paused(monkeypatch):
    """Publishing never activates any more — the go_live_confirm gate does.

    Between the two sits an interrupt where the user reviews Meta's own previews,
    so a publish that went live on its own would spend money on something nobody
    had seen yet.
    """
    rec = _Recorder()
    rec.install(monkeypatch)

    async def _boom(*a, **k):
        raise AssertionError("publish must not activate")

    monkeypatch.setattr(meta_ads, "activate_campaign", _boom)
    monkeypatch.setattr(meta_ads, "activate_adsets", _boom)
    monkeypatch.setattr(meta_ads, "activate_ads", _boom)

    result = await _publish()
    assert result["ad_ids"]
    assert result["activated"] is False


@pytest.mark.asyncio
async def test_activation_reports_activation_state(monkeypatch):
    """``activated`` reflects reality — callers must not infer it from ad_ids."""
    rec = _Recorder()
    rec.install(monkeypatch)
    result = await _publish_then_activate()
    assert result["ad_ids"]
    assert result["activated"] is True


# ── what the draft row records ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_state_advances_status_and_records_every_campaign():
    """``campaigns.status`` used to stop at ``approved`` forever, so a campaign
    living in Meta was indistinguishable from one never sent — and an
    App-promotion split dropped its second campaign id entirely."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from app.modules.campaigns.repository import CampaignsRepository
    from app.shared.enums import CampaignStatus

    db = AsyncMock()
    await CampaignsRepository().save_publish_state(
        db, _uuid.uuid4(),
        {
            "campaign_id": "camp-1",
            "campaigns": {"0": "camp-1", "1": "camp-2"},
            # Deliberately out of insertion order: ids must come back by index.
            "adsets": {"1": "adset-1", "0": "adset-0"},
        },
    )

    values = db.execute.await_args.args[0].compile().params
    assert values["status"] is CampaignStatus.published
    assert values["ext_campaign_id"] == "camp-1"
    assert values["ext_ad_group_ids"] == ["adset-0", "adset-1"]
    assert values["publish_state"]["campaigns"] == {"0": "camp-1", "1": "camp-2"}


@pytest.mark.asyncio
async def test_publish_state_before_any_campaign_leaves_status_alone():
    """The ledger persists from the very first write, which happens before the
    campaign exists. Nothing is in Meta yet, so nothing is 'published'."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from app.modules.campaigns.repository import CampaignsRepository

    db = AsyncMock()
    await CampaignsRepository().save_publish_state(
        db, _uuid.uuid4(), {"custom_audience_id": "aud-1"},
    )
    values = db.execute.await_args.args[0].compile().params
    assert "status" not in values
    assert "ext_campaign_id" not in values


# ── a plan Meta refuses AFTER the campaign exists ──────────────────────────────


def _meta_error(**kw):
    return meta_ads.MetaAdsError("Invalid parameter", 100, **kw)


@pytest.mark.asyncio
async def test_a_creative_meta_blames_a_field_for_tears_the_campaign_down(monkeypatch):
    """Past preflight the ledger holds real ids, so an edit in the plan editor was
    ignored on retry — a link Meta refuses at ad-creation time left the user
    pressing Publish against the same failure until the 3-strike cap, with no way
    back to the field. blame_field_specs says the PLAN is at fault, so the paused
    campaign comes back out and the editor reopens on the link."""
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    async def _reject(**k):
        raise _meta_error(
            user_msg="The link field is required.", blame_field=["link"],
        )

    monkeypatch.setattr(meta_ads, "create_ad_creative", _reject)

    with pytest.raises(MetaPublishError) as excinfo:
        await _publish()

    exc = excinfo.value
    assert exc.step == "ad_creative_rejected"
    assert exc.step in media_exec.PLAN_FIXABLE_PUBLISH_STEPS
    assert exc.plan_errors == {
        "adsets[0].ads[0].creative.link": "The link field is required."
    }
    # The campaign it had already built is gone, and the ledger no longer claims
    # it — otherwise the retry would hand Meta ids that no longer exist.
    assert rec.deleted == ["camp-1"]
    assert ledger.campaigns == {}
    assert ledger.adsets == {}
    assert ledger.ads == {}


@pytest.mark.asyncio
async def test_media_survives_the_teardown(monkeypatch):
    """Uploaded media lives on the ad account, not inside the campaign. Dropping
    it would make the user wait through a re-upload for nothing."""
    ledger = PublishLedger({"media": {"0:0": "img-hash"}, "custom_audience_id": "aud-1"})
    _Recorder().install(monkeypatch, ledger=ledger)

    async def _reject(**k):
        raise _meta_error(user_msg="Nope.", blame_field=["link"])

    monkeypatch.setattr(meta_ads, "create_ad_creative", _reject)

    with pytest.raises(MetaPublishError):
        await _publish()

    assert ledger.media == {"0:0": "img-hash"}
    assert ledger.custom_audience_id == "aud-1"


@pytest.mark.asyncio
async def test_a_failure_meta_blames_no_field_for_leaves_the_campaign_standing(
    monkeypatch,
):
    """A permission problem or an outage is not the plan's fault. Deleting a
    campaign over one would throw away work the retry could have resumed."""
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    async def _reject(**k):
        raise _meta_error(user_msg="Temporarily unavailable.")

    monkeypatch.setattr(meta_ads, "create_ad_creative", _reject)

    with pytest.raises(MetaPublishError) as excinfo:
        await _publish()

    exc = excinfo.value
    assert exc.step == "ad_creative"
    assert exc.step not in media_exec.PLAN_FIXABLE_PUBLISH_STEPS
    assert exc.plan_errors == {}
    assert rec.deleted == []
    assert ledger.campaigns == {"0": "camp-1"}


@pytest.mark.asyncio
async def test_a_rejection_meta_only_explains_in_prose_still_marks_the_field(
    monkeypatch,
):
    """Some rejections name the offending field only in ``error_user_msg`` and
    send no ``blame_field_specs`` — subcode 1815316 is one, and it is reachable on
    any Leads plan for a business with no website (the spec builder falls back to
    the Facebook Page URL). Without the subcode map the whole thing landed on the
    banner, the publish gate was re-asked, and the user could only republish the
    identical spec."""
    ledger = PublishLedger()
    rec = _Recorder()
    rec.install(monkeypatch, ledger=ledger)

    msg = (
        "Lead Generation Ads should always link to external content, but this ad "
        "does not."
    )

    async def _reject(**k):
        raise _meta_error(subcode=1815316, user_msg=msg)

    monkeypatch.setattr(meta_ads, "create_ad", _reject)

    with pytest.raises(MetaPublishError) as excinfo:
        await _publish()

    exc = excinfo.value
    assert exc.step == "ad_rejected"
    assert exc.step in media_exec.PLAN_FIXABLE_PUBLISH_STEPS
    assert exc.plan_errors == {"adsets[0].ads[0].creative.link": msg}
    assert rec.deleted == ["camp-1"]
    assert ledger.campaigns == {}


@pytest.mark.asyncio
async def test_the_second_ads_rejection_marks_the_second_ad(monkeypatch):
    """``_find_form_path`` walks the ad set breadth-first, so "link" resolved to
    ``ads[0]`` whichever ad Meta actually refused — the user was sent to fix a
    field that was never wrong."""
    plan = _plan(adsets=("Solo",))
    plan["adsets"][0]["ads"].append({
        "name": "Solo Ad 2",
        "creative": {
            "title": "t2", "body": "b2", "call_to_action": "LEARN_MORE",
            "link": "https://y.example", "media_id": "m1",
        },
    })
    rec = _Recorder()
    rec.install(monkeypatch, ledger=PublishLedger())

    async def _reject_second(**k):
        if len(rec.ads) == 1:
            raise _meta_error(subcode=1815316, user_msg="Bad link.")
        rec.ads.append(f"ad-{len(rec.ads)}")
        return rec.ads[-1]

    monkeypatch.setattr(meta_ads, "create_ad", _reject_second)

    with pytest.raises(MetaPublishError) as excinfo:
        await _publish(plan=plan)

    assert excinfo.value.plan_errors == {"adsets[0].ads[1].creative.link": "Bad link."}


@pytest.mark.asyncio
async def test_an_edited_plan_rebuilds_instead_of_resuming(monkeypatch):
    """Every publish failure now reopens the plan editor, so the ledger has to
    stop resuming once the plan actually changes: ``ledger.adset_for`` would hand
    Meta the ad set built from the OLD plan and the user's edit would silently
    never run."""
    ledger = PublishLedger({
        "campaigns": {"0": "camp-old"}, "adsets": {"0": "adset-old"},
    })
    rec = _Recorder(campaign_prefix="new")
    rec.install(monkeypatch, ledger=ledger)

    await _publish(plan_dirty=True)

    assert rec.deleted == ["camp-old"]
    assert rec.campaigns == ["new-1"]          # rebuilt, not resumed
    assert "adset-old" not in rec.adsets


@pytest.mark.asyncio
async def test_an_unchanged_plan_still_resumes(monkeypatch):
    """The other half of the same rule — republishing without touching the plan
    must not throw away the campaign the last attempt got as far as building."""
    ledger = PublishLedger({
        "campaigns": {"0": "camp-old"}, "adsets": {"0": "adset-old"},
    })
    rec = _Recorder(campaign_prefix="new")
    rec.install(monkeypatch, ledger=ledger)

    await _publish()

    assert rec.deleted == []
    assert rec.campaigns == []                 # resumed camp-old, created nothing
