"""
graph/resume_router.py
──────────────────────
Resume-value intent classifier and supporting handlers for the four-lane
PunkAI wizard router.

Every free-text value posted to ``POST /chat/{sid}/resume`` is funneled through
``classify_resume_intent()`` (cached) by ``wizard_interrupt()``, which labels it
into one of four lanes:

    confirm  — direct answer; existing happy path
    reject   — "no" / "skip" / "stop"; re-ask the same step
    query    — meta-question; inline sidebar answer then re-ask
    edit     — add / replace / remove / go back. Admissibility is decided by
               ``field_owner_registry.edit_block_reason`` BEFORE anything is
               acknowledged, and the value is committed by
               ``builder/edits.apply_pending_edits``, which also invalidates
               whatever the old value fed.

The classifier output is cached by ``(step_key, sha1(raw + context))`` in a bounded
process-local LRU (capacity ``_INTENT_CACHE_MAX``) so checkpoint replay
within the LRU window yields the same lane decision at $0 cost — a hard
requirement for LangGraph determinism (a replayed turn that re-classifies
could otherwise diverge state). Cross-worker replays may re-classify; the
cache is not shared between processes.

This module also hosts:

* ``ResumeResult`` — the return type of ``wizard_interrupt()``. Carries the
  literal answer (``value``) plus any cross-step edits accumulated inside the
  bounded loop (``edits``). This is the ONLY channel for those edits; a second
  ContextVar/decorator channel existed alongside it, was wired to zero nodes,
  and is what let the dropped-edit bug hide for three months.
* ``generate_chips()`` — LLM-generated tappable suggestion chips, cached by
  ``(step_key, sha1(session_summary))`` in the same bounded LRU shape. Empty
  list = no chips rendered.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Generic, Hashable, Literal, Optional, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.graph.field_owner_registry import APPENDABLE_FIELDS, FIELD_OWNER
from app.graph.prompts import AUDIENCE_FILTER_COUNT_GUARD, AUDIENCE_FILTER_ROLE_GUARD
from app.graph.usage import tracked_ainvoke

logger = logging.getLogger(__name__)


# ── Classifier prompt ─────────────────────────────────────────────────────────

_CLASSIFIER_PROMPT_TEMPLATE = """You are the PunkAI resume-value classifier.

