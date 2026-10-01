"""
scripts/probe_meta_matrix.py
────────────────────────────
Measure which Meta ad set combinations are real, instead of guessing from docs.

``objective_matrix.py`` encodes Meta's rules by hand. Meta publishes no
combination table, and its documentation contradicts the v25 SDK in at least
three places (2-second video views, ``PHONE_CALL`` destination, the ``type``
field on frequency control specs). The only authority is Meta itself, which the
app already knows how to ask: ``execution_options: ["validate_only"]``.

This script walks the combination space, asks Meta about each one, and writes the
answers to ``tests/data/meta_matrix_probe.json``.
``tests/test_meta_spec_matrix.py`` then asserts our matrix against that file, so
a rule we invented — or one Meta changed — becomes a failing test.

**Payloads are built as raw dicts, deliberately.** Routing them through
``AdSetSpec`` would apply our own validators, which reject exactly the
combinations this script exists to test. The dict shape mirrors
``AdSetSpec.to_payload`` so what we probe is what we would send.

Probing is staged rather than a cross product: the full space is
6 × 23 × 32 × 11 × 4 ≈ 194k calls. Each stage narrows the next, which brings a
full run to roughly 1,300 calls.

  1. goals per objective          (no destination — what does the objective allow)
  2. destinations per objective   (using a goal stage 1 proved)
  3. goal × destination           (accepted goals against accepted destinations)
  4. billing event per goal       (the pairwise rule our model is missing)
  5. bid strategy per goal        (ditto)
  6. publisher platform per destination  (keyed by destination, not objective)
  7. existing-post ads + conversion_domain, per destination  (--existing-post)

Stage 1 also walks promoted_object shapes until one is accepted, which yields the
goal → promoted_object mapping for free.

Each stage is written to the results as it finishes, and stages 3-6 write after
each destination/goal within them. On a rate-limited account a run rarely gets to
the end, and re-paying for a sweep that already completed only feeds the limit
that stopped it.

This is a **build-time** tool, not a runtime one: it measures Meta's rules once
so the matrix compiled into the app is right. It never runs in production and
never touches a user's session. Runtime keeps using each user's own connected
account, and ``media.py`` re-checks every payload against *their* account with
``validate_only`` before publishing — so an account-specific rule the probe never
saw still surfaces as a preflight error rather than a broken campaign.

Point it at a connected account, read from ``oauth_tokens`` — the same
credentials the product publishes with, so no tokens in ``.env``::

    .venv/Scripts/python.exe scripts/probe_meta_matrix.py --user-id <uuid>

On a machine with no database (CI), supply them directly instead::

    PROBE_META_TOKEN=EAA...          # user token with ads_management
    PROBE_META_AD_ACCOUNT=act_123    # or bare 123
    PROBE_META_PAGE_ID=123           # optional, unlocks page-promoted goals
    PROBE_META_PIXEL_ID=123          # optional, unlocks conversion goals
    PROBE_META_APP_ID=123            # optional, unlocks app goals

Run from ``backend/``::

    ... --user-id <uuid>                        # fill gaps
    ... --user-id <uuid> --refresh              # re-probe everything
    ... --user-id <uuid> --objective OUTCOME_SALES

Pick an ordinary account, not one on a Meta beta or whitelist: the matrix it
produces ships to every user.

Nothing is created except one PAUSED campaign per objective, needed because
``/adsets`` validation requires a real parent campaign id. Every campaign is
deleted in a ``finally`` block, and they never carry a budget or leave PAUSED, so
they cannot spend.

``--existing-post`` (stage 7) is the one exception, and it is opt-in for exactly
that reason: validating an AD needs a real ad set, so it creates one per
conversion location plus a single ad creative pointing at a real Page post. They
are PAUSED under the same budget-less campaign and go away with it, so they still
cannot spend — but they are writes, and the default run makes none.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import facebook_business  # noqa: E402
from facebook_business.adobjects.adset import AdSet  # noqa: E402
from facebook_business.adobjects.campaign import Campaign  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import meta_ads as _meta  # noqa: E402

OUT_PATH = Path(__file__).resolve().parents[1] / "tests" / "data" / "meta_matrix_probe.json"
# The resume cache lives beside the answers, not inside them. It was two thirds
# of a 422 KB fixture, so every re-probe rewrote 270 KB of scratch and buried the
# handful of lines where Meta had actually changed its mind — and the diff is the
# whole review surface when reconciling OBJECTIVE_MATRIX. Gitignored.
CACHE_PATH = OUT_PATH.with_suffix(".cache.json")

# How many probes run at once. Meta throttles the ads API per app and per user
# (codes 4/17/80004); _request already backs off on those, but staying low means
# a full run rarely trips them at all.
CONCURRENCY = 2

# ── Vocabulary ───────────────────────────────────────────────────────────────
# The FULL SDK enums, not our curated subset in meta_spec.enums — the point is to
# discover values we do not currently offer.


def _sdk_values(enum_cls: type) -> tuple[str, ...]:
    return tuple(
        v for k, v in vars(enum_cls).items()
        if not k.startswith("_") and isinstance(v, str)
    )


# ODAX outcome objectives only. The pre-2022 vocabulary is still in the SDK but
# Meta rejects it for new campaigns, so probing it would only measure that.
OBJECTIVES: tuple[str, ...] = tuple(
    v for v in _sdk_values(Campaign.Objective) if v.startswith("OUTCOME_")
)
GOALS: tuple[str, ...] = tuple(g for g in _sdk_values(AdSet.OptimizationGoal) if g != "NONE")
BILLING_EVENTS: tuple[str, ...] = tuple(b for b in _sdk_values(AdSet.BillingEvent) if b != "NONE")
DESTINATIONS: tuple[str, ...] = _sdk_values(AdSet.DestinationType)
BID_STRATEGIES: tuple[str, ...] = _sdk_values(Campaign.BidStrategy)

# Documented but absent from the v25 SDK enum. Probed as raw strings so the run
# answers whether they are real — the reason this script exists.
EXTRA_DESTINATIONS: tuple[str, ...] = ("PHONE_CALL",)

# Placements, probed one platform at a time per conversion location. Nothing in
# meta_spec rejects `audience_network` on a WhatsApp destination today — only
# Meta does, and only sometimes. Keyed by destination alone (not objective) so
# the cache answers each pair once: Meta's placement rules follow the
# destination, and 24 destinations x 4 platforms is a one-time cost.
PUBLISHER_PLATFORMS: tuple[str, ...] = (
    "facebook", "instagram", "audience_network", "messenger", "threads",
)

_CAPPED = {"LOWEST_COST_WITH_BID_CAP", "COST_CAP"}
_ROAS = "LOWEST_COST_WITH_MIN_ROAS"
_BASELINE_BID = "LOWEST_COST_WITHOUT_CAP"
_BASELINE_BILLING = "IMPRESSIONS"

# Every probe needs a legal skeleton around the field under test, so a rejection
# is about that field and nothing else.
_BASELINE_TARGETING: dict[str, Any] = {"geo_locations": {"countries": ["US"]}}
# Minor units of the AD ACCOUNT'S currency, not cents of USD — Meta bills in the
# account currency and its minimum daily budget is per-currency (subcode 1885272,
# e.g. "must be more than BDT120.00"). A budget under that floor is rejected for
# the budget, which would make every stage here measure the wrong thing. This is
# set far above any currency's minimum; nothing spends under validate_only.
_BASELINE_DAILY_BUDGET = 500_00

# How many accepted goals stage 2 will try before calling a destination dead.
# Bounded because it multiplies the most expensive stage on a rate-limited
# account; 4 covers every case measured so far.
_DEST_GOAL_ATTEMPTS = 4


# ── Config ───────────────────────────────────────────────────────────────────


class ProbeConfig:
    """Which account to probe against.

    Two sources, in order of preference:

    1. ``--user-id`` — a user who has already connected Meta through the product.
       The token, ad account and Page all come from their ``oauth_tokens`` row,
       which is the same place every runtime Graph call reads from. No token
       copying, and no credentials living in ``.env``.
    2. ``PROBE_META_*`` environment variables — for CI or any machine with no
       database.
    """

    def __init__(self) -> None:
        self.token = os.getenv("PROBE_META_TOKEN", "").strip()
        self.ad_account = os.getenv("PROBE_META_AD_ACCOUNT", "").strip()
        self.page_id = os.getenv("PROBE_META_PAGE_ID", "").strip()
        self.pixel_id = os.getenv("PROBE_META_PIXEL_ID", "").strip()
        self.app_id = os.getenv("PROBE_META_APP_ID", "").strip()
        self.source = "env"

    async def load_from_connected_user(self, user_id: str) -> None:
        """Fill from a connected user's stored Meta credentials.

        Reads the same ``oauth_tokens`` row the app uses, so probing runs against
        a real connected account exactly as a publish would.
        """
        from sqlalchemy import select

        from app.db.database import AsyncSessionLocal
        from app.modules.ads.models import OAuthToken
        from app.shared.enums import AdPlatform

        # SQLAlchemy resolves relationship() targets by name at first use, and
        # importing one model does not register the rest. The app gets them
        # transitively through app.api.router; importing that here would drag in
        # the whole request layer, so pull in just the modules the mappers
        # reference.
        import app.modules.user.models  # noqa: F401
        import app.modules.campaigns.models  # noqa: F401
        import app.modules.media.models  # noqa: F401

        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(OAuthToken).where(
                        OAuthToken.user_id == user_id,
                        OAuthToken.platform == AdPlatform.meta,
                    )
                )
            ).scalars().first()

        if row is None or not row.access_token:
            raise SystemExit(
                f"user {user_id} has no connected Meta account. Connect one in the "
                "app first, or use the PROBE_META_* environment variables."
            )

        self.token = row.access_token
        self.ad_account = (row.ad_account_id or "").strip()
        self.page_id = (row.page_id or "").strip()
        self.source = f"user {user_id}"

        if not self.ad_account:
            raise SystemExit(
                f"user {user_id} has connected Meta but not selected an ad account."
            )

        # The pixel is not on the token row; ask the account for one. A probe
        # without it simply records conversion goals as needing something we
        # could not supply, which is a worse map of the rules.
        if not self.pixel_id:
            from app.services.meta_ads import fetch_ad_pixels

            pixels = await fetch_ad_pixels(self.ad_account, self.token)
            if pixels:
                self.pixel_id = str(pixels[0]["id"])

    @property
    def usable(self) -> bool:
        return bool(self.token and self.ad_account)

    def promoted_variants(self) -> list[tuple[str, dict[str, Any] | None]]:
        """promoted_object shapes to try, in order, until Meta accepts one.

        Ordering matters: ``none`` first so a goal that needs no promoted object
        is recorded as such rather than as "page works too".
        """
        variants: list[tuple[str, dict[str, Any] | None]] = [("none", None)]
        if self.page_id:
            variants.append(("page", {"page_id": self.page_id}))
        if self.pixel_id:
            variants.append((
                "pixel",
                {"pixel_id": self.pixel_id, "custom_event_type": "PURCHASE"},
            ))
        if self.app_id:
            variants.append((
                "application",
                {
                    "application_id": self.app_id,
                    "object_store_url": "https://apps.apple.com/app/id123456789",
                },
            ))
        return variants


# ── Payload building ─────────────────────────────────────────────────────────


def _start_time() -> str:
    """Tomorrow. A start time in the past is its own rejection reason."""
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def _adset_payload(
    *,
    campaign_id: str,
    goal: str,
    billing: str = _BASELINE_BILLING,
    bid_strategy: str = _BASELINE_BID,
    destination: str | None = None,
    promoted: dict[str, Any] | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """One ad set body, shaped like ``AdSetSpec.to_payload``."""
    targeting = dict(_BASELINE_TARGETING)
    if platform:
        targeting["publisher_platforms"] = [platform]
    payload: dict[str, Any] = {
        "name": f"probe {goal}",
        "campaign_id": campaign_id,
        "optimization_goal": goal,
        "billing_event": billing,
        "bid_strategy": bid_strategy,
        "daily_budget": _BASELINE_DAILY_BUDGET,
        "targeting": targeting,
        "start_time": _start_time(),
        "status": "PAUSED",
    }
    # A capped strategy without its amount is rejected for the amount, not for the
    # strategy — which would make the bid-strategy stage measure the wrong thing.
    if bid_strategy in _CAPPED:
        payload["bid_amount"] = 200
    elif bid_strategy == _ROAS:
        payload["bid_constraints"] = {"roas_average_floor": 10000}  # 1.0x, scaled 10000x
    if destination:
        payload["destination_type"] = destination
    if promoted:
        payload["promoted_object"] = promoted
    return payload


# ── Probing ──────────────────────────────────────────────────────────────────


class ProbeThrottled(Exception):
    """Meta was too busy to answer — the combination is UNMEASURED, not illegal.

    The distinction is the whole correctness of this script. A throttle
    (subcode 2446079, "There have been too many calls to this ad-account") used
    to be cached as ``{"ok": False}``, indistinguishable from a real rejection —
    so a throttled run produced a map saying Meta forbids combinations it
    actually allows, and reconciling the matrix against it would have deleted
    working features from the product. One measured run recorded 187 of 484
    answers this way, including ``LOWEST_COST_WITHOUT_CAP`` (Meta's own default
    bid strategy) on Post Engagement.

    Raised instead, so the objective is abandoned with nothing written and the
    next run re-probes it.
    """


# Rejections that describe *this ad account*, not the combination. Recording
# them as a "no" would prune shipped features from OBJECTIVE_MATRIX on the
# evidence of one immature test account:
#
#   2446404  "Ad accounts owned by businesses new to Facebook Products can
#            choose this option to pay for ads after several weeks of following
#            our policies." — every non-impression billing event on a new
#            account. Measured on act_997894704000491: it rejected
#            LINK_CLICKS billing with the LINK_CLICKS goal and THRUPLAY billing
#            with the THRUPLAY goal, both of which Meta documents and mature
#            accounts accept.
#   1815430  "Please select a promoted object for your ad set."
#   1815143  offsite conversions needs a pixel_id (or app + event type)
#   1885011  app promotion needs object_store_url
#
# The last three are prerequisites the probe cannot supply without
# PROBE_META_PIXEL_ID / an app, so they say nothing about legality either.
#
# Counted as accepted, and listed under ``account_gated`` in the output so a
# human can see which answers were assumed rather than measured. Meta's own
# validate_only preflight still catches these at publish time, with the exact
# user_msg above.
_GATED_SUBCODES: frozenset[int] = frozenset({2446404, 1815430, 1815143, 1885011})


class Prober:
    """Runs validate_only probes and remembers the answers.

    ``cache`` is keyed by a stable string so an interrupted run resumes instead of
    re-paying for calls it already made. Only real verdicts are cached — see
    ``ProbeThrottled``.
    """

    def __init__(self, cfg: ProbeConfig, cache: dict[str, Any], *, refresh: bool) -> None:
        self.cfg = cfg
        self.cache = cache
        self.refresh = refresh
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.calls = 0
        # Stages that finished and were written into the results. The file is
        # only rewritten when this is non-zero — see main().
        self.committed = 0
        # Set by main() only for a --existing-post run: the shared creative that
        # promotes a real Page post. None means stage 7 is off (or the Page had
        # nothing to promote), and stage 7 is skipped rather than recording "no".
        self.boost_creative_id: str | None = None

    async def probe(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.refresh and key in self.cache:
            return self.cache[key]

        async with self.sem:
            self.calls += 1
            try:
                await _meta._request(
                    "POST",
                    f"{_meta._act(self.cfg.ad_account)}/adsets",
                    self.cfg.token,
                    json_data=payload,
                    validate_only=True,
                    # A rejected payload cannot become valid on retry, and the
                    # throttle codes are handled inside _request already.
                    retries=2,
                )
                result: dict[str, Any] = {"ok": True}
            except _meta.MetaAdsError as exc:
                # _request already exhausted its retries on the throttle codes,
                # so reaching here with one means the account is genuinely
                # rate-limited — an absence of data, never a "no".
                #
                # Deliberately NOT `exc.retryable`: that set includes code 1
                # ("An unknown error occurred"), which Meta also returns for
                # permanent semantic rejections carrying a user_msg — e.g.
                # "To use on-Facebook vehicle listings as a destination, please
                # select the Facebook Marketplace placement." Treating that as a
                # throttle abandoned a whole objective (OUTCOME_TRAFFIC) with
                # nothing written.
                if exc.subcode == 2446079 or exc.code in _meta._THROTTLE_CODES:
                    raise ProbeThrottled(str(exc)) from exc
                if "too many calls" in str(exc).lower():
                    raise ProbeThrottled(str(exc)) from exc
                if exc.subcode in _GATED_SUBCODES:
                    result = {
                        "ok": True,
                        "gated": exc.user_msg or str(exc)[:200],
                        "subcode": exc.subcode,
                    }
                else:
                    result = {"ok": False, "error": str(exc)[:400], "code": exc.code}

        self.cache[key] = result
        return result

    async def probe_ad(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Same contract as ``probe``, against ``/ads`` instead of ``/adsets``.

        Two things are only decidable at the ad: whether a creative that promotes
        an EXISTING post is accepted under this objective and conversion location,
        and whether Meta wants a ``conversion_domain``. Neither appears anywhere in
        an ad set payload, so the ad-set sweeps above can say nothing about them.
        """
        if not self.refresh and key in self.cache:
            return self.cache[key]

        async with self.sem:
            self.calls += 1
            try:
                await _meta._request(
                    "POST",
                    f"{_meta._act(self.cfg.ad_account)}/ads",
                    self.cfg.token,
                    json_data=payload,
                    validate_only=True,
                    retries=2,
                )
                result: dict[str, Any] = {"ok": True}
            except _meta.MetaAdsError as exc:
                if exc.subcode == 2446079 or exc.code in _meta._THROTTLE_CODES:
                    raise ProbeThrottled(str(exc)) from exc
                if "too many calls" in str(exc).lower():
                    raise ProbeThrottled(str(exc)) from exc
                if exc.subcode in _GATED_SUBCODES:
                    result = {
                        "ok": True,
                        "gated": exc.user_msg or str(exc)[:200],
                        "subcode": exc.subcode,
                    }
                else:
                    result = {"ok": False, "error": str(exc)[:400], "code": exc.code}

        self.cache[key] = result
        return result

    async def probe_with_promoted(
        self, key: str, *, campaign_id: str, goal: str, destination: str | None = None
    ) -> dict[str, Any]:
        """Try each promoted_object shape until one is accepted.

        Which shape wins IS the answer to "what does this goal require", so the
        winning variant is recorded alongside the verdict.

        A **gated** answer does not win. Two of the gated subcodes — 1815430
        ("Please select a promoted object for your ad set") and 1815143
        (offsite conversions needs a pixel_id) — are the very thing this walk is
        measuring: they say a promoted object is REQUIRED. Counting them as
        accepted, which is right for "is this combination legal", made the
        ``none`` variant win for every goal and recorded
        ``promoted_object_kind: "none"`` for OFFSITE_CONVERSIONS.

        So: a genuine acceptance wins outright; failing that, a gated one keeps
        the goal (it is legal, the account merely lacks the prerequisite) but
        reports the kind as unknown rather than inventing "none".
        """
        last: dict[str, Any] = {"ok": False, "error": "no variant attempted"}
        gated: dict[str, Any] | None = None
        for kind, promoted in self.cfg.promoted_variants():
            result = await self.probe(
                f"{key}|promoted={kind}",
                _adset_payload(
                    campaign_id=campaign_id,
                    goal=goal,
                    destination=destination,
                    promoted=promoted,
                ),
            )
            if result.get("gated"):
                gated = gated or result
                continue
            if result.get("ok"):
                return {**result, "promoted_object_kind": kind}
            last = result
        if gated is not None:
            return {**gated, "promoted_object_kind": None}
        return {**last, "promoted_object_kind": None}


