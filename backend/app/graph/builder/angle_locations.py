"""
graph/builder/angle_locations.py
────────────────────────────────
"Events only in Montreal, gyms in Toronto": where each targeting angle searches.

A build has ONE flat location list (``filled["locations"]``, mirrored in
``user_info["location"]``) and optionally per-angle overrides
(``user_info["geo_angle_specs"]`` — ``[{"angle", "locations", ...}]``). An angle
with no ``locations`` of its own inherits the flat list. The flat list is the
union the geocode + confirm map work on, so it must always contain every name any
angle uses.

Pure functions over plain data — ``edits.apply_edits`` does the writing.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Optional

# angle token -> (the filled slot, the spec field) holding what it searches FOR.
_ANGLE_ITEMS: dict[str, tuple[str, str]] = {
    "category": ("poi_types", "poi_types"),
    "competitor_brand": ("brand_names", "competitor_brands"),
    "named_places": ("named_places", "named_places"),
    "event_based": ("event_queries", "event_queries"),
}
# Angles anchored on the user's own store addresses have no location list.
_ANCHORED = frozenset({"store_set", "competitor_nearby"})
_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("event", "festival", "concert", "trade show", "conference"), "event_based"),
    (("store", "shop", "outlet"), "store_set"),
    (("competitor", "rival"), "competitor_nearby"),
    (("brand", "chain"), "competitor_brand"),
    (("venue", "named place", "landmark"), "named_places"),
    (("categor", "kind of place", "type of place"), "category"),
)


def norm(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def dedupe(names: list) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = norm(n)
        if key and key not in seen:
            seen.add(key)
            out.append(str(n).strip())
    return out


def flat_names(filled: dict, ui: dict) -> list[str]:
    """The build's flat location list — the structured mirror when present (a
    name may contain a comma: "Montreal, QC"), else the joined slot."""
    mirror = (ui or {}).get("location")
    if isinstance(mirror, (list, tuple)) and mirror:
        return dedupe([str(x) for x in mirror])
    if isinstance(mirror, str) and mirror.strip():
        return dedupe([mirror])
    return dedupe(str((filled or {}).get("locations") or "").split(","))


def _tokens(filled: dict) -> list[str]:
    return [t.strip() for t in str((filled or {}).get("det_type") or "").split(",") if t.strip()]


def _items(angle: str, filled: dict, spec: Optional[dict]) -> list[str]:
    if angle not in _ANGLE_ITEMS:
        return []
    slot, field = _ANGLE_ITEMS[angle]
    out = [x for x in re.split(r"[;,]", str((filled or {}).get(slot) or "")) if x.strip()]
    return out + [str(x) for x in ((spec or {}).get(field) or [])]


def resolve_angle(target: str, filled: dict, specs: list) -> tuple[Optional[str], list[str]]:
    """Which ACTIVE angle ``target`` names: ``(token, [])`` when exactly one,
    else ``(None, candidates)`` — empty when it matched nothing. Order: the token
    itself, a keyword ("events"), then the angle's own items ("gyms", "Starbucks")."""
    active = _tokens(filled)
    text = norm(target)
    if not text or not active:
        return None, []
    for tok in active:
        if text in (tok, tok.replace("_", " ")):
            return tok, []
    for words, tok in _KEYWORDS:
        if tok in active and any(w in text for w in words):
            return tok, []
    spec_by = {s.get("angle"): s for s in specs if isinstance(s, dict)}
    hits = []
    for tok in active:
        for item in _items(tok, filled, spec_by.get(tok)):
            a, b = _stem(norm(item)), _stem(text)
            if a and b and (a == b or a in b or b in a):
                hits.append(tok)
                break
    return (hits[0], []) if len(hits) == 1 else (None, hits)


def rewrite_specs_for_flat_edit(specs: list, old_flat: list, new_flat: list) -> Optional[list]:
    """A flat location edit ("remove Montreal", "add Laval", "use Toronto") means
    EVERY angle — including one that pinned its own cities. Strip removed names
    from each spec's own list and give it the added ones. ``None`` when nothing
    changes."""
    old, new = {norm(n) for n in old_flat}, {norm(n) for n in new_flat}
    removed, added = old - new, [n for n in new_flat if norm(n) not in old]
    if not specs or (not removed and not added):
        return None
    out = copy.deepcopy(specs)
    changed = False
    for spec in out:
        own = spec.get("locations")
        if not own:
            continue
        kept = [n for n in own if norm(n) not in removed]
        kept = dedupe(kept + added)
        if kept != list(own):
            changed = True
            if kept:
                spec["locations"] = kept
            else:
                spec.pop("locations", None)          # nothing of its own left: inherit the flat list
    return out if changed else None


def apply_op(op: dict, *, filled: dict, specs: list, flat: list) -> dict:
    """One typed change ``{"target", "op": set|add|remove, "names"}`` →
    ``{"status": applied|no_op|refused, "detail", "specs", "flat"}``. ``specs``
    and ``flat`` are the NEW values (inputs are not mutated)."""
    names = dedupe(op.get("names") or [])
    kind = op.get("op") or "set"
    target = str(op.get("target") or "").strip()
    fail = lambda why: {"status": "refused", "detail": why, "specs": specs, "flat": flat}  # noqa: E731

    if not names:
        return fail("no place was named")
    tok, cands = resolve_angle(target, filled, specs)
    if tok is None:
        if cands:
            pretty = " or ".join(c.replace("_", " ") for c in cands)
            return fail(f"which search did you mean — {pretty}?")
        return fail(f"I couldn't tell which search {target!r} means (searches running: "
                    f"{', '.join(t.replace('_', ' ') for t in _tokens(filled)) or 'none'})")
    if tok in _ANCHORED:
        return fail(f"the {tok.replace('_', ' ')} search is anchored on your own store address, not on a city")

    new_specs = copy.deepcopy(specs)
    spec = next((s for s in new_specs if s.get("angle") == tok), None)
    if spec is None:
        spec = {"angle": tok}
        new_specs.append(spec)
    before_specs_union = {norm(n) for s in specs for n in (s.get("locations") or [])}
    shared_only = [n for n in flat if norm(n) not in before_specs_union]

    current = list(spec.get("locations") or flat)
    if kind == "add":
        result = dedupe(current + names)
    elif kind == "remove":
        gone = {norm(n) for n in names}
        missing = [n for n in names if norm(n) not in {norm(c) for c in current}]
        if missing:
            return fail(f"{', '.join(missing)} isn't one of the places for the {tok.replace('_', ' ')} search "
                        f"({', '.join(current)})")
        result = [n for n in current if norm(n) not in gone]
    else:
        result = names
    if not result:
        return fail(f"that would leave the {tok.replace('_', ' ')} search with no place to look in")
    if [norm(n) for n in result] == [norm(n) for n in current]:
        return {"status": "no_op", "detail": f"the {tok.replace('_', ' ')} search already looks in "
                f"{', '.join(current)}", "specs": specs, "flat": flat}

    if [norm(n) for n in result] == [norm(n) for n in flat]:
        spec.pop("locations", None)                    # same as the shared list: inherit again
    else:
        spec["locations"] = result
    new_specs = [s for s in new_specs if set(s) != {"angle"}]      # an angle with no overrides is no spec
    spec_union = [n for s in new_specs for n in (s.get("locations") or [])]
    return {
        "status": "applied", "specs": new_specs, "flat": dedupe(shared_only + spec_union),
        "detail": f"the {tok.replace('_', ' ')} search now looks in {', '.join(result)}",
    }
