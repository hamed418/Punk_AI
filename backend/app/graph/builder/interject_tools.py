"""
graph/builder/interject_tools.py
──────────────────────────────────
Tools + orchestration for the resume-router's `handoff` lane — a mid-build
reply that is not a direct answer/reject/query/edit: process control ("do
the rest for me", "start over", "undo that"), advisory over what's already
found ("which of these are worth it", "is $500 enough"), and status ("what
have I got so far").

Deliberately NOT campaign_manager_node's shape. That module is a multi-turn
ReAct agent living in its own graph node, with its own interrupt/permission
gate for writes and its own iteration budget — built for POST-publish
analytics, where a session may need many turns across many possible actions.
`run_handoff_turn` here is ONE bounded tool-calling exchange (tool-select →
execute → compose an answer) that runs INSIDE wizard_interrupt's existing
loop and always ends by falling back to the caller re-rendering the SAME
widget — no new interrupt boundary, no separate permission gate. What IS
reused from campaign_manager_tools.py is the pattern: `@tool` definitions,
context injected via a ContextVar so it never appears in the LLM-visible tool
schema (there it's credentials; here it's which build we're operating on).
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.graph.tools import retrieve_marketing_knowledge
from app.graph.usage import tracked_ainvoke
from app.graph.wizard_exit import WizardExitRequested

logger = logging.getLogger(__name__)

# ── Context — which build this turn operates on ─────────────────────────────
# Same reasoning as campaign_manager_tools.py's credential contextvars: kept
# out of the tool schema so the model cannot pass (or hallucinate) it, and out
# of the tool-call log.
_ho_state: contextvars.ContextVar[Any] = contextvars.ContextVar("ho_state", default=None)
# The interrupt's `edits` accumulator in single-interrupt mode (write tools
# queue ops there — see `_queue`); None in legacy mode (they write directly).
_ho_edits: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("ho_edits", default=None)


def _bs() -> dict:
    """The live `campaign_builder_state` dict — mutable, the SAME reference
    `state` holds, never a copy. `.get(...) or {}` would be wrong here: it
    silently substitutes a throwaway dict whenever `campaign_builder_state`
    is PRESENT but happens to be empty (e.g. the very start of a build,
    before anything is filled) — exactly where undo()/delegate_rest() are
    likely to fire, and exactly where their writes would then vanish
    unnoticed. Only fall back to a throwaway dict when there is truly no
    state to read/write.
    """
    state = _ho_state.get()
    try:
        bs = (state or {}).get("campaign_builder_state")
    except AttributeError:
        return {}
    return bs if bs is not None else {}


# ── READ tools ────────────────────────────────────────────────────────────────

@tool
def get_build_state() -> dict:
    """What has been collected so far in THIS campaign build: every filled
    field, which stages are complete, and which build operations have
    already run. Call this for "what have I got so far" / "where am I" /
    any status or recap question about the build itself.
    """
    bs = _bs()
    return {
        "filled": dict(bs.get("filled") or {}),
        "stages_complete": list(bs.get("stages_complete") or []),
        "ops_done": list(bs.get("ops_done") or []),
    }


@tool
def get_pois(max_sample: int = 15) -> dict:
    """The spots (POIs) discovered so far for this build's geo targeting.
    Call this BEFORE answering any question about the discovered spots
    ("which of these are worth it", "are these any good", "what did you
    find") — never guess at the list from memory.

    `by_category` — count, rated-count, average rating, and (once the
    audience step has run) summed visitor count PER CATEGORY, via the same
    grouping the map tabs use. Prefer THIS over `sample` for "which category
    is worth it" / "compare the types" — it covers every POI, not just the
    top `max_sample`. WARNING: `audience` sums each POI's own device count,
    and a device inside two overlapping geofences counts in both — treat it
    as "visits at this category", never sum it across categories and call
    the result a unique-visitor total (use `get_audience`'s `total`/
    `filtered` for that).

    `sample` is up to `max_sample` named examples, BEST-RATED FIRST (raise
    `max_sample` if a question needs more than the default 15 — e.g. "list
    them all" over a small set). `rated` is how many of `total` carry a
    Google rating at all — event venues, web-fallback named places, and
    store-set points never do; when it's 0 or a small fraction of `total`,
    say so instead of claiming the whole set was quality-ranked.

    `distance_km` on each sample entry is measured from the build's own
    center/anchor point when one exists (`has_reference_point`); omitted
    (never guessed) when it doesn't — a build with no resolvable center
    cannot honestly answer "how far is the farthest one".
    """
    det = _bs().get("geo_result") or {}
    pois = det.get("targetable_pois") or []
    by_angle: dict[str, int] = {}
    for p in pois:
        angle = str(p.get("source_angle") or "unknown")
        by_angle[angle] = by_angle.get(angle, 0) + 1

    from app.graph.builder.builder_node import _poi_ref_point
    from app.graph.builder.executors.geo import _distance_km, poi_group_id
    from app.graph.builder.executors.poi_selection import _rank_key

    ref = _poi_ref_point(_bs())
    dist_fn = (lambda p: _distance_km(ref[0], ref[1], float(p["lat"]), float(p["lng"]))) if ref else None

    by_category: dict[str, dict] = {}
    for p in pois:
        gid = poi_group_id(p)
        c = by_category.setdefault(gid, {"count": 0, "rated": 0, "_rating_sum": 0.0, "audience": 0})
        c["count"] += 1
        if (p.get("user_ratings_total") or 0) > 0 and p.get("rating") is not None:
            c["rated"] += 1
            c["_rating_sum"] += float(p["rating"])
        if p.get("audience_count"):
            c["audience"] += int(p["audience_count"])
    for c in by_category.values():
        c["avg_rating"] = round(c.pop("_rating_sum") / c["rated"], 2) if c["rated"] else None

    sample = sorted(pois, key=_rank_key(pois), reverse=True)[:max(0, max_sample)]
    return {
        "total": len(pois),
        "rated": sum(1 for p in pois if (p.get("user_ratings_total") or 0) > 0),
        "by_angle": by_angle,
        "by_category": by_category,
        "has_reference_point": ref is not None,
        "sample": [
            {
                "name": p.get("name"), "type": p.get("parent_poi_type"),
                "angle": p.get("source_angle"), "area": p.get("parent_label"),
                "rating": p.get("rating"), "reviews": p.get("user_ratings_total") or 0,
                "audience": p.get("audience_count"),
                **({"distance_km": round(dist_fn(p), 2)} if dist_fn else {}),
            }
            for p in sample
        ],
    }


@tool
def get_audience() -> dict:
    """The real-visitor audience extracted so far. Call this for "is this
    audience good", "how big is it", "is that enough people", "is anyone a
    regular", "which category has the most visitors" — never guess these from
    memory, the numbers here are the only ones grounded in the actual
    extraction.

    `ran` is False before the audience step has even run — every other field
    is then a stub (0 / null / empty), and the caller should say "haven't
    pulled that yet" rather than report a zero as if it were a real count.
    `ran` is True but `query_failed` is also True right after a retry-gate
    query fails outright (budget/breaker/etc.) — `total`/`filtered` are
    stubbed to 0 here too, on purpose: `total` can otherwise be a STALE
    pre-edit number and `filtered` a meaningless fresh 0 from the failed
    attempt (see executors/maid.py's zero-or-keep-prior-nonzero guard). Say
    the query failed (`failure_kind`), never a number, when this is set.

    `total` is the TRUE unfiltered device count for the spots on screen;
    `filtered` is what the ACTIVE filter (`filter_chips` / `filter_raw`)
    narrows it to — these can genuinely differ now (they used to be mirrored
    to the same value, which made "how many did the filter cut" unanswerable
    from this tool; see the fix in executors/maid.py and builder_node.py).

    `visit_stats` is the sighting-frequency summary — repeat-visitor count/
    pct, the 1x/2x/3-5x/6+ buckets, total visits, the most-seen device. This
    is THE answer to "is this audience any good": a `repeat_visitor_pct` near
    0 means one-time passersby; a high one means regulars.

    `by_category` sums each POI's already-stamped `audience_count` by
    `poi_group_id` (no new query — attribution already stamped these) so
    "which category is actually worth it" is answerable without dumping the
    whole spot list. WARNING: a device inside two overlapping POI geofences
    counts toward EACH one, so a `by_category` value can exceed `total`/
    `filtered`, and the categories do NOT sum to either — never report a
    `by_category` figure, or a sum of them, as "the unique audience"; it only
    ever answers "which category has the most visits", not "how many people".
    """
    det = _bs().get("geo_result") or {}
    pois = det.get("targetable_pois") or []
    ran = det.get("maid_extraction_id") is not None
    if not ran:
        return {
            "ran": False, "total": 0, "filtered": 0,
            "filter_chips": [], "filter_raw": None,
            "visit_stats": {}, "by_category": {},
            "lookback_days": det.get("lookback_days"),
            "radius_km": det.get("poi_radius_km"),
        }

    # A total query failure (budget exhausted, breaker open, ...) leaves the
    # numbers unreliable in TWO different ways at once: executors/maid.py's
    # zero-or-keep-prior-nonzero guard never overwrites `maid_count` on a
    # total failure, so it can still be a STALE pre-edit value (e.g. from
    # before the radius/lookback change that triggered this retry), while
    # `filtered_maid_count` IS unconditionally overwritten to this failed
    # attempt's empty 0. Reporting either as "the audience" here is the same
    # false-acknowledgment narrator/grounding.py's `_build_maid` already
    # refuses to make for the user-facing reveal (it drops `count`/
    # `count_before_filter` and surfaces `query_failed`/`failure_kind`
    # instead) — this tool must refuse the same way, or the handoff-lane
    # compose LLM states a number that predates the very edit the user is
    # asking about.
    failure_kind = det.get("maid_failure_kind")
    if failure_kind:
        return {
            "ran": True, "total": 0, "filtered": 0,
            "query_failed": True, "failure_kind": failure_kind,
            "filter_chips": [], "filter_raw": None,
            "visit_stats": {}, "by_category": {},
            "lookback_days": det.get("lookback_days"),
            "radius_km": det.get("poi_radius_km"),
        }

    from app.graph.builder.executors.geo import poi_group_id
    from app.services.maid_store import describe_audience_filter

    by_category: dict[str, int] = {}
    for p in pois:
        cnt = p.get("audience_count")
        if cnt:
            gid = poi_group_id(p)
            by_category[gid] = by_category.get(gid, 0) + int(cnt)

    audience_filter = det.get("audience_filter")
    return {
        "ran": True,
        "total": det.get("maid_count") or 0,
        "filtered": det.get("filtered_maid_count") or 0,
        "filter_chips": describe_audience_filter(audience_filter),
        "filter_raw": audience_filter,
        "visit_stats": det.get("maid_visit_stats") or {},
        "by_category": by_category,
        "lookback_days": det.get("lookback_days"),
        "radius_km": det.get("poi_radius_km"),
    }


# retrieve_marketing_knowledge (graph/tools.py) is reused as-is — grounded
# Meta Ads / Punk knowledge, already an @tool, already the single source of
# truth for "is $500 enough" / general marketing questions. Not reimplemented.


# ── WRITE / process-control tools ───────────────────────────────────────────
# The undo stack itself (bs["_undo_stack"], bounded to
# edits._UNDO_STACK_MAX) is owned and pushed to by
# builder/edits.apply_pending_edits, right before it commits — see that
# module's docstring for why the commit point is the right place to snapshot
# from. This tool only pops.


def _queue(op: str, value: Any = True) -> bool:
    """Single-interrupt mode: park a write as a control op on the interrupt's
    `edits` instead of mutating state now. builder_plan runs it after this
    node returns — once, in the request that handled the reply, never again on
    a replay (the in-place writes re-ran every replay, Postgres ones included).
    Returns False in legacy mode, where the caller writes directly."""
    edits = _ho_edits.get()
    if edits is None:
        return False
    if op == "_poi_selection":
        edits[op] = [*(edits.get(op) or []), value]
    else:
        edits[op] = value
    return True


@tool
async def undo() -> str:
    """Reverts the LAST applied edit (a field change, a POI trim, an
    audience-filter change) — restores the build to how it was one edit ago.
    Call this ONLY for an explicit "undo that" / "put it back" / "never mind,
    undo" — not for a vague "that's wrong", which should be asked about
    first.
    """
    if not (_bs().get("_undo_stack") or []):
        return "nothing to undo — no edit has been applied yet this build"
    if _queue("_undo"):
        return "reverting the last edit now"
    text, _ui_restore = await perform_undo(_bs(), _ho_state.get())
    return text


async def perform_undo(bs: dict, state: Any) -> tuple[str, dict]:
    """Revert the top of ``bs["_undo_stack"]``. Called by the `undo` tool
    (legacy mode) and by builder_plan for a queued ``_undo`` op.

    Returns ``(message, user_info_restore)`` — the caller merges the patch into
    ``user_info`` (v2 snapshots only; see ``builder/edits.apply_edits``).
    """
    stack = bs.get("_undo_stack") or []
    if not stack:
        return "nothing to undo — no edit has been applied yet this build", {}
    snapshot = stack[-1]
    bs["_undo_stack"] = stack[:-1]
    bs["filled"] = dict(snapshot.get("filled") or {})
    ui_restore: dict = {}
    if snapshot.get("v") == 2:
        # Inverse edit: put the decisions back and invalidate the same unit the
        # edit invalidated, so everything derived from them is REBUILT. (v1
        # restored `ops_done`, claiming work whose outputs were already popped.)
        from app.graph.builder.edits import invalidate_from
        from app.graph.builder.executors.geo import restamp_search_rings

        ws = dict(bs.get("geo_ws") or {})
        for key, prev in (snapshot.get("geo_ws") or {}).items():
            if prev is None:
                ws.pop(key, None)
            else:
                ws[key] = prev
        restamp_search_rings(ws)
        bs["geo_ws"] = ws
        if snapshot.get("unit"):
            invalidate_from(bs, bs["filled"], snapshot["unit"])
        ui_restore = dict(snapshot.get("user_info") or {})
        if snapshot.get("plan") is not None:
            # A typed edit to the BUILT plan: put the previous plan back and
            # show it (the editor is the campaign stage's exit gate).
            from app.graph.builder.builder_node import _reopen_plan_editor

            bs["marketing_plan"] = snapshot["plan"]
            _reopen_plan_editor(bs, bs["filled"])
        # Plain replayable lists (no derived state to recompute here — the unit
        # above rebuilds whatever reads them).
        for key in ("_map_added_pois", "_poi_ring_specs"):
            if key in snapshot:
                bs[key] = list(snapshot[key] or [])
    else:
        bs["ops_done"] = list(snapshot.get("ops_done") or [])
    # Restore the POI-selection spec list too, or "reverts a POI trim" (above)
    # is a lie for the common case: a turn that only trims POIs pushes a
    # snapshot carrying this key (see builder_node._apply_geo_poi_selection_
    # edit / edits.apply_pending_edits), but until this line only `filled`/
    # `ops_done` came back, so the trimmed set stayed trimmed after "undo".
    # Restoring the spec LIST alone isn't enough — det["targetable_pois"] is
    # the actual displayed/committed result of folding those specs over the
    # superset (apply_specs), so it has to be recomputed from the restored
    # list, not left at the pre-undo (still-trimmed) value.
    if "_poi_selection_specs" in snapshot:
        restored_specs = list(snapshot.get("_poi_selection_specs") or [])
        bs["_poi_selection_specs"] = restored_specs
        det = bs.get("geo_result")
        from app.graph.builder.builder_node import _poi_superset

        superset = _poi_superset(bs, det)
        if isinstance(det, dict) and superset:
            from app.graph.builder.builder_node import _poi_ref_point
            from app.graph.builder.executors.poi_selection import apply_specs

            report = apply_specs(superset, restored_specs, ref_point=_poi_ref_point(bs))
            det["targetable_pois"] = report.kept
            det["pois_found"] = len(report.kept)
            bs["geo_result"] = det
            bs["_geo_recommit"] = True
            # The audience was already extracted before the trim being undone —
            # without this, undo() restores the POI count locally but leaves the
            # PERSISTED extraction (Postgres `pois`/observations, the map's tabs,
            # the MAID list Meta uploads) at the still-trimmed set. Same
            # delegation `_apply_geo_poi_selection_edit` uses on the forward
            # path (builder_node.py) — narrate=False, this tool speaks its own
            # return string.
            if det.get("maid_extraction_id"):
                from app.graph.builder.builder_node import _apply_maid_poi_edits

                await _apply_maid_poi_edits(
                    bs, state,
                    {"removed": report.dropped, "added": report.kept}, narrate=False,
                )
    # Same restore for the audience-filter history — the mirror gap
    # undo()'s own docstring used to claim was already closed and wasn't:
    # bs["_audience_filter_specs"] was never in the snapshot at all, so an
    # audience-filter edit could not actually be undone. Recompute (not just
    # restore the list) because the merged filter / filtered count / map are
    # all DERIVED from this history against the persisted extraction — same
    # reasoning as the POI restore just above, now needing a real DB round
    # trip (`_recompute_audience_filter`) since the observation superset
    # lives in Postgres, not local `bs` state — the reason this tool is
    # `async` now.
    if "_audience_filter_specs" in snapshot:
        restored_specs = list(snapshot.get("_audience_filter_specs") or [])
        bs["_audience_filter_specs"] = restored_specs
        det = bs.get("geo_result") or {}
        if det.get("maid_extraction_id"):
            from app.graph.builder.builder_node import _recompute_audience_filter

            await _recompute_audience_filter(bs, state, restored_specs)
    # A revert is a change like any other: without a ledger entry the narrator
    # had nothing true to say about it, and a `heard` left by the edit being
    # undone could still read as pending.
    from app.graph.narrator.beats import record_change

    record_change(state, applied={"__undo__": "reverted the last edit"})
    return "reverted the last edit", ui_restore


@tool
def list_changeable() -> dict:
    """What the user can change in this build right now, in plain words, and
    what they currently are. Call this for "what can I change?", "what are my
    options?", "what else can you adjust?" — answer ONLY from what it returns;
    never promise a change that isn't listed."""
    from app.graph.builder.knobs import KNOBS, current_values

    state = _ho_state.get()
    now = current_values(state)
    return {
        "changeable": [
            {"setting": k.name.replace("_", " "), "what_it_does": k.describe,
             **({"now": now[k.name]} if k.name in now else {})}
            for k in KNOBS.values()
        ],
        "not_changeable_here": "Meta ad account, Page and Pixel (they come from the Meta connection)",
    }


@tool
async def narrow_pois(spec: dict) -> str:
    """Narrow the spots ALREADY on screen — "just the top 10", "shortlist
    these", "drop everything in Laval", "top 5 of each category". Ranks by
    Google rating (review-count weighted) before cutting when ratings are
    available. Reversible: a later narrow_pois with a bigger `n` widens back
    out from the full discovered set, and undo() restores this one. `spec` is
    a JSON object using ONLY: op ("keep"|"drop", default "keep"), n (the count
    named — an unnumbered "shortlist these" / "just the best ones" names a
    count too, default n to 15), scope ("all"|"each" — "each" for "of each category"/"per type"),
    match (a named subset — "Laval", "Tim Hortons", "gym" — OR one specific
    POI by its own name, e.g. "Denver Animal Hospital"; write a category
    singular, "pet store" not "pet stores"), sort ({"by":
    rating|reviews|distance_km|name, "dir": "asc"|"desc"} — only when the
    user named a specific order, e.g. "closest first"), min_rating /
    max_rating (a star threshold), min_reviews (a review-count floor),
    max_distance_km (a distance ceiling from the build's center — reported
    unsupported when there's no center point yet), unsupported (a clause none
    of the other keys express — put it VERBATIM here, never approximate it).

    NOT the same tool as resume_router's `trim_pois` (a different module,
    different purpose — that one only classifies a reply's INTENT for the
    primary confirm-gate lane; this one actually executes mid-handoff). Kept
    a distinct name on purpose: `_handoff_tool_names()` (resume_router.py)
    matches by name alone to detect a handoff-triggering call, so a same-named
    tool here would make every "top 10" at the confirm gate misroute to the
    handoff lane instead of the edit lane.

    Call this only when the user asked to CHANGE the set — never to answer a
    question about it (that's get_pois).
    """
    bs = _bs()
    if not (bs.get("geo_result") or {}).get("targetable_pois"):
        return "no spots on record yet — nothing to trim"
    if _queue("_poi_selection", spec):
        # The trim runs in builder_plan, which narrates the real result.
        return "narrowing the spots on screen now"
    # Reuses the exact resolver the edit-lane uses (builder_node.py) — it
    # already folds bs["_poi_selection_specs"] from the discovery superset,
    # pushes the undo snapshot, and sets _geo_recommit. narrate=False: this
    # runs mid wizard_interrupt loop with no pause to flush an add_beat into,
    # so the return value IS the message — the handoff compose LLM speaks it
    # directly instead of a beat narrating it a second time next pause.
    from app.graph.builder.builder_node import _apply_geo_poi_selection_edit

    return await _apply_geo_poi_selection_edit(bs, _ho_state.get(), [spec], narrate=False)


@tool
def delegate_rest() -> str:
    """Hands the REST of this build's remaining optional questions to Punk's
    own defaults instead of asking one at a time. Call this for "just do the
    rest for me" / "you decide" / "finish it your way". Does not skip a
    required field that has no safe default, and the plan is still shown
    before anything publishes.
    """
    if not _queue("_delegate_rest"):
        _bs()["_auto_default_remaining"] = True
    return (
        "nothing publishes until the user approves the final plan — until "
        "then, the remaining optional details are filled in with sensible "
        "defaults. Do not describe this as ready to publish."
    )


@tool
def abort() -> str:
    """Stops the CURRENT build step-flow entirely (everything collected so
    far is kept). Call this ONLY for an explicit "stop"/"cancel this
    build"/"start over from scratch" — never for a single-field undo or a
    momentary pause.
    """
    # Not raised here — a tool executing mid tool-call batch is the wrong
    # place to unwind the interrupt loop (same reasoning `abort` gets special-
    # cased in run_handoff_turn: it is checked and raised by the ORCHESTRATOR,
    # after this turn's other tool calls — if any — have already run and been
    # narrated, exactly like the escape menu's "exit wizard" raises with no
    # narration of its own).
    return "__ABORT__"


# `HANDOFF_` prefix is load-bearing, not decoration: `campaign_manager_tools.py`
# ALSO defines `WRITE_TOOLS`/`ALL_TOOLS` (aliases of its `LEGACY_WRITE_TOOLS`),
# and THOSE names ARE gated — every tool in that set requires the user's
# explicit approval via campaign_manager_node's permission-gate round trip
# (a live budget/status/bid change on a REAL Meta account) before it executes.
# Nothing in THIS module's write set is gated at all, on purpose — see the
# module docstring: every tool here (undo/delegate_rest/abort/narrow_pois)
# is reversible/no-external-side-effect by construction, so no gate is the
# correct design, not a gap. Sharing a bare `WRITE_TOOLS` name across two
# modules with opposite protection invited exactly the wrong assumption —
# see MONEY BOUNDARY below.
HANDOFF_READ_TOOLS = [get_build_state, get_pois, get_audience, retrieve_marketing_knowledge, list_changeable]
HANDOFF_WRITE_TOOLS = [undo, delegate_rest, abort, narrow_pois]
HANDOFF_ALL_TOOLS = HANDOFF_READ_TOOLS + HANDOFF_WRITE_TOOLS

# ── MONEY BOUNDARY ───────────────────────────────────────────────────────────
# Stated once, here, because this module is the thing a "give the mid-build
# assistant more tools" instinct would most naturally reach for next. The
# ONLY operations in this entire codebase that move real money or start
# live ad spend are: `campaign_manager_tools.apply_budget_change` /
# `apply_status_change` / `apply_bid_adjustment` (gated behind
# campaign_manager_node's permission round trip — see that module), and
# activating a published-but-paused campaign (`media.activate_published_tree`,
# gated behind the `go_live_confirm` interrupt — see builder_node.py's
# `_OP_GATE`). Publishing itself is deliberately NOT gated — see
# builder_node.py's comment at the publish op — because publishing always
# creates campaign objects PAUSED; nothing spends until the go-live gate
# clears separately. No tool added to THIS module should ever be able to
# reach any of those four operations, directly or via a growing `spec`
# shape — if a future "let the handoff lane do more" change needs to touch
# budget/status/bid/activation, it belongs behind campaign_manager_node's
# gate, not here.


# ── Orchestration ────────────────────────────────────────────────────────────

_HANDOFF_SYSTEM_PROMPT = """You are PunkAI's mid-build assistant. The user is
partway through building a Meta Ads campaign and just said something that
isn't a direct answer to the question on screen — a status check, a request
about what's already been found, or an instruction to change how the build
proceeds (not what field to fill).

Call whichever tool(s) apply, using the RESULTS to ground your answer — never
invent a count, a spot name, or a fact you did not just read. Call NO tool
when the user's reply needs no tool to answer (rare — most of what reaches
you needs at least one read).

abort / undo / delegate_rest / narrow_pois are ACTIONS, not questions — call
them only when the user gave a real instruction to that effect, never
speculatively. "which of these are worth it" is get_pois (a read); "just
keep the best ones" is narrow_pois (a write) — the same words about ranking
can be either, so tell them apart by whether the user asked to SEE or to
CHANGE.
"""


def _make_handoff_llm() -> ChatGoogleGenerativeAI:
    # thinking_budget=0 on BOTH passes (tool-select is temp-0 routing, same
    # reasoning as resume_router's classifier; compose only restates tool
    # output that is already ranked/counted, so it needs no reasoning either).
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL, **settings.llm_auth,
        temperature=0.0, thinking_budget=0,
    )


_HANDOFF_TIMEOUT_S = 12.0

# Shown when a handoff turn crashed or timed out. Without it the user's reply
# vanished: the widget re-rendered with no acknowledgement at all.
_HANDOFF_FAILED_TEXT = (
    "I couldn't work that one out just now. Try rephrasing it, or answer the "
    "question on screen."
)


def _msg_text(msg: Any) -> str:
    """Text of an AIMessage — `.text` also flattens list-of-parts content."""
    text = getattr(msg, "text", None)
    if callable(text):  # older langchain-core exposed .text() as a method
        text = text()
    if not isinstance(text, str):
        text = msg.content if isinstance(getattr(msg, "content", None), str) else ""
    return text.strip()


class HandoffResult:
    """What one handoff turn produced. `text` is the grounded answer to
    narrate (None when no tool fired and nothing to say). `abort` is True
    when the model called the abort tool — the caller raises
    WizardExitRequested AFTER narrating `text`, if any, mirroring the escape
    menu's own "exit wizard" precedent of finishing the turn's own message
    (if it had one) before unwinding.
    """

    __slots__ = ("text", "abort")

    def __init__(self, text: Optional[str], abort: bool) -> None:
        self.text = text
        self.abort = abort


async def run_handoff_turn(
    raw: str, step_key: str, state: Any, edits: Optional[dict] = None,
) -> HandoffResult:
    """Select and run whichever interject_tools apply to `raw`, then compose
    a short grounded answer from the results. Two Gemini Flash calls at most
    (tool-select, then compose) — no chained tool calls in v1, since every
    tool here is a single independent read/action, not a multi-step plan.

    ``edits`` (single-interrupt mode): write tools queue control ops onto it
    instead of mutating state — see ``_queue``.
    """
    token = _ho_state.set(state)
    edits_token = _ho_edits.set(edits)
    try:
        llm = _make_handoff_llm().bind_tools(HANDOFF_ALL_TOOLS)
        import asyncio

        select_msg, _ = await asyncio.wait_for(
            tracked_ainvoke(
                llm,
                [
                    SystemMessage(content=_HANDOFF_SYSTEM_PROMPT),
                    HumanMessage(content=f"Active step: {step_key}\nUser said: {raw}"),
                ],
                node_name=f"resume_router/handoff/{step_key}",
                writer=None,
            ),
            timeout=_HANDOFF_TIMEOUT_S,
        )
        tool_calls = getattr(select_msg, "tool_calls", None) or []
        if not tool_calls:
            # The prompt tells the model to call NO tool when none is needed
            # ("what's a POI?") — its reply IS the answer, not something to drop.
            return HandoffResult(_msg_text(select_msg) or None, abort=False)

        did_abort = False
        tool_msgs: list[ToolMessage] = []
        by_name = {t.name: t for t in HANDOFF_ALL_TOOLS}
        for call in tool_calls:
            fn = by_name.get(call.get("name") if isinstance(call, dict) else call["name"])
            call_id = call.get("id") if isinstance(call, dict) else call["id"]
            call_args = call.get("args") if isinstance(call, dict) else call["args"]
            if fn is None:
                tool_msgs.append(ToolMessage(content="unknown tool", tool_call_id=call_id))
                continue
            try:
                result = await fn.ainvoke(call_args or {})
            except Exception as exc:
                logger.warning("handoff tool %s failed: %s", getattr(fn, "name", "?"), exc)
                result = f"tool error: {exc}"
            if fn is abort and result == "__ABORT__":
                did_abort = True
            tool_msgs.append(ToolMessage(content=str(result), tool_call_id=call_id))

        # abort ends the turn — no compose pass needed, nothing else the model
        # said matters once the build itself is stopping.
        if did_abort:
            return HandoffResult(None, abort=True)

        compose_msg, _ = await asyncio.wait_for(
            tracked_ainvoke(
                _make_handoff_llm(),
                [
                    SystemMessage(content=(
                        "Answer the user's message using ONLY the tool results below. "
                        "Two to four sentences, plain prose, no markdown headers. "
                        "Never invent a number or name not present in the tool output."
                    )),
                    HumanMessage(content=f"User said: {raw}"),
                    # The RAW select reply, not a rebuilt AIMessage: Gemini 3.x
                    # attaches a thought signature to the function call and
                    # gemini-3.5-flash-lite 400s when it is missing.
                    select_msg,
                    *tool_msgs,
                ],
                node_name=f"resume_router/handoff_compose/{step_key}",
                writer=None,
            ),
            timeout=_HANDOFF_TIMEOUT_S,
        )
        return HandoffResult(_msg_text(compose_msg) or None, abort=False)
    except Exception:
        logger.exception("run_handoff_turn failed")
        return HandoffResult(_HANDOFF_FAILED_TEXT, abort=False)
    finally:
        _ho_edits.reset(edits_token)
        _ho_state.reset(token)


__all__ = [
    "HANDOFF_READ_TOOLS", "HANDOFF_WRITE_TOOLS", "HANDOFF_ALL_TOOLS",
    "HandoffResult", "run_handoff_turn",
]