async def _create_probe_campaign(cfg: ProbeConfig, objective: str) -> str:
    """A real PAUSED campaign — /adsets validation needs a parent id.

    No budget, never activated, deleted by the caller. Meta only truly deletes
    campaigns with no spend, which this always qualifies as.
    """
    result = await _meta._request(
        "POST",
        f"{_meta._act(cfg.ad_account)}/campaigns",
        cfg.token,
        json_data={
            "name": f"[punk probe] {objective}",
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": [],
            # Probe campaigns carry no budget, which makes them ABO — and since
            # v25 Meta rejects an ABO campaign that omits this field (code 100,
            # subcode 4834011). CampaignSpec.to_payload gates it the same way.
            "is_adset_budget_sharing_enabled": False,
        },
    )
    campaign_id = result.get("id")
    if not campaign_id:
        raise _meta.MetaAdsError(f"probe campaign for {objective} returned no id")
    return str(campaign_id)


# ── Stages ───────────────────────────────────────────────────────────────────


async def probe_objective(
    prober: Prober, objective: str, out: dict[str, Any]
) -> None:
    """All six stages for one objective, against one throwaway campaign."""
    cfg = prober.cfg
    # Committed per stage, as each one finishes. The unit of "half-measured" is
    # the stage, not the objective: a completed goal sweep is a complete answer
    # to "which goals does this objective accept", whatever happens at stage 4.
    #
    # It was all-or-nothing, which is right about the danger (a throttle
    # part-way through a stage must not replace good answers with a partial map)
    # and wrong about the unit. On this ad account OUTCOME_TRAFFIC measured 13
    # goals and 18 destinations twice, and both times threw them away when a
    # later stage hit the limit — so the next run re-paid for them, into the same
    # limit that caused the problem.
    def commit(section: str, value: Any) -> None:
        # platforms_by_destination is keyed by destination, not objective — Meta's
        # placement rules follow the conversion location, so keying it per
        # objective would re-probe the same pair up to six times.
        if section == "platforms_by_destination":
            out[section] = value
        else:
            out[section][objective] = value
        prober.committed += 1

    campaign_id = await _create_probe_campaign(cfg, objective)
    print(f"  campaign {campaign_id}")
    try:
        # ── 1. goals ─────────────────────────────────────────────────────────
        goals: list[str] = []
        promoted_by_goal: dict[str, str | None] = {}
        measured = 0
        for goal in GOALS:
            res = await prober.probe_with_promoted(
                f"{objective}|goal={goal}", campaign_id=campaign_id, goal=goal
            )
            if res.get("ok"):
                goals.append(goal)
                promoted_by_goal[goal] = res.get("promoted_object_kind")
                measured += 0 if res.get("gated") else 1
            else:
                out["rejections"].append({
                    "stage": "goal", "objective": objective, "goal": goal,
                    "error": res.get("error"),
                })
        print(f"    goals: {len(goals)}/{len(GOALS)} accepted")

        if goals and measured == 0:
            # Every "yes" was a gated one, so the sweep measured nothing. Writing
            # it would claim Meta accepts all 31 goals, which is what
            # OUTCOME_APP_PROMOTION produced on an account with no app: every goal
            # answered with 1885011 ("you must provide an object_store_url"),
            # which is legal-but-unconfigured, not accepted. An unmeasured
            # objective belongs absent from the file, not present and wrong.
            print(f"    !! every goal for {objective} was account-gated; nothing measured")
            return

        commit("goals_by_objective", goals)
        commit("promoted_object_kind_by_goal", promoted_by_goal)

        if not goals:
            # Nothing below can be measured without a goal that works — usually an
            # account permission problem, not a Meta rule.
            print(f"    !! no goal accepted for {objective}; skipping later stages")
            return

        baseline_goal = goals[0]
        baseline_promoted = _promoted_for(cfg, promoted_by_goal.get(baseline_goal))

        # ── 2. destinations ──────────────────────────────────────────────────
        # Against SEVERAL goals, not just the first. A destination rejected with
        # 2490408 ("You can't use the selected performance goal with your
        # campaign objective") is telling us about the goal, not the destination —
        # and this stage gates stage 3, so a destination wrongly excluded here is
        # never swept at all.
        #
        # That is not hypothetical: goals[0] is CONVERSATIONS for both Engagement
        # and Sales, which is nonsense with a Website destination, so WEBSITE was
        # dropped from both — and the matrix tests passed while the real default
        # for both objectives failed against Meta.
        destinations: list[str] = []
        for dest in (*DESTINATIONS, *EXTRA_DESTINATIONS):
            res = {}
            for goal in goals[:_DEST_GOAL_ATTEMPTS]:
                res = await prober.probe(
                    f"{objective}|dest={dest}|via={goal}",
                    _adset_payload(
                        campaign_id=campaign_id,
                        goal=goal,
                        destination=dest,
                        promoted=_promoted_for(cfg, promoted_by_goal.get(goal)),
                    ),
                )
                if res.get("ok"):
                    break
                # Anything other than a goal↔objective complaint is about the
                # destination itself, so trying more goals only burns quota.
                if "subcode=2490408" not in (res.get("error") or ""):
                    break
            if res.get("ok"):
                destinations.append(dest)
            else:
                out["rejections"].append({
                    "stage": "destination", "objective": objective, "destination": dest,
                    "error": res.get("error"),
                })
        commit("destinations_by_objective", destinations)
        print(f"    destinations: {len(destinations)} accepted")

        # ── 3. goal × destination ────────────────────────────────────────────
        # The pair our two-axis matrix gets wrong: a goal legal for the objective
        # can still be illegal for the conversion location.
        # Seeded from the previous answer so a run that is throttled part-way
        # ADDS to a complete map instead of replacing it with a shorter one.
        pairs: dict[str, list[str]] = dict(
            out["goals_by_objective_destination"].get(objective) or {}
        )
        for dest in destinations:
            ok_goals: list[str] = []
            # Objective-accepted goals PLUS whatever the matrix offers here.
            #
            # Stage 1 probes goals with no destination_type, so a goal that only
            # makes sense WITH one is rejected there and never reaches this
            # sweep — PROFILE_VISIT (Instagram profile) and VALUE (app) are both
            # in that position. They then look "rejected" to
            # test_offered_goals_are_accepted_by_meta purely because nobody
            # asked. Measuring what we actually ship is the point of the file.
            for goal in _goals_to_sweep(objective, dest, goals):
                res = await prober.probe(
                    f"{objective}|dest={dest}|goal={goal}",
                    _adset_payload(
                        campaign_id=campaign_id,
                        goal=goal,
                        destination=dest,
                        promoted=_promoted_for(cfg, promoted_by_goal.get(goal)),
                    ),
                )
                if res.get("ok"):
                    ok_goals.append(goal)
            # Per destination, not per stage: one destination's goal sweep is a
            # complete answer, and on a throttled account the stage rarely gets
            # to finish all of them.
            pairs[dest] = ok_goals
            commit("goals_by_objective_destination", pairs)

        # ── 4. billing event per goal ────────────────────────────────────────
        billing: dict[str, list[str]] = dict(out["billing_by_goal"].get(objective) or {})
        for goal in goals:
            ok_billing: list[str] = []
            for event in BILLING_EVENTS:
                res = await prober.probe(
                    f"{objective}|goal={goal}|billing={event}",
                    _adset_payload(
                        campaign_id=campaign_id,
                        goal=goal,
                        billing=event,
                        promoted=_promoted_for(cfg, promoted_by_goal.get(goal)),
                    ),
                )
                if res.get("ok"):
                    ok_billing.append(event)
            billing[goal] = ok_billing
            commit("billing_by_goal", billing)

        # ── 5. bid strategy per goal ─────────────────────────────────────────
        bids: dict[str, list[str]] = dict(
            out["bid_strategies_by_goal"].get(objective) or {}
        )
        for goal in goals:
            ok_bids: list[str] = []
            for strategy in BID_STRATEGIES:
                res = await prober.probe(
                    f"{objective}|goal={goal}|bid={strategy}",
                    _adset_payload(
                        campaign_id=campaign_id,
                        goal=goal,
                        bid_strategy=strategy,
                        promoted=_promoted_for(cfg, promoted_by_goal.get(goal)),
                    ),
                )
                if res.get("ok"):
                    ok_bids.append(strategy)
            bids[goal] = ok_bids
            commit("bid_strategies_by_goal", bids)

        # ── 6. publisher platform per destination ────────────────────────────
        # Nothing local rejects audience_network on a Messenger/WhatsApp
        # destination today. Keyed by destination only, so a destination shared
        # between objectives is paid for once.
        platforms: dict[str, list[str]] = dict(out["platforms_by_destination"])
        for dest in destinations:
            if dest in platforms:
                continue
            ok_platforms: list[str] = []
            for platform in PUBLISHER_PLATFORMS:
                res = await prober.probe(
                    f"dest={dest}|platform={platform}",
                    _adset_payload(
                        campaign_id=campaign_id,
                        goal=baseline_goal,
                        destination=dest,
                        promoted=baseline_promoted,
                        platform=platform,
                    ),
                )
                if res.get("ok"):
                    ok_platforms.append(platform)
            platforms[dest] = ok_platforms
            commit("platforms_by_destination", platforms)

        # ── 7. existing-post ads + conversion_domain (opt-in) ────────────────
        # Last, and only when asked: it is the one stage that creates ad sets, and
        # it answers two AD-level questions the sweeps above cannot reach.
        if prober.boost_creative_id:
            await probe_existing_post(
                prober,
                objective,
                campaign_id=campaign_id,
                creative_id=prober.boost_creative_id,
                # Only what the shipped matrix actually offers. Every accepted
                # destination would multiply real ad-set creates for answers no
                # user can reach.
                destinations=[
                    d.destination_type.value
                    for d in (_matrix_destinations(objective))
                    if d.destination_type.value in destinations
                ],
                promoted_by_goal=promoted_by_goal,
                goals=goals,
                out=out,
            )

    finally:
        # Always, including on Ctrl-C or a mid-run Meta failure: a probe campaign
        # left behind is clutter in the user's real ad account.
        #
        # NOT _meta.delete_campaign: that is best-effort by design (it runs while
        # already handling a publish error, where raising would mask the real
        # one) and only logs. Here the delete happens during a throttle often
        # enough that several [punk probe] campaigns accumulated unnoticed, so
        # this reports the id loudly instead of swallowing it.
        try:
            await _meta._request(
                "POST", campaign_id, cfg.token, json_data={"status": "DELETED"}
            )
        except _meta.MetaAdsError as exc:
            print(
                f"  !! COULD NOT DELETE probe campaign {campaign_id}: {exc}\n"
                f"     Delete it by hand in Ads Manager, or re-run once the "
                f"limit clears — it is PAUSED and has no budget, so it cannot spend.",
                file=sys.stderr,
            )


