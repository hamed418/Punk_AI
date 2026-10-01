"""
How ``scripts/probe_meta_matrix.py`` classifies a Meta rejection.

This is the only part of the probe worth testing, and it is the part that has
been wrong three separate times. The script writes ``tests/data/meta_matrix_probe.json``,
which ``test_meta_spec_matrix.py`` then holds OBJECTIVE_MATRIX to — so a
misclassified error does not fail loudly, it deletes a working feature from the
product's dropdowns and the test suite agrees with it.

Three buckets, and every one of them was learned the hard way:

  * **throttled** — the ad-account limit (subcode 2446079). Recorded as a "no"
    once, and 187 of 484 answers came back that way, including Meta's own
    default bid strategy on Post Engagement.
  * **account-gated** — a real rule about *this* ad account, not the
    combination. A brand-new account cannot use any non-impression billing
    (subcode 2446404), and the probe has no pixel or app to satisfy an
    offsite-conversions or app-promotion prerequisite. Counted as accepted.
  * **rejected** — everything else, including code 1 with a user_msg, which is
    where Meta puts permanent semantic verdicts. Treating code 1 as retryable
    abandoned a whole objective (OUTCOME_TRAFFIC) with nothing written.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
import importlib.util
import sys
from pathlib import Path

import pytest

from app.services import meta_ads as _meta

_SPEC = importlib.util.spec_from_file_location(
    "probe_meta_matrix",
    Path(__file__).resolve().parents[1] / "scripts" / "probe_meta_matrix.py",
)
probe_mod = importlib.util.module_from_spec(_SPEC)
sys.modules["probe_meta_matrix"] = probe_mod
_SPEC.loader.exec_module(probe_mod)


def _prober(monkeypatch, exc: Exception | None):
    """A Prober whose one Graph call raises ``exc`` (or succeeds when None)."""

    async def fake_request(*_args, **_kwargs):
        if exc is not None:
            raise exc
        return {"id": "1"}

    monkeypatch.setattr(_meta, "_request", fake_request)
    cfg = probe_mod.ProbeConfig()
    cfg.token = "t"
    cfg.ad_account = "act_1"
    return probe_mod.Prober(cfg, {}, refresh=False)


def _probe(monkeypatch, exc):
    p = _prober(monkeypatch, exc)
    return asyncio.run(p.probe("k", {}))


def test_ad_account_throttle_is_unmeasured_not_a_rejection(monkeypatch):
    exc = _meta.MetaAdsError("too many calls to this ad-account", code=4, subcode=2446079)
    with pytest.raises(probe_mod.ProbeThrottled):
        _probe(monkeypatch, exc)


def test_throttle_is_never_cached(monkeypatch):
    """The whole point: a cached throttle is indistinguishable from a "no"."""
    p = _prober(monkeypatch, _meta.MetaAdsError("x", code=4, subcode=2446079))
    with pytest.raises(probe_mod.ProbeThrottled):
        asyncio.run(p.probe("k", {}))
    assert p.cache == {}


def test_code_1_with_a_user_msg_is_a_real_rejection(monkeypatch):
    """Meta returns code 1 ("An unknown error occurred") for permanent semantic
    verdicts too. `MetaAdsError.retryable` includes code 1, so classifying on it
    abandoned OUTCOME_TRAFFIC on a vehicle-listings placement complaint."""
    exc = _meta.MetaAdsError(
        "An unknown error occurred",
        code=1,
        subcode=2124017,
        user_msg="To use on-Facebook vehicle listings as a destination, please "
                 "select the Facebook Marketplace placement.",
    )
    assert exc.retryable  # the trap
    assert _probe(monkeypatch, exc) == {
        "ok": False, "error": "An unknown error occurred", "code": 1,
    }


@pytest.mark.parametrize("subcode", sorted(probe_mod._GATED_SUBCODES))
def test_account_gated_rejections_count_as_accepted(monkeypatch, subcode):
    """A new ad account cannot use CPC billing and the probe has no pixel. Neither
    says the combination is illegal, and pruning the matrix on that evidence
    would remove shipped features for every mature US/CA account."""
    exc = _meta.MetaAdsError("Invalid parameter", code=100, subcode=subcode,
                             user_msg="account is too new")
    result = _probe(monkeypatch, exc)
    assert result["ok"] is True
    assert result["subcode"] == subcode
    assert result["gated"] == "account is too new"


def test_reclassify_gated_repairs_an_old_cache_without_re_probing():
    """~650 answers were already paid for before the gated bucket existed. The
    repair runs at cache load so a replay folds them into the sections for free —
    the alternative is another hour of ad-account rate limit."""
    cache = {
        "a": {"ok": False, "error": "OAuthException: x | subcode=2446404 | ...", "code": 100},
        "b": {"ok": False, "error": "OAuthException: y | subcode=1815117 | ...", "code": 100},
        "c": {"ok": True},
    }
    assert probe_mod._reclassify_gated(cache) == 1
    assert cache["a"] == {
        "ok": True, "gated": "OAuthException: x | subcode=2446404 | ...", "subcode": 2446404,
    }
    assert cache["b"]["ok"] is False       # a real rule stays a real rule
    assert cache["c"] == {"ok": True}
    # Idempotent: a second load must not touch anything.
    assert probe_mod._reclassify_gated(cache) == 0


def test_a_gated_variant_does_not_win_the_promoted_object_walk(monkeypatch):
    """The bug the gated bucket introduced. 1815430 ("Please select a promoted
    object") and 1815143 (offsite conversions needs a pixel_id) are the answer
    this walk is looking for — counting them as accepted made the ``none``
    variant win for every goal, so the probe recorded
    ``OFFSITE_CONVERSIONS -> "none"``, the opposite of the truth."""
    cfg = probe_mod.ProbeConfig()
    cfg.token, cfg.ad_account = "t", "act_1"
    cfg.page_id = "p1"  # unlocks the "page" variant; no pixel is configured

    async def fake_request(_method, _path, _token, **kwargs):
        promoted = (kwargs.get("json_data") or {}).get("promoted_object")
        if not promoted:
            raise _meta.MetaAdsError("Invalid parameter", code=100, subcode=1815430,
                                     user_msg="Please select a promoted object")
        return {"id": "1"}

    monkeypatch.setattr(_meta, "_request", fake_request)
    prober = probe_mod.Prober(cfg, {}, refresh=False)
    res = asyncio.run(prober.probe_with_promoted(
        "k", campaign_id="c1", goal="OFFSITE_CONVERSIONS"
    ))
    assert res["ok"] is True
    assert res["promoted_object_kind"] == "page", (
        "a real acceptance must beat the gated 'none' variant"
    )


def test_all_variants_gated_keeps_the_goal_but_reports_no_kind(monkeypatch):
    """With no pixel and no page configured, every shape is gated. The goal is
    still legal — the account just cannot express it — so it stays accepted, and
    the kind is unknown rather than a fabricated "none"."""
    exc = _meta.MetaAdsError("Invalid parameter", code=100, subcode=1815143,
                             user_msg="needs a pixel_id")
    prober = _prober(monkeypatch, exc)
    res = asyncio.run(prober.probe_with_promoted(
        "k", campaign_id="c1", goal="OFFSITE_CONVERSIONS"
    ))
    assert res["ok"] is True
    assert res["promoted_object_kind"] is None


def test_all_gated_is_recorded_as_unmeasured_not_as_everything_accepted():
    """An objective whose every goal was account-gated measured nothing, and must
    be absent from the file rather than present claiming all 31 goals work.

    OUTCOME_APP_PROMOTION on an account with no app answered 1885011 ("you must
    provide an object_store_url") to every goal. Counting those as accepted —
    correct for "is this legal" — wrote ``goals_by_objective: [all 31]``, an
    assertion no reader could tell from a measurement."""
    calls: list[tuple] = []

    class _P:
        cfg = SimpleNamespace(token="t", ad_account="act_1")
        committed = 0

        async def probe_with_promoted(self, key, **_kw):
            return {"ok": True, "gated": "needs an app", "promoted_object_kind": None}

    out = {k: {} for k in (
        "goals_by_objective", "promoted_object_kind_by_goal",
        "destinations_by_objective", "goals_by_objective_destination",
        "billing_by_goal", "bid_strategies_by_goal", "platforms_by_destination",
    )}
    out["rejections"] = []

    async def fake_campaign(_cfg, objective):
        calls.append(objective)
        return "c1"

    import app.services.meta_ads as _m
    orig_create, orig_delete = probe_mod._create_probe_campaign, _m.delete_campaign
    probe_mod._create_probe_campaign = fake_campaign

    async def noop_delete(*_a, **_k):
        return None

    _m.delete_campaign = noop_delete
    try:
        asyncio.run(probe_mod.probe_objective(_P(), "OUTCOME_APP_PROMOTION", out))
    finally:
        probe_mod._create_probe_campaign = orig_create
        _m.delete_campaign = orig_delete

    assert out["goals_by_objective"] == {}, "an unmeasured objective must not be written"
    assert out["promoted_object_kind_by_goal"] == {}


def test_an_ordinary_rejection_stays_a_rejection(monkeypatch):
    exc = _meta.MetaAdsError(
        "Invalid parameter", code=100, subcode=1815117,
        user_msg="The specified billing event is not a valid option",
    )
    assert _probe(monkeypatch, exc)["ok"] is False
