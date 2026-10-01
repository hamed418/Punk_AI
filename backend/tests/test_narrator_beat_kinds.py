"""Static guard: every literal beat `kind` passed to `add_beat` across
app/graph must be a key of `BEAT_HINTS` (narrator/prompts/composer.py).

A kind missing from BEAT_HINTS is not an error anywhere — `beat_hint_block`
silently drops it and the composer gets that beat with zero guidance on how
to weave it (see builder_node.py's old `"step_reframe"` bug, which is what
this test would have caught). Regex over the source, not an import + call,
because the whole point is to catch a typo before it ever reaches a beat
buffer.
"""
import re
from pathlib import Path

from app.graph.narrator.prompts.composer import BEAT_HINTS

_GRAPH_DIR = Path(__file__).resolve().parents[1] / "app" / "graph"
_CALL_RE = re.compile(r'add_beat\(\s*(?:\n\s*)?state,\s*"([a-z_]+)"')


def _literal_kinds_used() -> set[tuple[str, str]]:
    """(kind, file) for every add_beat(state, "literal_kind", ...) call site."""
    found: set[tuple[str, str]] = set()
    for path in _GRAPH_DIR.rglob("*.py"):
        if path.name in ("beats.py",):  # def add_beat / dynamic `kind` param
            continue
        text = path.read_text(encoding="utf-8")
        for m in _CALL_RE.finditer(text):
            found.add((m.group(1), str(path.relative_to(_GRAPH_DIR))))
    return found


def test_every_add_beat_kind_is_a_known_beat_hint():
    used = _literal_kinds_used()
    assert used, "regex found no add_beat call sites — it likely stopped matching the code shape"
    unknown = {(kind, f) for kind, f in used if kind not in BEAT_HINTS}
    assert not unknown, (
        f"add_beat used with a kind absent from BEAT_HINTS (silently dropped "
        f"from the composer prompt): {sorted(unknown)}"
    )
