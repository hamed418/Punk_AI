"""
Central config for the eval harness — model names, rate limits, pricing.

Every price in PRICING_USD_PER_MTOK is marked verified=False until someone
confirms it against a live, dated pricing page. The report refuses to print
a dollar total built from an unverified price — see report.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    verified: bool
    source_note: str


# Pipeline models (from app/core/config.py, confirmed by prior audit).
PIPELINE_FLASH_MODEL = os.environ.get("EVAL_PIPELINE_FLASH_MODEL", "gemini-2.5-flash")
PIPELINE_PRO_MODEL = os.environ.get("EVAL_PIPELINE_PRO_MODEL", "gemini-2.5-pro")

# Judge model — same vendor as the pipeline per spec, configurable via env var.
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", PIPELINE_FLASH_MODEL)
JUDGE_TEMPERATURE = float(os.environ.get("EVAL_JUDGE_TEMPERATURE", "0.0"))

# Verified 2026-08-26 against https://ai.google.dev/gemini-api/docs/pricing
# (standard paid tier, <=200K token prompts — Pro is more expensive above that).
PRICING_USD_PER_MTOK: dict[str, ModelPrice] = {
    "gemini-2.5-flash": ModelPrice(0.30, 2.50, verified=True, source_note="ai.google.dev/gemini-api/docs/pricing, verified 2026-08-26"),
    "gemini-2.5-pro": ModelPrice(1.25, 10.00, verified=True, source_note="ai.google.dev/gemini-api/docs/pricing, verified 2026-08-26, <=200K token prompts"),
}

# Rate limiting — conservative defaults to avoid hitting production quota.
# Both the pipeline's own Gemini calls and the judge calls share this limiter
# family; separate env vars because judge calls are typically much cheaper.
PIPELINE_MAX_CONCURRENCY = int(os.environ.get("EVAL_PIPELINE_MAX_CONCURRENCY", "3"))
PIPELINE_MIN_INTERVAL_SEC = float(os.environ.get("EVAL_PIPELINE_MIN_INTERVAL_SEC", "0.5"))
JUDGE_MAX_CONCURRENCY = int(os.environ.get("EVAL_JUDGE_MAX_CONCURRENCY", "5"))
JUDGE_MIN_INTERVAL_SEC = float(os.environ.get("EVAL_JUDGE_MIN_INTERVAL_SEC", "0.2"))

# Namespace prefix for every eval-run thread_id / checkpoint_ns — never collides
# with real conversation threads, and MemorySaver means it's discarded on exit
# regardless.
EVAL_THREAD_PREFIX = "eval"

# Where sampled inputs / run artifacts land.
EVAL_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SAMPLE_INPUTS_PATH = os.path.join(EVAL_DATA_DIR, "sample_inputs.json")
RUNS_DIR = os.path.join(EVAL_DATA_DIR, "runs")
