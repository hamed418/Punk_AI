"""
graph/prompts_registry.py
─────────────────────────
Central registry of wizard interrupt prompts.

Each key is a sub-node identifier (e.g. ``geo_collect_location_type``).  The
value describes how that sub-node should interrupt:

    field            — AgentState key / PendingAction.field slug returned to the UI
    action_type      — one of text_input | option_selection | permission |
                       map_interaction | file_upload
    prompt           — default human-readable prompt text (may be overridden at call
                       site when the phrasing depends on prior state)
    options          — default option list for option_selection actions
    preview_hint     — one-sentence description of what the *next* step will ask,
                       fed to the smart-ack LLM so it can preview what's coming
    next_step_key    — default successor step; sub-nodes with conditional branching
                       override this at the call site

The registry drives both the wizard helper's interrupt() payload and the smart
acknowledgement LLM, keeping all conversational scripting in one place.
"""

from __future__ import annotations


# ── Shared option lists (duplicated here so wizards don't import nodes.py) ─────

GEO_LOCATION_TYPE_OPTIONS: list[str] = [
    "Target country group",
    "Target State/Province or District",
    "Target a specific city, Zip or address",
    "Drop a pin and set the targeting area",
]

# Two competitor lines, not one: the anchored angle needs a street address the
# advertiser may not have (SaaS / e-commerce / service-area), so the whole-area
# alternative is offered where the user already clicks rather than behind a
# follow-up question. They map to the competitor_nearby / competitor_area tokens.
GEO_DETERMINISTIC_OPTIONS: list[str] = [
    "Let punk find the best spots for me",
    "Search for types of places (like gyms, cafes, or parks)",
    "Target people near my own business addresses",
    "Target people near my competitors — around my business address",
    "Target people near my competitors — across my whole targeting area",
    "Search for big brand names (like Starbucks or Walmart)",
    "I already know the exact places I want to target",
    "Target people at events (like concerts, festivals, or games)",
]

PIXEL_STATUS_OPTIONS: list[str] = [
    "Installed & verified — pixel is live and sending confirmed conversion events",
    "Installed but not verified — pixel is on the site but conversion events are unconfirmed",
    "Not installed — no Meta Pixel on the website yet",
]

# How much of the campaign the user wants Punk to build, asked once the audience
# exists and Meta is connected. Matched in builder_node by the label prefix before
# the em-dash (`_normalize_publish_mode`), so only the first few words of each
# line are load-bearing — the description after the dash is free copy.
#   • Export audience to Meta       → export the audience as a Custom Audience and stop.
#   • Set up campaign manually in Punk → the full campaign editor (the flow that already exists).
#   • Let Punk setup the campaign   → short basics form, then an ads-only editor.
PUBLISH_MODE_OPTIONS: list[str] = [
    "Export audience to Meta — Finish setting up the campaign in Meta Ads Manager",
    "Set up campaign manually in Punk — Set campaign type, budget, optimization and other parameters through Punk",
    "Let Punk setup the campaign — Let Punk's expert agents create and optimize your entire campaign",
]

# Shown on the Preview & Publish screen, after the campaign exists in Meta but
# PAUSED. Matched by the `set live` / `leave it` prefixes.
GO_LIVE_OPTIONS: list[str] = [
    "Set it live — start delivering this campaign now",
    "Leave it paused — I'll switch it on myself in Ads Manager",
]

# There is no publish-confirm option list any more. The plan editor's own Publish
# button is the confirmation, publish creates every Meta object PAUSED, and
# GO_LIVE_OPTIONS above is the only thing standing between the campaign and spend.
# The audience-blocked case (an ad account outside a Business cannot hold a
# customer-list audience — subcode 1870050) no longer asks either: it publishes on
# Advantage+ inside the same locations and says so, in the publish message and on
# the Preview & Publish screen. See builder_node._audience_notice.


# ── STEP_PROMPTS ──────────────────────────────────────────────────────────────