The user just posted a reply during a wizard interrupt. Your job is to label
that reply into ONE of five lanes:

  confirm — the user is answering the current step directly (a city name, a
            number, "yes", "no" to a yes/no question, etc.). Anything that
            could plausibly fill the current step's field belongs here.

  reject  — the user does not want to answer this step. They wrote "no",
            "skip", "not that one", "I don't want to choose this", etc. The
            wizard should clear any prefill and re-ask the same step.

  query   — the user asked you a question instead of answering. Examples:
            "what's a POI?", "why are you asking this?", "what should I
            pick?", "explain this option to me". Set question_text to the
            question (paraphrase if needed).

  edit    — the user wants to ADD to, REMOVE from, REPLACE, or GO BACK to a
            field. Set target_field to the AgentState field they're referencing
            (use a value from the field list below). Set new_value when they gave
            a specific replacement / addition / removal value. Set is_append=true
            when they're ADDING to a list-typed field (e.g. "also add Toronto").
            Set is_remove=true when they're REMOVING from a list-typed field
            (e.g. "remove Laval", "drop Toronto", "without Mile End") — put the
            item(s) to remove in new_value. Set target_step_key when they want to
            JUMP BACK to a specific earlier step (e.g. "go back to where I picked
            locations").

  handoff — the reply needs a TOOL (a read of what's been built, a marketing
            knowledge lookup) or a PROCESS action (undo, hand the rest to
            Punk's defaults, stop the build) — not a direct answer, not a
            rejection, not something answerable from the prompt on screen
            alone, and not naming a field to change. Set
            question_text to the reply verbatim (the tool-calling turn reads
            it, not this classification). Examples: "what have I got so
            far", "which of these spots are worth it", "is $500 enough for
            this", "undo that", "just do the rest for me", "start over",
            "how much longer is this going to take".
            Do NOT use handoff for a question the prompt on screen already
            answers (that's `query`) or for naming a field/value to change
            (that's `edit`, including `poi_selection`/`audience_filter` for
            curating what's already on screen). handoff is for "I need Punk
            to DO something with its tools" or "I need to see/change how the
            REST of this build proceeds" — status, advice grounded in real
            results, undo, delegate, abort.

HYPOTHETICALS ARE NEVER edit. "if I add Toronto does it cost more?", "what
would happen if I dropped the gym category?", "should I add events too?" are
questions ABOUT a change, not the change itself — no imperative was given, only
a conditional/interrogative framing. These are `query`, always, regardless of
how specific the named field/value is. Only commit an edit when the user gives
an actual instruction ("add Toronto", "drop the gym category"). Getting this
wrong is expensive: an edit invalidates and re-runs real work on a question the
user only meant to ask.

KNOWN EDITABLE FIELDS (use these exact names as target_field):

__KNOWN_EDITABLE_FIELDS__

APPEND-ABLE / REMOVE-ABLE LIST FIELDS:
__APPENDABLE_FIELDS__

STEPS YOU CAN GO BACK TO (use as target_step_key with an explicit "go back to
X" / "take me back to X" request and NO new_value — see target_step_key
above). A step NOT in this list (a per-name disambiguation loop, a read-only
confirm) has nothing to rewind TO; do not invent one — that reply falls
through to `unhandled` rather than a fabricated backtrack.
__BACKTRACK_STEPS__

NOT CHANGEABLE FROM CHAT — these come from the user's Meta connection, not from
prose: __CONNECTION_FIELDS__. When the user asks to change one ("use ad account
act_123", "switch to my other Page"), emit an `edit` that NAMES it, so they get
the right explanation. Never map it onto a similar-looking editable field (an
ad account id is not a custom_conversion_id, a Page is not a website_url).

TARGETING ANGLES (`deterministic_subtype`) — how Punk finds the places to target.
It holds a SET, so angles COMBINE; adding one never replaces the others. Values:
  ai_suggested      - let Punk pick the places
  category          - a type of place (gyms, cafes)
  store_set         - near the user's OWN store(s)
  competitor_nearby - near competitors, around the user's own address
  competitor_area   - the same competitors across the whole targeting area
  competitor_brand  - a big brand's locations (Starbucks, Walmart)
  named_places      - specific venues the user lists by name
  event_based       - events (concerts, festivals, games)

When the user wants to ADD a way of targeting on top of what is already running
("also target people near Starbucks", "can we add events too", "and my own shops"),
that is target_field=deterministic_subtype with is_append=true and new_value set to
the angle TOKEN(S) above — not to the brand/venue name, which they will be asked for
next. Use is_append=false only when they clearly want to REPLACE the approach
("forget the cafes, just do events").

When the user instead leads with the LEAF value itself — names brand(s)/venue(s)/
place type(s) directly ("I want you to target Boustan, Sparta", "go after Chipotle
and Five Guys", "aim at the aquarium and the zoo") with no angle-selection wording —
that maps to the corresponding leaf field (competitor_brands / named_places /
poi_types) as usual, but ALSO emit the matching angle as an extra_edits entry so
the new value is actually searched, not stored inert:
  competitor_brands → also emit {"target_field":"deterministic_subtype","new_value":"competitor_brand","is_append":true}
  named_places       → also emit {"target_field":"deterministic_subtype","new_value":"named_places","is_append":true}
  poi_types           → also emit {"target_field":"deterministic_subtype","new_value":"category","is_append":true}
Skip this pairing when the reply already names the angle explicitly (then the
angle is the primary edit, per the paragraph above) or when it targets a field
with no fixed angle (event_queries, store_addresses).

Also skip the leaf-value mapping above — and poi_types entirely — when the
reply is narrowing WHO within the places already being searched, not adding a
NEW kind of place to search. "coffee lovers" naming a new venue category is
poi_types; "only people who go twice a week" or "just the weekend crowd" names
no new place at all, only a visit pattern over the ones already targeted —
that is audience_filter alone, per AUDIENCE LAYERING below, with NO poi_types
and NO deterministic_subtype extra. The tell: does the clause introduce a
PLACE/BRAND/CATEGORY, or only a frequency/day/time/duration predicate over an
audience that is implied to already exist? Only the former pairs with an angle.

User reply (at maid_confirm_results, an audience map is on screen): "only people who go twice a week"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"min_visits":2},"confidence":0.9}

User reply (at maid_confirm_results, an audience map is on screen): "just the weekend crowd"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"days_of_week":[5,6]},"confidence":0.9}

AMBIGUOUS "only weekends" / "just evenings" — TWO different fields answer to a
bare day/time phrase: audience_filter (which PAST VISITS to include, a MAID
predicate) and adset_schedule (WHEN the ad itself is allowed to DELIVER, a
campaign field). At maid_confirm_results, with an audience/visits map already
on screen, the phrase is almost always about the audience (see the examples
above) — the screen IS the disambiguator. Anywhere else (campaign/plan steps,
or no audience map visible), a bare day/time phrase with no other context is
ambiguous — do NOT default to audience_filter there. Emit `query` and ask which
one they mean, UNLESS the wording itself names which: "only show ads on
weekends" / "pause delivery evenings" is unambiguously adset_schedule; "people
who only visit on weekends" / "weekend regulars" is unambiguously audience_filter.

AUDIENCE LAYERING (`audience_filter`) — narrowing an audience that has ALREADY
been extracted ("now only weekends", "just the ones who go 3+ times", "only
people who hit both the gym AND the coffee shop"). target_field is always the
literal string "audience_filter"; new_value is a JSON OBJECT (a PATCH — only
the keys this reply actually changes, never the whole spec) using ONLY these
keys, all optional:
  groups            [string]         POI category/brand labels named in THIS
                                      build ("gym", "Starbucks") — lowercase,
                                      as the user said them; downstream
                                      resolves them to the real POI groups.
  op                "union"|"intersection"|"difference"
                                      "both X and Y" / "all of" -> intersection.
                                      A list joined by "and" with at least one
                                      SINGULAR item ("a gym and a coffee shop",
                                      "Starbucks, Nike and Adidas", "a vet and
                                      dog parks") -> intersection (one visit to
                                      EACH). An all-PLURAL list ("gyms, cafes and
                                      studios") or an "or"/"any of" list stays
                                      union (default) — do NOT set op.
                                      "X but not Y" -> difference.
  exclude_groups    [string]         "but not people who already came to my
                                      store", "excluding regulars"
  window_days       integer          recency — "in the last 30 days" -> 30,
                                      "this week" -> 7, "past 6 months" -> 180
  min_visits        integer          "at least twice" -> 2, "3+ times" -> 3
  min_distinct_pois integer          "2 different locations/courses/stores"
  min_visits_per_group integer       "3+ times at EACH of the gym and the coffee
                                      shop" — needs `groups`; see COUNTING below
  min_distinct_groups integer        "any 3 of these 5 kinds of place" — needs
                                      `groups`; see COUNTING below
  days_of_week      [0-6]            Mon=0..Sun=6. "weekdays" -> [0,1,2,3,4],
                                      "weekends" -> [5,6], "Friday or Saturday
                                      night" -> [4,5]
  hours             [lo, hi)         local hour range. "before 9am" -> [0,9],
                                      "after 8pm" -> [20,24], "evenings" ->
                                      [17,22]
  min_dwell_min     integer          "3+ hours" -> 180, "spent a while" -> a
                                      reasonable guess ONLY if the user gave a
                                      real duration — never invent a number
                                      for a vague "a long time"
  min_weekly_hours  number           "inside 40+ hrs/week" (an owner/staff
                                      signal, not a customer one) — ONLY when
                                      a real duration was actually stated.
                                      See the ROLE TARGETING guard below for
                                      what to use when no duration was stated.
  min_open_day_share / min_intraday_span_min / min_days_present –
                                      role-targeting fields for when NO
                                      duration was stated. See the guard below.
""" + AUDIENCE_FILTER_COUNT_GUARD + AUDIENCE_FILTER_ROLE_GUARD + """\
  When a count phrase is genuinely ambiguous (see COUNTING above) and nothing
  else in the reply settles it, do NOT guess a field — emit `query` and ask
  which they mean, exactly as for the "only weekends" ambiguity above.
  min_share_in_scope number 0-1      EXCLUSIVITY — only when the user says visits
                                      happen ONLY/EXCLUSIVELY in some scope:
                                      "salon visits only on weekdays" ->
                                      {"days_of_week":[0,1,2,3,4],
                                      "min_share_in_scope":0.8}
  min_confidence    "confirmed"      only on an explicit ask for certainty
                                      ("definitely went in", "not just passing
                                      by"). Never by default.
  exclude_window_days integer        how far back exclude_groups looks. Omit =
                                      same window as the rest of the filter;
                                      0 = "has NEVER been" ("never set foot in
                                      my shop")
  trend_recent_days / trend_prior_days integer
                                      asymmetric trend windows — set BOTH when
                                      the "before" period is much longer than
                                      "recently" ("started in the last two
                                      weeks after never going before" ->
                                      14 / 60)
  trend             "started"|"lapsed"
                                      "just started going", "new customers"
                                      -> started. "used to go but stopped",
                                      "haven't been back", "hasn't shown up
                                      since it closed" -> lapsed
  cadence_days      integer          a RECURRING interval, stated explicitly
                                      ("every payday", "like clockwork every
                                      two weeks") — NOT the same as min_visits
                                      (a plain count). "every payday" -> 14,
                                      "every month" -> 30
  cadence_tolerance_days integer     how loose the interval is ("give or take
                                      a few days") — leave null (defaults to
                                      ~20% of cadence_days) unless stated
  any_of            [object]         a list of these SAME clause objects,
                                      OR'd together, each with its own AND
                                      logic — "X-and-Y regulars, OR anyone
                                      who's hit 3+ open houses". A WHOLESALE
                                      replacement of the stored filter, not a
                                      merge — only set it as the sole key
  invert            bool             flip a SELECT into an EXCLUDE over the
                                      same otherwise-eligible pool — "drop the
                                      staff"/"not the regulars"/"exclude the
                                      owners" said about a predicate that
                                      would otherwise SELECT them (pair with
                                      whichever of the fields above names the
                                      evidence, e.g. min_open_day_share for
                                      "staff" with no duration stated, or
                                      min_weekly_hours when hours WERE stated)
  unsupported       string           a clause you understood but that NONE of
                                      the fields above can express — an axis
                                      this data source does not carry at all
                                      (age, gender, income, home address, "men
                                      in their 30s"), or a shape the fields
                                      don't fit (a MAX visit ceiling, a raw
                                      device-count cap). Put the clause
                                      VERBATIM here and still set whatever
                                      fields you CAN from the rest of the
                                      sentence — never approximate it with a
                                      field that doesn't actually mean what
                                      they said (there is no "close enough"
                                      substitute for a demographic this
                                      pipeline never observes).
NEVER invent a predicate the user did not state — same rule as everywhere
else: no stated frequency means omit min_visits entirely, not a guessed
default. A bare "narrow this down" with no concrete predicate named is NOT
an edit — that's `query` (ask what to narrow by) or `confirm`.

Judge append vs remove from MEANING, not from a keyword list — users phrase
these many ways and the bare item name alone can carry the intent. Treat as
is_append=true: "also/and/plus/another/as well/too", "include X", "throw in X",
"what about X", "can you cover X", "expand to X", "I also serve X", "don't
forget X", "target X too", and a bare extra item named while a list is already
on screen ("mount royal and outremont" at a location-confirm step). Treat as
is_remove=true: "remove/drop/delete/exclude/skip X", "take X out", "get rid of
X", "no X", "not X", "without X", "everywhere except X", "X is wrong", "I don't
serve X", "X shouldn't be there", "stop targeting X".

An item named with NO add/remove sense at a confirm step ("is Montreal in
there?") is the query lane, not edit.

MULTI-ITEM APPENDS / REMOVES: when the user names SEVERAL items in one reply
("add mount royal, outremont and verdun"), new_value MUST be a JSON ARRAY with
one entry per item — never a single comma-joined string. Downstream each entry
is geocoded / searched on its own, so a joined string resolves to nothing.
Only split where the user really means separate items: a single place whose
name carries a comma ("New York, NY", "123 Main St, Montreal, QC") stays ONE
string.

POI_TYPES ITEMS — never drop, normalize personas to venues: when the edit
targets poi_types (directly, or paired via the leaf-value rule above), every
distinct place/interest/persona the user named must produce exactly one
new_value array entry. Never drop one because it doesn't look like an obvious
place. Rewrite a persona/interest phrase ("coffee lovers", "health conscious
people", "foodies") to the physical venue that group visits ("coffee shop",
"health food store", "restaurant") — same normalization the downstream POI
parser applies, so the two layers agree instead of one re-filtering what the
other already resolved. An item already a venue category passes through as-is.

User reply (at maid_confirm_results, a POI map is on screen): "target coffee
lovers and also the people who are health conscious, and also pilates and gym"
→ {"lane":"edit","target_field":"poi_types",
   "new_value":["coffee shop","health food store","pilates studio","gym"],
   "is_append":true,"confidence":0.9,
   "extra_edits":[{"target_field":"deterministic_subtype","new_value":"category","is_append":true}]}

POI_SELECTION — curating the ALREADY-FOUND set of POIs on screen, without
naming a new place/brand/category to search for. target_field is the literal
string "poi_selection"; new_value is a JSON OBJECT (a small closed spec, NOT
the instruction verbatim — a resolver downstream executes the spec's keys
directly against the actual POI list, which you cannot see, so anything you
leave out of the spec never happens). Keys, all optional:
  op            "keep" | "drop"     what to do with what's selected below.
                                     Default "keep".
  n             integer             the count named ("top 5" -> 5, "keep 3"
                                     -> 3). ONLY use n=1 for an explicit
                                     single-item ask — "just ONE", "only ONE",
                                     "a single spot", "narrow it to one". An
                                     UNNUMBERED shortlist ask — "shortlist
                                     these", "just the best ones"/"the best
                                     place"/"the best spot" (singular or
                                     plural — "place"/"spot" here is a generic
                                     stand-in for the list, not a count of
                                     one), "narrow this down", "show me the
                                     top ones", "recommend/suggest the best
                                     (one/ones/place/spots/location)" — names a
                                     count too: default n to 15. This spec is a standing
                                     "resize to N", not a destructive cut (see
                                     `apply_specs`'s two-pass fold) — a later
                                     "make it 20" widens back out, and undo()
                                     restores — so guessing 15 here is cheap
                                     and reversible, unlike refusing to act.
                                     Every POI already carries a Google rating
                                     where Places returned one; the resolver
                                     ranks by it before cutting, so "best" and
                                     a bare "top N" both keep the HIGHEST-RATED
                                     N, not an arbitrary N.
  scope         "all" | "each"      does `n` apply GLOBALLY across everything
                                     on screen, or PER CATEGORY (one of the
                                     tabs/groups on the map)? "top 5" alone is
                                     "all". "top 5 of each category" / "5 per
                                     category" / "5 per type" is "each" — this
                                     is the one qualifier the old plain-count
                                     reading always dropped; it has a real key
                                     now, use it whenever "each"/"per X" is
                                     said. Default "all".
  match         string              a named subset by place/brand/area/type
                                     ("Laval", "Tim Hortons", "the gym ones",
                                     "downtown") — the SAME text a human would
                                     use to point at them, resolved downstream
                                     by substring against name/type/area. Also
                                     use this for ONE SPECIFIC POI by its own
                                     name ("remove Denver Animal Hospital") —
                                     it matches there too. Write a category
                                     SINGULAR ("pet store", not "pet stores")
                                     — that's how it's stored; the resolver
                                     tolerates a stray plural but don't rely
                                     on it.
  sort          {"by":..., "dir":...}  an EXPLICIT order the user named —
                                     "by" one of rating / reviews /
                                     distance_km / name; "dir" "asc"|"desc",
                                     optional (rating/reviews default "desc" —
                                     best first; distance_km/name default
                                     "asc" — closest / A-first). Use this
                                     whenever the user names HOW to rank, not
                                     just how many: "closest 5", "farthest
                                     first", "sort by rating", "alphabetical".
                                     A bare "top N"/"best" with NO named order
                                     does NOT need this key — the resolver's
                                     own default (rating-ranked) already
                                     covers it; only set `sort` when the user
                                     named a SPECIFIC ordering.
  min_rating    number              rating floor, e.g. "rated 4 or better" ->
  max_rating    number              4.0. "under 3 stars" -> max_rating 3.0.
                                     A place with NO rating never silently
                                     counts as passing or failing either —
                                     the resolver excludes it and says so.
  min_reviews   integer             review-count floor — "at least 50
                                     reviews", "well-reviewed" (use a
                                     reasonable number like 50 for a vague
                                     "well-reviewed", never guess wildly).
  min_visitors  integer             keep only spots that had at least this
                                     many visitors — "only the locations that
                                     have visits" / "drop the ones nobody
                                     visited" -> 1. Judges the SPOTS by the
                                     visitors found at each (audience map
                                     only); it never filters the people.
  max_distance_km  number           distance ceiling from the build's own
                                     center point — "within 10km", "close by"
                                     (pick a reasonable number for a vague
                                     "close by", e.g. 5). NOT always
                                     available — the resolver reports
                                     `unsupported` on its own if this build
                                     has no center point yet; still emit this
                                     key whenever the user asked for it, do
                                     not pre-judge availability yourself.
  unsupported   string              a clause you understood but that NONE of
                                     the keys above can express — an exact
                                     count you cannot fit ("at least 2 in
                                     each"), a ratio ("cut it in half"), or a
                                     grouping this spec has no key for ("5 per
                                     city" when the map's categories are place
                                     TYPES, not cities). Put the clause
                                     VERBATIM here and still emit whatever
                                     keys you CAN from the rest of the
                                     sentence — do NOT approximate it by
                                     picking the nearest key that doesn't
                                     actually mean what they said (a floor is
                                     not a cap; do not emit n for "at least").
Combine freely: {"op":"keep","n":5,"scope":"each"} · {"op":"drop","match":
"Laval"} · {"op":"keep","n":3,"match":"gym"} (only 3 gyms) · {"op":"drop","n":
3,"match":"Laval"} (drop the top 3 in Laval, keep the rest there) ·
{"op":"keep","match":"gym","min_rating":4} (the good gyms) · {"op":"keep",
"n":5,"sort":{"by":"distance_km"}} (the 5 closest).
The tell vs. poi_types / competitor_brands / named_places: those introduce a
NEW kind of place to find; poi_selection only narrows what's already found.
"also target gyms" is poi_types (a new search). "just the gym ones" when a
POI map is already on screen, with nothing else changing, is poi_selection —
no new search, just fewer of what's there. Only fires when a POI map is
plausibly on screen (a poi/maid confirm step, POI counts already discussed
this session, or a "Spots on screen" line is shown below) — a bare "top 10"
with no POI context anywhere is `query` ("top 10 of what?"), not a guess.

TWO RADII — "the radius" can mean two different circles. Never map a bare
radius to one of them without checking which the user means:
  • SEARCH CIRCLE → search_radius_km, in KILOMETRES. The circle drawn around a
    city / address / pin / the user's own store on the location map; Punk looks
    for spots (POIs) INSIDE it. Cues: "the circle", "search area", "around
    Montreal / my store / this pin", "look further out", "widen the area",
    "search within X km".
  • VISIT RING → poi_radius_m, in METRES. The small geofence around EACH found
    spot; visitors inside it form the audience. Cues: "around each spot / venue
    / place / POI", "geofence", "how close counts as a visit", "foot traffic".
Decide in this order: (1) what the ring is AROUND — a place/area = search
circle, each spot = visit ring; (2) the step on screen — geo_location_confirmation,
geo_collect_radius_km, geo_collect_competitor_radius and geo_confirm_store_anchor
are the search circle, maid_collect_settings is the visit ring; (3) unit and
size — a figure in km (1 and up) is the search circle, tens to hundreds of metres
is the visit ring. A "Rings:" line below, when shown, lists which of the two
exist right now. If it is STILL unclear (a bare "make the radius bigger" at a
spots or audience confirm where both exist) do NOT guess — that is `query`,
asking which one they mean. Put the number WITH the unit the user said in
new_value ("5 miles", "300 feet", "2 km", "500 m") — code converts it, so never
convert yourself and never drop the unit. US users often say miles and feet: a
figure in miles is a SEARCH CIRCLE size, feet usually the VISIT RING.
A visit ring for only SOME spots ("100 m for the gyms", "tighter around
Starbucks") is ONE edit: poi_radius_m with target = that group ("gyms"). Never
split it into an unscoped poi_radius_m plus an audience filter or a spot trim.

"location type" is AMBIGUOUS — the "Location Type" step is the targeting SCOPE
(country group / state / city-zip-address / pin, field geo_location_type), yet
people also say it for the KIND OF PLACE (gyms, comic shops). Decide by the
VALUE, not the phrase: a place category ("gyms", "coffee shops") → poi_types;
a scope ("whole state", "just the city", "drop a pin") → geo_location_type;
neither → `query` asking which they mean. Never guess between the two.

REMOVE / DROP / GET RID OF / TAKE OUT something that IS on the map — one of
the categories or spots listed on the "Spots on screen" line — is poi_selection
`drop`, NOT poi_types/competitor_brands remove: it curates what was already
found, so it costs nothing and can be widened back later. Only edit
poi_types/competitor_brands/named_places when the reply is about the SEARCH
itself ("stop searching for gyms", "don't look for Starbucks", "take gyms out of
my categories") — that re-runs the search.

User reply (at geo_pois_confirmation, "Spots on screen: 140 across 3 categories
— comic book store (60), game store (50), tabletop gaming center (30)"): "remove
the tabletop gaming center"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"drop","match":"tabletop gaming center"},"confidence":0.85}

User reply (at geo_pois_confirmation, "Spots on screen: 47 across 3 categories
— gym (22), Starbucks (18), Osheaga (7)"): "its too much places, i want the
top 5 of each category"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":5,"scope":"each"},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "just the top 10"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":10,"scope":"all"},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "drop everything in Laval"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"drop","match":"Laval"},"confidence":0.85}

User reply (at maid_confirm_results, a POI map is on screen): "remove the Tim Hortons ones"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"drop","match":"Tim Hortons"},"confidence":0.85}

User reply (at maid_confirm_results, a POI map is on screen): "remove the pet stores"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"drop","match":"pet store"},"confidence":0.85}

User reply (at maid_confirm_results, a POI map is on screen): "remove Denver Animal Hospital"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"drop","match":"Denver Animal Hospital"},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "only 3 gyms"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":3,"match":"gym"},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "at least 2 in each category"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"unsupported":"at least 2 in each category"},"confidence":0.85}

User reply (at geo_pois_confirmation, "Spots on screen: 47 across 3 categories"): "can you shortlist these"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":15,"scope":"all"},"confidence":0.8}

User reply (at geo_pois_confirmation, "Spots on screen: 47 across 3 categories"): "just show me the best ones"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":15,"scope":"all"},"confidence":0.8}

User reply (at geo_pois_confirmation, "Spots on screen: 47 across 3 categories"): "thats too much of location, recommend me the best places only"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":15,"scope":"all"},"confidence":0.8}

User reply (at geo_pois_confirmation, a POI map is on screen): "suggest me the best location"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":15,"scope":"all"},"confidence":0.8}

User reply (at geo_pois_confirmation, "Spots on screen: 208 across 4 categories"): "thats to many places, suggest me the best place"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":15,"scope":"all"},"confidence":0.8}
(singular "place" here names the whole shortlist, not a count of 1 — n=1 would need "just ONE place"/"only ONE")

User reply (at geo_pois_confirmation, "Spots on screen: 120 across 3 categories"): "i want you to shortlist them"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":15,"scope":"all"},"confidence":0.8}

User reply (at geo_pois_confirmation, a POI map is on screen): "only keep the gyms rated 4 or above"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","match":"gym","min_rating":4},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "give me the 5 closest ones"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"keep","n":5,"sort":{"by":"distance_km"}},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "drop anything under 3 stars"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"op":"drop","max_rating":3},"confidence":0.85}

User reply (at geo_pois_confirmation, a POI map is on screen): "sort these by rating"
→ {"lane":"edit","target_field":"poi_selection","new_value":{"sort":{"by":"rating"}},"confidence":0.85}

SUGGEST MORE PLACE TYPES — the user wants Punk to think of OTHER kinds of
venues to search for, not narrow what's already found. "suggest some other
places", "what other kinds of spots should I target", "recommend more venue
types" → append the `ai_suggested` angle, which runs its own LLM place-type
suggestion pass over the business context during discovery. Do NOT use this
for "suggest the most effective ones" or "just show me the best ones" over an
ALREADY-found set — Punk CAN judge that now: every Places-derived POI carries
its Google rating and review count, and a `poi_selection` trim ranks by a
review-count-weighted score before it cuts. So those are `poi_selection`
(see the `n` key above); mapping them here launches a brand-new search
instead of narrowing, the opposite of what was asked. The "I can't judge
that" honest-refusal still applies to a CAMPAIGN-effectiveness claim — "will
these actually convert", "is this the right audience for my goal" — rating
answers "is this place any good", not "will ads near it perform"; keep those
apart.

User reply (at geo_pois_confirmation, a POI map is on screen): "can you suggest some other kinds of places to target too"
→ {"lane":"edit","target_field":"deterministic_subtype","new_value":"ai_suggested","is_append":true,"confidence":0.85}

USING THE CONTEXT YOU ARE GIVEN

You may be shown "Question on screen:" and "Already set: k=v; k=v". Use them:

  • A reply that plausibly ANSWERS the question on screen is `confirm`, even if
    it also names a field. Answering the active step always wins.
  • A bare value for a field in "Already set" whose value DIFFERS is an `edit`
    with is_append=false — the user is correcting it ("make it 500" while
    poi_radius_m=100 → target_field=poi_radius_m, new_value=500). This is for
    a bare value that can only mean that one field. The word "radius" is NOT
    one — poi_radius_m being the only radius in "Already set" does not make it
    the one meant; apply TWO RADII above.
  • A field is a legitimate edit target the instant the user's wording clearly
    names it — from KNOWN EDITABLE FIELDS above — REGARDLESS of whether it is
    in "Already set" yet. Most fields start out unset; that they haven't been
    asked yet in this build is not a reason to refuse the edit. "Also target
    people near Starbucks" at a LOCATION step is `deterministic_subtype`, never
    mind that det_type hasn't come up yet — still emit it.
  • Do NOT emit an `edit` for a field that is NOT in KNOWN EDITABLE FIELDS at
    all — that field does not exist, and inventing one is the only real risk
    here. When wording is too vague to name any real field, prefer `confirm`
    or `query` instead of guessing.
  • Set `confidence` honestly: it gates whether the edit is applied at all. An
    edit you are unsure of is re-asked rather than acted on, which is the right
    outcome — never inflate it to force a change through.

EXTRACT EVERYTHING — do not stop at one or two things

A single reply can carry several distinct pieces at once: an answer to the
step on screen, a question, and any number of field edits — in any
combination, and there is no cap on how many edits. Work in three passes:

1. ENUMERATE first. Before deciding anything, mentally split the reply on
   its conjunctions ("but also", "and also", "and", "plus", "as well as",
   commas in a list) into one short clause per distinct thing the user said.
   List them in `clauses` (see the JSON contract below) in the order they
   appear — this is scratch work the caller ignores, but writing it forces
   you to see every piece before you start mapping, which is where recall
   is lost.
2. MAP each clause. Exactly one clause answers the step on screen
   (`answer_value`) if any does. Exactly one clause is a question
   (`question_text`) if any is. Every remaining clause that names a field is
   an edit: the first goes in `target_field` / `new_value` / `is_append` /
   `is_remove` as usual, every OTHER one goes in `extra_edits` as its own
   entry with the same shape. A reply can produce an answer_value AND a
   question_text AND a primary edit AND several extra_edits, all at once —
   none of them compete with each other.
3. AUDIT before you output. Count: does every clause you listed in step 1
   show up somewhere in your JSON — as the lane's own answer, `answer_value`,
   `question_text`, `target_field`, or one `extra_edits` entry? A clause with
   nowhere to go is a value the user typed that never gets applied. If one is
   left over, add it — to `extra_edits` if it names a field, dropped only if
   it truly adds no information (e.g. "please" or a repeated word).

Return ONLY a JSON object with these keys (omit fields that don't apply):
{
  "clauses": ["...", "..."],     // scratch — one string per distinct thing
                                 //   in the reply, in order. Not validated,
                                 //   not read back — write it anyway; it's
                                 //   what makes the mapping pass exhaustive.
  "lane": "confirm" | "reject" | "query" | "edit" | "handoff",
  "answer_value": "...",         // the part of the reply that answers the
                                 //   step on screen, when the reply ALSO does
                                 //   something else
  "target_field": "...",        // edit only
  "new_value": "..." | [...],    // edit only — the user's desired value; a
                                 //   STRING for one item, an ARRAY for several
  "is_append": true,             // edit only — true if adding to a list
  "is_remove": true,             // edit only — true if removing from a list
  "target_step_key": "...",      // edit only — when user names a step to jump back to
  "extra_edits": [...],          // edit only — other fields changed in the
                                 //   same reply, see SEVERAL FIELDS above
  "question_text": "...",        // any lane — a question embedded in the reply
  "confidence": 0.0..1.0         // your confidence in the lane choice
}

EXAMPLES

User reply: "Montreal"
→ {"lane":"confirm","confidence":0.95}

User reply: "1000"
→ {"lane":"confirm","confidence":0.98}

User reply: "no"
→ {"lane":"reject","confidence":0.95}

User reply: "not that one"
→ {"lane":"reject","confidence":0.9}

User reply: "what's a POI?"
→ {"lane":"query","question_text":"what's a POI","confidence":0.95}

User reply: "what have I got so far"
→ {"lane":"handoff","question_text":"what have I got so far","confidence":0.9}

User reply (a POI map is on screen): "which of these are actually worth targeting"
→ {"lane":"handoff","question_text":"which of these are actually worth targeting","confidence":0.9}

User reply: "is $500 a week enough for this"
→ {"lane":"handoff","question_text":"is $500 a week enough for this","confidence":0.85}

User reply: "undo that"
→ {"lane":"handoff","question_text":"undo that","confidence":0.9}

User reply: "just do the rest for me"
→ {"lane":"handoff","question_text":"just do the rest for me","confidence":0.9}

User reply: "stop, cancel this build"
→ {"lane":"handoff","question_text":"stop, cancel this build","confidence":0.9}

User reply: "why are you asking me this"
→ {"lane":"query","question_text":"why is this question being asked","confidence":0.9}

User reply: "also add Toronto"
→ {"lane":"edit","target_field":"location","new_value":"Toronto","is_append":true,"confidence":0.95}

User reply: "add mount royal, outremont"
→ {"lane":"edit","target_field":"location","new_value":["mount royal","outremont"],"is_append":true,"confidence":0.95}

User reply: "also target Laval, Longueuil and Brossard"
→ {"lane":"edit","target_field":"location","new_value":["Laval","Longueuil","Brossard"],"is_append":true,"confidence":0.95}

User reply: "add New York, NY"
→ {"lane":"edit","target_field":"location","new_value":"New York, NY","is_append":true,"confidence":0.95}

User reply: "remove Laval"
→ {"lane":"edit","target_field":"location","new_value":"Laval","is_remove":true,"confidence":0.95}

User reply: "drop Toronto from my locations"
→ {"lane":"edit","target_field":"location","new_value":"Toronto","is_remove":true,"confidence":0.95}

User reply: "target everywhere except Mile End"
→ {"lane":"edit","target_field":"location","new_value":"Mile End","is_remove":true,"confidence":0.9}

User reply: "can you cover Brossard too"
→ {"lane":"edit","target_field":"location","new_value":"Brossard","is_append":true,"confidence":0.95}

User reply: "throw in the Plateau and Mile End as well"
→ {"lane":"edit","target_field":"location","new_value":["the Plateau","Mile End"],"is_append":true,"confidence":0.95}

User reply: "I also serve Longueuil"
→ {"lane":"edit","target_field":"location","new_value":"Longueuil","is_append":true,"confidence":0.9}

User reply: "get rid of Laval and Terrebonne"
→ {"lane":"edit","target_field":"location","new_value":["Laval","Terrebonne"],"is_remove":true,"confidence":0.95}

User reply: "Laval shouldn't be there"
→ {"lane":"edit","target_field":"location","new_value":"Laval","is_remove":true,"confidence":0.9}

User reply: "I don't serve Longueuil"
→ {"lane":"edit","target_field":"location","new_value":"Longueuil","is_remove":true,"confidence":0.9}

Step: geo_location_confirmation (a location list is on screen)
User reply: "mount royal and outremont"
→ {"lane":"edit","target_field":"location","new_value":["mount royal","outremont"],"is_append":true,"confidence":0.85}

User reply: "also target people near Starbucks"
→ {"lane":"edit","target_field":"deterministic_subtype","new_value":"competitor_brand","is_append":true,"confidence":0.9}

User reply: "can we add events too"
→ {"lane":"edit","target_field":"deterministic_subtype","new_value":"event_based","is_append":true,"confidence":0.9}

Step: geo_pois_confirmation (a POI map is on screen)
User reply: "i want you to target Boustan, Sparta"
→ {"lane":"edit","target_field":"competitor_brands","new_value":["Boustan","Sparta"],"is_append":true,"confidence":0.9,
   "extra_edits":[{"target_field":"deterministic_subtype","new_value":"competitor_brand","is_append":true}]}

Step: geo_pois_confirmation (a POI map is on screen)
User reply: "also add Starbucks"
→ {"lane":"edit","target_field":"competitor_brands","new_value":["Starbucks"],"is_append":true,"confidence":0.9,
   "extra_edits":[{"target_field":"deterministic_subtype","new_value":"competitor_brand","is_append":true}]}
(a named chain — Starbucks, Walmart, Tim Hortons — is a BRAND: competitor_brands,
never poi_types, which is for kinds of place like "gyms" or "cafes")

User reply: "forget the cafes, just do events"
→ {"lane":"edit","target_field":"deterministic_subtype","new_value":"event_based","is_append":false,"confidence":0.9}

User reply: "change my budget to $500 and also add Toronto"
→ {"lane":"edit","target_field":"budget","new_value":"$500","confidence":0.9,
   "extra_edits":[{"target_field":"location","new_value":"Toronto","is_append":true}]}

Step: geo_location_confirmation (a location map with a search circle is on screen)
User reply: "change my radius to 2 km"
→ {"lane":"edit","target_field":"search_radius_km","new_value":"2 km","is_append":false,"confidence":0.95}

Step: geo_location_confirmation
User reply: "make the circle around Montreal 5km"
→ {"lane":"edit","target_field":"search_radius_km","new_value":"5km","is_append":false,"confidence":0.9}

Step: maid_confirm_results (spots and an audience are on screen)
User reply: "search within 3 km of the city instead"
→ {"lane":"edit","target_field":"search_radius_km","new_value":"3 km","is_append":false,"confidence":0.9}

Step: maid_confirm_results
User reply: "make it 300m around each spot"
→ {"lane":"edit","target_field":"poi_radius_m","new_value":"300m","is_append":false,"confidence":0.9}

Step: geo_location_confirmation
User reply: "make it 5 miles"
→ {"lane":"edit","target_field":"search_radius_km","new_value":"5 miles","is_append":false,"confidence":0.9}

Step: geo_pois_confirmation (Rings: search circle and visit ring both exist)
User reply: "make the radius bigger"
→ {"lane":"query","question_text":"which radius — the search circle around the city, or the ring around each spot","confidence":0.85}

User reply (at the maid_confirm map, audience already extracted): "actually only show me the ones who go on weekends"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"days_of_week":[5,6]},"confidence":0.9}

User reply: "just the regulars — 3 or more visits in the last two weeks"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"min_visits":3,"window_days":14},"confidence":0.9}

User reply: "narrow it to people who hit both the gym and the coffee shop"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"groups":["gym","coffee shop"],"op":"intersection"},"confidence":0.85}

User reply: "only people who went to a gym, a coffee shop, and a bookstore"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"groups":["gym","coffee shop","bookstore"],"op":"intersection"},"confidence":0.85}
(singular "a X, a Y, and a Z" = one visit to EACH → intersection)

