import type {
  Block,
  ConfirmLocationsData,
  MaidSplitViewData,
  MapDataBlock,
  MessageBlock,
  PendingActionBlock,
  PoiRadiusPickerData,
  RadiusPickerData,
} from "@/types/chat";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _id = 0;
const uid = () => `dummy-${++_id}`;

// ---------------------------------------------------------------------------
// pending_action blocks
// ---------------------------------------------------------------------------

export const dummyOptionSelection: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "option_selection",
    field: "geo_location_type",
    prompt: "What is your location targeting scope?",
    options: [
      "Country Groups — select broad regions like Asia, GCC Free Trade Areas, or Emerging Markets",
      "Admin Areas — choose specific countries, states/provinces, or congressional districts",
      "Granular Local Areas — select cities, postal codes (ZIP codes), or specific addresses",
      "Radius Targeting — pin a spot on the map and set a delivery radius (1–50 miles)",
    ],
    prefill: undefined,
    stepper: null,
    progress: null,
  },
};

export const dummyOptionSelectionWithProgress: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "option_selection",
    field: "geo_targeting_method",
    prompt: "Which targeting method would you like to use?",
    options: [
      "Programmatic — Meta's AI uses real-time signals to find new customers likely to convert",
      "Deterministic — reach exact device IDs observed at specific POIs; 1:1 precision geofencing",
    ],
    prefill: undefined,
    stepper: null,
    progress: [
      { label: "Targeting Scope", value: "Granular Local" },
      { label: "Locations", value: "Montreal, Toronto" },
      { label: "Business", value: "Coffee shop chain…" },
    ],
  },
};

export const dummyTextInput: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "text_input",
    field: "geo_locations",
    prompt:
      "What cities, towns, or postal codes to target? (e.g. Montreal QC, Brooklyn NY 11201)",
    options: [],
    prefill: "Montreal",
    stepper: null,
    progress: [{ label: "Targeting Scope", value: "Granular Local" }],
  },
};

export const dummyPermission: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "permission",
    field: "geo_location_confirmation",
    prompt:
      "Found 2 location(s) on the map: Montreal, Toronto. Proceed with these locations?",
    options: [],
    prefill: undefined,
    stepper: null,
    progress: null,
  },
};

export const dummyStepperInput: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "stepper_input",
    field: "geo_radius_miles",
    prompt: "What radius in miles should we target around your pin?",
    options: [],
    prefill: undefined,
    stepper: { default: 10, min: 1, max: 50, step: 1, unit: "miles" },
    progress: [{ label: "Targeting Scope", value: "Radius" }],
  },
};

export const dummyMapInteraction: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "map_interaction",
    field: "geo_radius_pin",
    prompt: "Pin your target location on the map.",
    options: [],
    prefill: undefined,
    stepper: null,
    progress: [{ label: "Targeting Scope", value: "Radius" }],
  },
};

export const dummyFileUpload: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "file_upload",
    field: "ad_creative",
    prompt:
      "Please upload your ad creative assets.\n\nRecommended sizes:\n• 1200x628 px for Feed\n• 1080x1920 px for Stories\n\nType 'skip' to continue without uploading.",
    options: [],
    prefill: undefined,
    stepper: null,
    progress: null,
  },
};

export const dummyOauthConnect: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "oauth_connect",
    field: "meta_oauth",
    prompt: "Connect your Meta Ads account to proceed.",
    options: ["https://www.facebook.com/v17.0/dialog/oauth?client_id=123456"],
    prefill: undefined,
    stepper: null,
    progress: null,
  },
};

export const dummyDateRangePicker: PendingActionBlock = {
  id: uid(),
  type: "pending_action",
  content: {
    action_type: "date_range_picker",
    field: "campaign_duration",
    prompt: "When should the campaign run?",
    options: [],
    prefill: undefined,
    stepper: null,
    progress: null,
  },
};

// ---------------------------------------------------------------------------
// map_data blocks — typed as MapDataBlock to satisfy the Block union
// ---------------------------------------------------------------------------

