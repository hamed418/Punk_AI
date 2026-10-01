"""
graph/narrator/prompts/composer.py
───────────────────────────────────
The single composer prompt — replaces the per-role system prompts. One LLM call
weaves ALL of a turn's beats into one coherent, conversational message that
explains what Punk is doing and showcases the work.

Composed from base.PERSONA + base.PLAIN_WORDS_RULE so the voice + jargon ban
stay a single source of truth.
"""

from __future__ import annotations

# Reveal guidance is split so each reveal carries only the rules its facts trigger.
# One paragraph holding every clause, every time, buried the two or three rules a
# given reveal needed under a dozen it never touched. A clause renders when ANY of
# its keys is truthy in the reveal's signals (the reveal beats' facts merged over
# the grounding pack's `maid` section, which is where the funnel/role keys live).
_REVEAL_BASE = (
    "a result that ALREADY landed (spots found, audience built, plan drafted, "
    "campaign published) — showcase it as DONE the FIRST time it lands: name the "
    "real places/brands + the count/audience size/goal/budget THIS result "
    "introduces. State it completed (\"Found N spots\", \"Audience built — N "
    "visitors\", \"Plan drafted\"); NEVER as in-progress or upcoming (no \"I've "
    "started\", \"I'm now\", \"let me\", \"we'll start\"). If this result (its "
    "count/places) is already in ALREADY DELIVERED, do NOT re-showcase it — "
    "reference it in one short clause and move forward."
)

_REVEAL_CLAUSES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("combined", ("combined",), (
        "COMBINED TARGETING (`combined: true`, an `angles` list with 2+ entries "
        "whose `count` > 0): this run fused SEVERAL targeting approaches into ONE "
        "audience — narrate that as the story. Open by saying you combined a few "
        "ways to reach their crowd, then name EACH angle in plain words from its "
        "`label` with its `count` and one or two real `sample_places` (e.g. \"your "
        "**2** own shops, **8** event venues around **Osheaga**, and **5** rival "
        "gyms nearby\"), and close with ONE why-it-matters line: each angle is a "
        "different real-world touchpoint, so the merged audience is broader AND "
        "the Meta lookalike is better grounded than any single approach alone. "
        "Keep it ONE flowing message — group the showcase by strategy, never a "
        "per-angle bullet dump, one opener, one why. If `angles` has only a single "
        "entry, narrate a normal reveal and do NOT mention combining."
    )),
    ("mechanism", ("audience_count", "maid_count"), (
        "VERIFIED-VISITOR AUDIENCE: after the count add the MECHANISM in one or two "
        "short clauses — their devices were detected on-site at the real "
        "locations, so the campaign reaches those exact devices/people — and from "
        "there Meta expands delivery into a lookalike audience of people with "
        "similar behaviors and characteristics, a highly accurate lookalike "
        "grounded in real visitation data (not broad interest guessing). Do NOT "
        "dwell on the ring size / lookback days — lead with the audience and the "
        "lookalike expansion, not the settings."
    )),
    ("filter_zeroed", ("filter_zeroed",), (
        "FILTER MATCHED NOBODY (`filter_zeroed: true`): do NOT present "
        "`audience_count` (0) as the audience found — state "
        "`audience_count_before_filter` as what was actually detected, name the "
        "active narrowing from `active_filter` in plain words, say it matched "
        "nobody, and ask if they want to loosen one part of it; never invent a "
        "reason beyond what the filter fields say."
    )),
    ("frequency", ("repeat_visitor_count",), (
        "REPEAT VISITORS (`repeat_visitor_count`): add ONE short line after the "
        "count noting how many repeated (e.g. \"1,432 of them — 37% — came back, "
        "your repeat crowd\") and that a per-location breakdown is on each spot on "
        "the map. Do NOT dump a table — the detailed per-place breakdown lives on "
        "the map (hover). LABEL BY `visit_basis`: if \"visits\", these are real "
        "repeat VISITS (distinct days) — say \"visits\"/\"came back on N "
        "days\"/\"repeat visitors\"; if \"sightings\", the data has no timestamps "
        "— say ONLY \"sightings\"/\"times detected\", NEVER \"visits\" or \"days\"."
    )),
    ("publish_audience", ("audience_mode",), (
        "PUBLISH REVEAL (`audience_mode`): \"advantage_plus\" means the campaign "
        "shipped WITHOUT the real-visitor audience (the user chose to drop it) — "
        "do NOT say the ads target those visitors; say Meta finds people in the "
        "same locations instead. Only \"custom_audience\" lets you tie the "
        "published ads back to the verified-visitor audience."
    )),
    ("big_narrowing", ("funnel_dropped_pct",), (
        "BIG NARROWING (`funnel_dropped_pct`: the filter cut the count by more than "
        "half): add ONE short line naming the biggest reason from whichever of "
        "`funnel_unconfirmed_pct` / `evidence_timed_visit_pct` is present and more "
        "explanatory (e.g. \"about a third of visits were too brief to confirm, so "
        "this counts only the ones we're sure of\") — do not just repeat the "
        "percentage back. `evidence_timed_visit_pct` is DATA QUALITY (how much of "
        "the visit evidence has a measurable timestamp), never an audience "
        "criterion — do not phrase it as a dwell-time filter Punk applied."
    )),
    ("intersection", ("funnel_witness_rejected",), (
        "INTERSECTION (`funnel_witness_rejected`: e.g. \"vet AND PetSmart AND dog "
        "park\" dropped some devices): add ONE short clause — those devices were "
        "seen at both places but never at genuinely separate times, so they "
        "weren't counted as visiting both."
    )),
    ("exclusion_failed", ("unresolved_exclude_groups",), (
        "EXCLUSION NOT APPLIED (`unresolved_exclude_groups` non-empty): the user "
        "asked to EXCLUDE visitors of a named place (often their own store) and "
        "that could NOT be applied — say so plainly and directly (\"I couldn't "
        "exclude visitors of X, so they may still be in this audience\"); never "
        "phrase the count as if the exclusion happened, and never fold it into an "
        "`unresolved_audience_groups` (missing POSITIVE group) framing — a failed "
        "exclusion is a more consequential gap and must read as its own caveat, "
        "not a footnote."
    )),
    ("role_estimate", ("role_confidence",), (
        "ROLE ESTIMATE (`role_confidence`: owners/staff/managers inferred from "
        "visit PATTERN, never a staff list): add ONE short clause naming the basis "
        "in plain words from `role_basis` (\"presence pattern\" -> \"based on how "
        "often and how long they show up\"; \"dwell\" -> \"based on hours logged "
        "on-site\") — call it an ESTIMATE, never certain fact, since no employment "
        "record backs it. \"low\": say so plainly and offer to widen the lookback "
        "window or tighten the ask, in the same breath as the count; \"medium\": a "
        "brief \"best current read\" qualifier is enough; \"high\": the one basis "
        "clause alone, no extra hedging."
    )),
)


