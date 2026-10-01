"""
services/resume_preflight.py
────────────────────────────
Resume-time graph orchestration extracted from the ``POST /chat/{sid}/resume``
endpoint.

The HTTP handler used to host ~180 LOC of routing logic — resume-router
preflight classification, backtrack rewind via checkpoint history, locked-
wizard refusal with read-only summary re-emit, MAID map re-emit, and a
standalone ``extract_user_info_from_text`` call. That coupled the FastAPI
layer to LangGraph internals (StateSnapshot.tasks, pending_action shape,
checkpoint history, field-owner registry) and turned the endpoint into a
near-untestable monolith.

This module owns that orchestration. The endpoint shrinks to:

    1. Persist user message → DB.
    2. ``async for ev in run_resume_preflight(graph, config, value, writer): yield ev``
       — emits SSE events for backtrack / locked refusal / MAID map; sets a
       ``short_circuit`` flag when the resume should NOT enter the graph.
    3. If not short-circuited, ``graph.astream(Command(resume=value), ...)``.

Why a service module and not a graph entry node:
    LangGraph 1.x does not expose a hook to intercept ``Command(resume=...)``
    before the interrupted subgraph re-executes. A pre-resume node would
    consume the resume value at the wrong interrupt. So the preflight runs
    OUTSIDE the graph but is encapsulated here, not in the HTTP handler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from app.services.maid_store import fetch_maid_extraction

logger = logging.getLogger(__name__)


# Sentinel-style resume payloads that should NOT trigger a standalone
# intent-extraction LLM call. Mirrors the chat-side allowlist that existed
# before the extraction.
_INFO_EXTRACTION_SKIP_SENTINELS = frozenset({
    "yes", "no", "skip", "connected", "ok", "proceed", "continue",
})

# Wizard-internal user_info keys that ``extract_user_info_from_text`` does
# not know about. Preserve them on merge so wizard progress trackers do not
# silently reset.
_WIZARD_INTERNAL_KEYS = ("wizard_steps_done", "pixel_status", "_needs_custom_budget")


@dataclass
class PreflightOutcome:
    """Result of running the resume preflight pipeline."""

    short_circuit: bool = False
    """Retained for the caller's contract (chat.py reads it). Always False now —
    the backtrack / locked-refusal short-circuit lanes were removed; every resume
    flows through ``graph.astream(Command(resume=...))``."""

    sse_events: list[dict] = field(default_factory=list)
    """SSE-shaped payloads emitted during preflight. Caller forwards each
    via its own ``_sse`` formatter."""

    replay_boundary_skip: int = 0
    """How many replayed ``resume_boundary`` events the /resume stream should skip
    before forwarding live (= paused interrupt index + 1). 0 = no gating (fresh
    /chat, non-builder interrupts, or a checkpoint with no stamped index). See
    ``paused_interrupt_index`` and the gate in ``chat.py``."""


# ── Public entry points ──────────────────────────────────────────────────────


def paused_interrupt_index(snapshot: Any) -> Optional[int]:
    """Return the ``_interrupt_index`` stamped on the currently-paused interrupt, or
    ``None`` if absent.

    ``wizard_interrupt`` stamps ``len(scratchpad.resume)`` (this interrupt's position
    in its task) onto the interrupt value. On resume the node replays exactly
    ``index + 1`` interrupts that RETURN (emitting ``index + 1`` ``resume_boundary``
    events) before any new work, so the stream gate skips that many. Reads
    ``tasks[].interrupts[].value["_interrupt_index"]``, recursing into a subgraph
    task's ``.state`` (``campaign_builder`` is a compiled subgraph; the snapshot must
    be fetched with ``subgraphs=True``).
    """
    if not snapshot:
        return None

    def _from_tasks(snap: Any) -> Optional[int]:
        for task in (getattr(snap, "tasks", None) or ()):
            for intr in (getattr(task, "interrupts", None) or ()):
                val = getattr(intr, "value", None)
                if isinstance(val, dict) and isinstance(val.get("_interrupt_index"), int):
                    return val["_interrupt_index"]
            nested = getattr(task, "state", None)
            if nested is not None and not isinstance(nested, dict):
                idx = _from_tasks(nested)
                if idx is not None:
                    return idx
        return None

    return _from_tasks(snapshot)


_NO_INTERRUPT = object()


def _first_interrupt_value(snapshot: Any) -> Any:
    """Raw value of the first pending interrupt in the snapshot, or ``_NO_INTERRUPT``.

    Recurses into subgraph tasks (``tasks[].state``). ``campaign_builder`` is a
    compiled subgraph, so a builder interrupt surfaces only in
    ``tasks[].state.tasks[].interrupts`` — the parent-level ``tasks[].interrupts``
    is empty. The snapshot must be fetched with ``subgraphs=True`` for nested
    tasks to appear at all.
    """
    if not snapshot:
        return _NO_INTERRUPT

    def _walk(snap: Any) -> Any:
        for task in (getattr(snap, "tasks", None) or ()):
            for intr in (getattr(task, "interrupts", None) or ()):
                return getattr(intr, "value", None)
            nested = getattr(task, "state", None)
            if nested is not None and not isinstance(nested, dict):
                found = _walk(nested)
                if found is not _NO_INTERRUPT:
                    return found
        return _NO_INTERRUPT

    return _walk(snapshot)


def _has_pending_interrupt(snapshot: Any) -> bool:
    """True if any task in the snapshot carries a pending interrupt."""
    return _first_interrupt_value(snapshot) is not _NO_INTERRUPT


def pending_interrupt_value(snapshot: Any) -> Optional[dict]:
    """The active interrupt's ``pending_action`` payload, or ``None``.

    ``wizard_interrupt`` calls ``interrupt(_iv)`` where ``_iv`` IS the
    pending_action dict plus an ``_interrupt_index`` stamp (wizard_helpers.py),
    so the checkpoint is the authoritative record of what the UI should be
    showing — no need to scrape the last assistant message's ``langchain_data``.

    Returns ``None`` when nothing is paused, or when the paused interrupt's value
    is not a dict (nothing to render a widget from).
    """
    value = _first_interrupt_value(snapshot)
    if not isinstance(value, dict):
        return None
    return {k: v for k, v in value.items() if k != "_interrupt_index"}


async def maid_map_reemit_event(graph, config: dict, snapshot: Any = None) -> Optional[dict]:
    """If the active interrupt is ``maid_results_confirmation``, build the
    SSE map_data payload that restores the map for a reconnecting client.

    Returns ``None`` when no re-emit is needed. The caller wraps the dict
    in its own ``_sse(...)`` formatter.

    ``snapshot`` — an already-fetched ``StateSnapshot`` (from ``run_preflight``)
    reused to avoid a second ``aget_state`` checkpointer round-trip. Falls back to
    self-fetching when called standalone (``snapshot=None``). Safe to reuse a
    pre-``refresh_user_info`` snapshot: that refresh only writes ``user_info``,
    never ``pending_action`` / ``geo_data`` (the fields read here).
    """
    state = snapshot
    if state is None:
        try:
            state = await graph.aget_state(config)
        except Exception as exc:
            logger.warning("maid_map_reemit_event aget_state failed: %s", exc)
            return None
    if not state:
        return None
    pa = state.values.get("pending_action") or {}
    # Builder gate step_key is "maid_confirm_results" (slots.py / prompts_registry);
    # the old "maid_results_confirmation" was a stale wizard-era key that never
    # matched, so the reconnect re-emit silently no-op'd.
    if pa.get("step_key") != "maid_confirm_results":
        return None
    geo = state.values.get("geo_data") or {}
    extraction_id = geo.get("maid_extraction_id")
    if not extraction_id:
        return None
    try:
        extraction = await fetch_maid_extraction(str(extraction_id))
    except Exception as exc:
        logger.warning("maid_map_reemit_event fetch failed: %s", exc)
        return None
    if not extraction:
        return None
    # Routed through build_maid_split_view — the single source of truth for
    # this payload shape (see its own docstring) — instead of hand-rolling it
    # from the raw extraction. The hand-rolled version above used to ship the
    # UNFILTERED superset (pois/categories/dots/maid_count all straight off
    # `extraction`, with no `apply_audience_filter` pass) next to per-POI
    # `audience_count`/`visit_stats` that WERE already filtered (stamped by
    # the run that queried the warehouse) — so a page refresh while an
    # audience_filter was active jumped the headline back up to the raw
    # count, brought back every dot, and reset the category tabs, while the
    # per-POI numbers stayed narrowed. Same bug class as every other
    # count-desync path this pipeline had; this was the one emit site that
    # never got migrated when build_maid_split_view was introduced.
    from app.graph.maid_query import build_maid_split_view
    return {
        "type": "map_data",
        "content": build_maid_split_view(
            pois=extraction["pois"],
            observations=extraction["observations"],
            audience_filter=extraction.get("audience_filter"),
            center=extraction["center"],
            # Whole-audience frequency summary. Not on the extraction row — it
            # lives on the checkpoint, stamped when the warehouse was queried.
            visit_stats=geo.get("maid_visit_stats"),
            search_radius_km=extraction["search_radius_km"],
            lookback_days=extraction["lookback_days"],
            event_date_ranges=extraction["event_date_ranges"],
            stamp_stats=True,
            # Restore the editable map so a reconnecting client keeps POI removal.
            editable=True,
            # Role-inference disclosure — this IS the reload/reconnect path,
            # so this is what proves the caveat survives one, not just the
            # turn that first spoke it. Lives on checkpoint state, same as
            # maid_visit_stats above.
            role_confidence_tier=(geo.get("maid_funnel") or {}).get("role_confidence"),
            role_basis=(geo.get("maid_funnel") or {}).get("role_basis"),
        ),
    }


async def refresh_user_info_pre_resume(
    graph,
    config: dict,
    raw_value: str,
    snapshot: Any = None,
) -> None:
    """Run ``extract_user_info_from_text`` on a resume value when the user
    is NOT inside a wizard interrupt. Mutates checkpoint via
    ``graph.aupdate_state``.

    Skipped on sentinel widget payloads, JSON blobs, and numeric values
    (none of which carry standalone business info worth re-extracting).
    Skipped while a wizard interrupt is active — calling ``aupdate_state``
    without ``as_node`` while a subgraph interrupt is pending makes
    LangGraph restart the subgraph from START, consuming the resume value
    at the wrong interrupt.
    """
    if raw_value is None:
        return
    # Widgets wrap their answer as "Q: <prompt>\nA: <value>"; the skip checks
    # below were matching that wrapped string, which never hits any of them
    # ("Q: Is this correct?\nA: yes" is neither a bare sentinel nor JSON) — so
    # this function's own comment above ("skipped on sentinel widget payloads,
    # JSON blobs...") was aspirational. In practice only in_wizard_step, below,
    # was ever gating the extraction call. Unwrap first so the documented skips
    # actually skip.
    from app.graph.wizard_helpers import _unwrap_qa

    stripped = str(_unwrap_qa(raw_value)).strip()
    if not stripped:
        return
    lowered = stripped.lower()
    if lowered in _INFO_EXTRACTION_SKIP_SENTINELS:
        return
    if stripped.startswith(("{", "[")):
        return
    if stripped.replace(".", "", 1).replace("-", "", 1).isdigit():
        return

    try:
        from app.graph.nodes import extract_user_info_from_text

        # Reuse the snapshot fetched once by run_preflight; self-fetch only when
        # called standalone (snapshot=None) — saves a checkpointer round-trip.
        # subgraphs=True so a nested campaign_builder interrupt surfaces in
        # tasks[].state for the _has_pending_interrupt guard below.
        existing_state = (
            snapshot if snapshot is not None
            else await graph.aget_state(config, subgraphs=True)
        )
        existing_values = (existing_state.values if existing_state else {}) or {}
        existing_user_info = existing_values.get("user_info") or {}

        # An aupdate_state without ``as_node`` while a wizard interrupt is
        # pending restarts the interrupted SUBGRAPH from START and consumes the
        # resume value at the wrong interrupt (→ plan-review loop). Detect the
        # pending interrupt three ways — the first two are unreliable on the
        # builder path, so the recursive walk is the real guard:
        #   1. pending_action.step_key — but chat/service.py never persists it to
        #      state with the active step_key on the builder path, so it is None
        #      during a builder interrupt.
        #   2. parent-level tasks[].interrupts — empty for a SUBGRAPH interrupt,
        #      which nests in tasks[].state.tasks[].interrupts.
        #   3. _has_pending_interrupt — recurses into subgraph tasks, catching the
        #      builder interrupt the two above miss.
        pending = existing_values.get("pending_action") or {}
        in_wizard_step = (
            bool(pending.get("step_key"))
            or bool(
                existing_state
                and any(
                    getattr(task, "interrupts", ())
                    for task in (existing_state.tasks or ())
                )
            )
            or _has_pending_interrupt(existing_state)
        )
        if in_wizard_step:
            return

        # Give resume-path extraction the same last-AI-turn context the entry
        # node's extract arm gets, so reference answers ("yes", "the second one")
        # resolve. The checkpoint carries the message history.
        last_ai = None
        if existing_values.get("messages"):
            from app.graph.nodes import _extract_last_ai_text

            last_ai = _extract_last_ai_text(existing_values)

        merged = await extract_user_info_from_text(
            raw_value, existing_user_info, last_ai_response=last_ai
        )
        for k in _WIZARD_INTERNAL_KEYS:
            if k not in merged and k in existing_user_info:
                merged[k] = existing_user_info[k]
        if merged != existing_user_info:
            await graph.aupdate_state(config, {"user_info": merged})
    except Exception as exc:
        logger.warning("refresh_user_info_pre_resume failed", exc_info=exc)


async def run_preflight(
    graph,
    config: dict,
    raw_value: str,
) -> PreflightOutcome:
    """Run the resume preflight pipeline.

    Pipeline:
      1. Refresh ``user_info`` if the resume value is free-form text and
         the user is not inside a wizard interrupt.
      2. Re-emit MAID map data if the active interrupt is the MAID
         results-confirmation step (for reconnecting clients).

    The classifier-driven **edit / backtrack / locked-refusal** lanes were
    removed: on the builder-only path all collection runs in one re-entered
    ``builder_ask`` node, so a checkpoint rewind discarded the later ``filled``
    slots and the builder re-asked every step after the rewind point — a
    user-visible loop-back. Every resume now flows straight through
    ``graph.astream(Command(resume=...))`` (``short_circuit`` is always False).
    A future re-enable must gate backtrack on a validated step_key + confidence.
    """
    outcome = PreflightOutcome()

    # Fetch the checkpoint snapshot ONCE and share it across both preflight
    # steps (each used to call aget_state itself → two checkpointer round-trips per
    # resume). The user_info refresh only writes user_info, so the same
    # pre-refresh snapshot is still valid for the MAID map re-emit's
    # pending_action / geo_data reads.
    try:
        # subgraphs=True so nested campaign_builder interrupts surface in
        # tasks[].state for paused_interrupt_index() below.
        snapshot = await graph.aget_state(config, subgraphs=True)
    except Exception as exc:
        logger.warning("run_preflight aget_state failed: %s", exc)
        snapshot = None

    # Interrupt-replay stream gate: skip the paused interrupt's replayed boundaries
    # (index + 1) so the /resume stream forwards only the genuinely-new events.
    _idx = paused_interrupt_index(snapshot)
    outcome.replay_boundary_skip = _idx + 1 if _idx is not None else 0

    await refresh_user_info_pre_resume(graph, config, raw_value, snapshot=snapshot)

    map_event = await maid_map_reemit_event(graph, config, snapshot=snapshot)
    if map_event is not None:
        outcome.sse_events.append(map_event)

    # NOTE: no geo confirm_locations re-emit here. Unlike MAID (whose split-view is
    # stored out-of-band in maid_extractions), the geo confirm map rides the assistant
    # message's langchain_data and the frontend rehydrates it from chat history on
    # reconnect (ChatContext); the geo node also re-emits it on every resume replay.
    # A checkpoint-based re-emit would also be inert — the confirm interrupt fires
    # INSIDE builder_act before geo_ws is persisted, so the geocoded locations are not
    # in the checkpoint to rebuild from.

    return outcome


__all__ = [
    "PreflightOutcome",
    "pending_interrupt_value",
    "maid_map_reemit_event",
    "paused_interrupt_index",
    "refresh_user_info_pre_resume",
    "run_preflight",
]
