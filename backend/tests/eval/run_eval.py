#!/usr/bin/env python
"""
One-command entry point for the PunkAI pipeline eval harness.

    cd backend && python -m tests.eval.run_eval [--input-file PATH] [--out PATH]

Default input file is tests/eval/data/sample_inputs.json — SYNTHETIC
placeholder examples, because DB-backed sampling (tests/eval/sampling.py)
is currently gated on a read-only Postgres role (`eval_readonly`) that does
not yet exist in the production DB, per the eval's hard safety constraints.
Run `python -m tests.eval.sampling` separately once that role exists to
regenerate data/sample_inputs.json from real (PII-scrubbed) production data.

Pipeline order (per spec — no interleaving):
  Step 2: run every example through the real pipeline stages (mocked writes)
  Step 3: draft AI reference outputs, chained turn-by-turn
  Step 4: batch-judge everything at once
  Step 6: aggregate + print + write report JSON
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.eval.config import (  # noqa: E402
    JUDGE_MAX_CONCURRENCY, JUDGE_MIN_INTERVAL_SEC,
    PIPELINE_MAX_CONCURRENCY, PIPELINE_MIN_INTERVAL_SEC,
    RUNS_DIR, SAMPLE_INPUTS_PATH,
)
from tests.eval.judge import judge_batch  # noqa: E402
from tests.eval.pipeline_runner import run_one  # noqa: E402
from tests.eval.rate_limit import RateLimiter  # noqa: E402
from tests.eval.reference_drafter import draft_all  # noqa: E402
from tests.eval.report import build_report, print_summary, to_json  # noqa: E402
from tests.eval.usage_capture import UsageCapture  # noqa: E402


def _check_google_api_key() -> None:
    from app.core.config import settings
    if not settings.GOOGLE_API_KEY:
        print("[BLOCKED] GOOGLE_API_KEY is not set — cannot call the real Gemini pipeline or judge.", file=sys.stderr)
        sys.exit(1)


async def _run(input_file: str, out_path: str) -> None:
    _check_google_api_key()

    with open(input_file) as f:
        examples = json.load(f)

    is_synthetic = input_file == SAMPLE_INPUTS_PATH
    flags: list[str] = []
    if is_synthetic:
        flags.append(
            f"Ran against {len(examples)} SYNTHETIC placeholder examples "
            f"({SAMPLE_INPUTS_PATH}), NOT real production data — DB sampling is "
            "gated on the eval_readonly role (see tests/eval/sampling.py)."
        )
    flags.append(
        "builder_ask / real Meta publish execution are NOT exercised by this "
        "harness — only builder_plan's single-turn planner decision is captured "
        "(see pipeline_runner.py module docstring, point 4)."
    )
    flags.append(
        "Each stage runs inside its own minimal single-node LangGraph graph "
        "(MemorySaver, no interrupts) rather than the full production graph, "
        "so builder_ask's interrupt()/Command(resume=...) loop is not driven "
        "end-to-end — state reducers themselves are real (see pipeline_runner.py, point 2)."
    )

    pipeline_limiter = RateLimiter(PIPELINE_MAX_CONCURRENCY, PIPELINE_MIN_INTERVAL_SEC)
    judge_limiter = RateLimiter(JUDGE_MAX_CONCURRENCY, JUDGE_MIN_INTERVAL_SEC)

    started_at = time.monotonic()
    usage = UsageCapture()

    # Step 2 — generation, ALL examples, before any judging.
    captures = []
    with usage.patched():
        async def _guarded_run_one(ex):
            async with pipeline_limiter:
                return await run_one(ex)

        captures = await asyncio.gather(*[_guarded_run_one(ex) for ex in examples])

        # Step 3 — reference drafting, chained per example, ALL examples before judging.
        draft_lists = await asyncio.gather(
            *[draft_all(ex, cap, pipeline_limiter) for ex, cap in zip(examples, captures)]
        )

    # Step 4 — single batch judge pass over every (example, stage) pair.
    judge_inputs: list[tuple[str, str, str, object, object]] = []
    flow_by_example: dict[str, str] = {}
    for ex, cap, drafts in zip(examples, captures, draft_lists):
        flow_by_example[ex["id"]] = ex.get("checkpoint_ns_prefix", "unknown")
        drafts_by_stage = {d.stage: d for d in drafts}

        map_draft = drafts_by_stage.get("map_extraction")
        judge_inputs.append((ex["id"], "map_extraction", ex["content"], cap.map_output, _draft_dict(map_draft)))

        resp_draft = drafts_by_stage.get("response_generation")
        judge_inputs.append((ex["id"], "response_generation", ex["content"], cap.response_text, _draft_dict(resp_draft)))

        if cap.confirmation is not None:
            c_draft = drafts_by_stage.get("confirmation_state")
            judge_inputs.append((ex["id"], "confirmation_state", ex["content"], cap.confirmation, _draft_dict(c_draft)))

        if cap.builder_action is not None:
            b_draft = drafts_by_stage.get("builder_meta_config")
            judge_inputs.append((ex["id"], "builder_meta_config", ex["content"], cap.builder_action, _draft_dict(b_draft)))

    verdicts = await judge_batch(judge_inputs, judge_limiter)

    user_message_by_example = {ex["id"]: ex["content"] for ex in examples}

    # Step 6 — aggregate.
    report = build_report(
        captures, verdicts, usage, started_at, flow_by_example, flags,
        user_message_by_example=user_message_by_example, judge_inputs=judge_inputs,
    )
    print_summary(report)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(to_json(report))
    print(f"\nFull report written to {out_path}")


def _draft_dict(draft) -> dict | None:
    if draft is None:
        return None
    from dataclasses import asdict
    return asdict(draft)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PunkAI pipeline eval harness.")
    parser.add_argument("--input-file", default=SAMPLE_INPUTS_PATH)
    parser.add_argument("--out", default=os.path.join(RUNS_DIR, f"run_{int(time.time())}.json"))
    args = parser.parse_args()
    asyncio.run(_run(args.input_file, args.out))


if __name__ == "__main__":
    main()