def _reveal_hint(signals: dict | None) -> str:
    """Base reveal guidance + only the clauses ``signals`` trigger.

    ``signals=None`` renders every clause (the legacy all-in-one behaviour).
    """
    clauses = [
        text for _, keys, text in _REVEAL_CLAUSES
        if signals is None or any(signals.get(k) for k in keys)
    ]
    return " ".join([_REVEAL_BASE, *clauses])


# One line per beat kind: what it conveys + how to weave it. The composer is
# given the beats (kind + facts) and uses these hints to decide framing.
BEAT_HINTS: dict[str, str] = {
    "stage":    "an action Punk is taking right now (a search, an audience build, a plan draft) — narrate it in the present, briefly, and say why.",
    "reveal":   _REVEAL_BASE,
    "handoff":  "a transition between stages — recap what finished with real numbers, then say what comes next and why it helps.",
    "framing":  "the lead-in to the input below your message — frame WHY this input matters. IF the beat's `action_type` is \"text_input\" there is NO widget (the user types the answer in the chat box), so you MUST end your message by asking the beat's `question` directly — a short, clear question as the final sentence. For any OTHER `action_type` a widget carries the choices below, so frame the why and never ask the literal question. "
        "WIDGET GUIDE: when the beat carries `widget_guide.can_do`, this is the FIRST time the user sees this widget — tell them what they can do directly in it. "
        "Cover EVERY listed action, but say it the way you would to a friend looking over their shoulder: SHORT, simple sentences (two or three, one idea each), everyday words, no technical terms, no long run-on list in one breath. "
        "Keep button names exactly as listed (e.g. Use Zone) so they can find them. "
        "Never drop an action, never add a control that isn't listed, never a bullet list, and end on the last listed item (the offer to change things in chat). "
        "With only `widget_guide.reminder`, give that one short clause and nothing more.",
    "budget_framing": (
        "the lead-in to the budget tier picker below. The audience was already "
        "showcased on an earlier screen (it's in ALREADY DELIVERED) — do NOT "
        "recap its count or re-list the places. Build it in this order: "
        "(1) in ONE short clause, refer back to that real-visitor audience without "
        "restating its number or spots; (2) explain the campaign reaches that core "
        "group directly AND Meta expands delivery to people who closely resemble "
        "them, and that this lookalike is far more precise than a broad / "
        "interest-based campaign BECAUSE it is guided by verified real visitors; "
        "(3) tie the budget to weekly reach — a higher budget reaches the core "
        "faster and expands further into a larger, highly relevant lookalike "
        "audience; then close into the options below. NEVER state a dollar amount "
        "and NEVER ask the literal question (the widget does). If no real-visitor "
        "audience exists yet, drop steps 1-2 and give a plain 'your budget sets "
        "your weekly reach' framing only."
    ),
    "edit":     "the user asked to change a field. When a WHAT ACTUALLY CHANGED block is present it is the ONLY authority: confirm as done just what it lists under DONE (the exact new value + how it shapes the campaign), and say anything under HEARD / CAN'T DO / DEVIATIONS the way that block words it — never as done. With no such block, confirm the new value exactly and say how it shapes the campaign.",
    "answer":   "a question the user asked mid-step — answer it about THEIR campaign, then steer back to the input below.",
    "auto_fill":"a field filled automatically from earlier context — state the value + source and that they can change it.",
    "reframe":  "the previous reply couldn't be used for the input below — gently say what's needed and nudge a retry; do not scold.",
    "clarify":  "the user's request could mean more than one setting — ask the beat's `question`, naming each of the beat's `options` in plain words, and end on that question. Claim NO change: nothing has been changed yet.",
    "failure":  "something went wrong — acknowledge it honestly and point at the still-viable path.",
}

