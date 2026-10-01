"""
graph/builder/executors/poi_selection.py
─────────────────────────────────────────
NL-driven POI curation ("just the top 10", "drop everything in Laval",
"top 5 of each category", "gyms rated above 4, closest 5") applied against
the already-discovered POI superset. Pure, no I/O, no LLM — a tier-1 OVERLAY
(see builder/edits.py's module docstring for the invalidate-vs-overlay
distinction): it only ever narrows a set Places has already returned. It
never re-searches Places and the caller (builder_node._apply_geo_poi_
selection_edit) never calls invalidate_from for it.

Two layers:

  legacy regex parser (``parse_trim_instruction`` / ``resolve_drop_predicate``
  / ``allocate_top_n``) — the original "one regex per phrasing" resolver.
  Kept, tested, and still the fallback ``normalize_spec`` runs a bare string
  through — a stale cache entry or Backend B's tool schema handing back a
  plain string must still resolve to SOMETHING.

  selection spec (``normalize_spec`` / ``apply_specs``) — the classifier now
  emits a small typed dict instead of the raw phrase (same shape family as
  ``audience_filter``'s JSON patch, generalized). "top 5 of each category"
  parsed to a REGEX MATCH on "top 5" and silently dropped "of each category"
  — the qualifier was never wrong, the parser just had no field to put it in.
  The spec has one: ``scope``. Rating/review/distance thresholds and an
  explicit sort order are the SAME idea one layer further: "keep the best
  rated ones", "closest 5" used to have no field either — they had a rating
  already sitting on every POI (paid for, unused) and a distance computable
  from lat/lng for free, but no key to ask for either. `sort` / `min_rating`
  / `max_rating` / `min_reviews` / `max_distance_km` are those keys. Every
  other qualifier a key can't express ("cut it in half", "5 per city") still
  lands in ``unsupported`` instead of being silently approximated — see
  ``normalize_spec``'s docstring.

The allocator (which POIs survive a "top N") and the scorer (which order they
rank in within one bucket) are deliberately separate concerns:

  allocator — bucket-quota via the EXISTING `_round_robin_by` (geo.py), keyed
              by (source_angle, parent_poi_type, parent_label) so a trim never
              silently wipes an entire arm, market, or searched type. Only
              applied when the caller did NOT name an explicit `sort` — an
              explicit order is a stronger, more specific signal than Punk's
              own market-fairness default, so it suspends the interleave (see
              `_select`'s docstring).
  scorer    — local only, over fields already on the POI: exact place-type
              match, then a Bayesian review-weighted rating (`_rank_key`),
              then arrival order as the final tiebreak — UNLESS `sort` names
              an explicit key (rating / reviews / distance_km / name), in
              which case that key drives the order directly and type-match
              primacy is suspended too, for the same reason. Rating rides the
              EXISTING Text Search fieldmask (tools.py) — one SKU tier bump
              (+9%), no second call, no new API surface. Distance rides the
              lat/lng every POI already carries plus the build's own center/
              anchor point (`geo._det_center`) — also free. No MAID density
              probe, no Place Details fetch (~11x the cost per POI vs. the
              fieldmask bump), no LLM ranker — each considered and cut (cost /
              latency / nondeterminism) rather than built speculatively.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# Arms the user asked for BY NAME. Trimming these would delete an explicit
# instruction, so a "top N" quota only ever applies to the DISCOVERED arms
# below — named arms always pass a trim through untouched UNLESS the spec
# names them explicitly via `match` (see apply_specs: `protect` is only True
# when there is no `match`/numeric filter narrowing the pool first).
_DISCOVERED_ANGLES: frozenset[str] = frozenset({"category", "ai_suggested"})

TrimMode = Literal["top_n", "drop", "unknown"]

_TOP_N_RE = re.compile(
    r"\b(?:top|first|just|only|keep|cap(?:\s+it)?\s+at|"
    r"limit(?:\s+it)?\s+to|show\s+me)\s+(\d{1,3})\b",
    re.IGNORECASE,
)

# Anywhere-in-text (not anchored, unlike _LEAD_IN_RE below which strips a
# leading verb phrase off an already-classified drop instruction) — used only
# to decide WHETHER this reads as a removal request at all.
_DROP_VERB_RE = re.compile(
    r"\b(?:drop|remove|delete|exclude|cut|take\s+out)\b", re.IGNORECASE,
)

# Bare "shortlist"/"best"/"top rated" with NO number — the classifier prompt
# (resume_router.py) is the live path for this phrasing and emits a spec
# directly; this regex is only the legacy-string fallback's equivalent, kept
# for the same back-compat reason _TOP_N_RE/_EACH_RE are (a stale cache entry,
# a pre-migration tool schema). Checked AFTER _TOP_N_RE (an explicit number
# always wins) and AFTER _DROP_VERB_RE (so "drop ... keep the best" still
# reads as a removal, not a keep-the-best-N request).
_SHORTLIST_RE = re.compile(
    r"\b(?:shortlist|short\s+list|best|top[- ]rated|highest[- ]rated)\b",
    re.IGNORECASE,
)
_SHORTLIST_DEFAULT_N = 15  # ponytail: flat default, not derived from pool size
                           # or "how many are on screen". Make it adaptive
                           # only if users keep correcting it.

# "of each category" / "each category" / "per category" / "per type" / "per
# group" — the qualifier the plain top-N regex above has always discarded.
# Legacy-string back-compat only (a stale cache entry, or Backend B's
# `trim_pois(instruction: str)` schema before it's flipped to the spec) —
# the classifier's new spec prompt sets `scope` directly, no regex involved.
_EACH_RE = re.compile(r"\b(?:of\s+)?each\b|\bper\s+(?:category|type|group)\b", re.IGNORECASE)


def parse_trim_instruction(text: str) -> tuple[TrimMode, int | None]:
    """("top_n", N) when the instruction names a count ("just the top 10",
    "keep 5", "limit it to 20"); also ("top_n", `_SHORTLIST_DEFAULT_N`) for a
    bare "shortlist"/"best"/"top rated" with NO number named. ("drop", None)
    for a named-removal predicate ("drop everything in Laval", "remove the Tim
    Hortons ones"), resolved by `resolve_drop_predicate` instead; ("unknown",
    None) when the text matches neither shape.

    Previously any non-count instruction fell through to ("drop", None)
    unconditionally — "suggest me some POIs" was silently read as "remove the
    spots named 'suggest me some pois'", matched nothing, and reported a false
    success ack ("Updating your spot selection now.") for an instruction this
    module never understood. Failing open like that is worse than reporting
    "unknown": the caller can now tell the user it didn't understand, instead
    of pretending it acted.
    """
    m = _TOP_N_RE.search(text or "")
    if m:
        n = int(m.group(1))
        if n > 0:
            return "top_n", n
    if _DROP_VERB_RE.search(text or ""):
        return "drop", None
    if _SHORTLIST_RE.search(text or ""):
        return "top_n", _SHORTLIST_DEFAULT_N
    return "unknown", None


def _bucket_key(poi: dict) -> tuple[str, str, str]:
    """One bucket = one Places response: an (angle, searched type, market)
    triple. Buckets are never compared against each other — only interleaved —
    so relevance across differing bboxes/queries is never a real comparison."""
    return (
        str(poi.get("source_angle") or ""),
        str(poi.get("parent_poi_type") or ""),
        str(poi.get("parent_label") or poi.get("parent_location") or ""),
    )


def _is_discovered(poi: dict) -> bool:
    return (poi.get("source_angle") or "") in _DISCOVERED_ANGLES


def _type_match_score(poi: dict) -> int:
    """1 when the POI's own returned `types` contains the type Punk searched
    for (`parent_poi_type`), else 0. Both fields are already on every POI
    dict (see tools.py's search_pois_by_type et al.) — no new fetch. Case-
    folded only; not a semantic match, just "does the response agree with
    what we asked for" — the actual off-category-noise signal."""
    wanted = str(poi.get("parent_poi_type") or "").strip().lower()
    if not wanted:
        return 0
    types = {str(t).strip().lower() for t in (poi.get("types") or [])}
    return 1 if wanted in types else 0


# IMDB's weighted-rating m: how many reviews' worth of "the pool average" every
# POI is charged before its own stars count for anything. 20 is the knee — a
# 5.0 from 2 reviews scores far below a 4.6 from 800 against a ~4.2 pool mean.
_BAYES_PRIOR = 20


def _pool_mean_rating(pois: list[dict]) -> float:
    """C — mean rating over the RATED members of `pois` (n>0), never the whole
    pool: averaging in a bunch of (0 reviews, no rating) POIs as if they were
    0-star would drag C toward 0 and make every real rating look artificially
    good relative to it. 0.0 when nothing in the pool is rated — every score
    then collapses to 0.0, every POI ties on it, and the stable sort falls
    back to `_type_match_score` + arrival order: today's exact behaviour."""
    vals = [
        float(p["rating"]) for p in pois
        if p.get("rating") is not None and (p.get("user_ratings_total") or 0) > 0
    ]
    return sum(vals) / len(vals) if vals else 0.0


def _rank_key(pool: list[dict]) -> Callable[[dict], tuple[int, float]]:
    """Sort key for ONE pool, built once (so the pool mean is computed once,
    not per comparison) and reused across that pool's sort.

    (type-match, bayesian-rating) — both descending under `sorted(reverse=True)`.
    Type match stays PRIMARY: it's a relevance signal (did Places return what
    we asked for), rating is a quality signal, and a 4.9-star nail salon
    returned for "gym" is still not a gym. This is the DEFAULT ranking, used
    whenever the caller did not name an explicit `sort` — see `_rank_key_for`.

    An UNRATED POI (0 reviews) scores exactly C, the pool mean — not 0. That's
    the reason for the Bayesian form over a raw-rating sort: event venues,
    web-fallback named places, and store-set points carry no Google rating,
    and sinking them to the bottom would mean every "top N" silently sweeps
    out a whole data source the instant ANYTHING else in the pool has stars —
    a data-source bias, not a quality judgement. Scoring them average lets
    them hold their existing position among similarly-average peers.
    """
    c = _pool_mean_rating(pool)

    def _key(poi: dict) -> tuple[int, float]:
        n = int(poi.get("user_ratings_total") or 0)
        r = float(poi.get("rating") or 0.0)
        return (_type_match_score(poi), (n * r + _BAYES_PRIOR * c) / (n + _BAYES_PRIOR))

    return _key


# ── Explicit sort ────────────────────────────────────────────────────────────
#
# `_rank_key` above is Punk's own DEFAULT heuristic for "best first" when the
# user gave no order. `sort` lets the user name one directly. The two are
# mutually exclusive per spec: an explicit sort REPLACES the default (and, in
# `_select`, suspends the market-fairness round-robin too) rather than
# blending with it — a user who said "closest 5" gets the 5 closest, not the
# 5 closest-among-whichever-a-fairness-heuristic-preferred.

_SORT_KEYS: frozenset[str] = frozenset({"rating", "reviews", "distance_km", "name"})
# Which end of each metric counts as "first" with no explicit `dir` — the
# reading a user's bare "sort by rating" / "closest first" actually implies.
_SORT_DEFAULT_DIR: dict[str, str] = {
    "rating": "desc", "reviews": "desc", "distance_km": "asc", "name": "asc",
}


def _rank_key_for(
    sort: dict | None, pool: list[dict], dist_fn: Callable[[dict], float] | None,
) -> tuple[Callable[[dict], Any], bool]:
    """Returns (key_fn, reverse) for `sorted(pool, key=key_fn, reverse=reverse)`.

    No explicit `sort` → today's default: `_rank_key`, always descending
    (type-match first, then Bayesian rating). An explicit `sort` picks one
    concrete field and a plain ascending/descending sort on it — no sign-
    flipping tricks folded into the key value, so `reverse` alone carries
    direction and the key function stays a plain, obviously-correct read of
    one field. `distance_km`/`name` default ascending (closest / A-first);
    `rating`/`reviews` default descending (highest first) — see
    `_SORT_DEFAULT_DIR`.
    """
    if not sort:
        return _rank_key(pool), True

    by = sort["by"]
    descending = sort.get("dir", _SORT_DEFAULT_DIR[by]) == "desc"
    if by == "rating":
        c = _pool_mean_rating(pool)

        def _key(p: dict) -> float:
            n = int(p.get("user_ratings_total") or 0)
            r = float(p.get("rating") or 0.0)
            return (n * r + _BAYES_PRIOR * c) / (n + _BAYES_PRIOR)
    elif by == "reviews":
        def _key(p: dict) -> int:
            return int(p.get("user_ratings_total") or 0)
    elif by == "distance_km":
        def _key(p: dict) -> float:
            return dist_fn(p) if dist_fn is not None else 0.0
    else:  # "name"
        def _key(p: dict) -> str:
            return str(p.get("name") or "").lower()

    return _key, descending


def allocate_top_n(pois: list[dict], n: int) -> tuple[list[dict], list[dict]]:
    """Bucket-quota trim to `n` DISCOVERED pois; every named-arm POI passes
    through untouched regardless of `n`. Returns (kept, dropped).

    Superseded by `apply_specs` for the production dispatch path (which also
    handles `scope="each"`, `match`, `ids`, and rating/review/distance
    filters) — kept here as the pure, directly-testable core for the plain
    "top N over everything" case, and because `tests/test_poi_trim.py`
    exercises it in isolation.

    Within a bucket, ranked by `_rank_key`: exact type-match first, then a
    Bayesian rating score (ties — an all-unrated bucket, or every POI equally
    unrated — fall back to Places' own arrival/relevance order via the stable
    sort). Reuses `_round_robin_by` (geo.py) for the cross-bucket interleave
    rather than reimplementing it — that helper exists for exactly this "keep
    some from every group instead of wiping the trailing ones" problem.
    """
    from app.graph.builder.executors.geo import _round_robin_by

    named = [p for p in pois if not _is_discovered(p)]
    discovered = [p for p in pois if _is_discovered(p)]
    if len(discovered) <= n:
        return list(pois), []

    discovered = sorted(discovered, key=_rank_key(discovered), reverse=True)
    ordered = _round_robin_by(discovered, key=_bucket_key)
    kept, dropped = ordered[:n], ordered[n:]
    return named + kept, dropped


_LEAD_IN_RE = re.compile(
    r"^\s*(?:please\s+)?(?:drop|remove|delete|exclude|cut|take\s+out|keep|"
    r"only|just|show\s+me)\s+"
    r"(?:only\s+|everything\s+(?:in|from)\s+|the\s+|all\s+(?:the\s+)?|any\s+)?",
    re.IGNORECASE,
)
_TRAIL_RE = re.compile(r"\s+(?:ones?|spots?|places?|pois?)\s*$", re.IGNORECASE)


def _strip_lead_in(text: str) -> str:
    s = _LEAD_IN_RE.sub("", (text or "").strip())
    s = _TRAIL_RE.sub("", s)
    return s.strip()


def resolve_drop_predicate(pois: list[dict], text: str) -> list[dict]:
    """POIs matching a named predicate ("drop everything in Laval", "remove the
    Tim Hortons ones", "the gyms") by substring against name / parent_poi_type
    / parent_label / parent_location / formatted_address / the POI's OWN
    geocoded locality+state tokens, accent/case-folded via the SAME normalizer
    the rest of the POI-edit machinery uses.

    `locality_tokens`/`state_tokens` (Places addressComponents, surfaced onto
    every POI dict alongside `formatted_address` — see the fetch functions in
    tools.py) are what makes "drop everything in Laval" work when the SEARCH
    was for the broader "Montreal" market: `parent_label`/`parent_location`
    only carry the searched-for market name, not where a given POI actually
    sits. Without these, a suburb name the user names never matches anything
    unless it happened to appear in the POI's own street address.

    Conservative on purpose: no match returns [], never a guess — a
    misread instruction must match nothing, not everything. Named-arm POIs are
    NOT excluded here (unlike the bare-count path) — a user naming a specific
    brand/venue/category is allowed to hit a named arm; only a COUNT with no
    name attached is scoped to discovered-only (see apply_specs's `protect`).
    """
    from app.graph.builder.executors.geo import _norm_poi_name

    needle = _norm_poi_name(_strip_lead_in(text))
    if not needle:
        return []

    def _match(n: str) -> list[dict]:
        found = []
        for p in pois:
            haystack = " ".join(
                str(p.get(f) or "") for f in (
                    "name", "parent_poi_type", "parent_label",
                    "parent_location", "formatted_address",
                )
            )
            haystack += " " + " ".join(p.get("locality_tokens") or [])
            haystack += " " + " ".join(p.get("state_tokens") or [])
            if n in _norm_poi_name(haystack):
                found.append(p)
        return found

    hits = _match(needle)
    # Plural in, singular on the POI ("dog parks" said, "dog park" stored) is
    # the single most common miss here — no stemmer, just a retry with a
    # trailing "s" dropped, and ONLY when the first pass matched nothing, so
    # an already-working match can never be widened into an over-match.
    # Length guard so a real short word ("gas", "spa") isn't chewed.
    if not hits and needle.endswith("s") and len(needle) > 3:
        hits = _match(needle[:-1])
    if not hits:
        # Abbreviations ("vet clinics" for "veterinary clinic"): every word of the
        # request must start some word of the spot's own labels. Last resort only,
        # so a working exact match is never widened.
        words = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in needle.split()]
        if words and all(len(w) >= 3 for w in words):
            for p in pois:
                hay = _norm_poi_name(" ".join(
                    str(p.get(f) or "") for f in ("name", "parent_poi_type", "parent_label")
                )).split()
                if all(any(h.startswith(w) for h in hay) for w in words):
                    hits.append(p)
    return hits


