"""
tests/evals/test_entry_angle_extraction_eval.py
─────────────────────────────────────────────────
Real-Gemini accuracy eval for the entry extraction prompt's TARGETING INTENT vs
PERSONA DESCRIPTOR rules (`prompts.EXTRACTION_FIELDS_SPEC`, `deterministic_subtype`).
Hits the live model — gated behind `pytest -m eval` (see pytest.ini's
`addopts = -m "not eval"`), never runs per-commit, costs real API calls.

The reported bug (thread c5def44c-95ba-4448-89ce-c54185f56657): "Target people
who own cafés in Chicago" has WHERE/WHO/WHAT all stated, but with no
`deterministic_subtype`/`poi_types` set, `nodes._has_angle` sees no concrete
angle and forces the two-path guidance fork instead of going straight to the
builder. Rule 5a (OWNER/OPERATOR of a concrete venue) was added to
`EXTRACTION_FIELDS_SPEC` so ownership phrasing over a physical, searchable venue
resolves to `deterministic_subtype="category"` — this is the corpus a future
prompt edit should be re-run against.

Run: `cd backend && PYTHONIOENCODING=utf-8 pytest -m eval tests/evals -v`
"""
from __future__ import annotations

import pytest

from app.graph.nodes import extract_user_info_from_text

pytestmark = pytest.mark.eval


def _assert_category_poi(field_value: str):
    def _check(extracted: dict) -> None:
        assert extracted.get("deterministic_subtype") == "category", (
            f"expected category, got {extracted.get('deterministic_subtype')!r} "
            f"(full: {extracted!r})"
        )
        pois = [str(p).lower() for p in (extracted.get("poi_types") or [])]
        assert any(field_value in p for p in pois), (
            f"expected a poi_type containing {field_value!r}, got {pois!r}"
        )
    return _check


def _assert_persona_descriptor(extracted: dict) -> None:
    assert extracted.get("deterministic_subtype") is None, (
        f"expected null (persona descriptor, no ownership word) — got "
        f"{extracted.get('deterministic_subtype')!r} (full: {extracted!r})"
    )


CASES = [
    pytest.param(
        "Target people who own cafés in Chicago.",
        _assert_category_poi("caf"), id="the-reported-bug-cafe-owners"),
    pytest.param(
        "reach gym owners nationwide",
        _assert_category_poi("gym"), id="gym-owners"),
    pytest.param(
        "salon owners in Miami",
        _assert_category_poi("salon"), id="salon-owners"),
    pytest.param(
        "hospital staff", _assert_persona_descriptor,
        id="employment-no-ownership-word-must-not-regress"),
    pytest.param(
        "people who work in hospitals", _assert_persona_descriptor,
        id="employment-phrase-must-not-regress"),
    pytest.param(
        "café staff", _assert_persona_descriptor,
        id="bare-occupation-noun-no-ownership-word"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("text,check", CASES)
async def test_ownership_phrasing_resolves_to_category(text, check):
    extracted = await extract_user_info_from_text(text)
    check(extracted)


# ── Two layers, fill both (thread a1d41109-d9b2-4170-9799-41095ecbd94e) ──────
# "women 24-38 who visited a wedding venue, a jeweler, and a bridal show" landed
# ONLY in audience_filter.groups — no poi_types/event_queries/deterministic_
# subtype(s) — so `nodes._has_angle` saw no angle and forced the two-path
# guidance fork + the geo_collect_det_type picker even though the user had
# already named every place. `extract_user_info_from_text` (the resume-path
# extractor entry_node also calls) does NOT run the deterministic_subtypes →
# deterministic_subtype collapse (that only happens in entry_node), so these
# assertions read the plural `deterministic_subtypes` list directly.

@pytest.mark.asyncio
async def test_demographic_visit_list_fills_angle_and_filter():
    extracted = await extract_user_info_from_text(
        "I run a bridal boutique in Nashville. I want to reach women 24-38 "
        "who visited a wedding venue, a jeweler, and a bridal show in the "
        "last 1 months."
    )
    subtypes = set(extracted.get("deterministic_subtypes") or (
        [extracted["deterministic_subtype"]] if extracted.get("deterministic_subtype") else []
    ))
    assert "category" in subtypes, f"expected category angle, got {extracted!r}"
    assert "event_based" in subtypes, f"expected event_based angle, got {extracted!r}"

    pois = [str(p).lower() for p in (extracted.get("poi_types") or [])]
    assert any("wedding" in p for p in pois), f"expected a wedding-venue poi_type, got {pois!r}"
    assert any("jewel" in p for p in pois), f"expected a jeweler poi_type, got {pois!r}"

    events = [str(e).lower() for e in (extracted.get("event_queries") or [])]
    assert any("bridal" in e for e in events), f"expected a bridal-show event_query, got {events!r}"

    af = extracted.get("audience_filter") or {}
    groups = [str(g).lower() for g in (af.get("groups") or [])]
    assert len(groups) >= 3, f"expected the filter groups preserved too, got {af!r}"
    assert af.get("window_days") == 30, f"expected window_days=30, got {af!r}"
    assert af.get("op") == "intersection", (
        f"a singular 'a X, a Y, and a Z' list means one visit to each, got op={af.get('op')!r}"
    )


@pytest.mark.asyncio
async def test_explicit_both_still_sets_intersection_alongside_angle():
    extracted = await extract_user_info_from_text(
        "reach people who visited both a gym and a spa in Austin"
    )
    pois = [str(p).lower() for p in (extracted.get("poi_types") or [])]
    assert any("gym" in p for p in pois), f"expected gym poi_type, got {pois!r}"
    assert any("spa" in p for p in pois), f"expected spa poi_type, got {pois!r}"

    af = extracted.get("audience_filter") or {}
    assert af.get("op") == "intersection", (
        f"explicit 'both X and Y' must still set intersection, got {af!r}"
    )


# ── Thread a90cc17c: flash-lite dropped everything but product_offer/audience ──
# Turn 1 extraction lost location, the angle and business_description, so the
# onboarding gate downgraded a correct geo_agent route to a filler guidance turn.

@pytest.mark.asyncio
async def test_singular_visit_list_with_window_fills_everything():
    extracted = await extract_user_info_from_text(
        "I sell custom dog gear online. Target people who visited a vet clinic, "
        "PetSmart, and a dog park all within the last 45 days in Denver."
    )
    assert "Denver" in (extracted.get("location") or []), extracted
    assert extracted.get("business_description"), extracted
    assert extracted.get("poi_types"), extracted
    assert any("petsmart" in str(b).lower() for b in extracted.get("competitor_brands") or []), extracted
    af = extracted.get("audience_filter") or {}
    assert af.get("op") == "intersection" and af.get("window_days") == 45, af