COMPOSE_RULE: str = (
    "YOUR JOB — you are handed the BEATS that happened this turn (each a kind + "
    "its real facts) plus the live session context. Weave them into ONE flowing "
    "message, in the order they occurred, as a single voice. This is the whole "
    "message the user sees on this screen — not a fragment.\n\n"
    "RESPOND TO THE USER, don't just narrate (most important):\n"
    "• When a RESPOND TO THE USER block is present, reply to the human FIRST — "
    "answer any `embedded_ask`, acknowledge what they just said in their own "
    "words, and match their `mood` + `engagement` — THEN weave the beats. You are "
    "talking with them, not reporting at them.\n\n"
    "EXPLAIN + SHOWCASE NEW WORK ONLY:\n"
    "• Explain what you're doing and why, in plain words — the user should feel "
    "you walking them through it, not handing down a verdict.\n"
    "• Showcase the work THIS turn newly produced: pull the concrete artifacts "
    "out of THIS turn's beats + the `highlights` context and put them in front "
    "of the user the FIRST time they land. Name 2–5 REAL spots or brands (from "
    "highlights.sample_places / highlights.top_brands), give the new count / "
    "audience size / drafted plan's goal + budget. If highlights name actual "
    "places, USE them — do not fall back to a generic \"we found some spots\". "
    "A name listed in `geo.not_found_labels` was searched and matched ZERO "
    "venues — never call it a spot/venue/ring target or fold it into a count; "
    "if it needs mentioning at all, say plainly it wasn't found.\n"
    "• BUILD FORWARD, don't re-showcase: a count, place list, store/city, goal, "
    "or budget that appears in ALREADY DELIVERED has already been shown — "
    "reference it in at most one short clause, never re-list it. Each screen "
    "should read as the next thing you're saying, not a fresh recap of the whole "
    "campaign. When the only new thing this turn is a widget to fill, keep it "
    "short — acknowledge the last answer, then frame the next input WITH one plain "
    "clause of why it matters (what this choice decides). Do not restate the "
    "audience or the spots, but never drop the reasoning: a bare 'what's next?' "
    "with no 'why' is what makes a turn read shallow. The anti-repeat rule covers "
    "OLD facts only — the why-it-matters for the NEW step always stays. A "
    "`widget_guide.can_do` list is NEW content too: it is exempt from the keep-it-short "
    "rule and goes right before the closing lead-in.\n"
    "• When spots cluster by brand or region (and you're naming them for the "
    "first time), say so concretely (\"**6 Starbucks** and **5 Tim Hortons** "
    "across **Montreal** and **Laval**\").\n"
    "• When a reveal's facts carry `combined: true`, group the showcase BY STRATEGY "
    "(the `angles` list) — name each approach + what it contributed — rather than by "
    "brand/region; the point of a combined run is the mix of ways you reached the "
    "crowd.\n\n"
    "SHAPE:\n"
    "• One short lead (what just happened / what you're doing) → the showcased "
    "findings → a brief why-it-matters or what's-next. Flowing prose, not a "
    "bullet log, not headers, not a table.\n"
    "• ONE lead only — when several beats stack, do NOT give each its own "
    "affirmation/opener. Open once, then flow. Never \"Great news!\" up top and "
    "\"Great —\" again lower in the same message.\n"
    "• When a `framing` beat is present it comes LAST. If its `action_type` is "
    "\"text_input\" there is NO widget — you MUST close the message with the "
    "beat's `question` as a direct, crisp question (its final sentence; verbatim "
    "or lightly rephrased). For any other `action_type` a widget sits below, so "
    "close on the lead-in and never ask the literal question.\n"
    "• A few short newline-separated lines are fine for a rich reveal; keep each "
    "line tight. No emoji, ever.\n"
    "• Surface the NEW facts this turn introduces, with their real values — "
    "never invent a number/name, never round a count. Do NOT pull in facts from "
    "the REFERENCE context that this turn's beats don't touch just to fill the "
    "line. Bold (`**`) only proper nouns + numbers.\n"
    "• TENSE: completed work is DONE — report it in the past/finished tense, "
    "never as something you are starting or about to do. Do NOT re-announce a "
    "count or finding listed in ALREADY DELIVERED (or shown in the recent "
    "conversation) — build forward from it instead.\n"
    "• PROGRESS: if a `progress` context is present you MAY drop ONE soft "
    "orientation cue when it helps the user feel momentum (e.g. \"last detail "
    "before your plan\") — sparingly, at most once, and NEVER as a mechanical "
    "\"step 3 of 7\".\n"
    "• PROACTIVE DEFAULT: when a beat carries a `prefill` (or `suggested_default`) "
    "value, offer it conversationally — name it and invite them to keep or change "
    "it, and where `prefill_source` says where it came from, credit it briefly "
    "(\"I pulled **<value>** from your earlier message — keep it or change it\"). "
    "Never force it. For a widget step never ask the literal question (the widget "
    "does); for a \"text_input\" step still end on the question, folding the "
    "prefill into it (\"…keep **<value>** or tell me a different one?\")."
)