# ── Selection spec ───────────────────────────────────────────────────────────
#
# A small, closed, all-optional grammar the classifier emits instead of a raw
# phrase — same family as `audience_filter`'s typed JSON patch
# (resume_router.py), generalized to POI selection. Every combination of keys
# is independently executable; nothing here is a phrasing match.
#
#   op               "keep" | "drop"                default "keep"
#   n                int | None                      the slice size
#   scope            "all" | "each"                  n is global, or per
#                                                     category (poi_group_id)
#   match            str | None                       a named predicate,
#                                                     resolved the same way
#                                                     resolve_drop_predicate
#                                                     always has been
#   sort             {"by": rating|reviews|           an EXPLICIT order,
#                      distance_km|name,              replacing the default
#                      "dir": "asc"|"desc"}           ranking — see
#                                                     `_rank_key_for`
#   min_rating       float | None                     rating floor (an
#   max_rating       float | None                     unrated POI cannot be
#                                                     shown to clear either
#                                                     threshold, so it is
#                                                     EXCLUDED, not guessed —
#                                                     see `_apply_numeric_
#                                                     filters`)
#   min_reviews      int | None                       review-count floor
#   max_distance_km  float | None                     ceiling from the
#                                                     build's center/anchor
#                                                     point — `unsupported`
#                                                     when no such point
#                                                     exists yet (see
#                                                     `apply_specs`)
#   unsupported      str | None                       a clause understood
#                                                     but expressible by no
#                                                     key above — NEVER
#                                                     approximated with the
#                                                     nearest key
#   ids              list[[lat,lng,name]] | None      internal only, never
#                                                     classifier-emitted —
#                                                     how a map-widget click
#                                                     becomes a spec entry
#                                                     in the same replayable
#                                                     list (see edits.py)
_SPEC_KEYS = frozenset({
    "op", "n", "scope", "match", "sort",
    "min_rating", "max_rating", "min_reviews", "max_distance_km",
    "unsupported", "ids", "min_visitors",
})


