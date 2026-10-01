"""
graph/narrator/grounding.py
───────────────────────────
Builds the :class:`GroundingPack` from live AgentState.

Supersedes ``wizard_helpers._session_summary``. The legacy helper produced a
single ``;``-joined string and truncated every list to 2–3 items, which meant
a narrator literally could not cite the 5th POI or the 4th location. This
builder keeps the full structured data; the composer decides what to surface
and the post-processor handles length.

Pure reads from state — no mutation, no IO, no LLM. Degrades gracefully: every
section is independently optional, so a cold-start state yields an (almost)
empty pack rather than raising.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Any

from app.graph.narrator import beats as _beats
from app.graph.narrator.types import GroundingPack


def _safe_get(state: Any, key: str) -> dict:
    try:
        return (state or {}).get(key) or {}
    except AttributeError:
        return {}


def _build_business(user_info: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if user_info.get("business_name"):
        out["name"] = user_info["business_name"]
    industry = user_info.get("industry") or user_info.get("business_description")
    if industry:
        out["industry"] = industry
    if user_info.get("business_description"):
        out["description"] = user_info["business_description"]
    if user_info.get("website_url"):
        out["website"] = user_info["website_url"]
    if user_info.get("product_offer"):
        out["offer"] = user_info["product_offer"]
    return out


def _build_audience(user_info: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if user_info.get("target_audience"):
        out["descriptor"] = user_info["target_audience"]
    age_min = user_info.get("target_age_min")
    age_max = user_info.get("target_age_max")
    if age_min and age_max:
        out["age_range"] = f"{age_min}-{age_max}"
    gender = user_info.get("target_gender")
    if gender and gender != "all":
        out["gender"] = gender
    loc = user_info.get("location")
    if loc:
        out["target_locations"] = loc if isinstance(loc, list) else [loc]
    return out


def _build_geo(geo_data: dict, ws_geo: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    method = geo_data.get("targeting_method") or ws_geo.get("targeting_method")
    if method:
        out["method"] = method
    det_type = geo_data.get("targeting_type") or ws_geo.get("deterministic_type")
    if det_type:
        out["targeting_type"] = det_type

    # Full location names — NOT truncated (the key fix vs _session_summary).
    locs = geo_data.get("locations") or []
    loc_names = [
        l.get("location_name") or l.get("formatted_address", "")
        for l in locs
    ]
    loc_names = [n for n in loc_names if n]
    if loc_names:
        out["locations"] = loc_names

    pois = geo_data.get("pois_found")
    if pois:
        out["poi_count"] = pois
    # `poi_types` is the union of every search term REQUESTED, found or not
    # (geo.py's collected_types.extend runs regardless of hit/miss) — keep a
    # term that matched zero venues out of it, or the composer reads it as a
    # confirmed target alongside the real ones (highlights.top_brands) and
    # narrates a not-found name as if it were an actual spot.
    not_found = geo_data.get("not_found_labels") or []
    poi_types = geo_data.get("poi_types") or (ws_geo.get("extra_inputs") or {}).get("poi_types_list")
    if poi_types:
        poi_types = [t for t in poi_types if t not in not_found]
    # A poi_selection trim (drop-by-category or a count cut) can empty a
    # category out of `targetable_pois` without ever touching `poi_types` —
    # that list is the union of every term SEARCHED, not what's still on the
    # map. Left unfiltered, the composer names a just-dropped category as if
    # a surviving spot were still one (e.g. "the best longevity clinic" for a
    # spot whose actual parent_poi_type is "IV therapy lounge"). Only applied
    # when `targetable_pois` is present — during discovery, before any POI is
    # materialized, `poi_types` alone still describes what's being searched.
    targetable = geo_data.get("targetable_pois")
    if poi_types and targetable is not None:
        survived = {p.get("parent_poi_type") for p in targetable if p.get("parent_poi_type")}
        poi_types = [t for t in poi_types if t in survived]
    if poi_types:
        out["poi_types"] = list(poi_types)
    if targetable:
        # `poi_count` is the TOTAL across categories. Without the split a composer
        # given "18" and one category name calls it "18 dog parks" (the map showed
        # 3 dog parks, 8 pet stores, 7 clinics).
        by_cat: dict[str, int] = {}
        for p in targetable:
            label = str(p.get("parent_poi_type") or "").strip()
            if label:
                by_cat[label] = by_cat.get(label, 0) + 1
        if by_cat:
            out["poi_counts_by_category"] = by_cat
    if not_found:
        out["not_found_labels"] = list(not_found)
    radius_km = geo_data.get("poi_radius_km")
    if radius_km:
        out["poi_radius_km"] = radius_km
    # Groups of spots with their own visit ring — so one ring is never quoted for
    # spots that were counted with another.
    if geo_data.get("poi_ring_overrides"):
        out["poi_ring_overrides"] = [
            {"spots": o["match"], "radius_m": o["radius_m"], "count": o["count"]}
            for o in geo_data["poi_ring_overrides"]
        ]
    search_radius = geo_data.get("search_radius_km")
    if search_radius:
        out["search_radius_km"] = search_radius
    return out


def _build_maid(geo_data: dict, ws_maid: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    maid_count = geo_data.get("maid_count")
    audience_filter = geo_data.get("audience_filter")
    # A `_derived` filter is a system default (executors/maid.py stamps
    # {"window_days": lookback_days, "_derived": True} when the user stated no
    # narrowing) — it still genuinely governs `filtered_count` below, but it is
    # NOT something the user chose, so it must not surface as `active_filter`
    # or trip the "your narrowing cut the audience" funnel explanation.
    _is_derived_filter = bool((audience_filter or {}).get("_derived"))
    filtered_count = geo_data.get("filtered_maid_count")
    if audience_filter and filtered_count is not None:
        # A narrowing filter ("3+ visits", "only weekends") is active — the
        # FILTERED number is the one that matters (it's what Meta will
        # actually target), so it's the one under "count", the key every
        # other turn's composer prompt looks at. `maid_count` (the raw
        # superset) stays available for lookup under its own key so a later
        # turn can still explain "narrowed from N" without EVER treating the
        # stale raw figure as the current one — which is exactly the bug this
        # branch fixes: without it, any turn whose own add_beat facts don't
        # carry the count (a no-op edit, a plain reject) fell back to this
        # pack and re-stated the pre-filter count as if the filter had never
        # happened.
        from app.services.maid_store import describe_audience_filter

        out["count"] = filtered_count
        out["count_before_filter"] = maid_count
        if not _is_derived_filter:
            out["active_filter"] = describe_audience_filter(audience_filter)
    elif maid_count is not None:
        out["count"] = maid_count
    conf = geo_data.get("maid_count_confidence")
    if conf:
        out["confidence"] = conf
    visit_stats = geo_data.get("maid_visit_stats")
    if visit_stats and visit_stats.get("repeat_visitor_count"):
        out["visit_stats"] = visit_stats
    # `audience_filter.window_days` (a stated recency narrowing) wins over the
    # separate "how far back to search" slot when both are live and differ —
    # it's the number actually enforced on `count` above, so it's the one a
    # later turn should quote back, not an unrelated search-depth default.
    _shown_lookback = (
        (audience_filter or {}).get("window_days")
        or ws_maid.get("lookback_days")
        or geo_data.get("lookback_days")
    )
    if _shown_lookback:
        out["lookback_days"] = _shown_lookback
    if ws_maid.get("poi_radius_m"):
        out["poi_radius_m"] = ws_maid["poi_radius_m"]
    if geo_data.get("maid_query_skipped"):
        out["skipped"] = True
    # A real, nonzero superset that the active audience_filter narrowed to
    # nobody — distinct from "no visitors at all" (out["count"] == 0 with no
    # filter). Lets a later turn's composer keep explaining the 0 rather
    # than silently re-stating it as the found audience. See executors/
    # maid.py's `geo["maid_filter_zeroed"]`.
    if filtered_count == 0 and maid_count:
        out["filter_zeroed"] = True
    # A NONZERO filter narrowed the audience by more than half, or an
    # intersection's co-located-geofence witness test rejected some devices —
    # both are legitimate but not obvious, and `maid_funnel` (executors/
    # maid.py) already carries the breakdown that explains them. Surfaced
    # only when there's something worth explaining, not on every result —
    # most prompts filter little enough that this would just be noise.
    _funnel = geo_data.get("maid_funnel") or {}
    if (
        audience_filter and not _is_derived_filter
        and filtered_count and maid_count and filtered_count < maid_count * 0.5
    ):
        out["funnel_dropped_pct"] = round((1 - filtered_count / maid_count) * 100)
        out["funnel_unconfirmed_pct"] = _funnel.get("unconfirmed_visit_pct")
        # `dwell_measurable_pct` is evidence QUALITY (share of visits with a
        # measurable stay), not an audience criterion — expose it under a name
        # that reads that way, and only when the active filter actually asked
        # for a dwell threshold (`min_dwell_min`). Otherwise a composer with no
        # other cue reads a key named "dwell" as a filter Punk applied and
        # invents a number for it (the "at least 10 minutes" bug).
        if audience_filter.get("min_dwell_min"):
            out["evidence_timed_visit_pct"] = _funnel.get("dwell_measurable_pct")
    _witness_raw = _funnel.get("intersection_raw") or 0
    _witness_after = _funnel.get("intersection_after_witness_test") or 0
    if _witness_raw and _witness_after < _witness_raw:
        out["funnel_witness_rejected"] = _witness_raw - _witness_after
    # Role-inference confidence — deliberately UNCONDITIONAL, unlike the
    # funnel_dropped_pct block above: that >50%-cut gate (plus the
    # min_dwell_min gate just above) is exactly why evidence_timed_visit_pct
    # is effectively never emitted today (most role-targeting prompts don't
    # cut the audience that hard, and few filters state a dwell minimum), and this
    # caveat matters precisely BECAUSE it's an inference, regardless of how
    # much the filter narrowed. Present only when a role predicate was
    # actually active (`_funnel.get("role_confidence")` is None otherwise —
    # see executors/maid.py's `is_role_spec` gate).
    if _funnel.get("role_confidence"):
        out["role_confidence"] = _funnel["role_confidence"]
        out["role_basis"] = _funnel.get("role_basis")
    # THE QUERY DID NOT RUN.
    #
    # Without this, a budget refusal, a saturated concurrency pool or a
    # non-allowlisted egress IP all reach the composer as `count == 0` and get
    # narrated as "zero devices were detected" — a confident, false statement
    # about the world made when we never asked the vendor anything. It is the
    # live-test report's open issue H, and it is the difference between "nobody
    # goes there" and "we couldn't look".
    #
    # `failed` gates it rather than the kind alone, so a composer that does not
    # know a particular kind still knows not to report an empty audience.
    failure_kind = geo_data.get("maid_failure_kind")
    if failure_kind:
        out["query_failed"] = True
        out["failure_kind"] = failure_kind
        out.pop("count", None)
        out.pop("count_before_filter", None)
        if failure_kind == "timeout":
            # Without this the composer offered "widen to 60 days" (thread
            # 77e403d3) — the one change guaranteed to make it slower. Nothing
            # is ever refused up front for predicted size any more (see
            # unacast_query.py) — this is the terminal case where even the
            # smallest possible request (one POI, one day) still times out.
            out["failure_note"] = (
                "The data provider timed out on some very busy spots even after "
                "splitting the request down as far as it goes. A shorter lookback, "
                "fewer or smaller rings, or simply retrying helps; a longer "
                "lookback makes it slower."
            )

    # SOME spots could not be pulled. The count stays — it is real for the spots
    # that landed — but a composer must not present it as covering all of them.
    partial = geo_data.get("maid_partial_failure")
    if partial and not failure_kind:
        out["partial_failure"] = partial

    # A filter that could not be EVALUATED (its history was never bought) is a
    # different thing again: the audience below is real, it just is not the one
    # that was asked for. See maid_store.AudienceFilterUnevaluable.
    if geo_data.get("maid_filter_unevaluable"):
        out["filter_unevaluable"] = geo_data["maid_filter_unevaluable"]
    return out


def _build_campaign(user_info: dict, marketing_plan: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if user_info.get("campaign_objective"):
        out["objective"] = user_info["campaign_objective"]
    if user_info.get("budget"):
        out["budget"] = user_info["budget"]
    if user_info.get("budget_type"):
        out["budget_type"] = user_info["budget_type"]
    if user_info.get("campaign_start_date"):
        out["start_date"] = user_info["campaign_start_date"]
    if user_info.get("campaign_end_date"):
        out["end_date"] = user_info["campaign_end_date"]
    if user_info.get("pixel_status"):
        out["pixel_status"] = user_info["pixel_status"]
    if isinstance(marketing_plan, dict) and marketing_plan.get("campaign_name"):
        out["plan_name"] = marketing_plan["campaign_name"]
    return out


def _build_media(user_info: dict, media_ws: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if media_ws.get("published"):
        out["published"] = True
    if user_info.get("meta_ad_account_id"):
        out["ad_account"] = user_info["meta_ad_account_id"]
    return out


def _build_highlights(geo_data: dict) -> dict[str, Any]:
    """Compute place-specific showcase signals from ``targetable_pois``.

    This is the data the old narrator threw away — the individual place names,
    the brand/category breakdown, the regions, the event names — that let the
    composer tell the user WHICH spots it's targeting and why. Each POI element
    (see state.POICoordinate) carries: ``name``, ``parent_poi_type`` (the
    category OR brand OR event query the POI was found under), ``brand`` (set
    only on the competitor-brand path), ``parent_location``, event dates, and
    ``rating``/``user_ratings_total`` (Places-derived POIs only — None/0 on
    event/web-fallback/store-set/map-pick POIs).

    Everything is bounded (top-N / first-N) so a 200-POI run stays scannable;
    the composer decides what to surface. Returns {} when no POIs exist yet.
    """
    pois = geo_data.get("targetable_pois") or []
    if not pois:
        return {}

    out: dict[str, Any] = {}

    # name → count, grouped by the most specific label available per POI.
    grouping = Counter()
    for p in pois:
        label = (p.get("brand") or p.get("parent_poi_type") or "").strip()
        if label:
            grouping[label] += 1
    if grouping:
        out["top_brands"] = [[name, n] for name, n in grouping.most_common(5)]

    sample = [str(p.get("name")).strip() for p in pois if p.get("name")]
    if sample:
        out["sample_places"] = sample[:5]

    by_region: "OrderedDict[str, list[str]]" = OrderedDict()
    for p in pois:
        region = (p.get("parent_location") or "").strip()
        name = (p.get("name") or "").strip()
        if region and name:
            by_region.setdefault(region, [])
            if len(by_region[region]) < 4:
                by_region[region].append(name)
    if len(by_region) > 1:  # only interesting when spots span multiple regions
        out["places_by_region"] = dict(list(by_region.items())[:5])

    events = []
    event_dates = []
    for p in pois:
        if p.get("event_start_date"):
            ev = (p.get("parent_poi_type") or p.get("name") or "").strip()
            if ev and ev not in events:
                events.append(ev)
                start = p.get("event_start_date")
                end = p.get("event_end_date")
                event_dates.append(f"{start} → {end}" if end and end != start else str(start))
    if events:
        out["event_names"] = events[:5]
        out["event_dates"] = event_dates[:5]

    rated = [p for p in pois if (p.get("user_ratings_total") or 0) > 0]
    if rated:
        # Same ranking a trim uses (lazy import, leaf-module convention same
        # as poi_selection's own geo.py imports) — if the composer says "the
        # best ones are X" and a "top N" kept Y, that's a contradiction the
        # user WILL notice. One definition of "best", two readers of it.
        from app.graph.builder.executors.poi_selection import _rank_key

        best = sorted(rated, key=_rank_key(pois), reverse=True)[:5]
        out["top_rated"] = [
            [p.get("name"), p.get("rating"), p.get("user_ratings_total")] for p in best
        ]
        # The composer's only licence to say "ranked by rating" for the WHOLE
        # set. On an event-heavy or web-fallback pool this reads e.g. [4, 47]
        # — 4 of 47 rated — and the composer must hedge, not claim the full
        # set was quality-ranked.
        out["rating_coverage"] = [len(rated), len(pois)]

    return out


def _build_open_questions(geo_data: dict, maid: dict) -> list[str]:
    gaps: list[str] = []
    if maid.get("count") == 0:
        gaps.append("no real-visitor data found for the chosen spots / window")
    if geo_data.get("targeting_method") == "deterministic" and not geo_data.get("pois_found"):
        gaps.append("no spots located yet")
    return gaps


def build_pack(state: Any, *, drain_changes: bool = True) -> GroundingPack:
    """Assemble a :class:`GroundingPack` from AgentState. Never raises on a
    partial / empty state.

    ``drain_changes=False`` leaves the turn's change ledger untouched — for a
    read-only caller (the chatbot) that must not consume what the narrator's
    flush is about to report.
    """
    try:
        user_info = _safe_get(state, "user_info")
        # Layered, not a bare read: `state["geo_data"]` is only refreshed when
        # builder_plan runs and pops `bs["_geo_recommit"]` — but the maid_confirm
        # widget re-fetches straight from `bs["geo_result"]` on EVERY pause (see
        # builder_node._maid_confirm_map_event), with no such gate. Any edit
        # applied inside wizard_interrupt's loop that re-asks the same gate
        # without a builder_plan round trip (the handoff lane, a no-op edit, a
        # plain reject) previously left the narrator quoting the pre-edit count
        # while the widget it sits next to already showed the new one.
        # `bs["geo_result"]` wins per-key — it's the live dict every maid/geo
        # edit path writes to — but a key it doesn't carry still falls back to
        # the committed mirror instead of vanishing.
        geo_data = {
            **_safe_get(state, "geo_data"),
            **(_safe_get(state, "campaign_builder_state").get("geo_result") or {}),
        }
        ws_geo = _safe_get(state, "geo_wizard_state")
        ws_maid = _safe_get(state, "maid_wizard_state")
        marketing_plan = (state or {}).get("marketing_plan")
        media_ws = _safe_get(state, "media_wizard_state")
    except AttributeError:
        return GroundingPack()

    maid = _build_maid(geo_data, ws_maid)

    # ``history`` — the user-facing lines already narrated this session, for
    # repetition suppression. Primary source is the process-local per-session
    # ring in ``narrator.beats`` (composer._compose appends each composed line);
    # fall back to the AgentState ``narrator_history`` ledger when the ring is
    # cold (cross-worker replay). Kept out of ``as_prompt_dict`` so it never
    # enters the replay-cache fingerprint.
    history = _beats.recent_history(state)
    if not history:
        try:
            history = list((state or {}).get("narrator_history") or [])
        except AttributeError:
            history = []

    return GroundingPack(
        business=_build_business(user_info),
        audience=_build_audience(user_info),
        geo=_build_geo(geo_data, ws_geo),
        maid=maid,
        campaign=_build_campaign(user_info, marketing_plan),
        media=_build_media(user_info, media_ws),
        highlights=_build_highlights(geo_data),
        history=history,
        user_turn=_build_user_turn(state),
        progress=_build_progress(state),
        open_questions=_build_open_questions(geo_data, maid),
        # Drained HERE, not peeked — same lifecycle as `_beats.drain(state)`
        # a few lines up the call stack in composer._compose (beats drained,
        # THEN build_pack called): both empty exactly once per turn, at flush.
        changes=_beats.drain_changes(state) if drain_changes else {},
    )


# Pipeline stages, in order, with a plain-words phase label for the soft
# progress cue. Kept local (not imported from builder.slots) to keep the
# narrator package free of a builder import cycle; the order is stable.
_STAGE_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("geo", "finding the spots your customers go"),
    ("maid", "building your real-visitor audience"),
    ("campaign", "drafting your campaign plan"),
    ("media", "getting your ads ready to publish"),
)


def _build_user_turn(state: Any) -> dict[str, Any]:
    """The per-turn read of the human's latest message (mood/phrase/etc.), set
    by entry_node or builder_ask. Empty when absent (cold start / no signal)."""
    try:
        ut = (state or {}).get("user_turn") or {}
    except AttributeError:
        return {}
    return {k: v for k, v in ut.items() if v not in (None, "", [])}


def _build_progress(state: Any) -> dict[str, Any]:
    """Soft orientation: 1-based index of the current stage in the build
    pipeline + a plain phase label. Empty outside the builder (no campaign
    builder state yet) so non-build screens carry no progress cue."""
    try:
        bs = (state or {}).get("campaign_builder_state") or {}
    except AttributeError:
        return {}
    if not bs:
        return {}
    done = set(bs.get("stages_complete") or [])
    total = len(_STAGE_SEQUENCE)
    for idx, (stage, label) in enumerate(_STAGE_SEQUENCE, start=1):
        if stage not in done:
            return {"index": idx, "total": total, "phase_label": label}
    return {"index": total, "total": total, "phase_label": "ready to publish"}


__all__ = ["build_pack"]
