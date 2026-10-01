"""
graph/narrator/cache.py
───────────────────────
L1 in-process cache for narrator outputs.

LangGraph replays a node from START on every resume, so any LLM-backed
emission must be deterministic across replays or the checkpointed state
diverges. The legacy ``wizard_milestone_cache`` solved this for tier-2 only,
stored in AgentState. The narrator generalises it to every role.

Key design:
  • Key = ``(role, fact_fingerprint, session_fingerprint)``. Same role + same
    grounding facts + same session state → same string, no LLM call.
  • Bounded LRU (process-local). Cross-worker replays may regenerate; that is
    acceptable because the *content* is grounded in the same facts, so the
    text is equivalent even if not byte-identical.
  • The cached string is ALSO returned to the caller as a ``cache_update`` dict
    so it can be splatted into the node's state diff. That makes the entry
    survive the checkpoint round-trip and gives cross-worker determinism for
    the immediate next replay (the dominant replay case).

The state-merge half intentionally reuses the existing
``wizard_milestone_cache`` AgentState field + its ``_shallow_dict_merge``
reducer, so no new reducer / state key is needed and the migration is
transparent.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any, Optional


def _hash(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]


def stable_fingerprint(obj: Any) -> str:
    """Deterministic short hash for cache keys.

    Sorts keys + stringifies nondeterministic types so the fingerprint is
    invariant across dict iteration order and checkpoint round-trips.
    """
    try:
        norm = json.dumps(obj or {}, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        norm = repr(obj)
    return _hash(norm)


def cache_key(role: str, facts: dict, session_fp: str) -> str:
    """Compose the flat string key used in both the in-process LRU and the
    AgentState ``wizard_milestone_cache`` dict."""
    return f"{role}:{stable_fingerprint(facts)}:{session_fp}"


class _BoundedLRU:
    """Minimal stdlib LRU. O(1) get/set, capacity-bounded eviction.

    (Local copy rather than importing resume_router._BoundedLRU to keep the
    narrator package dependency-free at import time.)
    """

    __slots__ = ("_data", "_capacity")

    def __init__(self, capacity: int = 2048) -> None:
        self._data: "OrderedDict[str, str]" = OrderedDict()
        self._capacity = capacity

    def get(self, key: str) -> Optional[str]:
        try:
            value = self._data[key]
        except KeyError:
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: str) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


_CACHE = _BoundedLRU(2048)


def lookup(key: str, state: Any = None) -> Optional[str]:
    """Two-level read: in-process LRU first, then the AgentState-resident
    ``wizard_milestone_cache`` (survives worker restarts / cross-worker replay).
    """
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    if state is not None:
        try:
            persisted = (state.get("wizard_milestone_cache") or {}).get(key)
        except AttributeError:
            persisted = None
        if persisted is not None:
            _CACHE.set(key, persisted)
            return persisted
    return None


def store(key: str, value: str) -> dict[str, str]:
    """Write to the in-process LRU and return the state-merge fragment the
    caller splats into its node diff (persists into ``wizard_milestone_cache``).
    """
    _CACHE.set(key, value)
    return {key: value}


def evict_prefix(prefix: str) -> int:
    """Drop every in-process entry whose key starts with ``prefix``.

    Used by the edit lane (Phase 6) to bust stale ``step_frame`` / ``handoff``
    entries after a cited field (e.g. business_name) changes. Returns the count
    evicted. Note: only clears the process-local LRU; persisted AgentState
    entries are superseded on next write since the fact fingerprint changes.
    """
    victims = [k for k in list(_CACHE._data.keys()) if k.startswith(prefix)]
    for k in victims:
        del _CACHE._data[k]
    return len(victims)


def clear() -> None:
    """Test hook — empty the process-local cache."""
    _CACHE.clear()


__all__ = [
    "cache_key",
    "stable_fingerprint",
    "lookup",
    "store",
    "evict_prefix",
    "clear",
]
