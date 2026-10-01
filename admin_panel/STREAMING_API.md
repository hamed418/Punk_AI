# PunkAI — `map_data` & `pending_action` Streaming Reference

All events arrive as `(mode, data)` from the SSE stream.
This document covers only the two event types the UI must act on.

---

## Event wrapper

```json
{ "type": "map_data",      "content": { ... } }
{ "type": "pending_action","content": { ... } }
```

Within a single turn, order is always: **`map_data` fires first → `pending_action` fires second.**
Render the map update, then show the input widget.

---

## `pending_action` — base shape

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "geo_location_type",
    "prompt":      "What is your location targeting scope?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

| field | type | notes |
|---|---|---|
| `action_type` | string | see values below |
| `field` | string | step identifier |
| `prompt` | string | question shown above widget |
| `options` | string[] | non-empty for `option_selection` and `oauth_connect` |
| `prefill` | string \| null | pre-fill value extracted from earlier chat; user confirms or overrides |
| `stepper` | object \| null | only for `stepper_input` — `{default, min, max, step, unit}` |
| `progress` | `{label,value}[]` \| null | confirmed steps — render as summary card above widget |

### `action_type` values & resume value

| `action_type` | UI | Resume with |
|---|---|---|
| `text_input` | Free text field | The typed string |
| `option_selection` | Button list | Selected option string or `"1"` / `"2"` index |
| `permission` | Yes / No | Any affirmative (`"yes"`, `""`, `"confirm"`) |
| `map_interaction` | Interactive map | JSON string — see each step |
| `file_upload` | File picker | Path from `POST /media/upload`, or `"skip"` |
| `oauth_connect` | OAuth button — `options[0]` is URL | `"connected"` |
| `stepper_input` | Numeric stepper | Number as plain string e.g. `"500"` |

---

## `map_data` — shapes

### `radius_picker`

```json
{
  "type": "map_data",
  "content": {
    "action_type":          "radius_picker",
    "center":               { "lat": 0, "lng": 0 },
    "locations":            [],
    "default_radius_miles": 10,
    "default_radius_km":    null
  }
}
```

With known centre:

```json
{
  "type": "map_data",
  "content": {
    "action_type":       "radius_picker",
    "center":            { "lat": 45.4991, "lng": -73.5747 },
    "locations": [
      {
        "location_name":      "123 Main St, Montreal",
        "formatted_address":  "123 Rue Principale, Montréal, QC H3A 1A1, Canada",
        "latitude":           45.4991,
        "longitude":          -73.5747,
        "is_city":            false
      }
    ],
    "default_radius_km":    5,
    "default_radius_miles": null
  }
}
```

### `confirm_locations`

```json
{
  "type": "map_data",
  "content": {
    "action_type": "confirm_locations",
    "locations": [
      {
        "location_name":     "Montreal",
        "formatted_address": "Montreal, QC, Canada",
        "latitude":          45.5017,
        "longitude":         -73.5673,
        "is_city":           true
      },
      {
        "location_name":     "Toronto",
        "formatted_address": "Toronto, ON, Canada",
        "latitude":          43.6532,
        "longitude":         -79.3832,
        "is_city":           true
      }
    ],
    "editable": true
  }
}
```

Store pins (store_set targeting):

```json
{
  "type": "map_data",
  "content": {
    "action_type": "confirm_locations",
    "locations": [
      { "name": "Store A", "lat": 45.4991, "lng": -73.5747, "radius_km": null, "parent_location": "123 Main St, Montreal" },
      { "name": "Store B", "lat": 45.5048, "lng": -73.5719, "radius_km": null, "parent_location": "456 Ste-Catherine, Montreal" }
    ],
    "editable": true
  }
}
```

### `maid_split_view`

After geo execute (no MAIDs yet):

```json
{
  "type": "map_data",
  "content": {
    "action_type": "maid_split_view",
    "pois": [
      {
        "name":             "Starbucks – Peel St",
        "lat":              45.4993,
        "lng":              -73.5716,
        "radius_km":        null,
        "parent_location":  "Montreal",
        "types":            ["cafe", "coffee"],
        "brand":            "Starbucks",
        "event_start_date": null,
        "event_end_date":   null
      }
    ],
    "maid_observations": [],
    "center": {
      "location_name":     "Montreal",
      "formatted_address": "Montreal, QC, Canada",
      "latitude":          45.5017,
      "longitude":         -73.5673,
      "is_city":           true
    },
    "maid_count":        0,
    "radius_km":         null,
    "lookback_days":     null,
    "event_date_ranges": null
  }
}
```