User reply: "only people who went to gyms, cafes and bookstores"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"groups":["gym","cafe","bookstore"]},"confidence":0.85}
(every item a PLURAL type of place = sweep the types → union, NO `op`; "only" here narrows to those places, it does not mean all of them)

User reply: "only the ones who come every payday, give or take a couple days"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"cadence_days":14,"cadence_tolerance_days":2},"confidence":0.85}

User reply (at the maid_confirm map): "drop the staff, just keep the actual customers"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"min_open_day_share":0.5,"invert":true},"confidence":0.8}

User reply (at the maid_confirm map): "just women in their 30s who go a lot"
→ {"lane":"edit","target_field":"audience_filter","new_value":{"min_visits":3,"unsupported":"women in their 30s"},"confidence":0.85}

User reply: "only run on Instagram"
→ {"lane":"edit","target_field":"publisher_platforms","new_value":["instagram"],"is_append":false,"confidence":0.85}

User reply: "only show ads on weekdays 9 to 5"
→ {"lane":"edit","target_field":"adset_schedule","new_value":"weekdays 9am-5pm","is_append":false,"confidence":0.85}

User reply: "cap how often someone sees the ad at twice a week"
→ {"lane":"edit","target_field":"frequency_control_specs","new_value":"max 2 per week","is_append":false,"confidence":0.85}

