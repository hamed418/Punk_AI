"""
scripts/chat_autopilot.py
──────────────────────────
Drive the real campaign_builder graph end to end over the live SSE API,
answering every ``pending_action`` from a step_key-keyed table instead of a
human at a terminal.

Reuses chat_terminal.py's auth (`_get_token`) and SSE parsing (`_iter_sse`)
rather than reimplementing them — only the interrupt-answering loop and event
capture are new, because ``_ask`` there calls ``input()`` and the terminal's
``_stream_round`` throws away ``campaign_published`` / ``error`` payloads this
script needs to report and clean up.

Safety, same as live_publish_test.py:
  1. Refuses to run unless ``META_PUBLISH_ACTIVATE=false``.
  2. Always answers the go_live_confirm gate with "leave it paused".
  3. Prints the session id and every id the publish reports, so
     cleanup_test_publish.py can delete them afterwards.

    .venv/Scripts/python.exe scripts/chat_autopilot.py \
        --email user@example.com --password '***' \
        --message "I run a chain of gyms in New York, NY. Want to reach \
                    people who visit fitness centers and yoga studios nearby."
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from chat_terminal import DEFAULT_URL, _get_token, _iter_sse  # noqa: E402

_MAX_TURNS = 40  # generous ceiling so a genuine loop bug fails loud, not silent


def _log(msg: str) -> None:
    print(f"   {msg}", flush=True)


# ── the answer table ────────────────────────────────────────────────────────
#
# Keyed on pending_action["step_key"]. A callable gets the full pending_action
# dict and must return the resume value (str, or JSON-encoded for widget
# submissions). Anything not listed falls back to _default_answer.

def _pick(options: list[str], *prefixes: str) -> str | None:
    for opt in options:
        if any(opt.startswith(p) for p in prefixes):
            return opt
    return None


def _answer_intake_form(action: dict) -> str:
    # Widget-specific payload is merged onto the pending action's top level
    # (wizard_helpers.py: `pending.update(extra)`), not nested under "extra".
    floor = action.get("min_daily_budget") or 12330
    values = {
        "business_name": "Punk Autopilot Gym Co.",
        "business_context": "A chain of boutique gyms and yoga studios in New York.",
        "objective": "TRAFFIC",
        "budget_type": "daily",
        "budget_amount": int(floor) * 3,
        "website_url": "https://example.com",
    }
    return json.dumps({"values": values})


# Run-scoped scratch: the POI list the last map_data carried, plus the caller's
# --max-pois cap. The poi_confirm gate's POIs arrive on a `map_data` event, not
# inside the pending_action, so _round stashes them here for _answer_poi_confirm.
_STATE: dict = {"pois": [], "max_pois": 0}

# A 5.0 from 3 reviews is noise, not a busy store. Rank anything at or above
# this review count ahead of the thin-sample places regardless of star rating.
_MIN_RATINGS_FOR_TRUST = 50


def _rank_poi(p: dict):
    """Best-rated first, but a 5.0 from 3 reviews is noise, not a busy store —
    anything at or above the trust threshold outranks every thin-sample place."""
    n = int(p.get("user_ratings_total") or 0)
    return (n >= _MIN_RATINGS_FOR_TRUST, float(p.get("rating") or 0.0), n)


def _answer_poi_confirm(action: dict) -> str:
    """Confirm the discovered POIs, keeping the best-rated N *per category*.

    Per category, not overall: a search that returns 20 Sephora and 3 Ulta would,
    under a global top-N, drop Ulta entirely and silently answer a different
    question than the one asked. Categories are the same
    ``(source_angle, parent_poi_type)`` groups the frontend renders as tabs, so a
    brand angle splits per brand, an event angle per event, a store set per
    search term. Without --max-pois-per-category this is a plain "yes".
    """
    cap = int(_STATE.get("max_pois") or 0)
    pois = list(_STATE.get("pois") or [])
    if cap <= 0 or not pois:
        return "yes"

    from app.graph.builder.executors.geo import poi_group_id

    groups: dict[str, list[dict]] = {}
    for p in pois:
        groups.setdefault(poi_group_id(p), []).append(p)

    keep: list[dict] = []
    drop: list[dict] = []
    for gid, members in groups.items():
        ranked = sorted(members, key=_rank_poi, reverse=True)
        keep.extend(ranked[:cap])
        drop.extend(ranked[cap:])
        _log(f"    [{gid}] keeping {min(cap, len(ranked))} of {len(ranked)}")
        for p in ranked[:cap]:
            _log(f"      keep  {p.get('rating')}* ({p.get('user_ratings_total')}) {p.get('name')}")

    if not drop:
        return "yes"
    _log(f"    POI trim: {len(keep)} kept across {len(groups)} categor(ies), {len(drop)} dropped")
    return json.dumps({
        "confirm": True,
        "removed": [
            {"name": p.get("name"), "lat": p.get("lat"), "lng": p.get("lng")}
            for p in drop
        ],
    })


def _answer_plan_confirm(action: dict) -> str:
    """Echo back the spec the widget handed us, with action=publish. The plan
    editor's own Publish button is the confirmation — building a spec from
    scratch here would test our JSON encoding, not the plan editor's."""
    spec = action.get("spec")
    if not isinstance(spec, dict):
        raise RuntimeError(f"campaign_plan_confirm carried no spec to echo back; keys={sorted(action.keys())}")
    return json.dumps({"action": "publish", "spec": spec})