After MAID execute (populated):

```json
{
  "type": "map_data",
  "content": {
    "action_type": "maid_split_view",
    "pois": [
      {
        "name":             "Starbucks – Peel St",
        "lat":              45.4993,
        "lng":              -73.5716,
        "radius_km":        0.5,
        "parent_location":  "Montreal",
        "types":            ["cafe"],
        "brand":            "Starbucks",
        "event_start_date": null,
        "event_end_date":   null
      }
    ],
    "maid_observations": [
      { "lat": 45.4994, "lng": -73.5718 },
      { "lat": 45.4991, "lng": -73.5712 }
    ],
    "center": {
      "location_name":     "Montreal",
      "formatted_address": "Montreal, QC, Canada",
      "latitude":          45.5017,
      "longitude":         -73.5673,
      "is_city":           true
    },
    "maid_count":        3842,
    "radius_km":         0.5,
    "lookback_days":     7,
    "event_date_ranges": null
  }
}
```

Event-based targeting (event dates on POIs):

```json
{
  "type": "map_data",
  "content": {
    "action_type": "maid_split_view",
    "pois": [
      {
        "name":             "Parc Jean-Drapeau — Osheaga Stage",
        "lat":              45.5093,
        "lng":              -73.5315,
        "radius_km":        0.3,
        "parent_location":  "Montreal",
        "types":            ["event_venue", "park"],
        "brand":            null,
        "event_start_date": "2026-08-01",
        "event_end_date":   "2026-08-03"
      }
    ],
    "maid_observations": [
      { "lat": 45.5095, "lng": -73.5317 }
    ],
    "center": {
      "location_name": "Montreal",
      "latitude":      45.5017,
      "longitude":     -73.5673,
      "is_city":       true
    },
    "maid_count":        11240,
    "radius_km":         0.3,
    "lookback_days":     3,
    "event_date_ranges": ["2026-08-01 -> 2026-08-03"]
  }
}
```

### `poi_radius_picker`

Fires before the MAID geofence radius stepper. Shows **all N confirmed POIs** on the map simultaneously; frontend should render one radius circle per POI using `default_radius_km` as the initial value, updating all circles live as the stepper changes.

```json
{
  "type": "map_data",
  "content": {
    "action_type":       "poi_radius_picker",
    "pois": [
      { "name": "Starbucks – Peel St",       "lat": 45.4993, "lng": -73.5716, "parent_location": "Montreal" },
      { "name": "Starbucks – McGill College", "lat": 45.5021, "lng": -73.5707, "parent_location": "Montreal" }
    ],
    "center": {
      "location_name":    "Montreal",
      "formatted_address": "Montreal, QC, Canada",
      "latitude":          45.5017,
      "longitude":         -73.5673,
      "is_city":           true
    },
    "default_radius_km": 0.5
  }
}
```

> `default_radius_km` matches the stepper default (500 m = 0.5 km). All circles share the same radius value.

---

## Geo Wizard — all steps

> **Streaming guarantee:** Within a single turn, each wizard node emits at most **one `map_data` event**. This ensures stable frontend state management and prevents unnecessary re-renders.

### Step 1 — Location Type *(always)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "geo_location_type",
    "prompt":      "What is your location targeting scope?",
    "options": [
      "Country Groups — select broad regions like Asia, GCC Free Trade Areas, or Emerging Markets",
      "Admin Areas — choose specific countries, states/provinces, or congressional districts",
      "Granular Local Areas — select cities, postal codes (ZIP codes), or specific addresses",
      "Radius Targeting — pin a spot on the map and set a delivery radius (1–50 miles)"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

---

### Step 2A — Locations *(Country Groups / Admin Areas / Granular Local)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_locations",
    "prompt":      "What cities, towns, or postal codes to target? (e.g. Montreal QC, Brooklyn NY 11201)",
    "options":     [],
    "prefill":     "Montreal",
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" }
    ]
  }
}
```

> `prompt` varies by scope:
> - Country Groups → `"What country groups or countries to target? (e.g. North America, Europe, Brazil)"`
> - Admin Areas → `"What states, provinces, or regions to target? (e.g. California, Ontario, Bavaria)"`
> - Granular Local → `"What cities, towns, or postal codes to target? (e.g. Montreal QC, Brooklyn NY 11201)"`

Resume: `"Montreal, Toronto"` → parsed to `["Montreal","Toronto"]`

---

### Step 2B — Radius Pin *(Radius scope only)*

Map fires first:

```json
{
  "type": "map_data",
  "content": {
    "action_type":          "radius_picker",
    "center":               { "lat": 0, "lng": 0 },
    "locations":            [],
    "default_radius_miles": 10
  }
}
```

Then interrupt:

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "map_interaction",
    "field":       "geo_radius_pin",
    "prompt":      "Pin your target location on the map.",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Radius" }
    ]
  }
}
```