STEP_PROMPTS: dict[str, dict] = {
    # ── geo_wizard — smart-confirm steps (shown when context was pre-extracted) ──
    "geo_context_confirm_location_type": {
        "field": "geo_location_type",
        "title": "Location Type",
        "subtitle": "Select a location type.",
        "action_type": "option_selection",
        "prompt": "We detected a targeting scope — continue or choose a different one?",
        "options": ["Yes, continue", "No, choose different"],
        "preview_hint": "Next I'll ask where exactly to target.",
        "next_step_key": "geo_collect_locations",
    },
    "geo_context_confirm_det_type": {
        "field": "geo_deterministic_type",
        "title": "Audience Signals",
        "subtitle": "Select audience signals.",
        "action_type": "option_selection",
        "prompt": "We detected a POI discovery approach — continue or pick a different one?",
        "options": ["Yes, continue", "No, pick different"],
        "preview_hint": "Depending on the choice, I'll ask for place types, addresses, brands, or events.",
        "next_step_key": "geo_execute",
    },
    "geo_wizard_plan_review": {
        "field": "geo_plan_confirm",
        "title": "Geo Plan Confirm",
        "subtitle": "Provide the requested information.",
        "action_type": "permission",
        "prompt": "Are these the right locations?",
        "options": [],
        "preview_hint": "If confirmed, I'll jump straight to the next phase of planning.",
        "next_step_key": None,
    },
    # ── geo_wizard ────────────────────────────────────────────────────────────
    "geo_collect_location_type": {
        "field": "geo_location_type",
        "title": "Location Type",
        "subtitle": "Select a location type.",
        "action_type": "option_selection",
        "prompt": "What is your location targeting scope?",
        "options": GEO_LOCATION_TYPE_OPTIONS,
        "preview_hint": "Next I'll ask where exactly to target.",
        "next_step_key": "geo_collect_locations",
    },
    "geo_collect_locations": {
        "field": "geo_locations",
        "title": "Location Confirmation",
        "subtitle": "Review selected locations.",
        "action_type": "text_input",
        "prompt": "What locations to target?",
        "options": [],
        "preview_hint": "Then I'll ask how to find your target locations.",
        "next_step_key": "geo_collect_det_type",
    },
    "geo_collect_radius_pin": {
        "field": "geo_radius_pin",
        "title": "Geo Radius Pin",
        "subtitle": "Provide the requested information.",
        "action_type": "map_interaction",
        "prompt": "Pin your target location on the map.",
        "options": [],
        "preview_hint": "Next I'll ask for the radius around that pin.",
        "next_step_key": "geo_collect_radius_km",
    },
    "geo_collect_radius_km": {
        "field": "geo_radius_km",
        "title": "Geo Radius Km",
        "subtitle": "Provide the requested information.",
        "action_type": "stepper_input",
        "prompt": "What radius in kilometers should we target around your pin?",
        "options": [],
        "stepper": {"default": 10, "min": 1, "max": 80, "step": 1, "unit": "km"},
        "preview_hint": "Next I'll ask how to find your target locations.",
        "next_step_key": "geo_collect_det_type",
    },
    "geo_collect_det_type": {
        "field": "geo_deterministic_type",
        "title": "Audience Signals",
        "subtitle": "Select audience signals.",
        "action_type": "option_selection",
        "prompt": "How would you like to find your target locations?",
        "options": GEO_DETERMINISTIC_OPTIONS,
        "preview_hint": "Depending on the choice, I'll ask for place types, addresses, brands, or events.",
        "next_step_key": "geo_execute",
    },
    "geo_collect_poi_types": {
        "field": "geo_poi_types",
        "title": "Points of Interest",
        "subtitle": "Choose relevant locations.",
        "action_type": "text_input",
        "prompt": "What types of places to target? (comma-separated, e.g. gym, fitness center, yoga studio)",
        "options": [],
        "preview_hint": "After this I'll search for those locations and confirm them on the map.",
        "next_step_key": "geo_execute",
    },
    "geo_collect_stores": {
        "field": "geo_store_addresses",
        "title": "Business Addresses",
        "subtitle": "Review business locations.",
        "action_type": "text_input",
        "prompt": (
            "Enter your business address(es). Use a semicolon ( ; ) to separate multiple "
            "addresses. Example: 123 Main St, Montreal, QC ; 456 Rue Sainte-Catherine, Montreal, QC"
        ),
        "options": [],
        "preview_hint": "After this I'll map your locations and show them for confirmation.",
        "next_step_key": "geo_execute",
    },
    "geo_collect_store_anchor": {
        "field": "geo_store_address_for_competitors",
        "title": "Business Locations",
        "subtitle": "Enter one or more business addresses.",
        "action_type": "text_input",
        "prompt": (
            "Enter your business address — got multiple locations? Separate them with a semicolon (;). "
            "We'll find competitors near each. Example: 123 Main St, Montreal, QC ; 456 Rue Sainte-Catherine, Montreal, QC"
        ),
        "options": [],
        "preview_hint": "Next I'll ask how far around your business to look for competitors.",
        "next_step_key": "geo_collect_competitor_radius",
    },
    "geo_collect_competitor_radius": {
        "field": "geo_competitor_radius",
        "title": "Geo Competitor Radius",
        "subtitle": "Provide the requested information.",
        "action_type": "stepper_input",
        "prompt": "How far around your business should we search for competitors?",
        "options": [],
        "stepper": {"default": 5, "min": 0.5, "max": 50, "step": 0.5, "unit": "km"},
        "preview_hint": "After this I'll search for competitor locations and show them on the map.",
        "next_step_key": "geo_execute",
    },
    "geo_collect_brands": {
        "field": "geo_brand_names",
        "title": "Competitor Brands",
        "subtitle": "Enter competitor brands.",
        "action_type": "text_input",
        "prompt": "Which brand(s) to target? (comma-separated, e.g. Starbucks, Tim Hortons)",
        "options": [],
        "preview_hint": "After this I'll look up those brand locations and confirm them.",
        "next_step_key": "geo_execute",
    },
    "geo_collect_named_places": {
        "field": "geo_named_places",
        "title": "Specific Places",
        "subtitle": "Name the exact places to target.",
        "action_type": "text_input",
        "prompt": "Which places? Name them (comma-separated), e.g. Fight Club, McGrill Bar, Tomahawk.",
        "options": [],
        "preview_hint": "After this I'll find each place and show them on the map to confirm.",
        "next_step_key": "geo_execute",
    },
    "geo_collect_events": {
        "field": "geo_event_type",
        "title": "Target Events",
        "subtitle": "Choose relevant events.",
        "action_type": "text_input",
        "prompt": (
            "Which event(s) to target? Enter event types or specific names, comma-separated. "
            "(e.g. music festivals, Osheaga, tech conferences, F1 Grand Prix)"
        ),
        "options": [],
        "preview_hint": "Next I'll ask for the date range to search within.",
        "next_step_key": "geo_collect_event_date_range",
    },
    "geo_collect_event_date_range": {
        "field": "geo_event_date_range",
        "title": "Geo Event Date Range",
        "subtitle": "Provide the requested information.",
        "action_type": "text_input",
        "prompt": "What date range should we search? (e.g. Summer 2025, Jan 2025 - Dec 2025, next 6 months)",
        "options": [],
        "preview_hint": "After this I'll run the event search and show venues on the map.",
        "next_step_key": "geo_execute",
    },
    # Runtime confirmations that live inside geo_execute (dynamic prompt text)
    "geo_disambiguate_location": {
        "field": "geo_disambiguate_location",
        "title": "Location Confirmation",
        "subtitle": "Select your proffered location",
        "action_type": "option_selection",
        "prompt": "That place name matches more than one location — which one do you mean?",
        "options": [],   # overridden per call with the enumerated candidate labels
        "preview_hint": "Then I'll continue mapping your target area.",
        "next_step_key": None,
    },
    "geo_disambiguate_named_place": {
        "field": "geo_disambiguate_named_place",
        "title": "Which Place?",
        "subtitle": "Select the exact place you mean",
        "action_type": "option_selection",
        "prompt": "That name matches more than one place — which one do you mean?",
        "options": [],   # overridden per call with the enumerated candidate labels
        "preview_hint": "Then I'll pin it and continue building your audience.",
        "next_step_key": None,
    },
    "geo_location_confirmation": {
        "field": "geo_location_confirmation",
        "title": "Geo Location Confirmation",
        "subtitle": "Provide the requested information.",
        "action_type": "permission",
        "prompt": "Are these locations correct?",
        "options": [],
        "preview_hint": "Next I'll search for targeting locations within these areas.",
        "next_step_key": None,
    },
    "geo_store_confirmation": {
        "field": "geo_store_confirmation",
        "title": "Business Location Confirmation",
        "subtitle": "Provide the requested information.",
        "action_type": "permission",
        "prompt": "Are the business locations on the map correct?",
        "options": [],
        "preview_hint": "Next I'll build your audience from these locations.",
        "next_step_key": None,
    },
    "geo_confirm_store_anchor": {
        "field": "geo_competitor_store_confirmation",
        "title": "Business Location Confirmation",
        "subtitle": "Provide the requested information.",
        "action_type": "permission",
        "prompt": "Is this your business location?",
        "options": [],
        "preview_hint": "Next I'll search nearby competitors.",
        "next_step_key": None,
    },
    "geo_pois_confirmation": {
        "field": "geo_pois_confirmation",
        "title": "Geo Pois Confirmation",
        "subtitle": "Provide the requested information.",
        "action_type": "permission",
        "prompt": "Confirm these as your targeting locations.",
        "options": [],
        "preview_hint": "Next I'll ask how tight to draw the ring and how far back to count visits.",
        "next_step_key": "maid_collect_poi_radius",
    },

    # ── maid_wizard ───────────────────────────────────────────────────────────
    "maid_collect_poi_radius": {
        "field": "maid_poi_radius",
        "title": "Maid Poi Radius",
        "subtitle": "Provide the requested information.",
        "action_type": "stepper_input",
        "prompt": "How close to each spot should we draw the ring?\n\n(50–100 m = inside the venue · 200–500 m = nearby foot traffic)",
        "options": [],
        "stepper": {"default": 100, "min": 1, "max": 500, "step": 5, "unit": "m"},
        "preview_hint": "Next I'll ask how far back to count visits.",
        "next_step_key": "maid_collect_lookback",
    },
    # Combined poi_radius + lookback ask — one interrupt, two steppers. Used by the
    # builder's poi_radius_m slot (slots.py). action_type stays "stepper_input"; the
    # presence of `steppers` (a non-null list) is the discriminator — when set, the
    # frontend renders N stepper controls in one widget and resumes with JSON keyed
    # by each `key`, e.g. {"poi_radius_m": 250, "lookback_days": 14}. `stepper`
    # (singular) is intentionally absent so there is no ambiguity. builder_ask splits
    # the JSON answer into both slots; a non-JSON answer fills only poi_radius_m and
    # lookback_days is asked standalone (maid_collect_lookback).
    "maid_collect_settings": {
        "field": "maid_poi_radius",
        "title": "Maid Poi Radius",
        "subtitle": "Provide the requested information.",
        "action_type": "stepper_input",
        "prompt": "Tune your audience — set the ring around each spot and how far back to count visits:",
        "options": [],
        "steppers": [
            {"key": "poi_radius_m", "label": "Ring radius", "hint": "How close to a spot counts as a visit. 50–100 m = inside the venue, 200–500 m = nearby foot traffic.", "default": 100, "min": 1, "max": 500, "step": 5, "unit": "m"},
            {"key": "lookback_days", "label": "Look back", "hint": "How far back to count visits. More days means a bigger audience.", "default": 7, "min": 1, "max": 90, "step": 1, "unit": "days"},
        ],
        "preview_hint": "After this I'll build the audience and show you a summary.",
        "next_step_key": "maid_execute",
    },
    "maid_collect_lookback": {
        "field": "maid_lookback",
        "title": "Maid Lookback",
        "subtitle": "Provide the requested information.",
        "action_type": "stepper_input",
        "prompt": "How far back should we count visits? More days means a bigger audience.",
        "options": [],
        "stepper": {"default": 7, "min": 1, "max": 90, "step": 1, "unit": "days"},
        "preview_hint": "After this I'll build the audience and show you a summary.",
        "next_step_key": "maid_execute",
    },
    "maid_confirm_results": {
        "field": "maid_confirm_results",
        "title": "Maid Confirm Results",
        "subtitle": "Provide the requested information.",
        "action_type": "permission",
        "prompt": "Does this audience look right?",
        "options": [],
        "preview_hint": "Next I'll start planning your campaign details.",
        "next_step_key": "END",
    },

    # ── campaign_builder ─────────────────────────────────────────────────────
    # First question of the campaign stage, asked right after connect_meta so the
    # answer can decide whether the rest of the stage runs at all.
    "campaign_publish_mode": {
        "field": "campaign_publish_mode",
        "title": "Campaign Setup",
        "subtitle": "Choose how you'd like Punk to prepare your campaign.",
        "action_type": "option_selection",
        "prompt": "Your audience is ready. How would you like to take it to Meta?",
        "options": PUBLISH_MODE_OPTIONS,
        "preview_hint": "Whichever you pick, nothing goes live until you say so.",
        # No static next step: "Export audience to Meta" exports the audience and
        # stops, "Set up campaign manually in Punk" goes straight to the plan
        # editor (business name/what-you-sell are collected upstream by the entry
        # gate, objective is inferred by the brief), and only "Let Punk setup the
        # campaign" opens the intake form. The mode isn't known until this
        # question is answered, so nothing here can be resolved ahead of time.
        "next_step_key": None,
    },
    # The express-only intake form: budget, flight, Page, and the objective select
    # — the answers the ads-only editor cannot default because it never shows the
    # campaign/ad-set panes. Business name and what-you-sell/USP are collected by
    # the entry gate before the build even starts and simply prefill here.
    # action_type is emitted as campaign_intake_form with form_schema attached by
    # builder_node._enrich_slot_ask (campaign_intake branch).
    "campaign_intake_form": {
        "field": "campaign_intake",
        "title": "Campaign Setup",
        "subtitle": "Tell us about your business and campaign.",
        "action_type": "campaign_intake_form",
        "prompt": "Let's set up your campaign — fill in the details below.",
        "options": [],
        "preview_hint": "Next I'll draft the full campaign plan for review.",
        "next_step_key": "campaign_plan_confirm",
    },
    # No campaign_collect_pixel_id step: the Meta Pixel is asked in the plan
    # editor below, where the account's actual pixels are the options.
    # The bespoke campaign editor. action_type + spec / catalog / locks / errors
    # are attached at call time by builder_node._plan_form_extra.
    "campaign_plan_confirm": {
        "field": "campaign_plan_confirm",
        "title": "Campaign editor",
        "subtitle": "Review and edit your campaign, ad sets and ads.",
        "action_type": "campaign_plan_editor",
        "prompt": (
            "Here's your campaign. Everything is editable — add ad sets or ads, adjust "
            "targeting and creative, then publish. Where your audience includes visitor "
            "profiles, they come from commercially licensed mobile location data — "
            "publishing uploads that audience to the Meta ad account you connect."
        ),
        "options": [],
        "preview_hint": "Next I'll connect Meta and publish.",
        "next_step_key": None,
    },

    # ── media_wizard ──────────────────────────────────────────────────────────
    "media_check_meta_auth": {
        "field": "meta_oauth_connect",
        "title": "Meta Oauth Connect",
        "subtitle": "Provide the requested information.",
        "action_type": "oauth_connect",
        "prompt": (
            "To publish your campaign, connect your Meta Ads account. "
            "Click the button below to authorize PunkAI — it only takes a moment."
        ),
        "options": [],  # overridden at call site with the live OAuth URL
        "preview_hint": "Once connected, I'll load your ad accounts automatically.",
        "next_step_key": "media_select_ad_account",
    },
    "media_select_ad_account": {
        "field": "meta_ad_account_id",
        "title": "Meta Ad Account Id",
        "subtitle": "Provide the requested information.",
        "action_type": "option_selection",
        "prompt": "Which Meta ad account should we use for this campaign?",
        "options": [],  # overridden at call site with the user's actual accounts
        "preview_hint": "Next I'll confirm pixel tracking (if needed), then ask to publish.",
        "next_step_key": "media_select_pixel",
    },
    "media_select_pixel": {
        "field": "meta_pixel_id",
        "title": "Meta Pixel Id",
        "subtitle": "Provide the requested information.",
        "action_type": "option_selection",
        "prompt": "Which Pixel should track conversions for this campaign?",
        "options": [],  # overridden at call site with the user's actual pixels
        "preview_hint": "After this I'll build the campaign in Meta, paused, for you to preview.",
        "next_step_key": "media_confirm_go_live",
    },
    # Asked AFTER the campaign exists in Meta, PAUSED. The widget payload
    # (campaign/ad ids + the summary rows) is attached at call time by
    # builder_node._preview_extra; the ad previews themselves are fetched by the
    # client from /ads/ad-previews so their short-lived iframe URLs stay fresh.
    "media_confirm_go_live": {
        "field": "meta_go_live_confirm",
        "title": "Preview & Publish",
        "subtitle": "Review your campaign before it goes live.",
        "action_type": "option_selection",
        "prompt": (
            "Your campaign is built in Meta and PAUSED — nothing is spending yet. "
            "Preview how it looks, then switch it on when you're happy."
        ),
        "options": GO_LIVE_OPTIONS,
        "preview_hint": "Setting it live is the last step.",
        "next_step_key": None,
    },
}