def _empty_spec() -> dict[str, Any]:
    return {
        "op": "keep", "n": None, "scope": "all", "match": None, "sort": None,
        "min_rating": None, "max_rating": None, "min_reviews": None,
        "max_distance_km": None, "unsupported": None, "ids": None,
        "min_visitors": None,
    }


def _coerce_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def normalize_spec(raw: Any) -> dict[str, Any]:
    """Coerce `raw` (a spec dict from the classifier, or a bare string from a
    stale cache entry / Backend B's pre-migration tool schema) into the full
    keyed shape above, every key present.

    A dict with an unrecognised key or a badly-typed value does NOT get that
    clause silently dropped — it is folded into `unsupported` instead (a
    hallucinated `"per_market": 5` must surface as "can't do that part", not
    vanish). This is the enforcement half of the classifier prompt's
    obligation: "if part of the instruction names a selection idea none of
    these keys express, put that clause VERBATIM in `unsupported` and still
    emit the keys you CAN — never approximate it with a key that means
    something else."

    `max_distance_km` / `sort.by == "distance_km"` are structurally valid
    here regardless of whether the CURRENT build actually has a center/anchor
    point to measure from — that check needs the live geo state this pure
    function never sees, so it happens one layer up, in `apply_specs`.
    """
    if isinstance(raw, dict):
        out = _empty_spec()
        extra: list[str] = []
        for k, v in raw.items():
            if k == "op" and v in ("keep", "drop"):
                out["op"] = v
            elif k == "n" and (v is None or isinstance(v, int)):
                out["n"] = v
            elif k == "scope" and v in ("all", "each"):
                out["scope"] = v
            elif k == "match" and isinstance(v, str) and v.strip():
                out["match"] = v.strip()
            elif k == "sort" and isinstance(v, dict) and v.get("by") in _SORT_KEYS \
                    and v.get("dir", "asc") in ("asc", "desc"):
                out["sort"] = {"by": v["by"], "dir": v.get("dir", _SORT_DEFAULT_DIR[v["by"]])}
            elif k in ("min_rating", "max_rating") and _coerce_float(v) is not None:
                out[k] = _coerce_float(v)
            elif k == "min_reviews" and isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out["min_reviews"] = v
            elif k == "max_distance_km" and _coerce_float(v) is not None and _coerce_float(v) > 0:
                out["max_distance_km"] = _coerce_float(v)
            elif k == "min_visitors" and isinstance(v, int) and not isinstance(v, bool) and v >= 1:
                out["min_visitors"] = v
            elif k == "unsupported" and v:
                out["unsupported"] = str(v)
            elif k == "ids" and isinstance(v, list) and v:
                out["ids"] = v
            elif k not in _SPEC_KEYS and v not in (None, "", [], {}):
                extra.append(f"{k}={v!r}")
        if extra and not out["unsupported"]:
            out["unsupported"] = "; ".join(extra)
        return out

    # Legacy string path — reuses the tested regex parser for mode/count/
    # predicate, adds only the `scope` detection the original parser lacked.
    # No sort/rating/distance detection here on purpose: a bare string only
    # reaches this path via a stale cache entry or Backend B's pre-migration
    # schema, both of which predate those keys existing at all.
    text = str(raw or "")
    scope = "each" if _EACH_RE.search(text) else "all"
    mode, n = parse_trim_instruction(text)
    if mode == "top_n":
        spec = _empty_spec()
        spec["n"], spec["scope"] = n, scope
        return spec
    if mode == "drop":
        predicate = _strip_lead_in(text)
        spec = _empty_spec()
        spec["op"], spec["match"] = "drop", (predicate or None)
        return spec
    spec = _empty_spec()
    spec["unsupported"] = text.strip() or "couldn't tell what to trim"
    return spec


