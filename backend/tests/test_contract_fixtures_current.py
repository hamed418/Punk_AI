"""
The committed frontend contract fixtures still describe the live payload.

``frontend/contracts/campaign_plan_form/*.json`` is what a frontend developer
writes against. Nothing checked it against the code, and it drifted: every one of
the eleven fixtures shipped ``"action_type": "campaign_plan_form"`` while the
graph emits ``campaign_plan_editor`` (``prompts_registry.STEP_PROMPTS``), so a
client that matched on action_type never saw the form at all. Regenerating fixed
that once; this test is what stops it happening again.

Regenerate with::

    .venv/Scripts/python.exe scripts/dump_plan_form_contract.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_DIR = _ROOT.parent / "frontend" / "contracts" / "campaign_plan_form"

_SPEC = importlib.util.spec_from_file_location(
    "dump_plan_form_contract", _ROOT / "scripts" / "dump_plan_form_contract.py"
)
dump = importlib.util.module_from_spec(_SPEC)
sys.modules["dump_plan_form_contract"] = dump
_SPEC.loader.exec_module(dump)

pytestmark = pytest.mark.skipif(
    not _CONTRACT_DIR.is_dir(),
    reason="frontend/ is not checked out beside backend/",
)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory) -> dict[str, dict]:
    """Every fixture the dump script would write right now."""
    out = tmp_path_factory.mktemp("contracts")
    dump.OUT_DIR = out
    dump.main()
    return {
        p.name: json.loads(p.read_text(encoding="utf-8")) for p in out.glob("*.json")
    }


def test_the_dump_script_still_runs(regenerated):
    """It reaches into builder internals (``_plan_form_extra``, ``build_intake_schema``)
    and is not exercised anywhere else, so it rots silently."""
    assert regenerated, "the dump script wrote nothing"


def test_no_committed_fixture_is_stale(regenerated):
    committed = {
        p.name: json.loads(p.read_text(encoding="utf-8"))
        for p in _CONTRACT_DIR.glob("*.json")
    }
    stale = sorted(
        name for name, payload in committed.items()
        if name in regenerated and regenerated[name] != payload
    )
    assert not stale, (
        f"contract fixtures no longer match what the code emits: {stale} — "
        "re-run scripts/dump_plan_form_contract.py"
    )
    missing = sorted(set(regenerated) - set(committed))
    assert not missing, f"the dump script writes fixtures nobody committed: {missing}"


def test_every_plan_fixture_carries_the_live_action_type(regenerated):
    """The exact drift that shipped. Asserted on its own so the failure names the
    field rather than dumping a whole JSON diff."""
    from app.graph.prompts_registry import STEP_PROMPTS

    live = STEP_PROMPTS["campaign_plan_confirm"]["action_type"]
    for name, payload in regenerated.items():
        if not name.startswith("pending_action.") or name.endswith(".intake.json"):
            continue
        assert payload["content"]["action_type"] == live, name