Resume: `{"lat": 45.5017, "lng": -73.5673}`

---

### Step 3 — Radius Miles *(Radius scope only)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "stepper_input",
    "field":       "geo_radius_miles",
    "prompt":      "What radius in miles should we target around your pin?",
    "options":     [],
    "prefill":     null,
    "stepper":     { "default": 10, "min": 1, "max": 50, "step": 1, "unit": "miles" },
    "progress": [
      { "label": "Targeting Scope", "value": "Radius" }
    ]
  }
}
```

Resume: `"10"` (plain number string)

After user confirms the stepper, backend immediately emits a live map preview with the pin + chosen radius:

```json
{
  "type": "map_data",
  "content": {
    "action_type":          "radius_picker",
    "center":               { "lat": 45.5017, "lng": -73.5673 },
    "default_radius_miles": 10
  }
}
```

---

### Step 4 — Business Description *(all paths)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_business_description",
    "prompt":      "Briefly describe your business (used to suggest relevant targeting).",
    "options":     [],
    "prefill":     "Coffee shop chain serving specialty drinks",
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal, Toronto" }
    ]
  }
}
```

---

### Step 5 — Targeting Method *(all paths)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "geo_targeting_method",
    "prompt":      "Which targeting method would you like to use?",
    "options": [
      "Programmatic — Meta's AI uses real-time signals to find new customers likely to convert",
      "Deterministic — reach exact device IDs observed at specific POIs; 1:1 precision geofencing"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal, Toronto" },
      { "label": "Business",        "value": "Coffee shop chain…" }
    ]
  }
}
```

---

### Programmatic path — confirmation interrupts inside execute

**Admin Areas / Granular Local** — map then permission:

```json
{
  "type": "map_data",
  "content": {
    "action_type": "confirm_locations",
    "locations": [
      { "location_name": "Montreal", "formatted_address": "Montreal, QC, Canada", "latitude": 45.5017, "longitude": -73.5673, "is_city": true },
      { "location_name": "Toronto",  "formatted_address": "Toronto, ON, Canada",  "latitude": 43.6532, "longitude": -79.3832, "is_city": true }
    ],
    "editable": true
  }
}
```

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "permission",
    "field":       "geo_location_confirmation",
    "prompt":      "Found 2 location(s) on the map: Montreal, Toronto. Proceed with these locations?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

Resume: `"yes"`

**Radius** — map fires with final values, no interrupt:

```json
{
  "type": "map_data",
  "content": {
    "action_type":          "radius_picker",
    "center":               { "lat": 45.5017, "lng": -73.5673 },
    "locations":            [],
    "default_radius_miles": 10
  }
}
```

---

### Step 6 — POI Discovery Type *(Deterministic only)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "geo_deterministic_type",
    "prompt":      "How should target POIs be discovered?",
    "options": [
      "AI Suggested POIs — PunkAI picks the best POI types for your business and searches them",
      "Category / POI Type — you know which POI category to target; PunkAI finds those locations",
      "Store Set (My Locations) — geocode your own store addresses and target people nearby",
      "Competitor Nearby — find competitor locations within a radius of your physical store",
      "Competitor Brand Locations — target locations of specific brands or chains (e.g. Starbucks)",
      "Events in City — target event venues (festivals, conferences, concerts) during event dates",
      "Map Selection — draw or pick exact locations on the interactive map"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal, Toronto" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" }
    ]
  }
}
```

---

### det_type: AI Suggested — execute events

Location confirmation (before POI search):

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "permission",
    "field":       "geo_location_confirmation",
    "prompt":      "Found 1 location(s) on the map: Montreal. Proceed with POI discovery here?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

POI results (after search):

