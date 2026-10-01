"""
tests/test_assert_groups_fetched.py
────────────────────────────────────
`maid_store._assert_groups_fetched` — the evaluability gate for an
intersection/difference/min_distinct_groups filter over groups whose query
came back "failed" (zero data) vs. "partial" (split under the vendor's
100k-observations-per-feature cap, but real rows came back).

The regression this guards (thread 76e8a789, the CEO's exact dog-gear
prompt: "vet clinic, PetSmart, and a dog park all within 45 days in
Denver"): extraction was correct (op=intersection, all 3 groups resolved),
but every group came back "partial" (Denver-wide category searches are
"partial" by DEFAULT under the observation cap, not by failure), and the
old code treated "partial" identically to "failed" — nulling the ENTIRE
filter and silently falling back to the raw unfiltered union (17,250 ==
17,250, geo.audience_filter: null). A big-market intersection was
unconditionally unevaluable regardless of how much real data came back.

"partial" must now behave like it already does for exclude_groups
(narrate, still apply) — only a genuinely FAILED group (zero rows) raises.
"""
from __future__ import annotations

import pytest

from app.services.maid_store import AudienceFilterUnevaluable, _assert_groups_fetched

# The real group_status captured from thread 76e8a789 — substantial rows on
# every group, all "partial" (a large-city category search splitting under
# the per-feature observation cap), none "failed".
_REAL_PARTIAL_STATUS = {
    "competitor_brand:PetSmart": {"status": "partial", "pois_requested": 7, "rows": 10757},
    "category:vet clinic": {"status": "partial", "pois_requested": 143, "rows": 75072},
    "category:dog park": {"status": "partial", "pois_requested": 51, "rows": 25546},
}

_INTERSECTION_SPEC = {
    "groups": ["category:vet clinic", "competitor_brand:PetSmart", "category:dog park"],
    "op": "intersection",
    "window_days": 45,
}


def test_partial_groups_do_not_raise_for_intersection():
    """The exact regression: a real-world market-scale intersection where
    every group is 'partial' (the default outcome, not a failure) must
    still evaluate — not silently degrade to the unfiltered union."""
    _assert_groups_fetched(_INTERSECTION_SPEC, _REAL_PARTIAL_STATUS)  # must not raise


def test_failed_group_still_raises_for_intersection():
    status = dict(_REAL_PARTIAL_STATUS)
    status["category:vet clinic"] = {"status": "failed", "pois_requested": 143, "rows": 0}
    with pytest.raises(AudienceFilterUnevaluable):
        _assert_groups_fetched(_INTERSECTION_SPEC, status)


def test_partial_groups_do_not_raise_for_difference():
    spec = {**_INTERSECTION_SPEC, "op": "difference"}
    _assert_groups_fetched(spec, _REAL_PARTIAL_STATUS)  # must not raise


def test_partial_groups_do_not_raise_for_min_distinct_groups():
    spec = {
        "groups": ["category:vet clinic", "competitor_brand:PetSmart", "category:dog park"],
        "min_distinct_groups": 2,
    }
    _assert_groups_fetched(spec, _REAL_PARTIAL_STATUS)  # must not raise


def test_failed_group_still_raises_for_min_distinct_groups():
    spec = {
        "groups": ["category:vet clinic", "competitor_brand:PetSmart"],
        "min_distinct_groups": 2,
    }
    status = {"category:vet clinic": {"status": "failed"}, "competitor_brand:PetSmart": {"status": "partial"}}
    with pytest.raises(AudienceFilterUnevaluable):
        _assert_groups_fetched(spec, status)


def test_any_of_branch_with_partial_groups_does_not_raise():
    spec = {
        "any_of": [
            {"groups": ["category:vet clinic", "category:dog park"], "op": "intersection"},
            {"groups": ["competitor_brand:PetSmart"]},
        ]
    }
    _assert_groups_fetched(spec, _REAL_PARTIAL_STATUS)  # must not raise


def test_any_of_branch_with_a_failed_group_still_raises():
    spec = {
        "any_of": [
            {"groups": ["category:vet clinic", "category:dog park"], "op": "intersection"},
        ]
    }
    status = {"category:vet clinic": {"status": "failed"}, "category:dog park": {"status": "partial"}}
    with pytest.raises(AudienceFilterUnevaluable):
        _assert_groups_fetched(spec, status)


def test_failed_exclude_group_still_raises_under_union():
    """The other half of the asymmetry — unchanged by this fix: a FAILED
    exclude group is the opposite of honest and must still raise, even
    under the default union op."""
    spec = {"groups": ["category:gym"], "exclude_groups": ["store_set:my stores"]}
    status = {"category:gym": {"status": "complete"}, "store_set:my stores": {"status": "failed"}}
    with pytest.raises(AudienceFilterUnevaluable):
        _assert_groups_fetched(spec, status)


def test_partial_exclude_group_does_not_raise_under_union():
    spec = {"groups": ["category:gym"], "exclude_groups": ["store_set:my stores"]}
    status = {"category:gym": {"status": "complete"}, "store_set:my stores": {"status": "partial"}}
    _assert_groups_fetched(spec, status)  # must not raise


def test_no_group_status_is_a_no_op():
    _assert_groups_fetched(_INTERSECTION_SPEC, None)
    _assert_groups_fetched(_INTERSECTION_SPEC, {})


def test_no_spec_is_a_no_op():
    _assert_groups_fetched(None, _REAL_PARTIAL_STATUS)
    _assert_groups_fetched({}, _REAL_PARTIAL_STATUS)


def test_complete_groups_never_raise():
    status = {k: {"status": "complete"} for k in ("category:vet clinic", "competitor_brand:PetSmart", "category:dog park")}
    _assert_groups_fetched(_INTERSECTION_SPEC, status)