User reply: "rename my business to PunkBakery"
→ {"lane":"edit","target_field":"business_name","new_value":"PunkBakery","is_append":false,"confidence":0.95}

User reply: "go back to where I picked locations"
→ {"lane":"edit","target_field":"geo_locations","target_step_key":"geo_collect_locations","is_append":false,"confidence":0.85}

User reply: "actually my budget should be $500/week not $1000"
→ {"lane":"edit","target_field":"budget","new_value":"$500/week","is_append":false,"confidence":0.95}

User reply: "yes 2km, and bump my budget to 500"
→ {"lane":"edit","target_field":"budget","new_value":"500","answer_value":"2km","confidence":0.9}

User reply: "what's a POI? also add Toronto"
→ {"lane":"edit","target_field":"location","new_value":"Toronto","is_append":true,"question_text":"what is a POI","confidence":0.9}

User reply: "Montreal — why do you need this?"
→ {"lane":"confirm","answer_value":"Montreal","question_text":"why is this needed","confidence":0.9}

Step: geo_location_confirmation (Manhattan is on screen, det_type not yet asked)
User reply: "manhattan is fine but also add brooklyn and also add starbucks in those areas"
→ {"clauses":["manhattan is fine","add brooklyn","add starbucks"],
   "lane":"edit","target_field":"location","new_value":"Brooklyn","is_append":true,
   "answer_value":"Manhattan is fine","confidence":0.9,
   "extra_edits":[{"target_field":"deterministic_subtype","new_value":"competitor_brand","is_append":true}]}

Step: geo_collect_locations (asking "What locations to target?")
User reply: "chicago works, what's a POI, also bump my budget to 500, and add events too"
→ {"clauses":["chicago works","what's a POI","bump my budget to 500","add events"],
   "lane":"edit","target_field":"budget","new_value":"500","is_append":false,
   "answer_value":"chicago works","question_text":"what is a POI","confidence":0.9,
   "extra_edits":[{"target_field":"deterministic_subtype","new_value":"event_based","is_append":true}]}