```json
{
  "type": "map_data",
  "content": {
    "action_type": "maid_split_view",
    "pois": [
      { "name": "Starbucks – Peel St",      "lat": 45.4993, "lng": -73.5716, "radius_km": null, "parent_location": "Montreal", "types": ["cafe"], "brand": "Starbucks", "event_start_date": null, "event_end_date": null },
      { "name": "Starbucks – McGill College","lat": 45.5021, "lng": -73.5707, "radius_km": null, "parent_location": "Montreal", "types": ["cafe"], "brand": "Starbucks", "event_start_date": null, "event_end_date": null }
    ],
    "maid_observations": [],
    "center":        { "location_name": "Montreal", "latitude": 45.5017, "longitude": -73.5673, "is_city": true },
    "maid_count":    0,
    "radius_km":     null,
    "lookback_days": null,
    "event_date_ranges": null
  }
}
```

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "permission",
    "field":       "geo_pois_confirmation",
    "prompt":      "Found 23 POI(s) shown on the map. Confirm to proceed with these as your targeting locations.",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

> Same execute pattern for **Category**, **Competitor Brand**, **Events** — only the POI contents differ.

---

### det_type: Category — extra collection step

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_poi_types",
    "prompt":      "What POI categories to target? (comma-separated, e.g. gym, fitness center, yoga studio)",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Category / POI Type" }
    ]
  }
}
```

Resume: `"gym, fitness center"` → then execute (geo_location_confirmation → maid_split_view → geo_pois_confirmation)

---

### det_type: Store Set — extra collection step

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_store_addresses",
    "prompt":      "Enter your store address(es). Use a semicolon ( ; ) to separate multiple addresses.\nExample: 123 Main St, Montreal, QC ; 456 Rue Sainte-Catherine, Montreal, QC",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Store Set (My Locations)" }
    ]
  }
}
```

Resume: `"123 Main St, Montreal ; 456 Ste-Catherine, Montreal"`

Execute events:

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "permission",
    "field":       "geo_store_confirmation",
    "prompt":      "Found 2 store location(s). Are these correct?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

Then: `maid_split_view` (pois=stores) → `geo_pois_confirmation`

---

### det_type: Competitor Nearby — 3 extra collection steps

**A) Store Address:**

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_store_address_for_competitors",
    "prompt":      "Enter your store address (we'll find competitor locations nearby).",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Competitor Nearby" }
    ]
  }
}
```

Resume: `"123 Main St, Montreal, QC"` — backend geocodes immediately

**B) Store Confirmation:**

```json
{
  "type": "map_data",
  "content": {
    "action_type": "confirm_locations",
    "locations": [
      { "location_name": "123 Main St, Montreal", "formatted_address": "123 Rue Principale, Montréal, QC H3A 1A1, Canada", "latitude": 45.4991, "longitude": -73.5747, "is_city": false }
    ],
    "editable": true
  }
}
```

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "permission",
    "field":       "geo_competitor_store_confirmation",
    "prompt":      "I found your store at **123 Rue Principale, Montréal, QC H3A 1A1, Canada**. Is this correct?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

**C) Search Radius:**

```json
{
  "type": "map_data",
  "content": {
    "action_type":       "radius_picker",
    "center":            { "lat": 45.4991, "lng": -73.5747 },
    "locations": [
      { "location_name": "123 Main St, Montreal", "formatted_address": "123 Rue Principale, Montréal, QC", "latitude": 45.4991, "longitude": -73.5747, "is_city": false }
    ],
    "default_radius_km": 5
  }
}
```

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "stepper_input",
    "field":       "geo_competitor_radius",
    "prompt":      "How far around your store should we search for competitors?",
    "options":     [],
    "prefill":     null,
    "stepper":     { "default": 5, "min": 1, "max": 50, "step": 1, "unit": "km" },
    "progress": [
      { "label": "Targeting Scope",  "value": "Granular Local" },
      { "label": "Locations",        "value": "Montreal" },
      { "label": "Business",         "value": "Coffee shop chain…" },
      { "label": "Method",           "value": "Deterministic" },
      { "label": "Discovery",        "value": "Competitor Nearby" },
      { "label": "Store Confirmed",  "value": "123 Rue Principale, Montréal, QC" }
    ]
  }
}
```

Resume: `"8"` (km as string)

Execute events: `maid_split_view` (competitor POIs) → `geo_pois_confirmation`

---

