"""
tests/evals/test_response_quality_eval.py
─────────────────────────────────────────
Prose-quality scoreboard for BOTH user-facing voices: the narrator composer
(`narrator.composer._compose`) and `nodes.chatbot_node`.

Every other eval here asserts build STATE, never text. This one grades the text:

  hard checks (deterministic, must be 100%)
    • every number ≥ 10 in the reply appears in the facts/state it was given
    • no internal jargon, hype word, emoji, or second affirmation
    • text_input framing ends on a question; widget framing asks none
    • a heard-but-not-applied edit is never reported as added/removed/changed/updated
    • composer replies stay within 1.25x their character budget
  judge (gemini, 1-5, mean of N samples): responds_to_user · builds_forward ·
    explains_why · clarity

Hits the live model, so it is gated behind `pytest -m eval`. The local .env
targets the PROD database — point Postgres at a dead port; nothing here opens a
session:

    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=9 PYTHONIOENCODING=utf-8 \\
        pytest -m eval tests/evals/test_response_quality_eval.py -s

    EVAL_SAMPLES=3   generations per scenario (default 3)
    EVAL_OUT=path    also write the scoreboard as JSON, to diff against a baseline
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.graph.narrator import beats, cache
from app.graph.narrator.composer import _compose, _max_chars
from app.graph.narrator.prompts.base import GLOBAL_FORBIDDEN_TERMS

pytestmark = pytest.mark.eval

SAMPLES = int(os.environ.get("EVAL_SAMPLES", "3"))
CRITERIA = ("responds_to_user", "builds_forward", "explains_why", "clarity")

_AFFIRMATIONS = ("Got it.", "Perfect.", "Great news!", "Great —")
_HYPE = ("Awesome", "Absolutely", "Love it", "Amazing")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅]")
_CHANGE_VERBS = re.compile(r"\b(added|removed|trimmed|updated|changed)\b", re.I)
# A leading "$" is exempt: "say you set $20 a day" is a hypothetical, which the
# chatbot prompt allows. Percentages and bare figures are the unsourced statistics.
_NUMBER = re.compile(r"(?<![\w.$])\d[\d,]*(?:\.\d+)?")
# Case-sensitive acronyms need word boundaries or "poi" matches inside words.
_ACRONYMS = {"POI", "MAID"}


# ── scenario model ─────────────────────────────────────────────────────────────


@dataclass
class Scenario:
    name: str
    voice: str  # "composer" | "chatbot"
    build: Callable[[], dict]
    user_text: str
    expect_question: bool = False      # text_input framing: must END on a question
    expect_no_question: bool = False   # widget framing: the widget asks, not the message
    no_change_claims: bool = False     # heard-not-applied: must not say added/removed/changed/...
    notes: str = ""                    # extra rubric context for the judge


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text, id="h1")


def _pois() -> list[dict]:
    rows = [("Starbucks", "Starbucks", "Montreal")] * 4 + [("Starbucks", "Starbucks", "Laval")] * 2
    rows += [("Tim Hortons", "Tim Hortons", "Montreal")] * 3 + [("Tim Hortons", "Tim Hortons", "Laval")] * 2
    rows += [("Cafe Olimpico", "coffee shop", "Montreal")]
    return [
        {"name": f"{n} #{i}", "brand": b, "parent_poi_type": b, "parent_location": loc,
         "rating": 4.3, "user_ratings_total": 100 + i}
        for i, (n, b, loc) in enumerate(rows)
    ]


def _geo(**over: Any) -> dict:
    return {
        "targeting_method": "deterministic", "pois_found": 12,
        "locations": [{"location_name": "Montreal"}, {"location_name": "Laval"}],
        "targetable_pois": _pois(), **over,
    }


def _composer_state(*, beat_list: list[tuple[str, dict]], user_text: str = "yes", geo: dict | None = None,
                    user_info: dict | None = None, history: list[str] | None = None,
                    user_turn: dict | None = None, applied: dict | None = None,
                    heard: dict | None = None) -> dict:
    state = {
        "messages": [_human(user_text)],
        "user_info": {"business_name": "Bean & Brew", "industry": "cafe", **(user_info or {})},
        "geo_data": geo or {},
        "user_turn": user_turn or {},
    }
    for line in history or []:
        beats.record_history(state, line)
    for kind, facts in beat_list:
        beats.add_beat(state, kind, facts)
    if applied or heard:
        beats.record_change(state, applied=applied, heard=heard)
    return state


def _combined_facts() -> dict:
    return {
        "poi_count": 15, "combined": True,
        "angles": [
            {"token": "store_set", "label": "Target people near my own businesses", "count": 2,
             "sample_places": ["Iron Temple Gym"]},
            {"token": "event_based", "label": "Target people at events", "count": 8,
             "sample_places": ["Osheaga Grounds"]},
            {"token": "competitor_nearby", "label": "Target people near my competitors", "count": 5,
             "sample_places": ["Rival Fitness"]},
        ],
    }


_DELIVERED = "Audience built — 8,400 verified visitors at your 12 spots."

SCENARIOS: list[Scenario] = [
    Scenario(
        "reveal_single", "composer", lambda: _composer_state(
            beat_list=[("reveal", {"poi_count": 12, "det_type": "category"}),
                       ("framing", {"stage": "maid_settings"})],
            geo=_geo()),
        "yes, go ahead", expect_no_question=True,
    ),
    Scenario(
        "reveal_combined", "composer", lambda: _composer_state(
            beat_list=[("reveal", _combined_facts())], geo=_geo(pois_found=15)),
        "yes", notes="Combined targeting: must group by strategy, one opener, one why.",
    ),
    Scenario(
        "reveal_filter_zeroed", "composer", lambda: _composer_state(
            beat_list=[("reveal", {"audience_count": 0, "audience_count_before_filter": 4200,
                                   "filter_zeroed": True, "active_filter": "weekends only, 3+ visits"}),
                       ("framing", {"stage": "maid_confirm_results"})],
            geo=_geo(maid_count=4200, filtered_maid_count=0,
                     audience_filter={"days_of_week": [5, 6], "min_visits": 3})),
        # No expect_no_question: the reveal hint itself tells the composer to ask
        # whether to loosen the filter.
        "only people who go on weekends, 3+ times",
        notes="The filter matched nobody: must NOT present 0 as the audience found.",
    ),
    Scenario(
        "reveal_query_failed", "composer", lambda: _composer_state(
            beat_list=[("failure", {"what": "audience_query", "failure_kind": "timeout"})],
            geo=_geo(maid_failure_kind="timeout")),
        "continue", notes="The query did not run: must not say nobody visited.",
    ),
    Scenario(
        "framing_text_input", "composer", lambda: _composer_state(
            beat_list=[("framing", {"stage": "business_name", "action_type": "text_input",
                                    "question": "What's the name of your business?"})],
            geo=_geo(maid_count=8400), history=[_DELIVERED, "Goal locked in: AWARENESS."]),
        "awareness", expect_question=True,
    ),
    Scenario(
        "framing_widget", "composer", lambda: _composer_state(
            beat_list=[("framing", {"stage": "objective", "action_type": "buttons"})],
            geo=_geo(maid_count=8400), history=[_DELIVERED]),
        "ok", expect_no_question=True, notes="8,400 was already delivered: must not be restated.",
    ),
    Scenario(
        "handoff", "composer", lambda: _composer_state(
            beat_list=[("handoff", {"from": "maid", "to": "campaign", "audience_count": 8400})],
            geo=_geo(maid_count=8400)),
        "proceed",
    ),
    Scenario(
        "answer_why_radius", "composer", lambda: _composer_state(
            beat_list=[("answer", {"question": "why does the radius matter?", "step": "maid_settings",
                                   "active_prompt": "How far around each spot should we look?"}),
                       ("framing", {"stage": "maid_settings", "action_type": "buttons"})],
            geo=_geo(maid_count=8400), history=[_DELIVERED],
            user_turn={"phrase": "why does the radius matter?", "embedded_ask": "why does the radius matter?",
                       "mood": "confused", "engagement": "terse"}),
        "why does the radius matter?", expect_no_question=True,
        notes="A real question: needs a genuinely explanatory answer, not one line.",
    ),
    Scenario(
        "edit_applied", "composer", lambda: _composer_state(
            beat_list=[("edit", {"field": "budget", "new_value": "$500 per day"}),
                       ("framing", {"stage": "campaign_plan", "action_type": "buttons"})],
            geo=_geo(maid_count=8400), applied={"budget": "Budget set to $500 per day"}),
        "make the budget $500 a day", expect_no_question=True,
    ),
    Scenario(
        "edit_heard_not_applied", "composer", lambda: _composer_state(
            beat_list=[("edit", {"field": "poi_selection", "request": "keep only the top 10 spots"}),
                       ("framing", {"stage": "geo_pois_confirmation", "action_type": "buttons"})],
            geo=_geo(), heard={"poi_selection": "trim to the top 10 spots"}),
        "keep only the top 10", expect_no_question=True, no_change_claims=True,
        notes="Heard but NOT applied: must not say the spots were trimmed.",
    ),
    Scenario(
        "failure_multi", "composer", lambda: _composer_state(
            beat_list=[("failure", {"blocker": "no payment method on the ad account"}),
                       ("failure", {"blocker": "no Pixel found on the ad account"}),
                       ("failure", {"blocker": "the Facebook Page is unpublished"})],
            geo=_geo(maid_count=8400)),
        "publish it", notes="All three blockers must be named; point to a viable path.",
    ),
    # ── chatbot ───────────────────────────────────────────────────────────────
    Scenario("chat_greeting", "chatbot", lambda: {"messages": [_human("hi, what can you do?")]},
             "hi, what can you do?"),
    Scenario(
        "chat_guidance_fork", "chatbot", lambda: {
            "messages": [_human("I want to advertise to beach goers in Miami")],
            "onboarding_active": True,
            "user_info": {"target_audience": "beach goers", "location": ["Miami"]},
        }, "I want to advertise to beach goers in Miami",
        notes="Offer the two targeting paths; do not ask for competitors or the goal.",
    ),
    Scenario(
        "chat_guided_recommendation", "chatbot", lambda: {
            "messages": [_human("you decide, I have no idea")],
            "onboarding_active": True,
            "user_info": {"target_audience": "injured MMA fighters", "location": ["Austin"],
                          "targeting_choice": "guided"},
        }, "you decide, I have no idea",
        notes="Must name a concrete angle with real place types, then invite to proceed.",
    ),
    Scenario(
        "chat_knowledge_question", "chatbot", lambda: {
            "messages": [
                _human("what's the difference between campaign budget and ad set budget?"),
                AIMessage(content=("Campaign budget optimization sets one budget at campaign level and Meta "
                                   "distributes it across ad sets. Ad set budgets give each ad set its own "
                                   "fixed spend."), additional_kwargs={"role": "knowledge_context"}),
            ],
        }, "what's the difference between campaign budget and ad set budget?",
        notes="Genuine question: fuller structured answer, then steer back.",
    ),
    Scenario(
        "chat_builder_failure", "chatbot", lambda: {
            "messages": [_human("continue")],
            "wizard_failure": "builder_act_failed",
            "user_info": {"business_name": "Bean & Brew"},
            "geo_data": _geo(maid_count=8400),
        }, "continue", notes="Our fault, progress saved, 'continue' retries; no invented cause.",
    ),
    Scenario(
        "chat_off_topic", "chatbot", lambda: {
            "messages": [_human("what's the price of bitcoin today?"),
                         AIMessage(content="bitcoin price", additional_kwargs={"role": "guardrail_reject"})],
        }, "what's the price of bitcoin today?", notes="Decline politely, pivot to Meta ads.",
    ),
    Scenario(
        "chat_midbuild_why", "chatbot", lambda: {
            "messages": [_human("why does audience size matter?")],
            "user_info": {"business_name": "Bean & Brew", "industry": "cafe"},
            "geo_data": _geo(maid_count=8400, maid_count_confidence="high"),
        }, "why does audience size matter?",
        notes="Real question: define, reason, tradeoff, steer back; cite 8,400 only if it helps.",
    ),
]

assert len({s.name for s in SCENARIOS}) == len(SCENARIOS)


# ── hard checks ────────────────────────────────────────────────────────────────


def _numbers(text: str) -> set[float]:
    out: set[float] = set()
    for m in _NUMBER.findall(text or ""):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def hard_checks(sc: Scenario, text: str, pool: str, budget: int | None) -> list[str]:
    bad: list[str] = []
    known = _numbers(pool)
    for m in _NUMBER.finditer(text):
        n = float(m.group(0).replace(",", "").rstrip("."))
        if n >= 10 and n not in known:
            bad.append(f"ungrounded number {m.group(0)!r} in ...{text[max(0, m.start() - 30):m.end() + 20]!r}")
    for term in GLOBAL_FORBIDDEN_TERMS:
        pat = rf"\b{re.escape(term)}\b" if term in _ACRONYMS else re.escape(term)
        if re.search(pat, text, 0 if term in _ACRONYMS else re.I):
            bad.append(f"jargon {term!r}")
    bad += [f"hype {h!r}" for h in _HYPE if h in text]
    if _EMOJI.search(text):
        bad.append("emoji")
    if sum(text.count(a) for a in _AFFIRMATIONS) > 1:
        bad.append("more than one affirmation")
    if sc.expect_question and not text.rstrip().endswith("?"):
        bad.append("text_input framing does not end on a question")
    if sc.expect_no_question and "?" in text:
        bad.append("widget framing asks a question")
    if sc.no_change_claims and _CHANGE_VERBS.search(text):
        bad.append(f"claims a change nothing applied: {_CHANGE_VERBS.search(text).group(0)!r}")
    if budget is not None and len(text) > budget * 1.25:
        bad.append(f"length {len(text)} > 1.25 x budget {budget}")
    if not text.strip():
        bad.append("empty reply")
    return bad


# ── judge ──────────────────────────────────────────────────────────────────────


class Score(BaseModel):
    responds_to_user: int = Field(ge=1, le=5, description="answers/acknowledges the user's actual message")
    builds_forward: int = Field(ge=1, le=5, description="does not restate facts already delivered; moves on")
    explains_why: int = Field(ge=1, le=5, description="ties the step/answer to WHY it matters for this business")
    clarity: int = Field(ge=1, le=5, description="plain words, one voice, no filler, right length for the moment")
    note: str = ""


_RUBRIC = (
    "You grade one reply from Punk, an assistant that builds Meta ad campaigns with a small-business owner. "
    "Score 1-5 (5 = excellent) on each criterion. Be strict: 3 is 'acceptable', 5 is rare. "
    "A reply that restates facts listed under ALREADY DELIVERED loses builds_forward. "
    "A one-liner to a genuine question loses responds_to_user. Jargon, filler or stacked openers lose clarity."
)


INFRA_FAILURES = 0  # 429s etc. that had to be retried — reported on the scoreboard


async def _retry(call, what: str, attempts: int = 5):
    """Vertex returns 429 under burst load; the SDK's own retries are exhausted by
    then. A quota error is not a quality signal, so wait it out rather than score it."""
    global INFRA_FAILURES
    for i in range(attempts):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001
            if i == attempts - 1:
                raise
            INFRA_FAILURES += 1
            print(f"[eval] {what} failed ({type(exc).__name__}); retry {i + 1}")
            await asyncio.sleep(15 * (i + 1))


async def _judge(sc: Scenario, text: str, delivered: list[str]) -> Score:
    # Default temperature on purpose: gemini-3 degrades below 1.0 (see SDK note), and
    # the samples are only worth averaging if they can differ.
    llm = ChatGoogleGenerativeAI(model=settings.GEMINI_MODEL_PRO, **settings.llm_auth)
    prompt = (
        f"{_RUBRIC}\n\nUSER SAID: {sc.user_text!r}\nSCENARIO NOTES: {sc.notes or 'none'}\n"
        f"ALREADY DELIVERED: {delivered or 'nothing'}\n\nREPLY TO GRADE:\n{text}"
    )
    return await _retry(lambda: llm.with_structured_output(Score).ainvoke(prompt), "judge")


# ── generators ─────────────────────────────────────────────────────────────────


async def _gen_composer(sc: Scenario) -> tuple[str, str, int, list[str]]:
    beats.clear()
    cache.clear()
    state = sc.build()
    budget = _max_chars(state, beats.peek(state))
    delivered = beats.recent_history(state)
    pool = json.dumps(state, default=str) + json.dumps([b.facts for b in beats.peek(state)], default=str)
    text, _ = await _compose(state, None, emit=False)
    return text, pool, budget, delivered


async def _gen_chatbot(sc: Scenario) -> tuple[str, str, None, list[str]]:
    from app.graph import nodes

    beats.clear()
    state = sc.build()
    pool = json.dumps(state, default=str)
    with patch.object(nodes, "get_stream_writer", return_value=lambda _event: None):
        out = await nodes.chatbot_node(state)
    return str(out["messages"][0].content), pool, None, beats.recent_history(state)


# The canned replies both voices emit when the model call itself failed. Grading
# one of these as a "reply" would score the quota, not the prose.
_INFRA_TEXT = ("I'm having trouble responding", "I hit a snag putting that together")


class _InfraFailure(Exception):
    pass


async def _generate(gen, sc: Scenario):
    async def call():
        out = await gen(sc)
        if out[0].startswith(_INFRA_TEXT):
            raise _InfraFailure(out[0])
        return out

    return await _retry(call, f"generate {sc.name}")


# ── run ────────────────────────────────────────────────────────────────────────

RESULTS: dict[str, dict[str, Any]] = {}


@pytest.mark.asyncio
@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.name)
async def test_scenario(sc: Scenario):
    gen = _gen_composer if sc.voice == "composer" else _gen_chatbot
    scores: dict[str, list[int]] = {c: [] for c in CRITERIA}
    violations: list[str] = []
    sample_text = ""
    for _ in range(SAMPLES):
        text, pool, budget, delivered = await _generate(gen, sc)
        sample_text = sample_text or text
        violations += hard_checks(sc, text, pool, budget)
        score = await _judge(sc, text, delivered)
        for c in CRITERIA:
            scores[c].append(getattr(score, c))
    RESULTS[sc.name] = {
        "voice": sc.voice,
        "mean": {c: round(statistics.mean(v), 2) for c, v in scores.items()},
        "violations": violations,
        "sample": sample_text,
    }
    assert not violations, f"{sc.name}: {violations}"


@pytest.mark.asyncio
async def test_zz_scoreboard():
    """Runs last (file order): prints the table and optionally dumps it as JSON."""
    if not RESULTS:
        pytest.skip("no scenario ran")
    print(f"\n{'scenario':30} {'voice':9} " + " ".join(f"{c[:9]:>9}" for c in CRITERIA) + "  viol")
    for name, r in RESULTS.items():
        print(f"{name:30} {r['voice']:9} " + " ".join(f"{r['mean'][c]:9.2f}" for c in CRITERIA)
              + f"  {len(r['violations'])}")
    for voice in ("composer", "chatbot"):
        rows = [r for r in RESULTS.values() if r["voice"] == voice]
        if rows:
            avg = {c: round(statistics.mean(r["mean"][c] for r in rows), 2) for c in CRITERIA}
            print(f"{'MEAN ' + voice:30} {'':9} " + " ".join(f"{avg[c]:9.2f}" for c in CRITERIA))
    print(f"infra failures retried (429 etc.): {INFRA_FAILURES}")
    if out := os.environ.get("EVAL_OUT"):
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(RESULTS, fh, indent=2, ensure_ascii=False)