Output JSON only. No prose, no markdown, no code fences.
"""


def _actionable_field_groups() -> "OrderedDict[str, list[str]]":
    """``FIELD_OWNER`` entries the router can actually apply, grouped by owner
    and ordered geo/maid/campaign/media to match this prompt's historical
    section order. Was a hand-maintained prose duplicate of ``FIELD_OWNER``
    (drifted silently — e.g. ``campaign_objective``/``publisher_platforms``
    were added to the registry without ever being added here, or vice versa
    for the 7 geo fields ``is_actionable_field`` now excludes). Deriving it
    makes drift structurally impossible instead of relying on a human to keep
    two lists in sync — see ``is_actionable_field``'s own docstring for the
    bug this closes.
    """
    from app.graph.builder.edits import is_actionable_field

    groups: "OrderedDict[str, list[str]]" = OrderedDict(
        (owner, []) for owner in ("geo", "maid", "campaign", "media")
    )
    for f in sorted(FIELD_OWNER):
        if is_actionable_field(f):
            groups.setdefault(FIELD_OWNER[f], []).append(f)
    return groups


def _connection_owned_fields() -> str:
    """Media-owned fields the ack gate lets through only to be refused
    (``_validate_edit_target``). Derived, so a new one is named to the model
    without a prompt edit."""
    from app.graph.builder.edits import is_actionable_field

    return ", ".join(sorted(
        f for f, owner in FIELD_OWNER.items() if owner == "media" and not is_actionable_field(f)
    ))


def _backtrack_step_keys() -> list[str]:
    """Every ``STEP_PROMPTS`` step ``resolve_backtrack_target`` can actually
    act on. Advertising the confirm/disambiguation steps here (rather than as
    edit targets, which ``is_actionable_field`` already excludes them from)
    is what lets a "go back to X" naming one of them resolve instead of
    silently landing on ``unhandled``.
    """
    from app.graph.builder.edits import resolve_backtrack_target
    from app.graph.prompts_registry import STEP_PROMPTS

    return sorted(k for k in STEP_PROMPTS if resolve_backtrack_target(k)[0] != "none")


@lru_cache(maxsize=1)
def _classifier_prompt() -> str:
    """The system prompt, with its three enumerations spliced in from the
    registries at first call (cached — the registries are static for the
    process lifetime, same reasoning as every other module-level constant
    here). Plain ``str.replace`` on placeholder tokens, not ``.format``/an
    f-string — the template is full of literal JSON-example braces
    (``{"lane":"edit",...}``) that an f-string would need escaping throughout;
    a unique token substring has no such collision.
    """
    groups = _actionable_field_groups()
    known_fields = "\n\n".join(
        f"{owner}: " + ", ".join(fields)
        for owner, fields in groups.items()
        if fields
    )
    appendable = ", ".join(sorted(f for fields in groups.values() for f in fields if f in APPENDABLE_FIELDS))
    backtrack_steps = ", ".join(_backtrack_step_keys())

    prompt = _CLASSIFIER_PROMPT_TEMPLATE
    prompt = prompt.replace("__KNOWN_EDITABLE_FIELDS__", known_fields)
    prompt = prompt.replace("__APPENDABLE_FIELDS__", appendable + ".")
    prompt = prompt.replace("__CONNECTION_FIELDS__", _connection_owned_fields())
    prompt = prompt.replace("__BACKTRACK_STEPS__", backtrack_steps)
    return prompt


def _make_classifier_llm() -> ChatGoogleGenerativeAI:
    """Flash LLM for the resume-router. temp=0.0 for determinism.

    thinking_budget=0: this is temp-0 JSON extraction, not reasoning — dynamic
    thinking bought nothing but was blowing _CLASSIFIER_TIMEOUT_S on ordinary
    replies (every other Gemini factory in the graph sets this; this was the
    one that didn't).
    """
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        **settings.llm_auth,
        temperature=0.0,
        thinking_budget=0,
    )


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _JSON_FENCE_RE.sub("", (text or "").strip()).strip()


# ── Public types ──────────────────────────────────────────────────────────────

ResumeLane = Literal["confirm", "reject", "query", "edit", "unhandled", "handoff", "clarify"]


class ExtraEdit(BaseModel):
    """One additional field changed in the same reply as the primary edit.

    A user saying "change my budget to 500 and also add Toronto" makes TWO
    changes. With a single ``target_field`` the second was silently lost, which
    is squarely the confuse-Punk case. Each entry is dispatched exactly like the
    primary edit — same admissibility check, same confidence floor.
    """

    target_field: str
    new_value: Optional[Any] = None
    is_append: bool = False
    is_remove: bool = False
    is_replace: bool = False
    # The ONE item this change is scoped to ("Laval", "the pin"), when named.
    edit_target: Optional[str] = None


class ResumeIntent(BaseModel):
    """Classifier output for a single ``/resume`` payload."""

    lane: ResumeLane = "confirm"

    # The part of the reply that ANSWERS the active step, when the reply also
    # does something else ("yes 2km, and bump my budget to 500"). None for a
    # pure edit / query / plain confirm — `lane` stays scalar; this is the
    # confirm half riding alongside another lane's payload.
    answer_value: Optional[str] = None

    # Edit-lane fields. None when ``lane != "edit"``.
    target_field: Optional[str] = None
    new_value: Optional[Any] = None
    is_append: bool = False
    is_remove: bool = False
    # An EXPLICIT replace of a list ("forget the cafes, just do events") — set
    # only by the tool-calling backend's `change(op="set")`. A bare replace from
    # the lane-JSON backend stays a union for targeting angles (see
    # builder/edits.apply_edits), because that backend's append flag was the
    # unreliable half.
    is_replace: bool = False
    edit_target: Optional[str] = None
    target_step_key: Optional[str] = None

    # Clarify lane: the knobs the reply could mean, and the question to ask.
    clarify_options: list[str] = Field(default_factory=list)

    # Unhandled lane (tool-calling backend): what the user asked for that
    # nothing can do, and the nearest setting worth offering instead.
    unsupported_what: Optional[str] = None
    nearest_field: Optional[str] = None

    # A question embedded in the reply. Set on ANY lane, not just query — a
    # reply can answer/edit AND ask something in the same message.
    question_text: Optional[str] = None

    # Additional fields changed in the SAME reply. Empty for the common
    # single-field edit. The primary target_field is never repeated here.
    extra_edits: list[ExtraEdit] = Field(default_factory=list)

    # 0.0–1.0 — classifier self-reported confidence. Used by callers to
    # decide whether to escalate ambiguous calls to the escape menu.
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ResumeResult(str):
    """Return type for ``wizard_interrupt()``.

    Subclasses ``str`` so existing callers that treat the return value as
    the literal answer (``response.lower()``, ``parse_radius_float(response)``,
    ``raw.strip()``, etc.) keep working without migration.

    The extra ``edits`` attribute carries cross-step / cross-field patches
    accumulated inside the bounded resume-router loop (``_dispatch_edit_intent``
    in ``wizard_helpers.py``). ``builder/edits.stash_edits`` is the only
    consumer: it parks ``response.edits`` onto ``bs`` or an executor's ``ws``,
    and ``apply_pending_edits`` drains and commits it in ``builder_plan``. Empty
    for the overwhelmingly common case — a plain confirm never populates it.

    ``answered`` is False when the reply did NOT answer the step on screen — an
    edit, a question, a reject (single-interrupt mode only; see
    ``settings.BUILDER_SINGLE_INTERRUPT``). The string value is then the raw
    reply, and a caller must never write it into the slot: it stashes
    ``edits`` and ends its task so the step is re-asked fresh.
    """

    edits: dict
    answered: bool

    def __new__(
        cls, value: str = "", edits: Optional[dict] = None, answered: bool = True,
    ) -> "ResumeResult":
        obj = super().__new__(cls, value or "")
        obj.edits = dict(edits or {})
        obj.answered = answered
        return obj

    @property
    def value(self) -> str:
        """Alias for the underlying string — kept for forward compatibility
        with documentation that talks about ``result.value``.
        """
        return str(self)


# ── Caches (module-level, bounded LRU — process-local) ───────────────────────

# Bounded so long-running workers do not grow unboundedly. Per-process — cross
# worker replays may re-classify but per-worker decisions stay deterministic
# for the LRU window.

_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class _BoundedLRU(Generic[_K, _V]):
    """Minimal stdlib LRU. O(1) get/set, capacity-bounded eviction."""

    __slots__ = ("_data", "_capacity")

    def __init__(self, capacity: int = 1024) -> None:
        self._data: "OrderedDict[_K, _V]" = OrderedDict()
        self._capacity = capacity

    def get(self, key: _K) -> Optional[_V]:
        try:
            value = self._data[key]
        except KeyError:
            return None
        self._data.move_to_end(key)
        return value

    def __setitem__(self, key: _K, value: _V) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


_INTENT_CACHE_MAX = 1024
_CHIP_CACHE_MAX = 1024

# ``_intent_cache`` keyed by ``(step_key, sha1(raw))``.
_intent_cache: _BoundedLRU[tuple[str, str], ResumeIntent] = _BoundedLRU(_INTENT_CACHE_MAX)

# ``_chip_cache`` keyed by ``(step_key, sha1(session_summary))``.
_chip_cache: _BoundedLRU[tuple[str, str], list[str]] = _BoundedLRU(_CHIP_CACHE_MAX)


def _hash(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]


def _thread_scope() -> str:
    """The LangGraph thread the current call runs in, or "" outside a graph run.

    Part of every intent-cache key: the cache is process-wide, and without it
    two users typing the same reply at the same step with the same context digest
    (a cold start has an empty one) shared one classification.
    """
    try:
        from langgraph.config import get_config

        return str((get_config().get("configurable") or {}).get("thread_id") or "")
    except Exception:
        return ""


# ── Sentinel skip — keep the happy path classifier-free ───────────────────────

_SENTINEL_VALUES = frozenset({
    "", "yes", "y", "no", "n", "skip", "ok", "okay", "sure", "confirm",
    "continue", "proceed", "connected", "true", "false",
})


def is_sentinel_resume(raw: str) -> bool:
    """True when the resume value is a widget-payload sentinel (yes/no/skip,
    a JSON blob, a numeric, etc.) and should bypass the classifier.

    The router invokes the classifier only on free-form text. Sentinels are
    short-circuited to the ``confirm`` lane to keep the happy path at $0.
    """
    if raw is None:
        return True
    stripped = raw.strip()
    if not stripped:
        return True
    if stripped.lower() in _SENTINEL_VALUES:
        return True
    # JSON payload from a map widget / multi-stepper / file upload.
    if stripped[0] in "{[" and stripped[-1] in "}]":
        return True
    # Plain number (stepper value).
    try:
        float(stripped)
        return True
    except ValueError:
        pass
    return False


# ── Layer-builder panel commit — structured, never classified ────────────────

AUDIENCE_PANEL_ACTION = "audience_filter_patch"


def sanitize_panel_patch(patch: dict) -> dict:
    """A layer-builder patch reduced to what the panel is allowed to say.

    Two lanes, both closed sets. The panel may SET a value only for
    ``maid_store.LAYER_BUILDER_KEYS`` (checked by the same validator the
    extraction path uses), and may CLEAR — a key set to ``None`` — any key in
    ``CLEARABLE_FILTER_KEYS``: a setting it lists as "also applied" and has no
    control for can be removed, never rewritten. Anything else is dropped.

    Used by BOTH the commit (``audience_panel_intent``) and the read-only
    preview, so a patch means exactly the same thing in each and the count the
    panel shows is the count Apply produces.
    """
    from app.graph.nodes import _validate_audience_filter_clause
    from app.services.maid_store import CLEARABLE_FILTER_KEYS, LAYER_BUILDER_KEYS

    cleared = {k: None for k, v in patch.items() if v is None and k in CLEARABLE_FILTER_KEYS}
    kept = _validate_audience_filter_clause(
        {k: v for k, v in patch.items() if v is not None and k in LAYER_BUILDER_KEYS}
    ) or {}
    return {**cleared, **kept}


def audience_panel_intent(raw: str) -> Optional["ResumeIntent"]:
    """The edit-lane intent for a layer-builder commit, or ``None`` for any
    other reply.

    The panel sends ``{"action": "audience_filter_patch", "patch": {...}}``.
    ``is_sentinel_resume`` would route any JSON straight to the confirm lane —
    which would read a filter edit as "yes" — and free text is what the
    classifier is for, so an exact structured edit must bypass both. The result
    is the same ``audience_filter`` edit-lane intent the classifier produces, so
    everything downstream (``_dispatch_edit_intent`` → the recompute from the
    persisted rows) is one code path, not two.

    ``patch`` is a PATCH like the classifier's: a key set to ``null`` CLEARS it
    (that is how the panel removes a layer — the fold in
    ``maid_store.fold_audience_filter_specs`` keeps keys a patch does not
    mention). Values are checked with the same validator the extraction path
    uses; one that fails is dropped, never guessed.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("action") != AUDIENCE_PANEL_ACTION:
        return None
    patch = payload.get("patch")
    if not isinstance(patch, dict):
        return None

    new_value = sanitize_panel_patch(patch)
    if not new_value:
        return None
    return ResumeIntent(
        lane="edit", target_field="audience_filter", new_value=new_value, confidence=1.0,
    )


# ── Classifier ────────────────────────────────────────────────────────────────

_CLASSIFIER_TIMEOUT_S = 10.0

# The model sometimes writes `"confidence": 0.0` on a reply it classified
# correctly (different phrases on different days — "just the top 10", "change my
# budget to $50/day" — even where a worked example shows 0.85). Confidence gates
# every edit, so a right answer carrying 0 was refused as "low confidence" and the
# user was told their sentence was unclear.
#
# The prompt says to choose `query` when unsure, so an action lane that ALSO
# names its target at 0.0 contradicts itself: read it as "not stated", not as "no
# trust". 0.75 clears the base floor (RESUME_EDIT_MIN_CONFIDENCE, 0.7) but NOT the
# cost-bearing floor (+0.1, edits.py), so an unreliable 0 can never commit an edit
# that re-buys vendor data — that still needs a real, stated confidence.
_UNSTATED_CONFIDENCE = 0.75


def _normalize_unstated_confidence(intent: "ResumeIntent") -> "ResumeIntent":
    """See ``_UNSTATED_CONFIDENCE``. Only an ``edit`` that names its target.

    ``handoff`` is deliberately excluded: it can undo or abort the whole build, so
    its floor stays strict — a 0.0 there still reframes instead of acting."""
    if intent.confidence != 0.0:
        return intent
    if intent.lane != "edit" or not (intent.target_field or intent.target_step_key):
        return intent  # reject / query / confirm / handoff at 0.0 mean what they say
    logger.info(
        "classifier stated confidence 0.0 on lane=%s target=%r — treating as unstated (%s)",
        intent.lane, intent.target_field, _UNSTATED_CONFIDENCE,
    )
    return intent.model_copy(update={"confidence": _UNSTATED_CONFIDENCE})

# Cap the slot digest so a 20-slot build cannot bloat the prompt (or the cache
# key) — the classifier only needs to recognise that a field is already set.
_CTX_MAX_SLOTS = 14
_CTX_VALUE_CHARS = 40


def _classifier_context(step_key: str, state: Any) -> str:
    """The question on screen + which slots already hold a value.

    Returns "" when there is nothing useful (cold start, no builder scratch), so
    the cache key degrades to exactly the old ``(step_key, hash(raw))`` shape.
    Best-effort throughout: a classifier that loses context still classifies.
    """
    lines: list[str] = []
    try:
        from app.graph.prompts_registry import STEP_PROMPTS

        prompt = (STEP_PROMPTS.get(step_key) or {}).get("prompt")
        if prompt:
            lines.append(f"Question on screen: {prompt}")
    except Exception:
        pass

    try:
        filled = ((state or {}).get("campaign_builder_state") or {}).get("filled") or {}
    except (AttributeError, TypeError):
        filled = {}
    if filled:
        pairs = [
            f"{k}={str(v)[:_CTX_VALUE_CHARS]}"
            for k, v in list(filled.items())[:_CTX_MAX_SLOTS]
            if str(v or "").strip()
        ]
        if pairs:
            lines.append("Already set: " + "; ".join(pairs))

    # POI category digest — the poi_selection spec's `scope`/`match` are only
    # resolvable if the classifier knows what's actually on the map. Was a
    # blind guess before ("only fires when a POI map is plausibly on screen")
    # — this turns that guess into a fact, AND makes the intent cache key
    # (which already includes `context`, see classify_resume_intent) sensitive
    # to the POI set: the same "top 5" said twice against two different counts
    # no longer replays one stale classification.
    try:
        det = ((state or {}).get("campaign_builder_state") or {}).get("geo_result") or {}
        pois = det.get("targetable_pois") or []
        if pois:
            from app.graph.builder.executors.geo import group_pois_by_category

            cats = group_pois_by_category(pois)
            shown = ", ".join(f"{c['key']} ({c['count']})" for c in cats[:8])
            if len(cats) > 8:
                shown += f", and {len(cats) - 8} more"
            lines.append(
                f"Spots on screen: {len(pois)} across {len(cats)} "
                f"categor{'y' if len(cats) == 1 else 'ies'} — {shown}"
            )
    except Exception:
        pass

    ring_line = _rings_digest(state)
    if ring_line:
        lines.append(ring_line)

    # Live value of every knob that has one, by knob name — what a relative
    # ("double it") or "is it already…" reply is measured against.
    try:
        from app.graph.builder.knobs import current_values

        values = current_values(state)
        if values:
            lines.append("Current values: " + "; ".join(
                f"{k}={str(v)[:_CTX_VALUE_CHARS]}" for k, v in values.items()
            ))
    except Exception:
        pass

    # A clarifying question Punk asked last turn — this reply most likely
    # answers it, and only makes sense next to the request that prompted it.
    try:
        pending_q = ((state or {}).get("campaign_builder_state") or {}).get("_clarify") or {}
        if pending_q.get("question"):
            lines.append(
                f"Punk just asked: \"{pending_q['question']}\" about the user's earlier "
                f"request \"{pending_q.get('raw', '')}\" (options: "
                f"{', '.join(pending_q.get('options') or [])}). If this reply picks one, "
                "apply the EARLIER request to that setting."
            )
    except Exception:
        pass

    return ("\n".join(lines) + "\n") if lines else ""


def _rings_digest(state: Any) -> str:
    """The two radii that exist right now, so a bare "change the radius" can be
    told apart (see TWO RADII in the prompt): the SEARCH CIRCLE per location
    (``search_radius_km``, km) and the per-POI VISIT RING (``poi_radius_m``, m).

    "" when neither exists. Read from live builder scratch rather than the
    ``Already set`` digest because that one is capped at ``_CTX_MAX_SLOTS`` and
    never shows the per-location circles at all. Best-effort, like the rest of
    the context.
    """
    try:
        bs = (state or {}).get("campaign_builder_state") or {}
        filled = bs.get("filled") or {}
        circles: list[str] = []
        for loc in (bs.get("geo_ws") or {}).get("_geocoded_locations") or []:
            if loc.get("ui_mode") == "pin_radius" and loc.get("search_radius_km"):
                name = str(loc.get("location_name") or "pin")[:_CTX_VALUE_CHARS]
                circles.append(f"{name} {loc['search_radius_km']} km")
        for slot in ("radius_km", "competitor_radius_km"):
            if str(filled.get(slot) or "").strip():
                circles.append(f"{slot} {str(filled[slot])[:_CTX_VALUE_CHARS]} km")
        parts: list[str] = []
        if circles:
            parts.append("search circle (search_radius_km) — " + ", ".join(circles[:6]))
        if str(filled.get("poi_radius_m") or "").strip():
            parts.append(
                f"visit ring (poi_radius_m) — {str(filled['poi_radius_m'])[:_CTX_VALUE_CHARS]} m around each spot"
            )
        return ("Rings: " + "; ".join(parts)) if parts else ""
    except Exception:
        return ""


def _validate_edit_target(
    target_field: Optional[str],
    is_append: bool,
    is_remove: bool,
    new_value: Any,
    step_key: str,
) -> Optional[tuple[bool, bool]]:
    """Admissibility + flag-correction for ONE edit target (primary or extra).

    Returns the corrected ``(is_append, is_remove)`` pair, or ``None`` when
    ``target_field`` is not a real field — the caller must drop that edit
    rather than dispatch it, or it reaches ``builder/edits.py`` as an
    unrecognised field and is dropped there AFTER an ``edit_ack`` already told
    the user it landed.

    Gated on ``is_actionable_field``, not bare ``FIELD_OWNER`` membership —
    see that function's docstring for the class of bug a looser gate here
    used to let through.
    """
    from app.graph.builder.edits import is_actionable_field

    # Media fields (ad account, Page, pixel, creative upload) are not editable
    # from chat, but they ARE something the user can ask for: let them through
    # so `_dispatch_edit_intent` refuses with the specific "comes from your Meta
    # connection" copy. `edit_block_reason` returns a refusal for EVERY media
    # owner, so nothing here can reach `apply_pending_edits` — the two gates
    # still agree on what gets WRITTEN. Left to fall through, they were labelled
    # `unhandled` and got a generic "I can't act on that yet".
    if not target_field or not (
        is_actionable_field(target_field) or FIELD_OWNER.get(target_field) == "media"
    ):
        if target_field:
            from app.graph import capability_miss

            capability_miss.record(
                "unknown_field", step_key=step_key, field=target_field,
                detail="classifier named a field with no owner/executor",
            )
        return None
    # An item-level op can only target a list field. Append/remove on a
    # non-list field is a contradiction; collapse to a plain replace.
    if is_append and target_field not in APPENDABLE_FIELDS:
        is_append = False
    if is_remove and target_field not in APPENDABLE_FIELDS:
        is_remove = False
    # Append and remove are mutually exclusive; prefer remove.
    if is_append and is_remove:
        is_append = False
    # A multi-item append/remove must arrive as a LIST — each item is
    # geocoded/searched on its own downstream, so a comma-joined string
    # resolves to nothing. The system prompt instructs + demonstrates the
    # array form; log when it comes back joined anyway so the failure is
    # visible in the field rather than silent.
    if (is_append or is_remove) and isinstance(new_value, str) and "," in new_value:
        logger.warning(
            "classify_resume_intent returned a comma-joined %s value "
            "instead of an array: %r (step=%s)",
            target_field, new_value, step_key,
        )
    return is_append, is_remove


async def classify_resume_intent(
    raw: str,
    step_key: str,
    state: Any = None,
) -> ResumeIntent:
    """Classify a ``/resume`` payload into one of four lanes.

    Sentinel widget payloads (yes/no/skip, numeric, JSON) short-circuit to
    the confirm lane without hitting the LLM. All other inputs flow through
    a Gemini Flash call (temp=0.0) with a cache keyed by ``(step_key, sha1(raw))``
    so checkpoint replay reads the same lane decision at $0 cost.

    On LLM error / timeout / parse failure the call is retried once; if the
    retry also fails the router falls back to the reject lane — re-showing the
    step honestly — rather than "confirm", which used to write the user's raw
    edit text into the gate as if they'd agreed to it (see the module-level
    incident this fixed: a timed-out "add brooklyn ... starbucks" edit was
    silently written into ``poi_confirm``, rejected as not a yes, and dropped
    with no trace while the narrator still told the user it landed).
    """
    if is_sentinel_resume(raw):
        return ResumeIntent(lane="confirm", confidence=1.0)

    # ``state`` was in this signature from the start and never read: the model got
    # a bare step_key and the raw reply, so it could not see the question on
    # screen or which fields already had values. "make it 500" was unresolvable
    # and target_field was guesswork. The digest is folded into the cache key so
    # replay within the LRU window still yields the same lane — a replayed turn
    # that re-classified differently would diverge state.
    context = _classifier_context(step_key, state)
    cache_key = (_thread_scope(), step_key or "", _hash(raw + "\x00" + context))
    cached = _intent_cache.get(cache_key)
    if cached is not None:
        return cached

    async def _attempt() -> ResumeIntent:
        llm = _make_classifier_llm()
        msg, _ = await asyncio.wait_for(
            tracked_ainvoke(
                llm,
                [
                    SystemMessage(content=_classifier_prompt()),
                    HumanMessage(content=(
                        f"Active step_key: {step_key}\n"
                        f"{context}"
                        f"User reply: {raw}"
                    )),
                ],
                node_name=f"resume_router/classify/{step_key}",
                writer=None,
            ),
            timeout=_CLASSIFIER_TIMEOUT_S,
        )
        # .text, not .content: Gemini 3.x returns a list of blocks (with thought
        # signatures) even for plain replies, where 2.5 returned a str.
        text = msg.text.strip() if hasattr(msg, "text") else str(msg)
        text = _strip_fences(text)
        payload = json.loads(text)
        return _normalize_unstated_confidence(ResumeIntent(**payload))

    intent: Optional[ResumeIntent] = None
    for _try in range(2):
        try:
            intent = await _attempt()
            break
        except (asyncio.TimeoutError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "classify_resume_intent %s (%s): step=%s raw=%r",
                "retrying" if _try == 0 else "fallback",
                type(exc).__name__, step_key, raw,
            )
        except Exception as exc:
            logger.warning(
                "classify_resume_intent unexpected error: %s step=%s raw=%r",
                exc, step_key, raw,
            )
            break
    if intent is None:
        # Nothing routine reaches here — sentinels and widget-option clicks are
        # short-circuited before the classifier ever runs — so this is always
        # free text the router failed to read twice. "reject" re-asks the step
        # honestly instead of guessing the user meant "yes".
        intent = ResumeIntent(lane="reject", confidence=0.0)

    intent = _post_validate_edit_lane(intent, step_key)
    _intent_cache[cache_key] = intent
    return intent


def _post_validate_edit_lane(intent: ResumeIntent, step_key: str) -> ResumeIntent:
    """Drop unknown ``target_field``s off an edit-lane intent so the dispatch
    handler treats them as no-ops rather than silently mutating misnamed
    state. Runs on the primary target AND every ``extra_edits`` entry — an
    extra used to skip validation entirely, so a hallucinated field survived
    all the way to ``builder/edits.py``, which drops it AFTER ``edit_ack``
    already told the user it landed.

    Shared by BOTH classifier backends (the lane-JSON one and Phase 3's
    tool-calling one) — a hallucinated field is exactly as dangerous coming
    from a tool call's ``field`` argument as from a JSON key, so this must not
    be reimplemented per backend.

    Backtrack targets (``target_step_key``) are validated where they are
    acted on — ``_dispatch_edit_intent`` in wizard_helpers.py, via
    ``edits.resolve_backtrack_target`` — rather than here, so that check holds
    regardless of caller (tests construct ``ResumeIntent`` directly, bypassing
    both classifiers entirely).
    """
    if intent.lane != "edit":
        return intent

    from app.graph.builder.edits import canonical_field

    # Canonicalize BEFORE validation: a slot-name alias (e.g. "locations" for
    # the `locations` slot) passes `is_actionable_field` but is not in
    # `APPENDABLE_FIELDS` or `FIELD_OWNER` under that spelling, so
    # `_validate_edit_target` silently drops an append flag and every
    # downstream consumer keyed on the registry name (rerun_on_edit,
    # stash_edits exclude sets, edit_base) misses it entirely. See
    # `canonical_field`'s docstring for the failure this closes.
    target_field = canonical_field(intent.target_field or "") or intent.target_field
    intent = intent.model_copy(update={"target_field": target_field})

    valid_extras: list[ExtraEdit] = []
    for extra in intent.extra_edits:
        extra_field = canonical_field(extra.target_field or "") or extra.target_field
        if extra_field != extra.target_field:
            extra = extra.model_copy(update={"target_field": extra_field})
        corrected = _validate_edit_target(
            extra.target_field, extra.is_append, extra.is_remove,
            extra.new_value, step_key,
        )
        if corrected is None:
            continue
        is_append, is_remove = corrected
        valid_extras.append(extra.model_copy(update={
            "is_append": is_append, "is_remove": is_remove,
        }))

    primary = _validate_edit_target(
        intent.target_field, intent.is_append, intent.is_remove,
        intent.new_value, step_key,
    )
    if primary is None:
        # The primary field is bogus. Don't throw away a valid extra (or
        # the question) just because the FIRST field named was wrong —
        # promote the first surviving extra to primary instead of
        # collapsing the whole reply to reject.
        if valid_extras:
            promoted, *rest = valid_extras
            return intent.model_copy(update={
                "target_field": promoted.target_field,
                "new_value": promoted.new_value,
                "is_append": promoted.is_append,
                "is_remove": promoted.is_remove,
                "extra_edits": rest,
            })
        # NOT "reject". `reject` re-asks the active step as though the
        # user said nothing — but they named a real thing, Punk just
        # has no field for it ("cap frequency at 2", "Instagram
        # only" pre-spec). `unhandled` carries the field they named so
        # the caller can say what it can't do yet, instead of quietly
        # pretending the reply was empty (the false-acknowledgment
        # class builder/edits.py exists to prevent, one layer up).
        return ResumeIntent(
            lane="unhandled",
            target_field=intent.target_field,
            answer_value=intent.answer_value,
            question_text=intent.question_text,
            confidence=intent.confidence,
        )
    is_append, is_remove = primary
    return intent.model_copy(update={
        "is_append": is_append, "is_remove": is_remove,
        "extra_edits": valid_extras,
    })


# ── Phase 3: tool-calling classifier (RESUME_ROUTER_TOOLCALLING) ──────────────
#
# `classify_resume_intent_tools` is an ALTERNATE backend for the same job as
# `classify_resume_intent` above — same ``ResumeIntent`` return shape, same
# cache mechanics, same post-validation (`_post_validate_edit_lane`, now
# shared) — selected instead of the lane-JSON classifier when
# ``settings.RESUME_ROUTER_TOOLCALLING`` is true (see ``wizard_helpers.
# wizard_interrupt``). Nothing downstream of the return value changes: the
# entire dispatch block in ``wizard_interrupt`` is untouched and cannot tell
# which backend produced its ``ResumeIntent``.
#
# Deliberately NOT a rewrite of that dispatch block against a new action-list
# shape (the plan's aspirational end-state). `ResumeIntent` already IS a
# workable shared shape once both backends agree to produce it — the model
# calling several tools per turn is what's new here, not a new contract with
# the rest of the loop. Translating N tool calls into one ResumeIntent
# (primary + extra_edits) is what deletes the classifier PROMPT's ~400 lines
# of few-shot enumerate-then-map choreography (a new capability is now a new
# tool + one translation branch, not prompt surgery) while keeping the
# regression surface to exactly this file — the dispatch block, and every
# test that exercises it, needs no changes and cannot diverge in behavior
# between backends. Collapsing the two ResumeIntent shapes into a genuinely
# new multi-action contract, and deleting the scalar fields this preserves
# (`extra_edits`, `answer_value`), stays real future work, not done here.

# ── Structural tools ─────────────────────────────────────────────────────────
# Schema-only: these are never invoked. `bind_tools` only needs their name +
# argument schema + docstring to build the function-calling contract; the
# translation below reads `AIMessage.tool_calls` (name + args) directly and
# maps each call onto the SAME ResumeIntent fields the lane classifier
# already produces, so the existing dispatch executes them exactly as before.
# Read/write tools with REAL effects (get_build_state, undo, abort, …) live in
# builder/interject_tools.py and are not redefined here — a call naming one of
# those is recognised below and translated to lane="handoff", deferring
# actual selection + execution to the existing `run_handoff_turn` (Phase 2),
# so tool execution has exactly one implementation, not two.


@tool
def answer_step(value: str) -> str:
    """Answer the ACTIVE step on screen directly with this value."""
    return "recorded"


@tool
def reject_step() -> str:
    """The user does not want to answer the active step right now (\"no\",
    \"skip\", \"not that one\") — clear any prefill and re-ask it."""
    return "recorded"


@tool
def ask_question(question: str) -> str:
    """The user asked a question instead of (or alongside) answering the
    active step — e.g. \"what's a POI?\", \"why are you asking this?\"."""
    return "recorded"


_EDIT_FIELD_DOC = """Change a setting OTHER than (or in addition to) the active step's
answer — a cross-step correction ("change my budget") or an addition/removal on
a list ("also add Toronto", "remove Laval").

`field` is one of the settings listed in its own description — pick by what
the user MEANS, using each setting's "NOT …" cue. When the reply fits two
settings equally well (a bare "make the radius bigger" when both a search
circle and a visit ring exist), call `clarify` instead of guessing.

`mode`: "replace" (default) · "append" / "remove" (one item of a list) ·
"scale" (relative multiply: value "double", "half", "3x") · "delta" (relative
add/subtract: value "+2 km", "5 more days", "500 m smaller"). Use scale/delta
whenever the user states the change RELATIVE to the current value — code does
the arithmetic from the live value; never compute it yourself.

`value`: the new value as plain text, KEEPING the user's unit ("5 miles",
"300 feet", "2 km") — code converts it. For a setting with "one of …" values,
use exactly one of those tokens. Several list items → a JSON list.

`target` (optional): which ONE item the change is scoped to, when the user
named it ("Laval's circle", "the parks") — leave empty to mean all of them.

Which list: a CITY / area ("Toronto") is location; a KIND of place ("gyms") is
poi_types; a CHAIN ("Starbucks") is competitor_brands; one specific venue
("Central Park") is named_places — the matching search angle switches on for
you. "location type" is ambiguous: a place category is poi_types, a scope
("whole state", "drop a pin") is geo_scope, neither → ask_question.

REMOVING a category or spot already on the map ("remove the tabletop gaming
center") is trim_pois op="drop", NOT mode="remove" here — this tool's remove
takes something out of the SEARCH itself ("stop searching for gyms"). For
narrowing an extracted audience use filter_audience.

Ad account, Page and pixel come from the user's Meta connection and cannot be
changed here: still call this with that field so the user gets the right
explanation — never a look-alike field."""


@lru_cache(maxsize=1)
def _edit_field_tool() -> Any:
    """`edit_field`, with `field` an enum generated from the knob registry
    (plus the Meta-connection fields, so a request for one gets the specific
    refusal). Built lazily: the registry imports builder modules."""
    from langchain_core.tools import StructuredTool
    from pydantic import create_model

    from app.graph.builder.knobs import edit_field_knobs, knob_catalog

    names = tuple(k.name for k in edit_field_knobs()) + tuple(
        f.strip() for f in _connection_owned_fields().split(",") if f.strip()
    )
    args = create_model(
        "EditFieldArgs",
        field=(Literal[names], Field(description="The setting to change:\n" + knob_catalog())),
        value=(str, Field(description="New value as plain text, keeping the user's unit.")),
        mode=(
            Literal["replace", "append", "remove", "scale", "delta"],
            Field(default="replace", description="How the value applies (see tool description)."),
        ),
        target=(Optional[str], Field(default=None, description="The one item this is scoped to, if named.")),
    )
    return StructuredTool.from_function(
        func=lambda **_kw: "recorded", name="edit_field",
        description=_EDIT_FIELD_DOC, args_schema=args,
    )


@tool
def clarify(options: list[str], question: str) -> str:
    """The reply could mean more than one setting and nothing on screen settles
    it (e.g. "make the radius bigger" when both the search circle and the visit
    ring exist). `options`: the edit_field names it could mean. `question`: one
    short question for the user naming each option in plain words. Never guess
    — asking is always better than changing the wrong thing."""
    return "recorded"


@tool
def go_back(step_key: str) -> str:
    """Jump back to change what was answered at an EARLIER step ("go back to
    where I picked locations"). `step_key` names the step to return to."""
    return "recorded"


@tool
def trim_pois(spec: dict) -> str:
    """Curate the POIs ALREADY discovered and on screen, without naming a
    new place/brand/category to search for — "just the top 10", "drop
    everything in Laval", "top 5 of each category", "get rid of the game
    stores" (spec {"op":"drop","match":"game store"}). Every POI already carries
    a Google rating where Places returned one, and a trim ranks by it before
    cutting. A QUESTION about the spots ("which of these is best?", "which are
    worth targeting?") is ask_question, never a trim — only an instruction to
    keep/show/cut is. So "just show me the best ones" / "shortlist these" over an
    already-found set is THIS tool too, not a new search; those unnumbered
    asks name a count too, default n to 15. `spec` is a JSON object using
    ONLY these keys, all optional: op ("keep"|"drop", default "keep"), n (the
    count named), scope ("all"|"each" — "each" for "of each category"/"per
    category"/"per type"), match (a named subset by place/brand/area/type,
    e.g. "Laval", "Tim Hortons", "gym" — OR one specific spot by its own
    name, e.g. "Denver Animal Hospital"), sort ({"by": rating|reviews|
    distance_km|name, "dir": "asc"|"desc"} — an explicit named order, e.g.
    "closest 5" / "sort by rating" — only set this when the user named a
    specific ordering, not for a bare "top N"), min_rating / max_rating
    (a star threshold — an unrated place never silently passes or fails one),
    min_reviews (a review-count floor), min_visitors (an integer: keep only
    spots that had at least that many visitors — "keep only the locations
    that have visits" is 1; it removes SPOTS, not people), max_distance_km (a distance ceiling
    from the build's own center — reported unsupported downstream if this
    build has none yet), unsupported (a clause you understood but that none
    of the keys above can express — an exact count you cannot fit, a ratio,
    an unbuilt grouping — put it VERBATIM here rather than approximating it
    with the wrong key)."""
    return "recorded"


def _audience_layering_doc() -> str:
    """The classifier prompt's own AUDIENCE LAYERING block — every key with its
    format, the counting and role-targeting guards, `invert`, `unsupported`.

    Sliced from the rendered template instead of restated: the tool used to
    carry a bare key list and the two backends disagreed on the same reply
    ("twice a week" -> a visit count on one, a spacing rule on the other; a role
    phrase -> `unsupported` on one). One text means one behaviour."""
    t = _CLASSIFIER_PROMPT_TEMPLATE
    # Start at the worked examples ("twice a week" -> a COUNT, not a cadence) and
    # the day/time ambiguity rule that precede the key table: they are what stops
    # a model over-inferring `cadence_days` on top of `min_visits`.
    a = t.index('User reply (at maid_confirm_results, an audience map is on screen): "only people who go twice')
    end_marker = "is NOT\nan edit"
    b = t.index("`confirm`.", t.index(end_marker, a)) + len("`confirm`.")
    return t[a:b]


_FILTER_AUDIENCE_INTRO = """Narrow an audience ALREADY extracted from real visits — "now only
weekends", "just the ones who go 3+ times", "gym AND coffee-shop regulars".
`patch` is the `new_value` object described below (only the keys this reply
changes). For a bare day/time phrase outside an audience screen, use
ask_question instead.

"""


@tool(description=_FILTER_AUDIENCE_INTRO + _audience_layering_doc())
def filter_audience(patch: dict) -> str:
    return "recorded"


@tool
def unhandled(what: str, nearest: Optional[str] = None) -> str:
    """Nothing else fits: the user asked for something real that no setting
    or tool here can do (e.g. "target people by household income", "show ads
    only to people who own a dog"). `what` names it briefly. `nearest`
    (optional): the edit_field setting that comes closest, if one genuinely
    helps — Punk will say it can't do `what` and offer that instead. Never force
    a request into a setting that doesn't mean it. An AUDIENCE clause the visit
    data can't express ("men in their 30s") goes in filter_audience's
    `unsupported` key instead — that tool reports it alongside what it CAN do."""
    return "recorded"


def _structural_tools() -> list[Any]:
    """Every tool the router binds. The handoff lane's tools are bound too
    (schema only — `_translate_tool_calls` recognises them by name and hands
    the turn to `run_handoff_turn`); without them the prompt told the model to
    call tools it could not, and "undo that" had nowhere to go."""
    from app.graph.builder.interject_tools import HANDOFF_ALL_TOOLS

    # narrow_pois is the handoff twin of trim_pois; binding both would split
    # one intent ("top 10") across two lanes.
    return [
        answer_step, reject_step, ask_question, _edit_field_tool(), clarify, go_back,
        trim_pois, filter_audience, unhandled,
        *(t for t in HANDOFF_ALL_TOOLS if t.name != "narrow_pois"),
    ]


def _handoff_tool_names() -> frozenset[str]:
    """Lazy import — resume_router.py stays builder-agnostic at module load,
    matching every other cross-layer reference in this file (e.g.
    ``edits.resolve_backtrack_target`` inside ``_post_validate_edit_lane``'s
    caller). Only the NAMES are needed here; execution is `run_handoff_turn`'s
    job, not this module's."""
    from app.graph.builder.interject_tools import HANDOFF_ALL_TOOLS as _handoff_tools
    return frozenset(t.name for t in _handoff_tools)


_TOOLCALL_SYSTEM_PROMPT = """You are the PunkAI resume-value router.

The user just posted a reply during a wizard interrupt. Call whichever
tool(s) describe what the reply actually does — a reply can call SEVERAL
tools at once (e.g. answering the step AND editing another field AND asking
a question, all in one message): call one tool per distinct thing the user
said, never fewer.

If the reply needs a read of what's been built, a marketing-knowledge lookup,
the list of what can be changed, or a PROCESS action (undo, hand the rest to
Punk's defaults, stop the build) — call get_build_state / get_pois /
get_audience / retrieve_marketing_knowledge / list_changeable / undo /
delegate_rest / abort; the actual tool selection for that turn happens in a
follow-up pass, so here you only need to recognise THAT it's one of those.

ON THE MAP vs IN THE SEARCH: when a "Spots on screen" line lists what the user
wants gone ("get rid of the game stores", "remove the tabletop gaming center",
"drop the ones in Laval"), that is trim_pois with op "drop" — it curates what
is already found, costs nothing and can be undone. edit_field mode "remove" on
poi_types / competitor_brands / named_places is ONLY for "stop SEARCHING for
X" / "don't look for X any more", which re-runs the whole search.

WHICH SETTING: read each edit_field setting's "NOT …" cue before choosing one.
Relative changes ("double it", "a bit bigger", "5 more days") are
edit_field mode scale/delta with the change as said — never compute the new
number yourself. Keep the user's unit ("5 miles", "300 feet"). When the reply
fits two settings equally and the screen doesn't settle it, call clarify —
changing the wrong setting is worse than asking. When the user asks for
something no setting or tool can do, call unhandled (with `nearest` when one
setting genuinely comes close) — never force it into a setting that means
something else. The "Current values" / "Rings" lines below are the live
values; use them.

A radius or circle size that names ONE of the user's places ("make the Fort
Collins radius 5 miles", "Denver 20 km") is location_ring with target = that
place — with or without the word "just". search_radius_km resizes EVERY circle.

A PLACE FOR ONE SEARCH ("only search the events in Montreal") is edit_field
location: value = the place, target = that search ("events"). Never write a
place name into event_queries or poi_types.

QUESTIONS ARE NEVER MUTATIONS EITHER. "which of these spots is best?", "what
have we built so far?" and "what's a POI?" ask to SEE or to UNDERSTAND — call
ask_question. "just keep the best ones" is an instruction — that is trim_pois.
Tell them apart by whether the user asked to see or to change.

HYPOTHETICALS ARE NEVER edit_field / trim_pois / filter_audience / go_back.
"if I add Toronto does it cost more?" is a question ABOUT a change, not the
change itself — call ask_question, never a mutating tool, when the reply is
conditional/interrogative with no actual instruction given.

Call a mutating tool (edit_field, trim_pois, filter_audience, go_back, or any
of the handoff write tools) ONLY when the user gave a real instruction. When
genuinely unsure, call ask_question or unhandled instead of guessing — not
calling a mutating tool IS the honest "unsure" signal here; there is no
confidence score to fake it with.

Call NO tool only when the reply is a widget-option click or sentinel value
that never reaches you (those are short-circuited before this call runs) —
in practice this means always call at least one tool.
"""


def _make_toolcall_classifier_llm() -> ChatGoogleGenerativeAI:
    # Same reasoning as _make_classifier_llm: temp-0 structured extraction,
    # no benefit from dynamic thinking.
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL, **settings.llm_auth,
        temperature=0.0, thinking_budget=0,
    )


