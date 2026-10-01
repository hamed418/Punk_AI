"""
Captures REAL token usage/cost from the pipeline's own instrumentation.

app/graph/usage.py already wraps every Gemini call in tracked_ainvoke /
tracked_astream, both returning (response, record) where record has
node/model/input_tokens/output_tokens/cost_usd pulled straight from the
provider's usage_metadata. Rather than re-deriving usage from node return
values (several nodes discard usage_metadata when rebuilding their own
AIMessage), this module monkeypatches those two functions at every import
site that holds its own reference to them, records every call, then
restores the originals. No guessing, no char-count estimates — only real
numbers from real API responses.
"""
from __future__ import annotations

import contextlib
import functools

from app.graph import usage as usage_mod

# Every module that did `from app.graph.usage import tracked_ainvoke, tracked_astream`
# holds its own name binding — patching app.graph.usage alone would miss them.
_PATCH_TARGETS = [
    "app.graph.nodes",
    "app.graph.campaign_manager_node",
    "app.graph.builder.builder_node",
]


class UsageCapture:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def _wrap(self, original):
        @functools.wraps(original)
        async def _wrapped(*args, **kwargs):
            response, record = await original(*args, **kwargs)
            self.records.append(dict(record))
            return response, record
        return _wrapped

    @contextlib.contextmanager
    def patched(self):
        import importlib

        originals: list[tuple[object, str, object]] = []
        wrapped_ainvoke = self._wrap(usage_mod.tracked_ainvoke)
        wrapped_astream = self._wrap(usage_mod.tracked_astream)

        for modname in _PATCH_TARGETS:
            try:
                mod = importlib.import_module(modname)
            except ImportError:
                continue
            if hasattr(mod, "tracked_ainvoke"):
                originals.append((mod, "tracked_ainvoke", mod.tracked_ainvoke))
                setattr(mod, "tracked_ainvoke", wrapped_ainvoke)
            if hasattr(mod, "tracked_astream"):
                originals.append((mod, "tracked_astream", mod.tracked_astream))
                setattr(mod, "tracked_astream", wrapped_astream)

        try:
            yield self
        finally:
            for mod, name, original in originals:
                setattr(mod, name, original)

    def totals_by_model(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for rec in self.records:
            model = rec.get("model", "unknown")
            bucket = out.setdefault(model, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
            bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
            bucket["output_tokens"] += int(rec.get("output_tokens", 0) or 0)
            bucket["calls"] += 1
        return out