async def _boost_creative(cfg: ProbeConfig) -> str | None:
    """One ad creative that promotes an existing Page post, or None.

    Reused across every objective and destination: a creative is account-scoped,
    so the answer to "does this destination accept a promoted post" needs one
    creative, not one per pair.

    Returns None only when this connection genuinely cannot promote a post — no
    Page, or a Page with nothing published. That is an UNMEASURED answer, not a
    "no": stage 7 skips and records nothing.

    A THROTTLE is different and raises ``ProbeThrottled`` instead. Returning None
    there disabled stage 7 for the whole run while stages 1-6 carried on burning
    the quota, so the one answer the run existed to get was the one it could never
    produce — and the log said "could not build a boost creative", which reads like
    the Page has no posts. Same distinction the rest of this script draws.
    """
    if not cfg.page_id:
        print("    !! no Page on this connection — cannot probe existing-post ads")
        return None
    posts = await _meta.list_page_objects(cfg.page_id, cfg.token, kind="post", limit=1)
    if not posts:
        # list_page_objects degrades to [] on ANY failure, throttle included, so a
        # cheap read confirms which it was before calling the Page empty.
        try:
            await _meta._request(
                "GET", f"{cfg.page_id}?fields=id", cfg.token, retries=1,
            )
        except _meta.MetaAdsError as exc:
            if exc.subcode == 2446079 or exc.code in _meta._THROTTLE_CODES:
                raise ProbeThrottled(f"reading the Page's posts: {exc}") from exc
        print(f"    !! Page {cfg.page_id} has no published posts to promote")
        return None
    try:
        result = await _meta._request(
            "POST",
            f"{_meta._act(cfg.ad_account)}/adcreatives",
            cfg.token,
            json_data={
                "name": "[punk probe] existing post",
                "object_story_id": str(posts[0]["id"]),
            },
        )
    except _meta.MetaAdsError as exc:
        if exc.subcode == 2446079 or exc.code in _meta._THROTTLE_CODES:
            raise ProbeThrottled(f"building the boost creative: {exc}") from exc
        print(f"    !! could not build a boost creative: {exc}")
        return None
    return str(result.get("id") or "") or None


