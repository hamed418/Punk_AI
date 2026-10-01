"""
Batch judging — run only after ALL generation (Step 2) and ALL reference
drafting (Step 3) are complete for every example, per Step 4 of the spec.
Never interleaved with generation.

Judge model defaults to the same vendor as the pipeline (Gemini Flash,
temp 0), configurable via EVAL_JUDGE_MODEL / EVAL_JUDGE_TEMPERATURE env vars
(tests/eval/config.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings

from tests.eval.config import JUDGE_MODEL, JUDGE_TEMPERATURE
from tests.eval.rate_limit import RateLimiter

_JUDGE_LLM = ChatGoogleGenerativeAI(
    model=JUDGE_MODEL, google_api_key=settings.GOOGLE_API_KEY, temperature=JUDGE_TEMPERATURE,
)

# Step 5: the map stage gets its own rubric that explicitly forbids literal
# ID/field matching (maid_id, pixel_id, or any UI-verified identifier) and
# instructs semantic reasoning about intent-to-extraction fit instead.
_MAP_STAGE_RUBRIC = """You are judging the MAP/EXTRACTION stage of an ads-campaign \
assistant. The pipeline extracted structured fields (location, audience, \
industry, targeting angle, etc.) and/or routed the conversation, from the \
user's natural-language message.

Do NOT check ID values (maid_id, pixel_id, ad_account_id, or any other \
backend/UI-verified identifier) — an LLM judge cannot and should not attempt \
to validate those. Instead, reason semantically: given the user's stated \
intent (location, audience type, business context), do the extracted \
fields/places/audience plausibly correspond to what the user described? \
Explain your reasoning.

User message: {user_message}
Actual extracted/routed output: {actual}
AI-drafted reference (first-pass, NOT ground truth — use only as a rough \
guide to what was expected, weigh the user message more heavily if they conflict): {expected}

Respond with ONLY this JSON object, no markdown fences:
{{"pass": true or false, "reasoning": "string explaining the pass/fail decision", "stage": "map_extraction", "example_id": "{example_id}"}}
"""

_RESPONSE_STAGE_RUBRIC = """You are judging the RESPONSE GENERATION stage of an \
ads-campaign assistant chatbot. Score for faithfulness (no invented numbers, \
names, or claims not supported by the user message or extracted context), \
completeness (addresses what the user asked), and tone (matches a helpful, \
professional ads-assistant persona).

User message: {user_message}
Actual response: {actual}
AI-drafted reference (first-pass, NOT ground truth): {expected}

Respond with ONLY this JSON object, no markdown fences:
{{"pass": true or false, "reasoning": "string explaining the pass/fail decision", "stage": "response_generation", "example_id": "{example_id}"}}
"""

_STATE_STAGE_RUBRIC = """You are judging a CONFIRMATION/STATE-TRANSITION or \
META-CONFIG-PLANNING stage of an ads-campaign assistant. Judge only whether \
the state/action the pipeline produced is a reasonable, safe next step given \
the user's message — e.g. a write action should only be proposed (never \
silently executed) and should match what the user asked for; a planner \
action should move toward a plausible next step in the campaign-build flow.

User message: {user_message}
Actual stage output: {actual}
AI-drafted reference (first-pass, NOT ground truth): {expected}

Respond with ONLY this JSON object, no markdown fences:
{{"pass": true or false, "reasoning": "string explaining the pass/fail decision", "stage": "{stage_name}", "example_id": "{example_id}"}}
"""


@dataclass
class JudgeVerdict:
    example_id: str
    stage: str
    passed: bool | None
    reasoning: str
    raw_error: str | None = None


def _rubric_for(stage: str) -> str:
    if stage == "map_extraction":
        return _MAP_STAGE_RUBRIC
    if stage == "response_generation":
        return _RESPONSE_STAGE_RUBRIC
    return _STATE_STAGE_RUBRIC


async def judge_one(
    example_id: str, stage: str, user_message: str, actual: object, expected: object, limiter: RateLimiter,
) -> JudgeVerdict:
    template = _rubric_for(stage)
    prompt = template.format(
        user_message=user_message,
        actual=json.dumps(actual, default=str),
        expected=json.dumps(expected, default=str),
        example_id=example_id,
        stage_name=stage,
    )
    async with limiter:
        try:
            resp = await _JUDGE_LLM.ainvoke(prompt)
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text)
            return JudgeVerdict(
                example_id=example_id, stage=stage,
                passed=bool(data.get("pass")), reasoning=data.get("reasoning", ""),
            )
        except Exception as exc:  # noqa: BLE001
            return JudgeVerdict(
                example_id=example_id, stage=stage, passed=None, reasoning="",
                raw_error=f"{type(exc).__name__}: {exc}",
            )


async def judge_batch(
    judge_inputs: list[tuple[str, str, str, object, object]], limiter: RateLimiter,
) -> list[JudgeVerdict]:
    """judge_inputs: list of (example_id, stage, user_message, actual, expected).
    Fires all judge calls concurrently (bounded by limiter) — this is the
    single batch judging pass, run only after every example has completed
    generation + reference drafting."""
    import asyncio

    tasks = [
        judge_one(example_id, stage, user_message, actual, expected, limiter)
        for example_id, stage, user_message, actual, expected in judge_inputs
    ]
    return await asyncio.gather(*tasks)