# Confidence values fed into the EXISTING confidence-gated dispatch paths
# (`_dispatch_edit_intent`'s floor, the handoff floor in wizard_helpers.py).
# Both clear settings.RESUME_EDIT_MIN_CONFIDENCE's default (0.7) — the model
# choosing a mutating tool AT ALL is the confidence signal in this backend
# (see the system prompt above), so a fixed value is honest, not a shortcut:
# there is no per-call score to preserve, only "did or didn't call one."
_TOOLCALL_CONFIDENCE = 0.9
_TOOLCALL_HANDOFF_CONFIDENCE = 0.85


# Knobs whose value is one number for the whole build; a `target` naming ONE
# item of them can't be honoured (the visit ring is scoped: see `poi_radius_m`).
_UNSCOPED_NUMERIC = frozenset({"lookback_days"})


def _resolve_edit_call(args: dict, state: Any) -> dict:
    """One `edit_field` call → an edit_like entry, or a clarify/unhandled
    marker when the change can't be made as asked. Relative changes are
    computed HERE, from the live value — the model only names them."""
    from app.graph.builder.knobs import current_values, knob_for_field, resolve_relative

    field = args.get("field")
    value = args.get("value")
    mode = str(args.get("mode") or "replace").strip().lower()
    target = _optional_str_local(args.get("target"))
    knob = knob_for_field(field)

    # One location's circle is its own setting (it needs a location to aim at).
    if target and knob is not None and knob.name == "search_radius_km":
        field, knob = "location_ring", knob_for_field("location_ring")
    if target and knob is not None and knob.name in _UNSCOPED_NUMERIC:
        return {"_unhandled_what": f"changing only {target}'s {knob.name.replace('_', ' ')}",
                "_nearest": knob.name}
    if target and knob is not None and knob.name == "poi_radius_m" and mode in ("scale", "delta"):
        # "double the gyms' ring": the current value is per spot group, which the
        # live-values digest doesn't hold — ask for the size instead of guessing.
        return {"_clarify": ["poi_radius_m"],
                "_question": f"What size should the visit ring around {target} be, exactly?"}
    if mode in ("scale", "delta"):
        current = current_values(state).get(knob.name) if knob else None
        resolved = resolve_relative(knob, mode, str(value or ""), current) if knob else None
        if resolved is None:
            what = knob.describe if knob else str(field)
            return {"_clarify": [knob.name if knob else str(field)],
                    "_question": (
                        f"What should it be exactly? The {what} is "
                        f"{current or 'not set yet'} right now."
                    )}
        value, mode = resolved, "replace"
    return {
        "target_field": field,
        "new_value": value,
        "is_append": mode == "append",
        "is_remove": mode == "remove",
        "is_replace": mode == "replace" and bool(knob and "add" in knob.ops),
        "edit_target": target,
    }