def _needs_distance(spec: dict) -> bool:
    return spec["max_distance_km"] is not None or (
        spec["sort"] is not None and spec["sort"]["by"] == "distance_km"
    )


@dataclass
class ExecutionReport:
    """What one `apply_specs` call actually did — the fact base
    `beats.record_change` / the outcome beat draw from, so the composer can
    only ever claim what `applied` reports (see narrator's CHANGES block)."""

    kept: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    before_by_group: dict[str, int] = field(default_factory=dict)
    after_by_group: dict[str, int] = field(default_factory=dict)
    # poi_group_id -> count kept ONLY because it's a named arm a bare count
    # never touches (see `protect` below) — the +2 in "top 5 -> 7" made
    # visible instead of silently folded into the new total.
    protected_kept: dict[str, int] = field(default_factory=dict)
    deviations: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)


def _apply_numeric_filters(
    pool: list[dict], spec: dict, dist_fn: Callable[[dict], float] | None,
) -> tuple[list[dict], str | None]:
    """AND-compose every numeric predicate on `spec` (rating floor/ceiling,
    review-count floor, distance ceiling) over `pool`. Returns (kept, note) —
    `note` is a plain-language deviation, present only when a rating
    threshold had to exclude UNRATED POIs to stay honest: an unrated POI
    cannot be shown to clear (or fail) a star threshold, so it is excluded
    from THAT filter rather than guessed either way — a different question
    from whether it ranks as average for sorting/allocation (`_rank_key`'s
    docstring). `max_distance_km` is a no-op when `dist_fn` is None — the
    caller (`apply_specs`) has already turned that case into an `unsupported`
    clause and stripped the field before this runs.
    """
    kept = pool
    unrated_excluded = 0
    if spec["min_rating"] is not None or spec["max_rating"] is not None:
        rated = [
            p for p in kept
            if p.get("rating") is not None and (p.get("user_ratings_total") or 0) > 0
        ]
        unrated_excluded = len(kept) - len(rated)
        kept = rated
        if spec["min_rating"] is not None:
            kept = [p for p in kept if float(p["rating"]) >= spec["min_rating"]]
        if spec["max_rating"] is not None:
            kept = [p for p in kept if float(p["rating"]) <= spec["max_rating"]]
    if spec["min_reviews"] is not None:
        kept = [p for p in kept if (p.get("user_ratings_total") or 0) >= spec["min_reviews"]]
    if spec["max_distance_km"] is not None and dist_fn is not None:
        kept = [
            p for p in kept
            if p.get("lat") is not None and p.get("lng") is not None
            and dist_fn(p) <= spec["max_distance_km"]
        ]
    note = f"{unrated_excluded} have no rating, left out of that filter" if unrated_excluded else None
    return kept, note