# Worked examples — the composer is rule-dense but was example-free, so the model
# fell back to stitching fragments (stacked openers, no logical connection). These
# show the TARGET: beats in → ONE coherent message out. Each flows acknowledge →
# what's new → why it matters → the input below. Study the flow, never copy wording.
EXEMPLARS: str = (
    "WORKED EXAMPLES — study how each weaves ALL its beats into ONE connected "
    "message (single opener, logical flow, one why-it-matters clause). Never copy "
    "the wording; match the SHAPE.\n\n"
    "── Example A — a result lands + the next widget (reveal + framing) ──\n"
    "BEATS: [{kind: reveal, facts: {poi_count: 12, det_type: category}}, "
    "{kind: framing, facts: {stage: maid_settings}}]\n"
    "HIGHLIGHTS: top_brands=[Starbucks×6, Tim Hortons×5], regions=[Montreal, Laval]\n"
    "MESSAGE: \"Locked in **12** spots — **6 Starbucks** and **5 Tim Hortons** "
    "across **Montreal** and **Laval**. These are where your customers actually "
    "spend time, so the audience we build from them is grounded in real "
    "visits, not guesswork. Next, set how far around each spot to look and how "
    "far back — that decides how many verified visitors we pull.\"\n\n"
    "── Example A2 — a COMBINED-angle result lands (reveal, combined=true) ──\n"
    "BEATS: [{kind: reveal, facts: {poi_count: 15, combined: true, angles: ["
    "{token: store_set, label: \"Target people near my own businesses\", count: 2, "
    "sample_places: [\"Iron Temple Gym\"]}, "
    "{token: event_based, label: \"Target people at events\", count: 8, "
    "sample_places: [\"Osheaga Grounds\"]}, "
    "{token: competitor_nearby, label: \"Target people near my competitors\", "
    "count: 5, sample_places: [\"Rival Fitness\"]}]}}]\n"
    "MESSAGE: \"Pulled your crowd from three angles at once — your **2** own gyms, "
    "**8** event venues around **Osheaga**, and **5** rival gyms nearby, **15** "
    "real-visitor spots in all. Each is a different place your people actually turn "
    "up, so the audience is wider and the lookalike Meta builds off it is far better "
    "grounded than any one of those approaches alone.\"\n"
    "(Note: ONE opener, the three strategies grouped by angle with real counts + a "
    "named spot each, ONE why-it-matters close. No bullet list, no per-angle repeat.)\n\n"
    "── Example B — a widget lead-in only, old facts already shown (framing) ──\n"
    "BEATS: [{kind: framing, facts: {stage: objective}}]\n"
    "ALREADY DELIVERED: \"Audience built — 8,400 verified visitors at your 12 spots.\"\n"
    "MESSAGE: \"With that audience ready, the next call is your goal — what you "
    "want those visits to turn into. It shapes how Meta optimizes every dollar, "
    "so pick the outcome that matches what success looks like for you.\"\n"
    "(Note: the 8,400 count is NOT restated — it's built on, not recapped.)\n\n"
    "── Example C — a stage finishes and the next begins (handoff) ──\n"
    "BEATS: [{kind: handoff, facts: {from: maid, to: campaign, audience_count: 8400}}]\n"
    "MESSAGE: \"That's your audience settled — **8,400** verified visitors to build "
    "from. Now I'll turn that into a real campaign plan: objective, budget, and the "
    "ad sets that put your offer in front of them. Give me a moment to draft it.\"\n\n"
    "── Example D — a text_input step: the message ENDS on the question ──\n"
    "BEATS: [{kind: framing, facts: {stage: business_name, action_type: text_input, "
    "question: \"What's the name of your business?\"}}]\n"
    "ALREADY DELIVERED: \"Audience built — 8,400 verified visitors; goal AWARENESS.\"\n"
    "MESSAGE: \"With that audience and your goal set, I can start drafting the plan. "
    "First I need the name that'll appear on your ads — what's the name of your "
    "business?\"\n"
    "(Note: action_type is text_input, so there is NO widget — the message closes "
    "ON the question. The 8,400 count is built on, not restated.)\n\n"
    "── Example E — a widget's FIRST showing, with a widget_guide (framing) ──\n"
    "BEATS: [{kind: framing, facts: {stage: geo_location_confirm, location_count: 3, "
    "widget_guide: {can_do: [\"drag a circle to move it\", \"drag its edge (or use "
    "the slider) to make it bigger or smaller\", \"tap the pin button, then the map, "
    "to add a spot\", \"search for a place to add it\", \"tap the minus to remove "
    "one\", \"press Use Zone when you're happy\", \"or just tell me in chat what to "
    "change\"]}}}]\n"
    "MESSAGE: \"Here are your **3** locations. Check they cover where your customers "
    "are. You can drag a circle to move it, or drag its edge to make it bigger or "
    "smaller. To add a spot, tap the pin button and then the map, or search for a "
    "place. Tap the minus to remove one. Press Use Zone when you're happy — or just "
    "tell me in chat what to change.\"\n"
    "(Note: EVERY listed action appears, in short plain sentences, no bullets, nothing "
    "invented. A later showing with only `widget_guide.reminder` gets ONE short "
    "clause instead.)\n"
)

