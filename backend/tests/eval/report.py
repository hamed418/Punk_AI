"""Aggregate report: per-example/per-stage pass-fail, pass rates by stage and
flow, sorted failure list, wall-clock time, real token usage, and a cost
table that refuses to fabricate a number for an unverified price."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from tests.eval.config import PRICING_USD_PER_MTOK
from tests.eval.judge import JudgeVerdict
from tests.eval.pipeline_runner import StageCapture
from tests.eval.usage_capture import UsageCapture


@dataclass
class RunReport:
    started_at: float
    finished_at: float
    n_examples: int
    per_example: list[dict] = field(default_factory=list)
    pass_rate_by_stage: dict[str, float] = field(default_factory=dict)
    pass_rate_by_flow: dict[str, float] = field(default_factory=dict)
    failures_by_stage: dict[str, list[dict]] = field(default_factory=dict)
    wall_clock_sec: float = 0.0
    token_usage_by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    cost_table: dict[str, dict] = field(default_factory=dict)
    cost_total_usd: float | None = None
    flags: list[str] = field(default_factory=list)


def build_report(
    captures: list[StageCapture],
    verdicts: list[JudgeVerdict],
    usage: UsageCapture,
    started_at: float,
    flow_by_example: dict[str, str],
    flags: list[str],
    user_message_by_example: dict[str, str] | None = None,
    judge_inputs: list[tuple[str, str, str, object, object]] | None = None,
) -> RunReport:
    """user_message_by_example / judge_inputs are optional so older callers
    still work, but passing them makes the persisted JSON self-contained:
    every verdict carries the prompt text, the actual pipeline output, and
    the AI-drafted expected output it was judged against — not just the
    judge's prose reasoning. Without them, per_example verdicts have
    reasoning only (as in earlier report versions)."""
    finished_at = time.monotonic()
    report = RunReport(started_at=started_at, finished_at=finished_at, n_examples=len(captures))
    report.wall_clock_sec = round(finished_at - started_at, 2)
    report.flags = list(flags)

    actual_expected: dict[tuple[str, str], dict] = {}
    if judge_inputs:
        for example_id, stage, _user_message, actual, expected in judge_inputs:
            actual_expected[(example_id, stage)] = {"actual": actual, "expected": expected}

    verdicts_by_example: dict[str, list[JudgeVerdict]] = {}
    for v in verdicts:
        verdicts_by_example.setdefault(v.example_id, []).append(v)

    stage_totals: dict[str, list[bool]] = {}
    flow_totals: dict[str, list[bool]] = {}
    failures: dict[str, list[dict]] = {}

    for cap in captures:
        example_verdicts = verdicts_by_example.get(cap.example_id, [])
        flow = flow_by_example.get(cap.example_id, "unknown")
        verdict_dicts = []
        for v in example_verdicts:
            vd = asdict(v)
            vd.update(actual_expected.get((v.example_id, v.stage), {"actual": None, "expected": None}))
            verdict_dicts.append(vd)
        example_record = {
            "example_id": cap.example_id,
            "flow": flow,
            "route": cap.route,
            "user_message": (user_message_by_example or {}).get(cap.example_id),
            "errors": cap.errors,
            "mocked_write_attempts": cap.mocked_write_attempts,
            "verdicts": verdict_dicts,
        }
        report.per_example.append(example_record)

        for v in example_verdicts:
            if v.passed is None:
                continue  # judge call itself errored — not a pass/fail signal
            stage_totals.setdefault(v.stage, []).append(v.passed)
            flow_totals.setdefault(flow, []).append(v.passed)
            if not v.passed:
                failures.setdefault(v.stage, []).append({
                    "example_id": v.example_id, "flow": flow, "reasoning": v.reasoning,
                })

    report.pass_rate_by_stage = {
        stage: round(sum(vals) / len(vals), 3) for stage, vals in stage_totals.items() if vals
    }
    report.pass_rate_by_flow = {
        flow: round(sum(vals) / len(vals), 3) for flow, vals in flow_totals.items() if vals
    }
    report.failures_by_stage = failures

    report.token_usage_by_model = usage.totals_by_model()

    for model, tok in report.token_usage_by_model.items():
        if tok["calls"] > 0 and (tok["input_tokens"] == 0 or tok["output_tokens"] == 0):
            report.flags.append(
                f"{model}: {tok['calls']} call(s) recorded but input_tokens="
                f"{tok['input_tokens']}/output_tokens={tok['output_tokens']} — usage_metadata may not be "
                "populated for this call path (e.g. streaming/thinking calls via tracked_astream can report "
                "differently than tracked_ainvoke). Treat this model's token count as unreliable until verified."
            )

    all_verified = True
    total_cost = 0.0
    for model, tok in report.token_usage_by_model.items():
        price = PRICING_USD_PER_MTOK.get(model)
        if price is None or not price.verified:
            report.cost_table[model] = {
                "input_tokens": tok["input_tokens"],
                "output_tokens": tok["output_tokens"],
                "calls": tok["calls"],
                "cost_usd": None,
                "note": "UNVERIFIED PRICE — not counted in total. " + (price.source_note if price else "no price on file"),
            }
            all_verified = False
            continue
        cost = (tok["input_tokens"] / 1_000_000) * price.input_per_mtok + (
            tok["output_tokens"] / 1_000_000
        ) * price.output_per_mtok
        report.cost_table[model] = {
            "input_tokens": tok["input_tokens"], "output_tokens": tok["output_tokens"],
            "calls": tok["calls"], "cost_usd": round(cost, 6),
        }
        total_cost += cost

    report.cost_total_usd = round(total_cost, 6) if all_verified and report.token_usage_by_model else None
    if not all_verified:
        report.flags.append(
            "Cost total is NOT computed because one or more models used in this run have "
            "no verified price on file (see tests/eval/config.py PRICING_USD_PER_MTOK). "
            "Real token counts ARE reported per model above — plug in a verified "
            "$/MTok price to get a real dollar total."
        )

    return report


def to_json(report: RunReport) -> str:
    return json.dumps(asdict(report), indent=2, default=str)


def print_summary(report: RunReport) -> None:
    print(f"\n=== Eval run summary ({report.n_examples} examples, {report.wall_clock_sec}s wall-clock) ===")
    print("\nPass rate by stage:")
    for stage, rate in report.pass_rate_by_stage.items():
        print(f"  {stage}: {rate:.0%}")
    print("\nPass rate by flow:")
    for flow, rate in report.pass_rate_by_flow.items():
        print(f"  {flow}: {rate:.0%}")
    print("\nFailures by stage:")
    for stage, fails in report.failures_by_stage.items():
        print(f"  {stage}: {len(fails)} failure(s)")
        for f in fails:
            print(f"    - [{f['example_id']}] ({f['flow']}) {f['reasoning'][:160]}")
    print("\nToken usage / cost:")
    for model, row in report.cost_table.items():
        cost_str = f"${row['cost_usd']}" if row.get("cost_usd") is not None else "UNVERIFIED — see note"
        print(f"  {model}: in={row['input_tokens']} out={row['output_tokens']} calls={row['calls']} cost={cost_str}")
    print(f"\nTotal cost: {'$' + str(report.cost_total_usd) if report.cost_total_usd is not None else 'NOT COMPUTED (unverified pricing)'}")
    if report.flags:
        print("\nFlags:")
        for f in report.flags:
            print(f"  - {f}")
