"""
graph/meta_spec/merge.py
────────────────────────
Keep the user's plan-editor work when the plan is REGENERATED.

A geo or audience edit after the plan exists used to delete ``marketing_plan``
and rebuild it from scratch — budgets, ad copy, media, schedule and any ad sets
the user added, gone. This is a three-way merge instead:

    base    the spec as Punk last GENERATED it (``bs["plan_base"]``)
    ours    the spec as the user left it        (``bs["marketing_plan_prev"]``)
    theirs  the spec generated from the edited build, just now

For every field the USER authors, ``ours != base`` means they changed it, so
their value wins; otherwise the regenerated value does. Everything the build
owns — geo, audience roles / ids, objective, optimisation, promoted object —
always comes from ``theirs``: a stale zip list must never survive a geo edit.

Ad sets are matched by name, then by audience role (a rename keeps its role).
An ad set only in ``ours`` was added by the user and is carried over; one in
``base`` but missing from ``ours`` was deleted by the user and stays deleted. A
user-edited ad set whose audience no longer exists in ``theirs`` can't be kept —
that is reported as a conflict, never dropped silently.

Pure: plain dicts in (``CampaignSpec.model_dump(mode="json")``), a dict out.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

# Fields the user can edit, and Punk must not overwrite when they did.
_CAMPAIGN_FIELDS = (
    "name", "daily_budget", "lifetime_budget", "bid_strategy",
    "budget_schedule_specs", "is_adset_budget_sharing_enabled",
)
_ADSET_FIELDS = (
    "name", "daily_budget", "lifetime_budget", "bid_strategy", "bid_amount",
    "bid_constraints", "start_time", "end_time", "adset_schedule",
    "budget_schedule_specs", "attribution_spec", "frequency_control_specs",
    "lead_form_draft", "attached_audience_ids", "excluded_audience_ids",
)
_AD_FIELDS = ("name", "creative", "status")
# Targeting keys the build owns (locked in the editor); every OTHER targeting
# key (placements, age, gender…) is user-authored.
_LOCKED_TARGETING = frozenset({"geo_locations", "custom_audiences", "excluded_custom_audiences"})


@dataclass
class MergeResult:
    spec: dict
    conflicts: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)      # human-readable, for narration

    @property
    def carried_anything(self) -> bool:
        return bool(self.kept)


def _changed(base: dict, ours: dict, key: str) -> bool:
    return ours.get(key) != base.get(key)


def _merge_fields(base: dict, ours: dict, theirs: dict, keys: tuple[str, ...], kept: list[str], where: str) -> None:
    """In-place onto ``theirs``: the user's value wherever they changed it."""
    for key in keys:
        if key not in base and key not in ours:
            continue
        if _changed(base, ours, key):
            if key in ours:
                theirs[key] = copy.deepcopy(ours[key])
            else:
                theirs.pop(key, None)
            kept.append(f"{where} {key.replace('_', ' ')}")


def _merge_targeting(base_t: dict, ours_t: dict, theirs_t: dict, kept: list[str], where: str) -> dict:
    out = dict(theirs_t)
    for key in (set(base_t) | set(ours_t)) - _LOCKED_TARGETING:
        if ours_t.get(key) != base_t.get(key):
            if key in ours_t:
                out[key] = copy.deepcopy(ours_t[key])
            else:
                out.pop(key, None)
            kept.append(f"{where} {key.replace('_', ' ')}")
    return out


def _match(adset: dict, candidates: list[dict], used: set[int]) -> Optional[int]:
    """Index of ``adset``'s counterpart: same name, else the one unused
    candidate with the same audience role."""
    for i, cand in enumerate(candidates):
        if i not in used and cand.get("name") and cand.get("name") == adset.get("name"):
            return i
    role = adset.get("audience_role")
    same_role = [i for i, c in enumerate(candidates) if i not in used and c.get("audience_role") == role]
    return same_role[0] if len(same_role) == 1 else None


def _merge_ads(base: list[dict], ours: list[dict], theirs: list[dict], kept: list[str], where: str) -> list[dict]:
    out: list[dict] = []
    for i, t_ad in enumerate(theirs):
        b_ad = base[i] if i < len(base) else None
        o_ad = ours[i] if i < len(ours) else None
        if b_ad is not None and o_ad is None:
            continue                                    # the user deleted this ad
        merged = copy.deepcopy(t_ad)
        if b_ad is not None and o_ad is not None:
            _merge_fields(b_ad, o_ad, merged, _AD_FIELDS, kept, f"{where} ad {i + 1}")
        out.append(merged)
    # ads the user added on top of the generated ones
    out.extend(copy.deepcopy(o) for o in ours[len(base):])
    if len(ours) > len(base):
        kept.append(f"{where}: {len(ours) - len(base)} ad(s) you added")
    return out


