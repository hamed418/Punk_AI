"""
graph/narrator/widget_guides.py
───────────────────────────────
What the user can DO inside each widget, told by the narrator.

The map and plan widgets carry many direct edits (drag/resize circles, drop
pins, search, remove, filter the audience, edit the plan) that nothing on the
screen advertises. This registry is the single source of those facts; the
composer attaches the matching guide to a widget's ``framing`` beat so the
lead-in message above the widget explains every control, in the narrator's own
voice, instead of a hidden ⓘ popover.

First showing of a widget in a session carries the full ``can_do`` list; every
later showing carries only the one-clause ``reminder`` (see
:func:`attach_widget_guides`).

Only interactions that actually take effect belong here — a control that looks
live but is dropped on confirm must not be advertised. Wording follows
``base.PLAIN_WORDS_RULE`` ("spot"/"place", never POI / MAID / geofence).
"""

from __future__ import annotations

from typing import Any

from app.graph.narrator import beats as _beats

# Every guide closes on this — mid-turn chat edits work on all of these steps.
_CHAT_TAIL = "or just tell me in chat what to change"

_LOCATION_MAP = {
    "can_do": [
        "drag a circle to move it",
        "drag its edge (or use the slider) to make it bigger or smaller",
        "tap the pin button, then the map, to add a spot",
        "search for a place to add it",
        "tap the minus to remove one",
        "press Use Zone when you're happy",
    ],
    "reminder": "same map as before — move, resize, add or remove spots",
    "fallback": (
        "You can drag a circle to move it, drag its edge to resize it, add a "
        "spot, or remove one."
    ),
}

WIDGET_GUIDES: dict[str, dict[str, Any]] = {
    "geo_location_confirm": _LOCATION_MAP,
    # Same widget; with no geocoded store there is no map to guide.
    "geo_store_confirm": {**_LOCATION_MAP, "skip_if_zero": "store_count"},
    "geo_collect_radius_pin": {
        "can_do": [
            "tap the map to drop your pin",
            "tap somewhere else to move it",
            "press Confirm Pin when it's right",
        ],
        "reminder": "same map — tap to place or move the pin",
        "fallback": "Tap the map to drop your pin, tap again to move it, then confirm.",
    },
    "geo_collect_radius_km": {
        "can_do": [
            "use plus and minus to make the circle bigger or smaller",
            "press Confirm when it covers the right area",
        ],
        "reminder": "same circle — plus and minus resize it",
        "fallback": "Use plus and minus to size the circle, then confirm.",
    },
    "maid_collect_settings": {
        "can_do": [
            "use plus and minus to pick how close someone must be to count — small means right inside the place, big includes people walking past",
            "use plus and minus to pick how many days back to look — more days means more people",
            "press Generate Audience when you're set",
        ],
        "reminder": "same two settings — how close, and how many days",
        "fallback": "Pick how close and how many days back, then generate the audience.",
    },
    "geo_pois_confirmation": {
        "can_do": [
            "tap a category to see just those places",
            "tap a place in the list to jump to it on the map",
            "tap the minus to remove a place you don't want",
            "search to add more places",
            "press Use these locations when the list looks right",
        ],
        "reminder": "same places map — filter, remove or add places",
        "fallback": (
            "You can filter by category, remove places you don't want, or "
            "search to add more, then confirm the list."
        ),
    },
    "maid_confirm_results": {
        "action_types": {"permission"},
        "can_do": [
            "zoom in close to see individual people instead of pins",
            "tap a pin to see how often people came back to that place",
            "press Adjust audience to narrow it down — by place, day of the week, how often people visited, and more — and you'll see the new number before you apply",
            "press Confirm Audience when it looks right",
        ],
        "reminder": "same audience map — zoom in, tap pins, or Adjust audience",
        "fallback": (
            "You can zoom in to see individual people, tap a pin for details, "
            "or press Adjust audience to narrow it down."
        ),
    },
    "campaign_intake_form": {
        "can_do": [
            "everything I already know is filled in, so change anything you like",
            "press Build my plan when you're done",
        ],
        "reminder": "same form — change anything, then Build my plan",
        "fallback": "Everything I know is filled in — change anything, then build the plan.",
    },
    "campaign_plan_confirm": {
        "can_do": [
            "use the list on the left to move between your campaign, ad sets and ads",
            "change anything you like — budget, dates, who sees it, the wording and the pictures",
            "use the sparkle button for wording ideas",
            "start from a previous campaign to save time",
            "red dots show what still needs fixing",
            "press Next to save and Preview to publish",
            "location and audience are locked here, so change those on the map",
        ],
        "express_extra": [
            "grayed-out parts are ones Punk set for you — press Unlock and View to see or change them",
        ],
        "reminder": "same editor — list on the left, Next to save, Preview to publish",
        "fallback": (
            "Everything here is editable — use the list on the left to move "
            "around, then press Preview to publish."
        ),
    },
    "media_confirm_go_live": {
        "can_do": [
            "click an ad to flip through the previews",
            "press Meta Setup and Tracking Details if you need the tracking code",
            "choose Set it live to start now, or Leave it paused to start it yourself later",
        ],
        "reminder": "same preview — Set it live or Leave it paused",
        "fallback": "Check the previews, then choose Set it live or Leave it paused.",
    },
}


def _is_express(state: Any) -> bool:
    try:
        filled = ((state or {}).get("campaign_builder_state") or {}).get("filled") or {}
        return str(filled.get("publish_mode") or "").strip().lower() == "express"
    except (AttributeError, TypeError):
        return False


def _guide_for(beat: Any) -> tuple[str, dict[str, Any]] | None:
    """The (key, guide) a framing beat should carry, or None."""
    if beat.kind != "framing":
        return None
    key = beat.facts.get("step") or beat.facts.get("stage")
    guide = WIDGET_GUIDES.get(key)
    if guide is None:
        return None
    types = guide.get("action_types")
    at = beat.facts.get("action_type")
    if types and at and at not in types:
        return None
    zero = guide.get("skip_if_zero")
    if zero and beat.facts.get(zero) == 0:
        return None
    return key, guide


async def attach_widget_guides(state: Any, beat_list: list[Any], turn: int) -> None:
    """Attach the widget guide to this turn's first matching framing beat.

    One beat per turn: the plan editor emits two framing beats for the same
    step, and a second copy would just make the composer repeat itself. On a
    first sight (never guided, or guided THIS turn — a same-turn replay must
    reproduce identical facts so the compose cache holds) the beat gets the
    full ``can_do`` list and its ``fallback`` sentence; afterwards only the
    ``reminder``.
    """
    for beat in beat_list:
        hit = _guide_for(beat)
        if hit is None:
            continue
        key, guide = hit
        first = _beats.guided_turn(state, key)
        if first is None or first == turn:
            can_do = [
                *guide["can_do"],
                *(guide.get("express_extra") or [] if _is_express(state) else []),
                _CHAT_TAIL,
            ]
            beat.facts["widget_guide"] = {"can_do": can_do}
            beat.fallback = " ".join(filter(None, [beat.fallback, guide["fallback"]]))
            await _beats.mark_guided(state, key, turn)
        else:
            beat.facts["widget_guide"] = {"reminder": guide["reminder"]}
        return


def guide_action_count(beat_list: list[Any]) -> int:
    """How many actions the turn's widget guide lists (0 for none/reminder)."""
    for b in beat_list:
        wg = (b.facts or {}).get("widget_guide") or {}
        if wg.get("can_do"):
            return len(wg["can_do"])
    return 0


__all__ = ["WIDGET_GUIDES", "attach_widget_guides", "guide_action_count"]
