"""
tests/evals/test_poi_selection_eval.py
────────────────────────────────────────
Real-Gemini accuracy eval for the poi_selection classifier prompt (the block
resume_router.py builds around `resume_router._classifier_prompt`'s
POI-selection-spec section). Hits the live model — gated behind
`pytest -m eval` (see pytest.ini's `addopts = -m "not eval"`), never runs
per-commit, costs real API calls.

Asserts the STATE the classifier resolves to — the `new_value` selection
spec / `unsupported` clause — never the narrated prose. This is the corpus a
prompt change should be re-run against before shipping; a regression here
means a real user phrasing that used to resolve now doesn't (or resolves to
the wrong spec), which is invisible to test_poi_selection_corpus.py's pure
`apply_specs` tests since those start from an already-correct spec.

Run: `cd backend && PYTHONIOENCODING=utf-8 pytest -m eval tests/evals -v`
"""

from __future__ import annotations

import pytest

from app.graph.resume_router import classify_resume_intent

pytestmark = pytest.mark.eval

_STEP = "geo_pois_confirmation"


def _pois() -> list[dict]:
    """3 categories (2 discovered angles + 1 named/brand arm), enough per
    group that a "top 5" genuinely trims something in every corpus case."""
    pois = []
    for i in range(12):
        pois.append({
            "name": f"Gym {i}", "lat": 45.5 + i * 0.001, "lng": -73.6,
            "source_angle": "category", "parent_poi_type": "gym",
            "parent_label": "Montreal", "types": ["gym"],
        })
    for i in range(9):
        pois.append({
            "name": f"Coffee Shop {i}", "lat": 45.5 + i * 0.001, "lng": -73.61,
            "source_angle": "category", "parent_poi_type": "coffee shop",
            "parent_label": "Montreal", "types": ["coffee shop"],
        })
    for i in range(3):
        pois.append({
            "name": f"Starbucks {i}", "lat": 45.5 + i * 0.001, "lng": -73.62,
            "source_angle": "competitor_brand", "parent_poi_type": "Starbucks",
            "parent_label": "Montreal", "types": ["cafe"], "brand": "Starbucks",
        })
    return pois


def _state() -> dict:
    return {"campaign_builder_state": {"geo_result": {"targetable_pois": _pois()}}}


# (utterance, assertion) — assertion takes the resolved spec (new_value) and
# raises on mismatch. `None` spec fields are absent keys, not explicit nulls.
def _assert_top5_each(spec: dict) -> None:
    assert spec.get("op", "keep") == "keep"
    assert spec.get("n") == 5
    assert spec.get("scope") == "each"


def _assert_top5_all(spec: dict) -> None:
    assert spec.get("op", "keep") == "keep"
    assert spec.get("n") == 5
    assert spec.get("scope", "all") == "all"


def _assert_top10_all(spec: dict) -> None:
    assert spec.get("op", "keep") == "keep"
    assert spec.get("n") == 10
    assert spec.get("scope", "all") == "all"


def _assert_drop_laval(spec: dict) -> None:
    assert spec.get("op") == "drop"
    assert "laval" in str(spec.get("match", "")).lower()


def _assert_only_3_gyms(spec: dict) -> None:
    assert spec.get("n") == 3
    assert "gym" in str(spec.get("match", "")).lower()


def _assert_unsupported_ratio(spec: dict) -> None:
    assert spec.get("unsupported"), f"expected an unsupported clause, got {spec}"


def _assert_unsupported_floor(spec: dict) -> None:
    assert spec.get("unsupported"), f"expected an unsupported clause, got {spec}"


CASES = [
    pytest.param(
        "its too much places, i want the top 5 of each category",
        _assert_top5_each, id="the-reported-bug"),
    pytest.param("top 5", _assert_top5_all, id="bare-top-5-still-global"),
    pytest.param("only 5 per category", _assert_top5_each, id="per-category-phrasing"),
    pytest.param("just the top 10", _assert_top10_all, id="top-10-global"),
    pytest.param("drop everything in Laval", _assert_drop_laval, id="drop-by-place"),
    pytest.param("just 3 gyms", _assert_only_3_gyms, id="named-subset-count"),
    pytest.param("cut it in half", _assert_unsupported_ratio, id="unsupported-ratio"),
    pytest.param("at least 2 in each category", _assert_unsupported_floor, id="unsupported-floor"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance,check", CASES)
async def test_classifier_resolves_poi_selection_spec(utterance, check):
    intent = await classify_resume_intent(utterance, _STEP, _state())
    assert intent.lane == "edit", f"{utterance!r} -> lane={intent.lane!r} (expected edit)"
    assert intent.target_field == "poi_selection", (
        f"{utterance!r} -> target_field={intent.target_field!r}"
    )
    spec = intent.new_value
    assert isinstance(spec, dict), f"{utterance!r} -> new_value={spec!r} (expected a spec dict)"
    check(spec)


@pytest.mark.asyncio
async def test_top_5_of_each_category_bare_top_5_are_distinguishable():
    """The bug in one assertion: two phrasings that a bare-integer regex
    could not tell apart must resolve to DIFFERENT specs."""
    each = await classify_resume_intent(
        "its too much places, i want the top 5 of each category", _STEP, _state())
    bare = await classify_resume_intent("top 5", _STEP, _state())
    assert each.new_value.get("scope") == "each"
    assert bare.new_value.get("scope", "all") == "all"
