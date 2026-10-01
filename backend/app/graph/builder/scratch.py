"""
app/graph/builder/scratch.py
────────────────────────────
Interrupt-durable scratch for ``builder_act``.

LangGraph discards a node's writes when ``interrupt()`` raises, so everything an
act cached before pausing is thrown away and re-fetched when the node replays on
resume. ``geo_discover`` can pause four times in one act (location
disambiguation × N ambiguous names, location confirm, named-place
disambiguation, store confirm), and each pause replays every lookup before it:
Nominatim/Places probes, geocodes, LLM tiebreaks, Places fan-out. For N
ambiguous names that is O(N²) network calls, throttled at ~1 req/s.

The caches themselves already exist on ``ws`` (``_loc_candidates``,
``_loc_picks``, ``_loc_tiebreak``, ``_geocoded_locations``, ``_named_resolved``,
``_geocoded_stores``, ``_all_pois_cache`` …) and are already invalidated by
content (``_loc_cache_key`` / ``_poi_cache_key`` / ``_prune_loc_scratch``). They were simply
unreachable across a pause — every docstring calling them "replay-safe" was
describing an intent the interrupt boundary silently broke. This parks them
in-process for exactly that window: saved when the act raises ``GraphInterrupt``,
popped when the same act replays.

Popping on load is what makes it safe. An entry lives only between one pause and
its resume, and nothing can mutate the builder state in that window — LangGraph
replays the same node from the same checkpoint (``builder_plan`` does not run in
between), and ``/chat`` refuses to stream over a live interrupt. An act that
completes, fails, or is never resumed leaves nothing behind, so a later run
always starts from the checkpoint.

ponytail: in-process dict, single uvicorn worker (see backend/Dockerfile CMD — no
``--workers``, the same assumption as app/modules/chat/runs.py). It is a pure
cache — a cross-worker miss or a deploy replays at today's cost, never a wrong
answer. Back it with Redis only if the deployment grows workers.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any

# Scratch dicts are small (geocode results, POI lists) and short-lived — one
# entry per concurrently-paused act.
_MAX_ENTRIES = 256

# key -> (inputs fingerprint, scratch)
_store: "OrderedDict[tuple[str, str], tuple[str, dict[str, dict]]]" = OrderedDict()


def act_stamp(filled: dict) -> str:
    """Fingerprint of the slots this act runs on.

    A pause the user never resumes leaves its entry parked until the next act
    with the same key pops it. That next act is normally the resume — same
    checkpoint, same ``filled`` — but it could equally be a fresh run in the same
    thread, whose scratch would then hold another run's geocodes and synced
    location list. Comparing the inputs separates the two: identical ``filled``
    means the parked scratch was built for exactly this work.
    """
    try:
        payload = repr(sorted((str(k), str(v)) for k, v in (filled or {}).items()))
    except Exception:
        return ""
    return hashlib.sha1(payload.encode("utf-8", "replace")).hexdigest()


def _key(config: Any, operation: str) -> tuple[str, str] | None:
    """``(thread_id, operation)``, or None when the thread is unknown.

    No thread means no safe key — two users mid-geo would share one entry — so
    the caller degrades to today's replay-everything behavior instead.
    """
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not thread_id or not operation:
        return None
    return (str(thread_id), str(operation))


def save_act_scratch(
    config: Any, operation: str, scratch: dict[str, dict], stamp: str = ""
) -> None:
    """Park an act's live scratch while it is paused on an interrupt.

    ``scratch`` maps the ``campaign_builder_state`` key (``"geo_ws"``,
    ``"maid_ws"``) to the working dict the act has been mutating — those are
    local copies, so ``bs`` alone does not carry them.
    """
    key = _key(config, operation)
    if key is None:
        return
    _store[key] = (
        stamp, {k: v for k, v in (scratch or {}).items() if isinstance(v, dict)}
    )
    _store.move_to_end(key)
    while len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)


def take_act_scratch(config: Any, operation: str, stamp: str = "") -> dict[str, dict]:
    """Pop the scratch parked by the pause this replay is resuming from.

    Popping (not peeking) bounds the entry to a single pause→resume window; see
    the module docstring.
    """
    key = _key(config, operation)
    if key is None:
        return {}
    parked = _store.pop(key, None)
    if not parked or parked[0] != stamp:
        return {}
    return parked[1]


def clear() -> None:
    """Test hook — drop every parked entry."""
    _store.clear()