def _translate_tool_calls(calls: list[Any], raw: str, step_key: str, state: Any = None) -> ResumeIntent:
    """N tool calls from one turn -> ONE ResumeIntent, in the shape
    `_post_validate_edit_lane` and the existing dispatch already expect.

    A call naming a handoff-trigger tool short-circuits everything else in
    the batch to lane="handoff" — that pass owns its OWN tool selection
    (`run_handoff_turn`), so this function's job for such a call is only to
    recognise it, not to interpret its arguments.
    """
    handoff_names = _handoff_tool_names()

    answer_value: Optional[str] = None
    question_text: Optional[str] = None
    saw_reject = False
    edit_like: list[dict] = []

    for call in calls:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        args = (call.get("args") if isinstance(call, dict) else getattr(call, "args", None)) or {}
        if not name:
            continue
        if name in handoff_names:
            return ResumeIntent(
                lane="handoff", question_text=raw, confidence=_TOOLCALL_HANDOFF_CONFIDENCE,
            )
        if name == "answer_step":
            answer_value = _optional_str_local(args.get("value")) or answer_value
        elif name == "reject_step":
            saw_reject = True
        elif name == "ask_question":
            question_text = _optional_str_local(args.get("question")) or question_text
        elif name == "edit_field":
            _entry = _resolve_edit_call(args, state)
            if "_clarify" in _entry:
                return ResumeIntent(
                    lane="clarify", clarify_options=_entry["_clarify"],
                    question_text=_entry["_question"], confidence=_TOOLCALL_CONFIDENCE,
                )
            edit_like.append(_entry)
        elif name == "clarify":
            _opts = [str(o) for o in (args.get("options") or []) if o]
            return ResumeIntent(
                lane="clarify", clarify_options=_opts,
                question_text=_optional_str_local(args.get("question")) or raw,
                confidence=_TOOLCALL_CONFIDENCE,
            )
        elif name == "go_back":
            # `_post_validate_edit_lane` requires a REAL target_field to keep
            # lane="edit" alive at all (it validates target_field unconditionally
            # for the "edit" lane — see its docstring on why target_step_key
            # is checked elsewhere, not that target_field is skippable here).
            # The lane-JSON classifier's own prompt example for a backtrack
            # always pairs target_step_key with a real target_field for
            # exactly this reason; resolve it here instead of trusting the
            # model to duplicate it — STEP_PROMPTS covers every step FIELD_OWNER
            # validates (test_field_owner_resolves_every_step_prompts_field),
            # so this resolution cannot itself invent an unknown field.
            from app.graph.prompts_registry import STEP_PROMPTS

            _target_step = args.get("step_key")
            _target_field = (STEP_PROMPTS.get(_target_step) or {}).get("field")
            edit_like.append({
                "target_field": _target_field, "new_value": None,
                "target_step_key": _target_step,
            })
        elif name == "trim_pois":
            spec = args.get("spec")
            if isinstance(spec, dict) and spec:
                edit_like.append({"target_field": "poi_selection", "new_value": spec})
        elif name == "filter_audience":
            patch = args.get("patch")
            if isinstance(patch, dict) and patch:
                edit_like.append({"target_field": "audience_filter", "new_value": patch})
        elif name == "unhandled":
            edit_like.append({
                "target_field": None, "new_value": None,
                "_unhandled_what": _optional_str_local(args.get("what")) or raw,
                "_nearest": _optional_str_local(args.get("nearest")),
            })
        # An unrecognised tool name is ignored — the model hallucinated a
        # call to something not in the bound tool set; nothing to translate.

    if not edit_like:
        if question_text:
            return ResumeIntent(
                lane="query", question_text=question_text,
                answer_value=answer_value, confidence=_TOOLCALL_CONFIDENCE,
            )
        if answer_value is not None:
            return ResumeIntent(
                lane="confirm", answer_value=answer_value, confidence=_TOOLCALL_CONFIDENCE,
            )
        if saw_reject:
            return ResumeIntent(lane="reject", confidence=_TOOLCALL_CONFIDENCE)
        # No recognisable tool call at all — same "the router failed to read
        # it" fallback classify_resume_intent uses after two failed attempts.
        return ResumeIntent(lane="reject", confidence=0.0)

    # Real edits and the part nothing can do are reported TOGETHER: an
    # `unhandled` call listed first used to discard every real edit after it.
    real = [e for e in edit_like if "_unhandled_what" not in e]
    unh = next((e for e in edit_like if "_unhandled_what" in e), None)
    _unsupported = {
        "unsupported_what": unh.get("_unhandled_what") if unh else None,
        "nearest_field": unh.get("_nearest") if unh else None,
    }

    if not real:
        return ResumeIntent(
            lane="unhandled", answer_value=answer_value, question_text=question_text,
            confidence=_TOOLCALL_CONFIDENCE, **_unsupported,
        )

    primary, *rest = real
    if primary.get("target_step_key"):
        return ResumeIntent(
            lane="edit", target_step_key=primary["target_step_key"],
            target_field=primary.get("target_field"),
            answer_value=answer_value, question_text=question_text,
            confidence=_TOOLCALL_CONFIDENCE, **_unsupported,
        )

    extra_edits = [
        ExtraEdit(
            target_field=e["target_field"], new_value=e.get("new_value"),
            is_append=e.get("is_append", False), is_remove=e.get("is_remove", False),
            is_replace=e.get("is_replace", False),
            edit_target=e.get("edit_target"),
        )
        for e in rest
        if e.get("target_field") and not e.get("target_step_key")
    ]
    return ResumeIntent(
        lane="edit",
        target_field=primary.get("target_field"),
        new_value=primary.get("new_value"),
        is_append=primary.get("is_append", False),
        is_remove=primary.get("is_remove", False),
        is_replace=primary.get("is_replace", False),
        edit_target=primary.get("edit_target"),
        answer_value=answer_value,
        question_text=question_text,
        extra_edits=extra_edits,
        confidence=_TOOLCALL_CONFIDENCE,
        **_unsupported,
    )