export const dummyRadiusPicker: MapDataBlock = {
  id: uid(),
  type: "map_data",
  content: {
    action_type: "radius_picker",
    center: { lat: 45.5017, lng: -73.5673 },
    locations: [
      {
        location_name: "Montreal",
        formatted_address: "Montreal, QC, Canada",
        latitude: 45.5017,
        longitude: -73.5673,
        is_city: true,
      },
    ],
    default_radius_km: 5,
    default_radius_miles: null,
  } satisfies RadiusPickerData,
};

export const dummyConfirmLocations: MapDataBlock = {
  id: uid(),
  type: "map_data",
  content: {
    action_type: "confirm_locations",
    locations: [
      {
        location_name: "Montreal",
        formatted_address: "Montreal, QC, Canada",
        latitude: 45.5017,
        longitude: -73.5673,
        is_city: true,
      },
      {
        location_name: "Toronto",
        formatted_address: "Toronto, ON, Canada",
        latitude: 43.6532,
        longitude: -79.3832,
        is_city: true,
      },
    ],
    editable: true,
  } satisfies ConfirmLocationsData,
};

export const dummyMaidSplitViewEmpty: MapDataBlock = {
  id: uid(),
  type: "map_data",
  content: {
    action_type: "maid_split_view",
    pois: [
      {
        name: "Starbucks – Peel St",
        lat: 45.4993,
        lng: -73.5716,
        radius_km: null,
        parent_location: "Montreal",
        types: ["cafe", "coffee"],
        brand: "Starbucks",
        event_start_date: null,
        event_end_date: null,
      },
      {
        name: "Starbucks – McGill College",
        lat: 45.5021,
        lng: -73.5707,
        radius_km: null,
        parent_location: "Montreal",
        types: ["cafe"],
        brand: "Starbucks",
        event_start_date: null,
        event_end_date: null,
      },
    ],
    maid_observations: [],
    center: {
      location_name: "Montreal",
      formatted_address: "Montreal, QC, Canada",
      latitude: 45.5017,
      longitude: -73.5673,
      is_city: true,
    },
    maid_count: 0,
    lookback_days: null,
    event_date_ranges: null,
  } satisfies MaidSplitViewData,
};

export const dummyMaidSplitViewPopulated: MapDataBlock = {
  id: uid(),
  type: "map_data",
  content: {
    action_type: "maid_split_view",
    pois: [
      {
        name: "Starbucks – Peel St",
        lat: 45.4993,
        lng: -73.5716,
        radius_km: 0.5,
        parent_location: "Montreal",
        types: ["cafe"],
        brand: "Starbucks",
        event_start_date: null,
        event_end_date: null,
      },
    ],
    maid_observations: [
      { lat: 45.4994, lng: -73.5718 },
      { lat: 45.4991, lng: -73.5712 },
      { lat: 45.4996, lng: -73.572 },
    ],
    center: {
      location_name: "Montreal",
      formatted_address: "Montreal, QC, Canada",
      latitude: 45.5017,
      longitude: -73.5673,
      is_city: true,
    },
    maid_count: 3842,
    radius_km: 0.5,
    lookback_days: 7,
    event_date_ranges: null,
  } satisfies MaidSplitViewData,
};