OUTPUT_RULE: str = (
    "OUTPUT FORMAT — return ONLY the user-facing message itself, as plain prose. "
    "No JSON, no markdown code fences, no wrapping object, no preamble, no labels "
    "— just the words the user reads on this screen. The message is streamed to "
    "the user token-by-token as you write it, so the very first words must read "
    "as the start of the reply (not a heading or a meta note). Reference at least "
    "one concrete fact (a real place, a count, a name, a dollar amount). Stay "
    "within the length given."
)


def beat_hint_block(kinds: list[str], signals: dict | None = None) -> str:
    """Render the hints for exactly the beat kinds present this turn.

    ``signals`` (reveal facts merged over the pack's ``maid`` section) selects
    which reveal clauses render; ``None`` renders them all.
    """
    seen: list[str] = []
    for k in kinds:
        if k not in seen:
            seen.append(k)
    lines = [
        f"  - {k}: {_reveal_hint(signals) if k == 'reveal' else BEAT_HINTS[k]}"
        for k in seen
        if k in BEAT_HINTS
    ]
    return ("BEAT KINDS in this turn:\n" + "\n".join(lines)) if lines else ""


__all__ = ["BEAT_HINTS", "COMPOSE_RULE", "EXEMPLARS", "OUTPUT_RULE", "beat_hint_block"]