async def probe_existing_post(
    prober: Prober,
    objective: str,
    campaign_id: str,
    creative_id: str,
    destinations: Iterable[str],
    promoted_by_goal: dict[str, str | None],
    goals: list[str],
    out: dict[str, Any],
) -> None:
    """Stage 7 — can an ad here promote a post that already exists?

    ``DestinationRules.allows_existing_post`` defaults to False precisely because
    this is not knowable from documentation: an ``object_story_id`` creative is
    accepted on some (objective, conversion location) pairs and rejected on others,
    and offering it where Meta says no publishes an ad that fails after the
    campaign and ad set already exist.

    ``conversion_domain`` is measured in the same pass, since it needs the same
    real ad set: the answer recorded is whether Meta ACCEPTS the field there, not
    whether it demands it — a domain we send and Meta ignores costs nothing, while
    one it rejects fails the ad.

    Unlike every stage above, this one CREATES ad sets: an ad can only be validated
    against a real parent. They are PAUSED under a PAUSED, budget-less campaign and
    go away with it, so they cannot spend — but it is why the stage is opt-in.
    """
    ok_posts: dict[str, bool] = dict(
        out["existing_post_by_objective_destination"].get(objective) or {}
    )
    ok_domains: dict[str, bool] = dict(
        out["conversion_domain_by_objective_destination"].get(objective) or {}
    )

    for dest in destinations:
        if dest in ok_posts:
            continue
        # A goal Meta already accepted for this pair, so a rejection below is
        # about the creative or the domain and nothing else.
        pair_goals = (
            out["goals_by_objective_destination"].get(objective, {}).get(dest) or goals
        )
        if not pair_goals:
            continue
        goal = pair_goals[0]
        try:
            adset = await _meta._request(
                "POST",
                f"{_meta._act(prober.cfg.ad_account)}/adsets",
                prober.cfg.token,
                json_data=_adset_payload(
                    campaign_id=campaign_id,
                    goal=goal,
                    destination=dest,
                    promoted=_promoted_for(prober.cfg, promoted_by_goal.get(goal)),
                ),
            )
        except _meta.MetaAdsError as exc:
            print(f"    {dest}: could not create a probe ad set — {exc}")
            continue
        adset_id = str(adset.get("id") or "")
        if not adset_id:
            continue

        base = {
            "name": "[punk probe] ad",
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        }
        post_res = await prober.probe_ad(f"{objective}|dest={dest}|existing_post", base)
        ok_posts[dest] = bool(post_res.get("ok"))
        if not post_res.get("ok"):
            out["rejections"].append({
                "stage": "existing_post", "objective": objective, "destination": dest,
                "error": post_res.get("error"),
            })

        domain_res = await prober.probe_ad(
            f"{objective}|dest={dest}|conversion_domain",
            {**base, "conversion_domain": "example.com"},
        )
        ok_domains[dest] = bool(domain_res.get("ok"))

        out["existing_post_by_objective_destination"][objective] = ok_posts
        out["conversion_domain_by_objective_destination"][objective] = ok_domains
        prober.committed += 1

    accepted = sorted(d for d, v in ok_posts.items() if v)
    print(f"    existing-post accepted on: {', '.join(accepted) or 'none'}")