### det_type: Competitor Brand — extra collection step

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_brand_names",
    "prompt":      "Which brand(s) to target? (comma-separated, e.g. Starbucks, Tim Hortons)",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal, Toronto" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Competitor Brand Locations" }
    ]
  }
}
```

Resume: `"Starbucks, Tim Hortons"` → then execute (geo_location_confirmation → maid_split_view → geo_pois_confirmation)

---

### det_type: Events in City — 2 extra collection steps

**A) Event Types:**

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_event_type",
    "prompt":      "Which event(s) to target? Enter event types or specific names, comma-separated.\n(e.g. music festivals, Osheaga, tech conferences, F1 Grand Prix)",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Events in City" }
    ]
  }
}
```

**B) Date Range:**

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "geo_event_date_range",
    "prompt":      "What date range should we search? (e.g. Summer 2025, Jan 2025 - Dec 2025, next 6 months)",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Events in City" },
      { "label": "Events",          "value": "Osheaga, Just For Laughs" }
    ]
  }
}
```

Execute events: `geo_location_confirmation` → `maid_split_view` (POIs have `event_start_date`/`event_end_date`) → `geo_pois_confirmation`

---

### det_type: Map Selection — extra collection step

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "map_interaction",
    "field":       "geo_map_selection",
    "prompt":      "Select locations on the map.",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress": [
      { "label": "Targeting Scope", "value": "Granular Local" },
      { "label": "Locations",       "value": "Montreal" },
      { "label": "Business",        "value": "Coffee shop chain…" },
      { "label": "Method",          "value": "Deterministic" },
      { "label": "Discovery",       "value": "Map Selection" }
    ]
  }
}
```

Resume: `[{"name":"Park Royal Mall","lat":49.3453,"lng":-123.1561},{"name":"Oakridge Centre","lat":49.2334,"lng":-123.1159}]`

Execute events: `maid_split_view` (picks as POIs) → `geo_pois_confirmation`

---

## MAID Wizard

Runs only for deterministic targeting. Skipped entirely for programmatic.

### Step 1 — Geofence Radius

Map fires first (all confirmed POIs, one circle each):

```json
{
  "type": "map_data",
  "content": {
    "action_type":       "poi_radius_picker",
    "pois": [
      { "name": "Starbucks – Peel St", "lat": 45.4993, "lng": -73.5716, "parent_location": "Montreal" }
    ],
    "center":            { "location_name": "Montreal", "latitude": 45.5017, "longitude": -73.5673, "is_city": true },
    "default_radius_km": 0.5
  }
}
```

Then interrupt:

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "stepper_input",
    "field":       "maid_poi_radius",
    "prompt":      "What radius (in km) should we draw around each of the 23 confirmed POI(s)? (e.g. 0.5, 1, 2)",
    "options":     [],
    "prefill":     null,
    "stepper":     { "default": 500, "min": 100, "max": 5000, "step": 100, "unit": "m" },
    "progress": [
      { "label": "POIs Found", "value": "23 location(s)" }
    ]
  }
}
```

Resume: `"500"` (metres as string)

### Step 2 — Lookback Days *(skipped for event_based)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "stepper_input",
    "field":       "maid_lookback",
    "prompt":      "How many days back should we look for device visits at these locations?",
    "options":     [],
    "prefill":     null,
    "stepper":     { "default": 7, "min": 1, "max": 90, "step": 1, "unit": "days" },
    "progress": [
      { "label": "POIs Found",      "value": "23 location(s)" },
      { "label": "Geofence Radius", "value": "0.5 km" }
    ]
  }
}
```

Resume: `"14"`

### After maid_execute — MAID map + confirmation

```json
{
  "type": "map_data",
  "content": {
    "action_type": "maid_split_view",
    "pois": [
      { "name": "Starbucks – Peel St", "lat": 45.4993, "lng": -73.5716, "radius_km": 0.5, "parent_location": "Montreal", "types": ["cafe"], "brand": "Starbucks", "event_start_date": null, "event_end_date": null }
    ],
    "maid_observations": [
      { "lat": 45.4994, "lng": -73.5718 },
      { "lat": 45.4991, "lng": -73.5712 }
    ],
    "center":        { "location_name": "Montreal", "latitude": 45.5017, "longitude": -73.5673, "is_city": true },
    "maid_count":    3842,
    "radius_km":     0.5,
    "lookback_days": 14,
    "event_date_ranges": null
  }
}
```

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "permission",
    "field":       "maid_results_confirmation",
    "prompt":      "Found **3,842 potential customers** (94% confidence) across 23 POI(s) within 0.5 km during past 14 day(s).\n\nThese are real people who physically visited those locations.\n\nTo reach all of them effectively, you'll need a minimum of **$650** on this Meta campaign. Spending more will also help Meta build stronger lookalike audiences from this data.\n\nDoes the audience and map look good, or would you like to adjust anything?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