def merge_plan(base: Optional[dict], ours: Optional[dict], theirs: dict) -> MergeResult:
    """See the module docstring. Never raises on shape surprises — the caller
    falls back to ``theirs`` and says so (see ``merge_or_fallback``)."""
    if not base or not ours:
        return MergeResult(copy.deepcopy(theirs))

    kept: list[str] = []
    conflicts: list[str] = []
    spec = copy.deepcopy(theirs)
    _merge_fields(base, ours, spec, _CAMPAIGN_FIELDS, kept, "campaign")

    b_sets, o_sets, t_sets = base.get("adsets") or [], ours.get("adsets") or [], theirs.get("adsets") or []
    used_base: set[int] = set()
    used_ours: set[int] = set()
    merged_sets: list[dict] = []
    matched_theirs: set[int] = set()

    # Walk THEIRS in order: its structure wins; each is paired with the base ad
    # set it descends from, and through that with the user's version.
    for t_idx, t_set in enumerate(t_sets):
        b_i = _match(t_set, b_sets, used_base)
        if b_i is None:
            merged_sets.append(copy.deepcopy(t_set))     # new in the regenerated plan
            continue
        used_base.add(b_i)
        b_set = b_sets[b_i]
        o_i = _match(b_set, o_sets, used_ours)
        if o_i is None:
            continue                                     # the user deleted this ad set
        used_ours.add(o_i)
        matched_theirs.add(t_idx)
        o_set = o_sets[o_i]
        where = f"ad set '{o_set.get('name') or t_set.get('name')}'"
        merged = copy.deepcopy(t_set)
        _merge_fields(b_set, o_set, merged, _ADSET_FIELDS, kept, where)
        merged["targeting"] = _merge_targeting(
            b_set.get("targeting") or {}, o_set.get("targeting") or {},
            t_set.get("targeting") or {}, kept, where,
        )
        merged["ads"] = _merge_ads(b_set.get("ads") or [], o_set.get("ads") or [],
                                   t_set.get("ads") or [], kept, where)
        merged_sets.append(merged)

    geo = next(((s.get("targeting") or {}).get("geo_locations") for s in t_sets
                if (s.get("targeting") or {}).get("geo_locations") is not None), None)
    for o_i, o_set in enumerate(o_sets):
        if o_i in used_ours:
            continue
        b_i = _match(o_set, b_sets, used_base)
        if b_i is not None:
            # A user-edited ad set whose counterpart the regeneration no longer
            # produces (its audience is gone) — can't carry over. Say so.
            used_base.add(b_i)
            edited = o_set != b_sets[b_i]
            if edited:
                conflicts.append(
                    f"your changes to the '{o_set.get('name')}' ad set couldn't carry over "
                    "because that audience no longer exists"
                )
            continue
        added = copy.deepcopy(o_set)                     # user-added: keep, on the NEW geo
        if geo is not None:
            added.setdefault("targeting", {})["geo_locations"] = copy.deepcopy(geo)
        merged_sets.append(added)
        kept.append(f"the '{o_set.get('name')}' ad set you added")

    if merged_sets:
        spec["adsets"] = merged_sets
    else:
        # Every ad set deleted (or nothing matched): an empty plan is invalid, so
        # keep the regenerated one and say what happened.
        conflicts.append("all of your ad sets were removed, so the plan was rebuilt fresh")
    return MergeResult(spec, conflicts, kept)


def merge_or_fallback(base: Optional[dict], ours: Optional[dict], theirs: dict, validate: Any = None) -> MergeResult:
    """``merge_plan``, but any failure — a shape surprise, or a merged spec that
    doesn't validate — returns ``theirs`` with a conflict saying the user's edits
    couldn't be carried over. Honest fallback beats a crash mid-rebuild."""
    try:
        result = merge_plan(base, ours, theirs)
        if validate is not None and result.carried_anything:
            validate(result.spec)
        return result
    except Exception as exc:                            # noqa: BLE001 — deliberate catch-all
        return MergeResult(
            copy.deepcopy(theirs),
            [f"your plan edits couldn't be carried over ({type(exc).__name__}), so the plan was rebuilt fresh"],
        )


__all__ = ["MergeResult", "merge_plan", "merge_or_fallback"]