def _matrix_destinations(objective: str) -> list[Any]:
    """The conversion locations the shipped matrix offers for one objective.

    Same trade as ``_goals_to_sweep``: reading OBJECTIVE_MATRIX makes stage 7 less
    independent, and buys measuring only the pairs a user can actually reach —
    which matters more here, where each pair costs a real ad-set create.
    """
    try:
        from app.graph.meta_spec.enums import Objective
        from app.graph.meta_spec.objective_matrix import matrix_for

        return list(matrix_for(Objective(objective)).destinations)
    except (KeyError, ValueError):
        return []


def _goals_to_sweep(objective: str, destination: str, accepted: list[str]) -> list[str]:
    """Goals to try against one conversion location, in order.

    The objective's accepted goals first, then any the shipped matrix offers for
    this exact pair. Reading OBJECTIVE_MATRIX here makes the probe slightly less
    independent, which is the right trade: an unmeasured combination we ship is
    worse than a measured one we do not.
    """
    out = list(accepted)
    try:
        from app.graph.meta_spec.enums import DestinationType, Objective
        from app.graph.meta_spec.objective_matrix import matrix_for

        dest = matrix_for(Objective(objective)).for_destination(
            DestinationType(destination)
        )
        out += [g.value for g in dest.optimization_goals]
    except (KeyError, ValueError):
        pass  # a destination or objective the matrix does not offer
    return list(dict.fromkeys(out))