def _optional_str_local(value: Any) -> Optional[str]:
    """Local twin of wizard_helpers._optional_str (not imported — that module
    imports THIS one; see the module docstring's note on the resume_router /
    wizard_helpers / builder_node lazy-import chain)."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


_TOOLCALL_TIMEOUT_S = 10.0


class _NoToolCall(Exception):
    """The tool-calling classifier answered with no tool call (retried once)."""


async def classify_resume_intent_tools(
    raw: str,
    step_key: str,
    state: Any = None,
) -> ResumeIntent:
    """Tool-calling backend for the same job as `classify_resume_intent` —
    selected instead of it when `settings.RESUME_ROUTER_TOOLCALLING` is true.
    Same sentinel short-circuit, same context digest, same cache SHAPE (a
    separate namespace below so the two backends never collide on one
    cache entry and silently serve each other's classification on replay),
    same post-validation, same ResumeIntent return contract. See the module
    section docstring above for what is and is not in scope here.
    """
    if is_sentinel_resume(raw):
        return ResumeIntent(lane="confirm", confidence=1.0)

    context = _classifier_context(step_key, state)
    cache_key = (_thread_scope(), step_key or "", _hash("TC\x00" + raw + "\x00" + context))
    cached = _intent_cache.get(cache_key)
    if cached is not None:
        return cached

    async def _attempt() -> ResumeIntent:
        llm = _make_toolcall_classifier_llm().bind_tools(_structural_tools())
        msg, _ = await asyncio.wait_for(
            tracked_ainvoke(
                llm,
                [
                    SystemMessage(content=_TOOLCALL_SYSTEM_PROMPT),
                    HumanMessage(content=(
                        f"Active step_key: {step_key}\n"
                        f"{context}"
                        f"User reply: {raw}"
                    )),
                ],
                node_name=f"resume_router/classify_tools/{step_key}",
                writer=None,
            ),
            timeout=_TOOLCALL_TIMEOUT_S,
        )
        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            # The prompt says to ALWAYS call a tool. Sampled live, a large tool
            # set sometimes answers with none — which used to become a
            # low-confidence reject ("I didn't catch that") for a perfectly
            # clear reply. Treat it as the transient failure it is.
            raise _NoToolCall()
        return _translate_tool_calls(calls, raw, step_key, state)

    intent: Optional[ResumeIntent] = None
    _failed_twice = False
    for _try in range(2):
        try:
            intent = await _attempt()
            break
        except _NoToolCall:
            logger.warning(
                "classify_resume_intent_tools %s (no tool call): step=%s raw=%r",
                "retrying" if _try == 0 else "fallback", step_key, raw,
            )
            _failed_twice = _try == 1
        except asyncio.TimeoutError as exc:
            logger.warning(
                "classify_resume_intent_tools %s (%s): step=%s raw=%r",
                "retrying" if _try == 0 else "fallback",
                type(exc).__name__, step_key, raw,
            )
            _failed_twice = _try == 1
        except Exception:
            # A crash here (e.g. a tool schema Gemini's converter rejects) is
            # NOT the user's reply being unclear — logging it loudly and
            # degrading to the lane-JSON backend keeps a broken tool set from
            # silently turning every mid-turn reply into "reject".
            logger.exception(
                "classify_resume_intent_tools crashed; falling back to lane-JSON "
                "classifier: step=%s raw=%r", step_key, raw,
            )
            # classify_resume_intent post-validates and caches under its own key.
            return await classify_resume_intent(raw, step_key, state)
    if intent is None and _failed_twice:
        # Twice with no tool call or two stalls (~1 in 10 Vertex calls sits
        # until the timeout): let the lane-JSON classifier read the same reply
        # rather than telling the user it was unclear. It post-validates and
        # caches under its own key.
        return await classify_resume_intent(raw, step_key, state)
    if intent is None:
        intent = ResumeIntent(lane="reject", confidence=0.0)

    intent = _post_validate_edit_lane(intent, step_key)
    _intent_cache[cache_key] = intent
    return intent


# ── Chip generator ────────────────────────────────────────────────────────────

_CHIPS_TIMEOUT_S = 4.0
_CHIPS_MAX = 4

_CHIPS_SYSTEM_PROMPT = """You generate short tappable answer chips for a wizard step.

You will receive:
  - The active wizard step's prompt (what the user is being asked)
  - A short session-context summary (business, location, audience, etc.)

Return ONLY a JSON array of 0–4 chip strings. Each chip must:
  - Be a plausible one-tap answer for the active step
  - Be short (≤ 32 characters when possible — chips render as buttons)
  - Be GROUNDED in the session context where relevant (the user's business
    name, city, audience, budget) — generic placeholder chips are forbidden
  - Read as something the user might actually type / tap, not a label

Return an empty array [] when:
  - The step is a confirmation / yes-no (options already exist in the widget)
  - You have no context to ground chips in (new session, empty summary)
  - Chips would be redundant with the widget options the user already sees

Output JSON only. No prose, no markdown fences.

EXAMPLES

Step prompt: "What locations to target?"
Session: "Business: PunkBakery (artisan bakery); Audience: 25-45 in Montreal"
→ ["Montreal", "Old Port Montreal", "Plateau Mont-Royal", "Mile End"]

Step prompt: "What is your campaign objective?"
Session: "Business: PunkBakery; Budget: $500/wk"
→ ["Awareness", "Traffic", "Sales", "Engagement"]

Step prompt: "How many days of historical visits should we include?"
Session: "Geo: deterministic — 12 POI(s) types: coffee shop"
→ ["7 days", "14 days", "30 days", "60 days"]

Step prompt: "Are these locations correct?"  (confirmation step)
Session: "..."
→ []
"""


def _make_chips_llm() -> ChatGoogleGenerativeAI:
    # thinking_budget=0 — same reasoning as _make_classifier_llm: short JSON-list
    # extraction, no benefit from dynamic thinking, and it was eating the timeout.
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        **settings.llm_auth,
        temperature=0.3,
        thinking_budget=0,
    )


async def generate_chips(
    step_key: str,
    state: Any = None,
) -> list[str]:
    """Return up to 4 tappable chip strings for a wizard step.

    Cached by ``(step_key, sha1(session_summary))`` — replay produces the
    same chips at $0 cost. On error / timeout returns an empty list so the
    frontend simply omits the chip row.
    """
    # Lazy imports to avoid a wizard_helpers → resume_router → wizard_helpers
    # circular dependency at module-load time.
    from app.graph.prompts_registry import STEP_PROMPTS
    from app.graph.wizard_helpers import _session_summary

    cfg = STEP_PROMPTS.get(step_key) or {}
    active_prompt = cfg.get("prompt") or ""
    if not active_prompt:
        return []

    session_summary = ""
    try:
        session_summary = _session_summary(state)
    except Exception:
        session_summary = ""

    cache_key = (step_key or "", _hash(session_summary))
    cached = _chip_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        llm = _make_chips_llm()
        msg, _ = await asyncio.wait_for(
            tracked_ainvoke(
                llm,
                [
                    SystemMessage(content=_CHIPS_SYSTEM_PROMPT),
                    HumanMessage(content=(
                        f"Active step: {step_key}\n"
                        f"Active prompt: {active_prompt}\n"
                        f"Session context: {session_summary}"
                    )),
                ],
                node_name=f"resume_router/chips/{step_key}",
                writer=None,
            ),
            timeout=_CHIPS_TIMEOUT_S,
        )
        text = msg.text.strip() if hasattr(msg, "text") else str(msg)
        text = _strip_fences(text)
        chips = json.loads(text)
        if not isinstance(chips, list):
            chips = []
        chips = [str(c).strip() for c in chips if isinstance(c, (str, int, float))]
        chips = [c for c in chips if c][:_CHIPS_MAX]
    except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
        logger.warning(
            "generate_chips fallback (%s) for step=%s", type(exc).__name__, step_key
        )
        chips = []
    except Exception as exc:
        logger.warning("generate_chips unexpected error: %s step=%s", exc, step_key)
        chips = []

    _chip_cache[cache_key] = chips
    return chips


__all__ = [
    "ResumeLane",
    "ResumeIntent",
    "ResumeResult",
    "is_sentinel_resume",
    "audience_panel_intent",
    "sanitize_panel_patch",
    "classify_resume_intent",
    "classify_resume_intent_tools",
    "generate_chips",
]
