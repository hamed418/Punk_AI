"""
Placements validated against the conversion location.

``AdSetSpec._targeting_placements_valid`` is a field validator on ``targeting``
alone, so it can check the placement *vocabulary* and that a positions key names
a platform that is present — but it cannot see the destination. Nothing rejected
``publisher_platforms: ["audience_network"]`` on a Messenger ad set, and Meta's
own preflight was the only thing standing between that and a failed publish.

Both rules here are measured, not documented — ``scripts/probe_meta_matrix.py``
probes one platform at a time per destination:

  * subcode 1815336, "The placement combination selected is not supported by the
    set up of the campaign" — every messaging destination rejected
    ``audience_network``. A destination rule.
  * subcode 1815985, "To use the Messenger Stories placement, please also select
    either Facebook Feeds or Instagram Stories" — a lone ``messenger``. A
    combination rule, so it holds everywhere rather than per destination.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydantic import ValidationError

from app.graph.meta_spec.enums import (
    DestinationType,
    Objective,
    OptimizationGoal,
)
from app.graph.meta_spec.objective_matrix import (
    MESSENGER_NEEDS_COMPANION,
    OBJECTIVE_MATRIX,
    matrix_for,
)

from tests.test_meta_spec_matrix import _adset, _campaign, _creative
from app.graph.meta_spec.models import AdSpec


def _messaging_dest():
    return matrix_for(Objective.ENGAGEMENT).for_destination(DestinationType.MESSENGER)


def _messenger_campaign(targeting: dict):
    """An Engagement → Messenger campaign, which is where the destination rule
    bites. The CTA lives on the creative, not the ad set."""
    dest = _messaging_dest()
    return _campaign(
        objective=Objective.ENGAGEMENT,
        adsets=[_adset(
            destination_type=DestinationType.MESSENGER,
            optimization_goal=dest.default_optimization_goal,
            billing_event=dest.default_billing_event,
            targeting=targeting,
            ads=[AdSpec(name="Ad 1", creative=_creative(
                call_to_action=dest.default_call_to_action,
            ))],
        )],
    )


# ── the destination rule ─────────────────────────────────────────────────────


def test_placements_meta_has_removed_are_not_offered():
    """Instagram Explore Feed and Messenger Stories were removed in Marketing API
    v26.0 (29 Jul 2026) — Explore now errors outright — and on 27 Oct 2026 that
    reaches every supported version, the v25.0 Punk pins included. Offering
    either in the editor buys a dated hard publish failure."""
    from app.graph.meta_spec.enums import INSTAGRAM_POSITIONS, MESSENGER_POSITIONS

    assert "explore" not in INSTAGRAM_POSITIONS
    assert "story" not in MESSENGER_POSITIONS


def test_audience_network_is_rejected_on_a_messenger_adset():
    with pytest.raises(ValueError, match="cannot deliver"):
        _messenger_campaign({
            "geo_locations": {"countries": ["US"]},
            "publisher_platforms": ["facebook", "audience_network"],
        })


def test_audience_network_is_fine_on_a_website_adset():
    """WEBSITE accepted every platform probed, so the rule must not be global."""
    _campaign(adsets=[_adset(targeting={
        "geo_locations": {"countries": ["US"]},
        "publisher_platforms": ["facebook", "audience_network"],
    })])


def test_absent_placements_are_advantage_plus_and_never_rejected():
    """Omitting publisher_platforms IS Meta's automatic placement — the good
    default. A destination constraint must not turn that into an error."""
    _messenger_campaign({"geo_locations": {"countries": ["US"]}})


# ── the combination rule ─────────────────────────────────────────────────────


def test_messenger_alone_is_rejected():
    with pytest.raises(ValueError, match="on its own"):
        _campaign(adsets=[_adset(targeting={
            "geo_locations": {"countries": ["US"]},
            "publisher_platforms": ["messenger"],
        })])


@pytest.mark.parametrize("companion", MESSENGER_NEEDS_COMPANION)
def test_messenger_with_a_companion_is_accepted(companion):
    _campaign(adsets=[_adset(targeting={
        "geo_locations": {"countries": ["US"]},
        "publisher_platforms": ["messenger", companion],
    })])


# ── the builder narrows instead of failing ───────────────────────────────────


def test_the_builder_drops_a_platform_the_destination_cannot_serve():
    """placement_strategy is LLM prose. A Messenger campaign whose rationale
    mentions Audience Network must still produce a publishable plan — killing
    plan generation over a phrase is worse than dropping the platform."""
    from app.graph.meta_spec.builder import _resolve_placements

    brief = {"placement_strategy": "Facebook and Audience Network for reach"}
    assert _resolve_placements(brief) == ["facebook", "audience_network"]
    assert _resolve_placements(brief, _messaging_dest()) == ["facebook"]


def test_the_builder_drops_a_lone_messenger_placement():
    from app.graph.meta_spec.builder import _resolve_placements

    brief = {"placement_strategy": "messenger only"}
    assert _resolve_placements(brief, _messaging_dest()) == []


# ── held to what Meta actually said ──────────────────────────────────────────

_PROBE_PATH = Path(__file__).parent / "data" / "meta_matrix_probe.json"
try:
    _PROBE = json.loads(_PROBE_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _PROBE = None


@pytest.mark.skipif(_PROBE is None, reason="no meta_matrix_probe.json")
@pytest.mark.parametrize(
    "objective,dest",
    [(o, d) for o, r in OBJECTIVE_MATRIX.items() for d in r.destinations],
    ids=lambda v: getattr(v, "value", None) or getattr(v, "label", ""),
)
def test_allowed_platforms_are_ones_meta_accepted(objective, dest):
    """The constraint narrows what the editor offers, so being wrong here removes
    a placement that works. Only assert where the probe measured the destination."""
    measured = (_PROBE.get("platforms_by_destination") or {}).get(
        dest.destination_type.value
    )
    if measured is None or dest.publisher_platforms is None:
        pytest.skip(f"{dest.destination_type.value} not probed, or unconstrained")
    # messenger is excluded from the comparison: the probe measured it alone,
    # which Meta rejects for a companion-placement reason rather than a
    # destination one.
    claimed = set(dest.publisher_platforms) - {"messenger"}
    assert claimed <= set(measured), (
        f"{objective.value} → {dest.label} allows platforms Meta rejected: "
        f"{sorted(claimed - set(measured))}"
    )


# ── destination_type is not always a field Meta wants ────────────────────────


def test_engagement_website_omits_destination_type_on_the_wire():
    """Live-measured. Meta shows "Website" under Engagement in Ads Manager, but
    the API models it as an ad set with NO destination_type — the creative's link
    does the work. Sending it is rejected with subcode 2490408, "You can't use the
    selected performance goal with your campaign objective", which is a red
    herring: POST_ENGAGEMENT, LINK_CLICKS, REACH, IMPRESSIONS and
    LANDING_PAGE_VIEWS were all rejected with the field present and all accepted
    with it absent.

    Engagement defaults to this conversion location, so every Engagement plan
    failed preflight."""
    spec = _campaign(
        objective=Objective.ENGAGEMENT,
        adsets=[_adset(
            destination_type=DestinationType.WEBSITE,
            # LINK_CLICKS, not POST_ENGAGEMENT: the latter is no longer offered
            # on this conversion location — it fails at ad creation with subcode
            # 1885154, a website link ad having no post to engage with.
            optimization_goal=OptimizationGoal.LINK_CLICKS,
        )],
    )
    payload = spec.adsets[0].to_payload(campaign_id="c1", ad_account_id="act_1")
    assert "destination_type" not in payload


def test_other_objectives_still_send_destination_type():
    """Awareness → Website and Traffic → Website both accept the field, so the
    omission must be scoped to the one conversion location that needs it."""
    payload = _campaign().adsets[0].to_payload(campaign_id="c1", ad_account_id="act_1")
    assert payload["destination_type"] == "WEBSITE"


def test_the_flag_cannot_be_supplied_by_a_client():
    """It is a private attribute set during CampaignSpec validation. A spec is
    built from user-submitted JSON, so an input key that switched a wire field
    off would be a way to smuggle a payload past the matrix."""
    with pytest.raises(ValidationError):
        _adset(_omit_destination_type=True)