def _promoted_for(cfg: ProbeConfig, kind: str | None) -> dict[str, Any] | None:
    """The promoted_object body for a kind stage 1 discovered."""
    if not kind or kind == "none":
        return None
    for name, body in cfg.promoted_variants():
        if name == kind:
            return body
    return None


# ── Entry point ──────────────────────────────────────────────────────────────


def _load_existing() -> dict[str, Any]:
    if not OUT_PATH.exists():
        return {}
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _load_cache(existing: dict[str, Any]) -> dict[str, Any]:
    """The resume cache, from its own file — or from the fixture, if this is a
    file written before the two were split. Losing it costs an hour of ad-account
    rate limit, so both locations are read."""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return dict(existing.get("_cache") or {})


def _reclassify_gated(cache: dict[str, Any]) -> int:
    """Upgrade answers cached before account-gated rejections were recognised.

    A run over a repaired cache costs no live calls, so this is how ~650 already
    paid-for answers get the new classification without re-probing. Matching on
    the subcode in the stored message is enough — that text is Meta's own,
    written by ``Prober.probe``.
    """
    changed = 0
    for entry in cache.values():
        if entry.get("ok") or entry.get("gated"):
            continue
        for sub in _GATED_SUBCODES:
            if f"subcode={sub}" in (entry.get("error") or ""):
                entry.update({"ok": True, "gated": entry.pop("error"), "subcode": sub})
                entry.pop("code", None)
                changed += 1
                break
    return changed