_TABLE = {
    "geo_collect_location_type": lambda a: "Target a specific city, Zip or address",
    "geo_collect_locations": lambda a: "New York, NY",
    "geo_collect_det_type": lambda a: _pick(a.get("options") or [], "Search for types of places")
        or "Search for types of places (like gyms, cafes, or parks)",
    "geo_collect_poi_types": lambda a: "gym, fitness center, yoga studio",
    "geo_pois_confirmation": lambda a: _answer_poi_confirm(a),
    "maid_collect_settings": lambda a: json.dumps({"poi_radius_m": 250, "lookback_days": 14}),
    "maid_collect_lookback": lambda a: "14",
    "maid_confirm_results": lambda a: "yes",
    "campaign_publish_mode": lambda a: _pick(a.get("options") or [], "Let Punk setup the campaign")
        or "Let Punk setup the campaign — Let Punk's expert agents create and optimize your entire campaign",
    "campaign_intake_form": _answer_intake_form,
    "campaign_plan_confirm": _answer_plan_confirm,
    # The one answer that matters most: never go live.
    "media_confirm_go_live": lambda a: _pick(a.get("options") or [], "Leave it paused")
        or "Leave it paused — I'll switch it on myself in Ads Manager",
}


def _default_answer(action: dict) -> str:
    """Best-effort answer for any step_key not in the table above — so an
    unexpected slot re-asks instead of the whole run crashing."""
    atype = action.get("action_type", "text_input")
    options = action.get("options") or []
    prefill = action.get("prefill")
    if atype == "option_selection" and options:
        return prefill if prefill in options else options[0]
    if atype == "permission":
        return "yes"
    if atype in ("map_interaction", "file_upload"):
        return prefill or "skip"
    return prefill or ""


def _ask(action: dict) -> str:
    step_key = action.get("step_key") or ""
    fn = _TABLE.get(step_key, _default_answer)
    answer = fn(action)
    _log(f"[{step_key or action.get('action_type')}] -> {str(answer)[:120]}")
    return answer


# ── streaming, with the events chat_terminal's _stream_round discards ───────

def _round(client: httpx.Client, base: str, session_id, body: dict, is_resume: bool) -> dict:
    url = f"{base}/chat/{session_id}/resume" if is_resume else f"{base}/chat"
    out = {"session_id": session_id, "pending": None, "published": None, "error": None, "done": False}
    # A MAID turn now fires one vendor request per POI category, each of which the
    # vendor can take ~130s to answer, so a multi-brand extraction legitimately
    # streams for several minutes before the next pending_action.
    with client.stream("POST", url, json=body, timeout=900) as resp:
        if resp.status_code != 200:
            out["error"] = f"HTTP {resp.status_code}: {resp.read().decode()[:500]}"
            return out
        for event in _iter_sse(resp):
            etype = event.get("type")
            content = event.get("content")
            if etype == "session_id":
                out["session_id"] = content
            elif etype == "pending_action":
                out["pending"] = content
            elif etype == "campaign_published":
                out["published"] = content
            elif etype == "error":
                out["error"] = content
            elif etype == "done":
                out["done"] = True
            elif etype == "map_data":
                if isinstance(content, dict) and content.get("pois"):
                    _STATE["pois"] = content["pois"]
            elif etype == "assistant_message":
                _log(f"AI: {str(content)[:160]}")
    return out


