"""Rewind a builder step by RESTORING its state, not by forking its checkpoint.

Why not fork: forking the inner checkpoint a step was stamped with and replaying it
does not re-ask that step. The parent graph still carries the last ``Command(resume=…)``
as a null-task resume write, and the first ``interrupt()`` of the replay swallows it —
so the step is answered with the WRONG (most recent) value and the run walks past it.
Reproduced on the pinned langgraph in ``tests/test_undo_rewind.py``.

What works: write the anchor's state onto the thread head as if the ``entry`` node had
just produced it. That is a new parent checkpoint, so ``campaign_builder`` starts fresh
(new task, new namespace, no stale resume), replans from the restored builder scratch
and re-arms exactly the step the user pointed at. The conversation resumes from that
point — at the cost of the re-run's tokens.

What is deliberately NOT rewound: accounting (token / cost / api-call counters, the
tool-call log) — that money was spent and stays recorded — and the append-only narrator
caches, which the caller resets separately.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from langchain_core.messages import RemoveMessage

from app.graph.state import AgentState

ENTRY_NODE = "entry"

# Written on every restore: the entry conditional edge routes on `next_nodes`, and the
# discarded turn's unbilled carry must not be billed onto the next completed turn.
_RESTORE_FORCED: dict[str, Any] = {"next_nodes": ["campaign_builder"], "pending_usage": None}

# Dict-merge reducers whose merge can't delete a key — cleared first so a key learned
# AFTER the anchor can't survive the restore.
_CLEAR_FIRST = ("user_info", "geo_data")


def reducer_fields(schema: Any = AgentState) -> frozenset[str]:
    """State keys that carry a reducer (``Annotated[..., fn]``). Derived from the
    schema, not listed by hand, so a newly added reducer field can't drift."""
    out: set[str] = set()
    for key, hint in typing.get_type_hints(schema, include_extras=True).items():
        if typing.get_origin(hint) is typing.Annotated and any(callable(m) for m in hint.__metadata__):
            out.add(key)
    return frozenset(out)


def restore_updates(
    anchor: Mapping[str, Any],
    head: Mapping[str, Any],
    *,
    schema: Any = AgentState,
    clear_first: tuple[str, ...] = _CLEAR_FIRST,
    forced: Optional[Mapping[str, Any]] = None,
) -> list[dict]:
    """The state writes (in order) that make the thread head look like ``anchor``.

    1. Explicit clear of the merge-reducer fields.
    2. Every non-reducer key from the anchor, the cleared fields' anchor values,
       the forced routing keys, and the message diff (head-only messages removed,
       anchor-only messages re-added; shared ids are left alone).

    Reducer fields other than ``clear_first`` and ``messages`` are skipped on purpose
    (see module docstring).
    """
    forced = _RESTORE_FORCED if forced is None else forced
    reducers = reducer_fields(schema)
    known = set(typing.get_type_hints(schema, include_extras=True))

    restore: dict[str, Any] = {
        k: v for k, v in anchor.items() if k in known and k not in reducers
    }
    for key in clear_first:
        if anchor.get(key) is not None:
            restore[key] = anchor[key]
    restore.update(forced)

    if "messages" in known:
        anchor_msgs = list(anchor.get("messages") or [])
        head_msgs = list(head.get("messages") or [])
        anchor_ids = {m.id for m in anchor_msgs if getattr(m, "id", None)}
        head_ids = {m.id for m in head_msgs if getattr(m, "id", None)}
        stale = [RemoveMessage(id=i) for i in _ordered(head_msgs) if i not in anchor_ids]
        missing = [m for m in anchor_msgs if getattr(m, "id", None) and m.id not in head_ids]
        if stale or missing:
            restore["messages"] = [*missing, *stale]

    # Clear only where the head holds keys the anchor doesn't — the common case has
    # none, and then the restore is ONE atomic write instead of two.
    clear = {
        k: None for k in clear_first
        if k in known and _leaks(head.get(k), anchor.get(k))
    }
    return ([clear] if clear else []) + [restore]