Resume: `"yes"`

---

## Campaign Wizard

### Website URL

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "campaign_website_url",
    "prompt":      "What is the website URL for Brew & Co? (e.g. https://mybrand.com — type 'skip' if none)",
    "options":     [],
    "prefill":     "https://brewandco.com",
    "stepper":     null,
    "progress":    null
  }
}
```

### Website Enrichment Confirm *(conditional)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "website_enrichment_confirm",
    "prompt":      "Does this look right?",
    "options": [
      "Yes, looks good — use this scraped data to pre-fill campaign details",
      "No, continue anyway — skip enrichment and fill in details manually"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

### Pixel Status

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "campaign_pixel_status",
    "prompt":      "Is Meta Pixel installed on your website?",
    "options": [
      "Installed & verified — pixel is live and sending confirmed conversion events",
      "Installed but not verified — pixel is on the site but conversion events are unconfirmed",
      "Not installed — no Meta Pixel on the website yet"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

### Campaign Objective

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "campaign_objective",
    "prompt":      "What is the primary goal of this campaign?",
    "options":     ["SALES", "LEADS", "AWARENESS", "TRAFFIC", "ENGAGEMENT", "APP_PROMOTION"],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

> Top 2 options are AI-recommended. Order varies per session.

### Budget

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "campaign_budget_amount",
    "prompt":      "Which budget works for you?",
    "options": [
      "Starter: $25/day",
      "Growth: $75/day",
      "Scale: $150/day",
      "Enter a custom amount"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

> Falls back to `text_input` with `options: []` when AI recs unavailable.

### Custom Budget *(only if "Enter a custom amount" selected)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "campaign_budget_custom",
    "prompt":      "Enter your budget amount (e.g. $75/day or $2,000 total):",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

### Budget Type

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "campaign_budget_type",
    "prompt":      "Is $75/day a daily budget or a total budget for the full campaign?",
    "options": [
      "Daily budget — spend a fixed amount each day; good for ongoing campaigns",
      "Lifetime (total) budget — set a total spend cap; Meta paces delivery over the flight window"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

### Start Date

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "campaign_start_date",
    "prompt":      "When should the campaign start? (e.g. May 1, 2026 — or type 'ASAP')",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

### End Date

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "campaign_end_date",
    "prompt":      "When should the campaign end? (type 'ongoing' for no end date)",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

### Product / Offer

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "text_input",
    "field":       "campaign_product_offer",
    "prompt":      "Is there a specific product, service, or promotion you want to highlight in the ads? (Optional — type 'skip' to continue)",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

### Campaign Plan Confirm

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "campaign_plan_confirm",
    "prompt":      "Ready to proceed?",
    "options": [
      "Looks good, proceed — generate the Meta campaign JSON and move to publishing",
      "I want to make changes — go back and adjust campaign details"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

> If user picks "I want to make changes": resume with free-text change request e.g. `"Change objective to LEADS"`. Backend patches and regenerates silently.

### Creative Upload *(one per ad set)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "file_upload",
    "field":       "creative_upload_0",
    "prompt":      "Upload an image or video for ad set: Retargeting — Warm Audience\n\nRecommended sizes:\n  • Image: 1200×628 px (Feed), 1080×1080 px (Square)\n  • Video: 1080×1920 px (Reels/Stories), 1280×720 px (Feed)\n\nType 'skip' to add a creative later.",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "file_upload",
    "field":       "creative_upload_1",
    "prompt":      "Upload an image or video for ad set: Lookalike — Cold Audience\n\nRecommended sizes:\n  • Image: 1200×628 px (Feed), 1080×1080 px (Square)\n  • Video: 1080×1920 px (Reels/Stories), 1280×720 px (Feed)\n\nType 'skip' to add a creative later.",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

> `field` increments per ad set: `creative_upload_0`, `creative_upload_1`, …

---

## Media Wizard

### Meta OAuth *(only if not connected)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "oauth_connect",
    "field":       "meta_oauth_connect",
    "prompt":      "To publish your campaign, connect your Meta Ads account. Click the button below to authorize PunkAI — it only takes a moment.",
    "options": [
      "https://www.facebook.com/v18.0/dialog/oauth?client_id=1234&redirect_uri=https%3A%2F%2Fpunkai.app%2Foauth%2Fcallback&state=user_uuid_here&scope=ads_management%2Cpages_read_engagement"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

> `options[0]` is the live auth URL. Open in popup or redirect. Resume: `"connected"`.

### Ad Account Selection *(only if multiple accounts)*

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "meta_ad_account_id",
    "prompt":      "Which Meta ad account should we use for this campaign?",
    "options": [
      "My Store Account — act_1234567890",
      "Agency Main Account — act_0987654321"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

### Publish Confirmation

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "media_buying_confirm",
    "prompt":      "Ready to publish \"Brew & Co — Summer 2026\" to Meta Ads?\n\nThe campaign will be created with status PAUSED so you can review it in Ads Manager before activating. We'll activate it once everything is confirmed.",
    "options": [
      "Yes, publish now — create campaign, ad sets, and ads in PAUSED state then activate",
      "Cancel — stop here; nothing will be sent to Meta"
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": null
  }
}
```

