"""
Drafts a first-pass "expected" output per stage/example, chaining turns the
way the real conversation would (stage-2 expectation is drafted given the
user message AND stage-1's actual map output, etc., per Step 3 of the spec).

IMPORTANT: this is an AI-drafted reference, not ground truth. Every record
this module produces carries "source": "ai_drafted" and must be surfaced to
a human for confirmation before anyone treats it as a golden label. The
judge in judge.py compares actual-vs-this-draft, which measures internal
pipeline consistency, not correctness against a human-verified standard.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings

from tests.eval.config import JUDGE_MODEL, JUDGE_TEMPERATURE
from tests.eval.pipeline_runner import StageCapture
from tests.eval.rate_limit import RateLimiter

_DRAFT_LLM = ChatGoogleGenerativeAI(
    model=JUDGE_MODEL, google_api_key=settings.GOOGLE_API_KEY, temperature=0.3,
)

_DRAFT_PROMPT = """You are drafting a FIRST-PASS reference answer for an eval golden \
dataset. You are NOT the production system — you are proposing what a good \
outcome would look like, for a human to later confirm or correct.

User message: {user_message}

Stage being drafted: {stage}
Context from earlier stages (if any): {context}

Respond with ONLY a JSON object, no markdown fences:
{{
  "expected_summary": "1-3 sentence description of what a correct output would contain",
  "must_include": ["short factual anchors the real output should mention or respect"],
  "must_not_include": ["things that would indicate hallucination or drift, e.g. invented numbers/names/places not implied by the user message"]
}}
"""


@dataclass
class DraftedReference:
    example_id: str
    stage: str
    source: str = "ai_drafted"
    expected_summary: str = ""
    must_include: list[str] | None = None
    must_not_include: list[str] | None = None
    raw_error: str | None = None


async def _draft(example_id: str, stage: str, user_message: str, context: str, limiter: RateLimiter) -> DraftedReference:
    async with limiter:
        try:
            resp = await _DRAFT_LLM.ainvoke(
                _DRAFT_PROMPT.format(user_message=user_message, stage=stage, context=context or "(none)")
            )
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text)
            return DraftedReference(
                example_id=example_id, stage=stage,
                expected_summary=data.get("expected_summary", ""),
                must_include=data.get("must_include", []),
                must_not_include=data.get("must_not_include", []),
            )
        except Exception as exc:  # noqa: BLE001
            return DraftedReference(example_id=example_id, stage=stage, raw_error=f"{type(exc).__name__}: {exc}")


async def draft_all(example: dict, capture: StageCapture, limiter: RateLimiter) -> list[DraftedReference]:
    """Chains context forward: map stage uses only the user message; response
    stage is drafted knowing the actual map output; confirmation/builder
    stages are drafted knowing the actual response, mirroring how a real
    conversation's later stages depend on earlier ones."""
    user_message = example["content"]
    out: list[DraftedReference] = []

    map_ref = await _draft(example["id"], "map_extraction", user_message, "", limiter)
    out.append(map_ref)

    response_context = f"Map/routing output: {json.dumps(capture.map_output, default=str)}"
    response_ref = await _draft(example["id"], "response_generation", user_message, response_context, limiter)
    out.append(response_ref)

    if capture.confirmation is not None:
        confirm_context = f"Assistant response: {capture.response_text}"
        confirm_ref = await _draft(example["id"], "confirmation_state", user_message, confirm_context, limiter)
        out.append(confirm_ref)

    if capture.builder_action is not None:
        builder_context = f"Assistant response: {capture.response_text}"
        builder_ref = await _draft(example["id"], "builder_meta_config", user_message, builder_context, limiter)
        out.append(builder_ref)

    return out