def _leaks(head_val: Any, anchor_val: Any) -> bool:
    """Would merging ``anchor_val`` over ``head_val`` leave a stale key behind?"""
    if not isinstance(head_val, dict) or not head_val:
        return False
    if not isinstance(anchor_val, dict):
        return True
    return bool(set(head_val) - set(anchor_val))


def _ordered(messages: list) -> list[str]:
    return [m.id for m in messages if getattr(m, "id", None)]


async def restore_from_anchor(
    graph: Any,
    config: dict,
    anchor_values: Mapping[str, Any],
    **restore_kwargs: Any,
) -> None:
    """Apply :func:`restore_updates` to the thread head, each as the ``entry`` node.

    ``config`` is the bare thread config (no checkpoint id / namespace) — the writes
    must land on the LATEST parent checkpoint so the pending builder task is replaced.
    ``restore_kwargs`` (schema / clear_first / forced) exist for tests on toy graphs.
    """
    head = await graph.aget_state(config)
    head_values = dict(head.values) if head is not None and head.values else {}
    updates = restore_updates(anchor_values, head_values, **restore_kwargs)
    cleared: dict[str, Any] = {}
    try:
        for i, update in enumerate(updates):
            await graph.aupdate_state(config, update, as_node=ENTRY_NODE)
            if i == 0 and len(updates) > 1:
                cleared = {k: head_values.get(k) for k in update}
    except Exception:
        # The clear landed but the restore did not: put the cleared fields back so a
        # failed rewind leaves the thread as it found it.
        if cleared:
            restored = {k: v for k, v in cleared.items() if v is not None}
            if restored:
                try:
                    await graph.aupdate_state(config, restored, as_node=ENTRY_NODE)
                except Exception:  # noqa: BLE001 - best effort; the original error wins
                    pass
        raise


GROUP_REFUSAL = (
    "That earlier answer can't be changed here — later steps of this stage were "
    "built on it. Use the plan editor, or start a new campaign."
)


@dataclass(frozen=True)
class RewindPlan:
    mode: str                       # "restart" (restore + fresh builder) | "fork" (checkpoint fork)
    refusal: Optional[str] = None   # user-facing reason when the rewind can't be honoured


def plan_rewind(
    *,
    anchor_ns: str,
    anchor_id: Any,
    group_ids: Sequence[Any],
    restart_enabled: bool = True,
) -> RewindPlan:
    """How to honour a rewind to the assistant row ``anchor_id`` — pure, for tests.

    A builder step (non-empty checkpoint namespace) is restored and restarted; a pause
    in the parent graph (``""``) can still be forked, because there the pending writes
    are keyed to the same checkpoint id.

    Rows sharing one stamp (several interrupts inside one node run, legacy
    ``BUILDER_SINGLE_INTERRUPT=false`` builds) cannot be told apart by the stamp:
    a restart re-arms the node's FIRST interrupt, a fork its SECOND. The row the user
    pointed at must be that one, or the answer would land on the wrong question.
    """
    mode = "restart" if restart_enabled and anchor_ns else "fork"
    if len(group_ids) > 1:
        reachable = group_ids[0] if mode == "restart" else group_ids[1]
        if reachable != anchor_id:
            return RewindPlan(mode, GROUP_REFUSAL)
    return RewindPlan(mode)


def with_question_text(events: Sequence[dict], question_text: str) -> list[dict]:
    """The replay's events, plus the question's stored text if the replay has none.

    A restart re-arms a step from saved state, where the narrator has nothing buffered
    (its beats were added by the work that PRECEDED the question), so the re-ask arrives
    as a widget with no words above it. The text goes just before the widget, where the
    narrator's own message would have been. Errors are dropped: they already went out
    live. A replay that carries its own message is left untouched.
    """
    out = [e for e in events if e.get("type") != "error"]
    if question_text and not any(e.get("type") == "assistant_message" for e in out):
        at = next(
            (i for i, e in enumerate(out) if e.get("type") in ("input_mode", "pending_action")),
            len(out),
        )
        out.insert(at, {"type": "assistant_message", "content": question_text})
    return out