def main() -> int:
    if settings.META_PUBLISH_ACTIVATE:
        print("REFUSING: META_PUBLISH_ACTIVATE is true — would activate real ads.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--message", default=None,
                         help="Opening message — must state market, audience and offer "
                              "so entry_node's WHERE/WHO/WHAT gate passes in one turn. "
                              "Omit with --resume-session to continue a paused one instead.")
    parser.add_argument("--session", default=None,
                         help="Send --message into an EXISTING session instead of opening a new "
                              "one. entry_node's route is non-deterministic: the same opening "
                              "message occasionally lands in chatbot rather than the builder, "
                              "which ends a run with no pending_action. This continues that "
                              "conversation rather than paying for a fresh one.")
    parser.add_argument("--resume-session", default=None,
                         help="Continue a session already paused at an interrupt, instead "
                              "of starting a fresh one — fetches its pending_action via "
                              "GET /chat/{id}/status.")
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""),
                         help="X-API-Key header — every route requires it (app/core/security.py).")
    parser.add_argument("--answer", action="append", default=[], metavar="STEP_KEY=VALUE",
                         help="Override one answer-table entry with a literal value, e.g. "
                              "--answer geo_collect_locations='New York, NY'. Repeatable. "
                              "The value is sent verbatim, so JSON widget payloads work too.")
    parser.add_argument("--stop-after", default=None, metavar="STEP_KEY",
                         help="Halt the run when this step_key is reached, WITHOUT answering "
                              "it — e.g. --stop-after campaign_publish_mode to exercise geo "
                              "and MAID extraction without creating anything on Meta. The "
                              "session stays paused there and can be continued later with "
                              "--resume-session.")
    parser.add_argument("--max-pois-per-category", "--max-pois", type=int, default=0,
                         dest="max_pois", metavar="N",
                         help="At the poi_confirm gate keep only the N best-rated POIs IN EACH "
                              "category (the same source_angle/parent_poi_type groups the UI "
                              "shows as tabs — one per brand, event or search term) and deselect "
                              "the rest. 0 (default) confirms all of them.")
    args = parser.parse_args()
    _STATE["max_pois"] = args.max_pois
    for override in args.answer:
        step_key, _, value = override.partition("=")
        if not _:
            parser.error(f"--answer expects STEP_KEY=VALUE, got {override!r}")
        _TABLE[step_key.strip()] = (lambda v: (lambda a: v))(value)
    if not args.message and not args.resume_session:
        parser.error("one of --message or --resume-session is required")
    base = args.url.rstrip("/")

    with httpx.Client(timeout=900) as client:
        if args.api_key:
            client.headers["X-API-Key"] = args.api_key
        token = _get_token(client, base, args.email, args.password)
        client.headers["Authorization"] = f"Bearer {token}"

        if args.resume_session:
            session_id = args.resume_session
            status = client.get(f"{base}/chat/{session_id}/status")
            status.raise_for_status()
            pending = status.json().get("pending_action")
            if pending is None:
                print("FAIL: session is not paused at an interrupt — nothing to resume.")
                return 1
            result = {"session_id": session_id, "pending": pending, "published": None, "error": None}
        else:
            result = _round(
                client, base, args.session,
                {"message": args.message, **({"session_id": args.session} if args.session else {})},
                is_resume=False,
            )
            session_id = result["session_id"] or args.session
        _log(f"session_id={session_id}")

        turns = 0
        published = result.get("published")
        stopped_early = False
        while result["pending"] and not result["error"] and turns < _MAX_TURNS:
            if args.stop_after and (result["pending"].get("step_key") or "") == args.stop_after:
                _log(f"reached --stop-after {args.stop_after}; leaving the session paused here")
                stopped_early = True
                break
            turns += 1
            answer = _ask(result["pending"])
            result = _round(client, base, session_id, {"value": answer}, is_resume=True)
            session_id = result["session_id"] or session_id
            published = result.get("published") or published  # campaign_published can
            # land on the plan_confirm round, before the later go_live_confirm round
            # (whose own result dict carries no "published" key) overwrites `result`.

        print()
        if result["error"]:
            print(f"FAIL: graph error — {result['error']}")
            print(f"session_id={session_id}")
            return 1
        if stopped_early:
            print(f"OK: stopped at {args.stop_after} as requested (nothing published).")
            print(f"session_id={session_id}")
            return 0
        if turns >= _MAX_TURNS:
            print(f"FAIL: hit the {_MAX_TURNS}-turn ceiling without finishing — "
                  f"an unanswered or looping step_key. session_id={session_id}")
            return 1
        if not published:
            print("FAIL: run ended with no campaign_published event.")
            print(f"session_id={session_id}")
            return 1

        print("OK: published")
        print(json.dumps(published, indent=2))
        print(f"session_id={session_id}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