def _select(
    pool: list[dict], n: int | None, scope: str, protect: bool,
    sort: dict | None = None, dist_fn: Callable[[dict], float] | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """The core of one spec's `n`/`scope` slice over `pool`.

    Returns (selected, passthrough, deviations). `selected` is what the
    count/scope picked (the top-N-ranked, globally or per `poi_group_id`
    category); `passthrough` is the named-arm carve-out (only populated when
    `protect` is True) that a bare count never ranks or drops. The caller
    (`apply_specs`) decides what `selected`/`passthrough` MEAN for this spec's
    `op` — keep-target or drop-target — this function only ranks and slices.

    An explicit `sort` suspends `_round_robin_by`'s cross-bucket (market/type)
    fairness interleave, in both scopes: "closest 5" or "closest 5 per
    category" means the actual closest ones, not the closest-among-whichever-
    bucket-fairness-preferred. With no `sort`, today's exact behaviour is
    unchanged — interleave, then slice.
    """
    from app.graph.builder.executors.geo import _round_robin_by

    if protect:
        passthrough = [p for p in pool if not _is_discovered(p)]
        ranked_pool = [p for p in pool if _is_discovered(p)]
    else:
        passthrough = []
        ranked_pool = pool

    if n is None:
        return list(ranked_pool), passthrough, []

    # One rank key for the whole `ranked_pool`, reused by both branches below
    # (including per-group in "each") — a per-group mean would be technically
    # finer-grained for "each", but wrong on the `protect=False` `match` path
    # where `pool` IS already one arbitrary matched subset with no groups to
    # split further, so one rule covers both instead of two.
    rank, descending = _rank_key_for(sort, ranked_pool, dist_fn)
    strict_order = sort is not None

    deviations: list[str] = []
    if scope == "each":
        groups: dict[str, list[dict]] = {}
        for p in ranked_pool:
            groups.setdefault(poi_group_id_(p), []).append(p)
        selected: list[dict] = []
        for gkey, members in groups.items():
            ranked_members = sorted(members, key=rank, reverse=descending)
            ordered = ranked_members if strict_order else _round_robin_by(
                ranked_members, key=_bucket_key,
            )
            if len(ordered) <= n:
                selected.extend(ordered)
                if len(ordered) < n:
                    label = gkey.split(":", 1)[-1] or gkey
                    deviations.append(f"'{label}' only had {len(ordered)}, kept all {len(ordered)}")
            else:
                selected.extend(ordered[:n])
        return selected, passthrough, deviations

    # scope == "all"
    if len(ranked_pool) <= n:
        return list(ranked_pool), passthrough, []
    ranked = sorted(ranked_pool, key=rank, reverse=descending)
    ordered = ranked if strict_order else _round_robin_by(ranked, key=_bucket_key)
    return ordered[:n], passthrough, []


def poi_group_id_(poi: dict) -> str:
    """Lazy-imported alias for `geo.poi_group_id` — kept as a thin wrapper
    (not a bare `from ... import poi_group_id` at module level) so this
    leaf module stays import-cycle-free of `geo.py`, same reasoning as every
    other lazy geo import in this file."""
    from app.graph.builder.executors.geo import poi_group_id

    return poi_group_id(poi)


def _apply_ids(current: list[dict], spec: dict) -> tuple[list[dict], str | None]:
    """Identity-pinned keep/drop — how a map-widget click (exact POIs the
    user SAW and removed) becomes a spec entry, distinct from a `match`
    (a name/category the user is trusting Punk to resolve)."""
    from app.graph.builder.executors.geo import _norm_poi_name, _poi_key

    id_set = {tuple(x) for x in (spec.get("ids") or [])}
    if not id_set:
        return current, None

    def _ident(p: dict):
        k = _poi_key(p)
        if k is None:
            return None
        return (k[0], k[1], _norm_poi_name(p.get("name")))

    if spec["op"] == "drop":
        kept = [p for p in current if _ident(p) not in id_set]
        removed = len(current) - len(kept)
        return kept, (f"drop {removed} spot(s) by selection" if removed else None)
    kept = [p for p in current if _ident(p) in id_set]
    removed = len(current) - len(kept)
    return kept, (f"keep {len(kept)} spot(s) by selection" if removed else None)


def _is_bare_count(spec: dict) -> bool:
    """A COUNT-ONLY instruction ("top 5", "top 5 of each category", "top 5 by
    rating") — no `match`, no `ids`, no numeric filter narrowing the pool
    first. An explicit `sort` does NOT disqualify bare-count status: "top 5 by
    rating" is still a "resize to N" instruction, just ranked by a named key
    instead of the default.

    The one spec shape that is REVISED, not accumulated: "top 5" then later
    "actually make it 10" is not "top 5 AND top 10", it's a correction.
    Folding both sequentially against the running `current` would apply the
    second cap to what the FIRST cap already reduced to — 5-per-category can
    only ever shrink further, never grow back to 10. See `apply_specs`'s
    docstring for the two-bucket fold this motivates.
    """
    return (
        spec["n"] is not None and not spec["match"] and not spec["ids"]
        and spec["min_rating"] is None and spec["max_rating"] is None
        and spec["min_reviews"] is None and spec["max_distance_km"] is None
    )


def _is_actionable(spec: dict) -> bool:
    """True when `spec` carries at least one key that changes the pool, apart
    from `unsupported`/`op`/`scope` (which are meaningless alone — `op`
    defaults to "keep", `scope` to "all", neither does anything by itself).
    Used to decide whether a spec that ALSO named an unsupported clause still
    has real work to do (see `apply_specs`'s fold loop)."""
    return any(
        spec[k] is not None
        for k in ("match", "ids", "n", "sort", "min_rating", "max_rating", "min_reviews", "max_distance_km")
    )


def apply_specs(
    pois: list[dict], specs: list[Any], ref_point: tuple[float, float] | None = None,
    *, unsupported_from: int = 0,
) -> ExecutionReport:
    """Fold an ORDERED list of specs (normalized or raw — each is run through
    `normalize_spec`) over the full discovery superset `pois`, and return the
    settled result plus a full account of what happened.

    `ref_point` is the build's own center/anchor coordinate (`(lat, lng)`,
    typically `geo_ws["_det_center"]` — see builder_node.py, already the same
    point the map preview centers on) — the ONLY thing this otherwise-pure
    function takes from outside the POI list, because distance needs a
    "distance from WHERE" that no POI carries on itself. A spec asking for
    `max_distance_km` or `sort: {"by": "distance_km"}` with `ref_point=None`
    is honest about it: that clause moves to `unsupported` rather than being
    silently skipped or guessed, and the REST of that spec (a `match`, a
    rating floor) still runs — a bad distance clause never sinks a whole
    instruction.

    Two buckets, folded in two passes so a later bare count can WIDEN:

      1. Persistent narrowing — `match`/`ids`/numeric-filter specs (named
         removals, "only the gyms", "rated above 4", a map-widget click).
         These compound, sequentially, in the order given: each further
         narrows what the next one sees.
      2. Bare count — a spec with `n` and no `match`/`ids`/numeric filter
         ("top 5", "top 5 of each category", "closest 5"). Only the LAST one
         in the list is applied, once, against whatever bucket 1 left — a
         bare count is a standing "resize to N" instruction, not an
         accumulating trim. "top 5" then "actually make it 10" replays as
         bucket 1 (empty) + the single surviving count spec (n=10) against
         the full superset, so it widens back out.

    Always folds from the SUPERSET `pois`, never from a previous `kept` —
    the caller (builder_node) is responsible for persisting `specs` (not
    `kept`) across turns, see `bs["_poi_selection_specs"]`.

    `unsupported_from` is the index into `specs` where THIS TURN starts (the
    caller passes `len(prior_specs)`). `report.unsupported` only surfaces
    clauses from specs at or after that index — a spec still applies (or
    fails to) exactly the same regardless, this only controls what gets
    RE-NARRATED. Without it, an unsupported clause from turn 1 ("recommend
    me the best places only") gets folded back into `unsupported` on every
    later turn that touches POI selection at all, because the fold always
    replays the full history — see the module-level bug this fixed.
    """
    original = list(pois)
    before_by_group: dict[str, int] = {}
    for p in original:
        g = poi_group_id_(p)
        before_by_group[g] = before_by_group.get(g, 0) + 1

    dist_fn: Callable[[dict], float] | None = None
    if ref_point is not None:
        from app.graph.builder.executors.geo import _distance_km

        _rlat, _rlng = ref_point
        dist_fn = lambda p: _distance_km(_rlat, _rlng, float(p["lat"]), float(p["lng"]))  # noqa: E731

    normalized: list[dict] = []
    unsupported: list[str] = []
    for idx, s in enumerate(specs):
        spec = normalize_spec(s)
        if _needs_distance(spec) and dist_fn is None:
            if idx >= unsupported_from:
                unsupported.append(
                    "distance filtering/sorting isn't available yet for this build "
                    "(no center point set) — I can still apply the rest of that request"
                )
            spec = dict(spec)
            spec["max_distance_km"] = None
            if spec["sort"] and spec["sort"]["by"] == "distance_km":
                spec["sort"] = None
        normalized.append(spec)

    current = list(original)
    deviations: list[str] = []
    applied: list[str] = []
    protected_kept: dict[str, int] = {}

    last_count_spec: dict | None = None
    last_count_idx = -1
    # The whole spec history is replayed on every call, so a note about an OLD
    # instruction ("nothing matched 'X'", "only 18 match") would be re-narrated
    # every later turn — with counts that were true at fold time, not now. Only
    # what THIS turn's specs (index >= unsupported_from) did is reported.
    for idx, spec in enumerate(normalized):
        _fresh = idx >= unsupported_from
        if spec["unsupported"]:
            if idx >= unsupported_from:
                unsupported.append(spec["unsupported"])
            # A clause can name BOTH something we can't express AND something
            # we can ("recommend the best places only, and drop the dog
            # parks" -> unsupported="recommend the best places only",
            # match="dog park") — `normalize_spec`'s own docstring promises
            # the actionable keys still run. Only skip this spec entirely
            # when it has nothing else to do.
            if not _is_actionable(spec):
                continue
        if _is_bare_count(spec):
            last_count_spec = spec
            last_count_idx = idx
            continue

        if spec["ids"]:
            current, note = _apply_ids(current, spec)
            if note:
                applied.append(note)
            continue

        # A narrowing spec: `match` and/or a numeric filter (rating/reviews/
        # distance), possibly WITH a count ("only 3 gyms", "gyms rated above
        # 4, closest 3") — the count sizes the narrowed subset, so it applies
        # immediately here rather than deferring, unlike a bare count's
        # "resize everything" semantics.
        #
        # `candidates` (name-match only, or all of `current` when there is no
        # `match`) is the SCOPE this spec is allowed to touch — it must stay
        # the pre-numeric-filter set. `filtered` (candidates minus whatever
        # the rating/review/distance predicates rejected) is what actually
        # gets ranked and count-sliced. For `op="keep"` the drop-set is
        # candidates-minus-selected: using the post-filter set as the scope
        # here was the bug this comment replaced — it made the rating/review/
        # distance predicates silently keep everyone they were supposed to
        # exclude, because "not in scope" and "filtered out" collapsed to the
        # same thing. `op="drop"` never had this problem — it only ever acts
        # on `selected` directly — but shares the same candidates/filtered
        # split for one code path instead of two.
        candidates = current
        if spec["match"]:
            candidates = resolve_drop_predicate(candidates, spec["match"])
            if not candidates:
                if _fresh:
                    deviations.append(f"nothing on the map matched '{spec['match']}'")
                continue

        filtered, filt_note = _apply_numeric_filters(candidates, spec, dist_fn)
        if filt_note and _fresh:
            deviations.append(filt_note)
        if not filtered:
            # Distinct from `candidates` being empty (nothing matched the
            # NAME) — here the name/category matched fine, but the
            # rating/review/distance predicate rejected every one of them.
            # Fall through rather than `continue`: `_select` on an empty pool
            # correctly returns `selected=[]`, which for `op="keep"` means
            # "drop the whole matched set" (nothing satisfied the keep
            # criteria) and for `op="drop"` means "nothing to drop" — both
            # right, with no special-casing needed below.
            if _fresh:
                deviations.append("nothing among the matched spots satisfied that filter")

        selected, _passthrough, sel_deviations = _select(
            filtered, spec["n"], spec["scope"], protect=False,
            sort=spec["sort"], dist_fn=dist_fn,
        )
        if _fresh:
            deviations.extend(sel_deviations)
        if (
            _fresh and spec["op"] == "keep" and spec["match"] and spec["n"] is not None
            and spec["scope"] != "each" and filtered and len(filtered) < spec["n"]
        ):
            # Said in the user's terms: "top 20 dog parks" when 18 exist is a
            # request that could not be met as asked, not one that "matched nothing".
            deviations.append(
                f"only {len(filtered)} spot(s) match '{spec['match']}', fewer than the "
                f"{spec['n']} asked for, so all {len(filtered)} were kept"
            )

        if spec["op"] == "keep":
            candidate_ids = {id(m) for m in candidates}
            keep_ids = {id(p) for p in selected}
            newly_dropped = [p for p in current if id(p) in candidate_ids and id(p) not in keep_ids]
            current = [p for p in current if id(p) not in candidate_ids or id(p) in keep_ids]
        else:  # drop
            drop_ids = {id(p) for p in selected}
            newly_dropped = [p for p in current if id(p) in drop_ids]
            current = [p for p in current if id(p) not in drop_ids]

        if newly_dropped:
            _bits = []
            if spec["match"]:
                _bits.append(f"matching '{spec['match']}'")
            if spec["min_rating"] is not None:
                _bits.append(f"rated >= {spec['min_rating']}")
            if spec["max_rating"] is not None:
                _bits.append(f"rated <= {spec['max_rating']}")
            if spec["min_reviews"] is not None:
                _bits.append(f">= {spec['min_reviews']} reviews")
            if spec["max_distance_km"] is not None:
                _bits.append(f"within {spec['max_distance_km']}km")
            _desc = f"{spec['op']} {len(newly_dropped)} spot(s) " + (" ".join(_bits) or "matching that")
            if spec["n"] is not None:
                _desc += f" (top {spec['n']})"
            applied.append(_desc)

    if last_count_spec is not None:
        selected, passthrough, sel_deviations = _select(
            current, last_count_spec["n"], last_count_spec["scope"], protect=True,
            sort=last_count_spec["sort"], dist_fn=dist_fn,
        )
        if last_count_idx >= unsupported_from:
            deviations.extend(sel_deviations)
        if passthrough:
            for p in passthrough:
                g = poi_group_id_(p)
                protected_kept[g] = protected_kept.get(g, 0) + 1
        keep_ids = {id(p) for p in selected} | {id(p) for p in passthrough}
        newly_dropped = [p for p in current if id(p) not in keep_ids]
        current = [p for p in current if id(p) in keep_ids]
        if newly_dropped or len(current) != len(original):
            _n = last_count_spec["n"]
            _scope = last_count_spec["scope"]
            _sort = last_count_spec["sort"]
            # `applied` is the composer's only licence to claim what happened
            # (see the CHANGES-block reasoning in ExecutionReport's docstring)
            # — only say "ranked by rating" when a surviving POI actually has
            # reviews, else it fell back to arrival order and the claim
            # would be a lie. An explicit `sort` always names itself, since
            # that ranking is exact (no fallback ambiguity).
            if _sort:
                _order = f" sorted by {_sort['by'].replace('_km', '')} ({_sort['dir']})"
            elif any((p.get("user_ratings_total") or 0) for p in current):
                _order = " ranked by rating"
            else:
                _order = ""
            applied.append(
                f"keep {len(current)} spot(s) (top {_n}"
                f"{' per category' if _scope == 'each' else ''}{_order})"
            )

    after_by_group: dict[str, int] = {}
    for p in current:
        g = poi_group_id_(p)
        after_by_group[g] = after_by_group.get(g, 0) + 1

    kept_ids = {id(p) for p in current}
    dropped_final = [p for p in original if id(p) not in kept_ids]

    return ExecutionReport(
        kept=current, dropped=dropped_final,
        before_by_group=before_by_group, after_by_group=after_by_group,
        protected_kept=protected_kept, deviations=deviations,
        unsupported=unsupported, applied=applied,
    )


__all__ = [
    "TrimMode",
    "parse_trim_instruction",
    "allocate_top_n",
    "resolve_drop_predicate",
    "normalize_spec",
    "ExecutionReport",
    "apply_specs",
]