def _empty_results() -> dict[str, Any]:
    return {
        "goals_by_objective": {},
        "promoted_object_kind_by_goal": {},
        "destinations_by_objective": {},
        "goals_by_objective_destination": {},
        "billing_by_goal": {},
        "bid_strategies_by_goal": {},
        # {destination: [publisher_platform, ...]} — keyed by destination, not
        # objective. See the commit loop in probe_objective.
        "platforms_by_destination": {},
        # Stage 7, only present after a --existing-post run. Both are AD-level
        # answers, which is why they are not in the sweeps above: nothing about an
        # ad set says whether an ad may promote a post that already exists, or
        # whether Meta wants a conversion_domain on it.
        #
        #   {objective: {destination: true|false}}
        "existing_post_by_objective_destination": {},
        "conversion_domain_by_objective_destination": {},
        "rejections": [],
    }


async def main(
    objectives: Iterable[str],
    *,
    refresh: bool,
    user_id: str | None = None,
    existing_post: bool = False,
) -> int:
    objectives = list(objectives)  # iterated twice below
    cfg = ProbeConfig()
    if user_id:
        await cfg.load_from_connected_user(user_id)
    if not cfg.usable:
        print(
            "No account to probe. Either pass --user-id <uuid> for someone who has\n"
            "connected Meta through the app, or set PROBE_META_TOKEN and\n"
            "PROBE_META_AD_ACCOUNT - see the module docstring.",
            file=sys.stderr,
        )
        return 2
    print(f"probing {cfg.ad_account} (credentials from {cfg.source})")

    existing = _load_existing()

    # Answers are only comparable within ONE ad account. Bid strategies, billing
    # events and pixel events are gated per account by spend history and
    # verification status, so merging two accounts produces a map that describes
    # neither — and the resulting matrix would be confidently wrong. If the file
    # was written by a different account, start clean rather than blending.
    previous_account = existing.get("ad_account")
    switched_account = bool(
        existing and previous_account and previous_account != cfg.ad_account
    )
    if switched_account:
        print(
            f"{OUT_PATH.name} was probed against {previous_account}, not "
            f"{cfg.ad_account} — starting fresh rather than merging two accounts. "
            f"Keep one account per file.",
            file=sys.stderr,
        )
        existing = {}

    # The cache has to go with it. Clearing `existing` alone left the resume cache
    # loaded from its own file, which is keyed by combination and carries no
    # account — so a run against a second account replayed the FIRST account's
    # answers and wrote them out stamped with the second account's id. That is
    # precisely the "map that describes neither" the guard above exists to
    # prevent, arriving through the back door and without the warning.
    cache: dict[str, Any] = (
        {} if (refresh or switched_account) else _load_cache(existing)
    )
    if switched_account:
        print(
            "  (resume cache dropped too — it holds the other account's answers, "
            "so this is a full re-probe)",
            file=sys.stderr,
        )
    _reclassify_gated(cache)
    out = _empty_results()
    # Keep answers for objectives this run is not touching.
    targeted = set(objectives)
    for section in out:
        if section == "rejections":
            # Rejections are the only human-readable record of *why* a value is
            # absent from a section, and they were being dropped wholesale on
            # every run — a single-objective run left the file describing that
            # objective and nothing else. Keep the ones this run will not replace.
            out[section] = [
                r for r in (existing.get(section) or [])
                if r.get("objective") not in targeted
            ]
            continue
        out[section] = dict(existing.get(section) or {})

    prober = Prober(cfg, cache, refresh=refresh)
    if existing_post:
        # One creative for the whole run — it is account-scoped, so per-objective
        # copies would buy nothing. None disables stage 7 entirely.
        #
        # Built BEFORE any probing, and a throttle here ends the run rather than
        # continuing without it: the alternative is a full pass over stages 1-6
        # that spends the remaining quota and still cannot answer the question the
        # --existing-post flag was passed to answer.
        try:
            prober.boost_creative_id = await _boost_creative(cfg)
        except ProbeThrottled as exc:
            print(
                f"Rate-limited before the boost creative could be built ({exc}).\n"
                f"Nothing was probed and {OUT_PATH.name} is unchanged. Wait for the "
                f"ad-account limit to clear and re-run the same command — the cache "
                f"resumes, so nothing already measured is re-paid for.",
                file=sys.stderr,
            )
            return 1
    throttled: list[str] = []

    for objective in objectives:
        print(f"probing {objective}")
        try:
            await probe_objective(prober, objective, out)
        except ProbeThrottled as exc:
            # UNMEASURED, not rejected. The stage that was interrupted writes
            # nothing, so the previous run's answer for it stands and the next
            # run re-probes it; stages that already finished are kept.
            throttled.append(objective)
            print(f"  !! {objective} throttled - left unmeasured: {exc}", file=sys.stderr)
        except _meta.MetaAdsError as exc:
            # One objective failing (a permission, an unsupported objective on this
            # account) should not throw away the objectives already measured.
            print(f"  !! {objective} failed: {exc}", file=sys.stderr)
            out["rejections"].append({
                "stage": "campaign", "objective": objective, "error": str(exc)[:400],
            })

    # A run that measured nothing must not overwrite a run that did. The
    # ad-account throttle (subcode 2446079) fails every objective at the campaign
    # create, and with --refresh that wrote an empty file over good answers —
    # discarding a completed probe and the hour of rate limit it cost.
    # Not `prober.calls == 0`: a re-run over a full cache legitimately makes no
    # live calls, and that run is exactly how a reclassified cache gets folded
    # back into the sections.
    if prober.committed == 0:
        print(
            f"\nNo stage completed: every objective failed before a single ad set "
            f"was checked ({len(out['rejections'])} rejections). "
            f"{OUT_PATH.name} left unchanged.\n"
            f"If those are rate-limit errors, wait for the ad-account limit to "
            f"clear (roughly an hour) and re-run.",
            file=sys.stderr,
        )
        return 1

    out["probed_at"] = datetime.now(timezone.utc).isoformat()
    # Which account these answers describe — see the merge guard above.
    out["ad_account"] = cfg.ad_account
    out["api_version"] = settings.META_API_VERSION
    out["sdk_version"] = facebook_business.__version__
    # Assumed, not measured — see _GATED_SUBCODES. Kept so a reviewer can tell an
    # answer Meta gave from one this account was too new (or too unconfigured) to
    # give, and so tests can skip rather than assert on them.
    out["account_gated"] = {
        key: {"subcode": v.get("subcode"), "user_msg": v.get("gated")}
        for key, v in sorted(cache.items())
        if v.get("gated")
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    # Plain ASCII: this prints through the console codepage (cp1252 on Windows),
    # which raises on the arrow character.
    print(
        f"\n{prober.calls} live probes, {prober.committed} stages committed "
        f"-> {OUT_PATH}"
    )
    if throttled:
        print(
            f"INCOMPLETE (rate-limited part-way): {', '.join(throttled)}. "
            "Stages that finished were kept; the rest is unmeasured. "
            "Wait for the ad-account limit to clear and re-run WITHOUT "
            "--refresh - the cache resumes, so only the gaps are re-probed.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    # Not __doc__: the module docstring has box-drawing characters, and argparse
    # writes help through the console codepage (cp1252 on Windows), which raises.
    parser = argparse.ArgumentParser(
        description="Probe which Meta ad set combinations are real, via validate_only.",
    )
    parser.add_argument(
        "--objective", action="append", choices=OBJECTIVES,
        help="probe only this objective (repeatable); default is all six",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="re-probe everything instead of reusing cached answers",
    )
    parser.add_argument(
        "--user-id",
        help="probe using this user's connected Meta account (read from "
             "oauth_tokens) instead of PROBE_META_* environment variables",
    )
    parser.add_argument(
        "--existing-post", action="store_true",
        help="also measure whether an ad may promote an existing Page post, and "
             "whether conversion_domain is accepted, per conversion location. "
             "Opt-in because it is the only stage that CREATES ad sets and one ad "
             "creative (all PAUSED, no budget, deleted with the probe campaign) — "
             "an ad can only be validated against a real parent",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(main(
            args.objective or OBJECTIVES,
            refresh=args.refresh,
            user_id=args.user_id,
            existing_post=args.existing_post,
        ))
    )