// Built from the real NYC "Sephora + Ulta" competitor_brand payload that
// surfaced the missing-poi_categories bug — this is the corrected shape:
// two brand tabs, each with its own redacted audience slice, plus the
// existing combined "All" tab on the top-level fields.
export const dummyMaidSplitViewCategorized: MapDataBlock = {
  id: uid(),
  type: "map_data",
  content: {
    action_type: "maid_split_view",
    pois: [
      { name: "SEPHORA", lat: 40.74998, lng: -73.98878, parent_location: "New York, NY, USA", formatted_address: "112 W 34th St., New York, NY 10120, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 41 },
      { name: "SEPHORA", lat: 40.72954, lng: -73.98936, parent_location: "New York, NY, USA", formatted_address: "3 St Marks Pl, New York, NY 10003, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 27 },
      { name: "SEPHORA", lat: 40.75859, lng: -73.98582, parent_location: "New York, NY, USA", formatted_address: "1535 Broadway, New York, NY 10036, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 63 },
      { name: "SEPHORA", lat: 40.75232, lng: -73.99921, parent_location: "New York, NY, USA", formatted_address: "435 W 31st St Ste 112, New York, NY 10001, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 19 },
      { name: "SEPHORA", lat: 40.72410, lng: -73.99839, parent_location: "New York, NY, USA", formatted_address: "557 Broadway, New York, NY 10012, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 55 },
      { name: "Ulta Beauty", lat: 40.73993, lng: -73.99476, parent_location: "New York, NY, USA", formatted_address: "620 6th Ave Ste 0105, New York, NY 10011, USA", parent_poi_type: "Ulta", source_angle: "competitor_brand", audience_count: 33 },
      { name: "Ulta Beauty", lat: 40.74987, lng: -73.98720, parent_location: "New York, NY, USA", formatted_address: "51 W 34th St. Ste 110, New York, NY 10001, USA", parent_poi_type: "Ulta", source_angle: "competitor_brand", audience_count: 22 },
      { name: "Ulta Beauty", lat: 40.77877, lng: -73.95440, parent_location: "New York, NY, USA", formatted_address: "188 East 86th St, New York, NY 10028, USA", parent_poi_type: "Ulta", source_angle: "competitor_brand", audience_count: 17 },
    ],
    poi_categories: [
      {
        id: "competitor_brand:Sephora",
        key: "Sephora",
        kind: "competitor_brand",
        source_angle: "competitor_brand",
        count: 5,
        pois: [
          { name: "SEPHORA", lat: 40.74998, lng: -73.98878, parent_location: "New York, NY, USA", formatted_address: "112 W 34th St., New York, NY 10120, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 41 },
          { name: "SEPHORA", lat: 40.72954, lng: -73.98936, parent_location: "New York, NY, USA", formatted_address: "3 St Marks Pl, New York, NY 10003, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 27 },
          { name: "SEPHORA", lat: 40.75859, lng: -73.98582, parent_location: "New York, NY, USA", formatted_address: "1535 Broadway, New York, NY 10036, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 63 },
          { name: "SEPHORA", lat: 40.75232, lng: -73.99921, parent_location: "New York, NY, USA", formatted_address: "435 W 31st St Ste 112, New York, NY 10001, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 19 },
          { name: "SEPHORA", lat: 40.72410, lng: -73.99839, parent_location: "New York, NY, USA", formatted_address: "557 Broadway, New York, NY 10012, USA", parent_poi_type: "Sephora", source_angle: "competitor_brand", audience_count: 55 },
        ],
        maid_observations: [
          { lat: 40.74991, lng: -73.98862 }, { lat: 40.75001, lng: -73.98890 }, { lat: 40.72960, lng: -73.98930 },
          { lat: 40.75855, lng: -73.98590 }, { lat: 40.75862, lng: -73.98570 }, { lat: 40.72400, lng: -73.99850 },
        ],
        maid_count: 205,
      },
      {
        id: "competitor_brand:Ulta",
        key: "Ulta",
        kind: "competitor_brand",
        source_angle: "competitor_brand",
        count: 3,
        pois: [
          { name: "Ulta Beauty", lat: 40.73993, lng: -73.99476, parent_location: "New York, NY, USA", formatted_address: "620 6th Ave Ste 0105, New York, NY 10011, USA", parent_poi_type: "Ulta", source_angle: "competitor_brand", audience_count: 33 },
          { name: "Ulta Beauty", lat: 40.74987, lng: -73.98720, parent_location: "New York, NY, USA", formatted_address: "51 W 34th St. Ste 110, New York, NY 10001, USA", parent_poi_type: "Ulta", source_angle: "competitor_brand", audience_count: 22 },
          { name: "Ulta Beauty", lat: 40.77877, lng: -73.95440, parent_location: "New York, NY, USA", formatted_address: "188 East 86th St, New York, NY 10028, USA", parent_poi_type: "Ulta", source_angle: "competitor_brand", audience_count: 17 },
        ],
        maid_observations: [
          { lat: 40.73998, lng: -73.99470 }, { lat: 40.74990, lng: -73.98715 }, { lat: 40.77880, lng: -73.95430 },
        ],
        maid_count: 72,
      },
    ],
    maid_observations: [
      { lat: 40.74991, lng: -73.98862 }, { lat: 40.75001, lng: -73.98890 }, { lat: 40.72960, lng: -73.98930 },
      { lat: 40.75855, lng: -73.98590 }, { lat: 40.75862, lng: -73.98570 }, { lat: 40.72400, lng: -73.99850 },
      { lat: 40.73998, lng: -73.99470 }, { lat: 40.74990, lng: -73.98715 }, { lat: 40.77880, lng: -73.95430 },
    ],
    center: {
      location_name: "NYC",
      formatted_address: "New York, NY, USA",
      latitude: 40.71278,
      longitude: -74.00597,
      is_city: true,
    },
    maid_count: 261,
    lookback_days: 7,
    event_date_ranges: null,
    editable: true,
  } satisfies MaidSplitViewData,
};

export const dummyPoiRadiusPicker: MapDataBlock = {
  id: uid(),
  type: "map_data",
  content: {
    action_type: "poi_radius_picker",
    pois: [
      {
        name: "Starbucks – Peel St",
        lat: 45.4993,
        lng: -73.5716,
        parent_location: "Montreal",
      },
      {
        name: "Starbucks – McGill College",
        lat: 45.5021,
        lng: -73.5707,
        parent_location: "Montreal",
      },
    ],
    center: {
      location_name: "Montreal",
      formatted_address: "Montreal, QC, Canada",
      latitude: 45.5017,
      longitude: -73.5673,
      is_city: true,
    },
    default_radius_km: 0.5,
  } satisfies PoiRadiusPickerData,
};

// ---------------------------------------------------------------------------
// message blocks — typed as MessageBlock to satisfy the Block union
// ---------------------------------------------------------------------------

export const dummyUserMessage: MessageBlock = {
  id: uid(),
  type: "message",
  role: "user",
  content:
    "I own a coffee shop in Montreal and want to target Starbucks customers nearby.",
  status: "complete",
};

export const dummyAssistantMessage: MessageBlock = {
  id: uid(),
  type: "message",
  role: "assistant",
  content:
    "I've analyzed your business profile. Let's set up your geo-targeting strategy step by step. I'll guide you through the process to ensure we reach the right audience.\n\n**Here's what we'll do:**\n1. Define your location targeting scope\n2. Identify high-traffic competitor locations\n3. Build your MAID-based audience\n4. Configure and launch the campaign",
  status: "complete",
};

export const dummyAssistantMessageWithThinking: MessageBlock = {
  id: uid(),
  type: "message",
  role: "assistant",
  content:
    "Great! Based on your business description, I'm going to suggest a deterministic targeting strategy using competitor POI data.",
  thinking:
    "Punk reasoning: **Analyzing Business Profile**\nThe user owns a coffee shop in Montreal. This is a local brick-and-mortar business. Best approach: deterministic geofencing around competitor Starbucks locations to capture customers who already demonstrate coffee-purchasing intent.\n\nPunk reasoning: **Strategy Selection**\nDeterministic MAID targeting will outperform programmatic here because we have a clear competitor set (Starbucks) and specific city (Montreal). We should use the maid_split_view flow.",
  status: "complete",
};

// ---------------------------------------------------------------------------
// Inline user reply helper
// ---------------------------------------------------------------------------

const userMsg = (content: string): MessageBlock => ({
  id: uid(),
  type: "message",
  role: "user",
  content,
  status: "complete",
});

// ---------------------------------------------------------------------------
// Full scenario: a sequence of all block types for rendering in order
// ---------------------------------------------------------------------------

export const allDummyBlocks: Block[] = [
  dummyUserMessage,
  dummyAssistantMessage,
  dummyAssistantMessageWithThinking,
  dummyOptionSelection,
  userMsg("Q: What is your location targeting scope?\nA: Granular Local Areas"),
  dummyTextInput,
  userMsg("Q: What cities, towns, or postal codes to target?\nA: Montreal, Toronto"),
  dummyPermission,
  userMsg("Q: Found 2 location(s) on the map: Montreal, Toronto. Proceed?\nA: confirmed"),
  dummyConfirmLocations,
  dummyOptionSelectionWithProgress,
  userMsg("Q: Which targeting method would you like to use?\nA: Deterministic"),
  dummyStepperInput,
  userMsg("Q: What radius in miles should we target?\nA: 10 miles"),
  dummyRadiusPicker,
  dummyMaidSplitViewEmpty,
  dummyMaidSplitViewPopulated,
  dummyPoiRadiusPicker,
  dummyFileUpload,
  dummyDateRangePicker,
];