---

## All Fields — Quick Reference

| `field` | `action_type` | Wizard | When |
|---|---|---|---|
| `geo_location_type` | `option_selection` | Geo | Always — first step |
| `geo_locations` | `text_input` | Geo | Country Groups / Admin / Granular Local |
| `geo_radius_pin` | `map_interaction` | Geo | Radius scope only |
| `geo_radius_miles` | `stepper_input` | Geo | Radius scope only |
| `geo_business_description` | `text_input` | Geo | Always |
| `geo_targeting_method` | `option_selection` | Geo | Always |
| `geo_deterministic_type` | `option_selection` | Geo | Deterministic only |
| `geo_poi_types` | `text_input` | Geo | det_type = category |
| `geo_store_addresses` | `text_input` | Geo | det_type = store_set |
| `geo_store_address_for_competitors` | `text_input` | Geo | det_type = competitor_nearby |
| `geo_competitor_store_confirmation` | `permission` | Geo | det_type = competitor_nearby |
| `geo_competitor_radius` | `stepper_input` | Geo | det_type = competitor_nearby |
| `geo_brand_names` | `text_input` | Geo | det_type = competitor_brand |
| `geo_event_type` | `text_input` | Geo | det_type = event_based |
| `geo_event_date_range` | `text_input` | Geo | det_type = event_based |
| `geo_map_selection` | `map_interaction` | Geo | det_type = map_pick |
| `geo_location_confirmation` | `permission` | Geo | Deterministic: ai_suggested / category / competitor_brand / event_based; Programmatic: admin_areas / granular_local |
| `geo_store_confirmation` | `permission` | Geo | det_type = store_set |
| `geo_pois_confirmation` | `permission` | Geo | All deterministic paths after POI search |
| `maid_poi_radius` | `stepper_input` | MAID | Deterministic — always |
| `maid_lookback` | `stepper_input` | MAID | Deterministic, non-event_based |
| `maid_results_confirmation` | `permission` | MAID | Deterministic — after execute |
| `campaign_website_url` | `text_input` | Campaign | Always |
| `website_enrichment_confirm` | `option_selection` | Campaign | If website has parseable content |
| `campaign_pixel_status` | `option_selection` | Campaign | Unless pre-known |
| `campaign_objective` | `option_selection` | Campaign | Unless pre-known |
| `campaign_budget_amount` | `option_selection` or `text_input` | Campaign | Always |
| `campaign_budget_custom` | `text_input` | Campaign | If "Enter a custom amount" selected |
| `campaign_budget_type` | `option_selection` | Campaign | Unless pre-known |
| `campaign_start_date` | `text_input` | Campaign | Unless pre-known |
| `campaign_end_date` | `text_input` | Campaign | Unless pre-known |
| `campaign_product_offer` | `text_input` | Campaign | Unless pre-known |
| `campaign_plan_confirm` | `option_selection` | Campaign | Always — inside execute |
| `creative_upload_0..N` | `file_upload` | Campaign | One per ad set |
| `meta_oauth_connect` | `oauth_connect` | Media | Only if not connected to Meta |
| `meta_ad_account_id` | `option_selection` | Media | Only if multiple accounts |
| `media_buying_confirm` | `option_selection` | Media | Always |
