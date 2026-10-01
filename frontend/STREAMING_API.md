# PunkAI — `map_data` & `pending_action` Streaming Reference

All events arrive as `(mode, data)` from the SSE stream.
This document covers only the two event types the UI must act on.

---

## Event wrapper

```json
{ "type": "map_data",      "content": { ... } }
{ "type": "pending_action","content": { ... } }
{ "type": "campaign_plan", "content": { ... } }
```

> **There is no `marketing_plan` event.** It was documented and handled for a
> long time, but nothing in the graph ever emitted one. The campaign plan
> arrives as `campaign_plan`; the editable payload rides on
> `pending_action.form_schema`.

### `campaign_plan`

The read-only plan summary. `content` is always the **v2 object**:
`{ version: 2, title, subtitle, sections[] }`. (The legacy HTML-string shape and
the `CAMPAIGN_PLAN_FORM_ENABLED` flag were removed — the form is the only path.)

Each section is `{ key, label, type, ... }`:

| `type` | Payload | Render as |
|---|---|---|
| `metrics` | `items: [{label, value}]` | Stat tiles |
| `kv` | `rows: [{label, value}]` | Label/value rows |
| `text` | `text: string` | Paragraph |
| `list` | `items: string[]` | Bullets |
| `table` | `columns: string[]`, `rows: string[][]` | Table |

Unknown section types should be skipped, not crash — new ones may be added.

Within a single turn, when a separate `map_data` event is sent, order is always:
**`map_data` fires first → `pending_action` fires second.** Render the map update, then
show the input widget.

> **Exception:** some steps carry their map **inline** on `pending_action.locations`
> instead of a separate `map_data` event — render that map from the widget itself. See
> [Inline map in `pending_action`](#inline-map-in-pending_action).

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
| `stepper` | object \| null | single stepper config — `{default, min, max, step, unit}`. `null` when `steppers` is used. |
| `steppers` | object[] \| null | **multi-stepper** — when this is a non-null array, render one stepper per entry in a single widget and **ignore `stepper`**. Each entry: `{key, label, hint, default, min, max, step, unit}` — `label` is the control title, `hint` is a short one-line explanation to show under it. Resume with a JSON string keyed by each `key`, e.g. `"{\"poi_radius_m\":250,\"lookback_days\":14}"`. |
| `progress` | `{label,value}[]` \| null | confirmed steps — render as summary card above widget |
| `locations` | `Location[]` \| absent | geocoded pins to draw on a map **inline above this widget**. When present, there is **no** separate `confirm_locations` `map_data` event — render the map from this field. Checkpointed, so it survives reconnect/refresh. See [Inline map in `pending_action`](#inline-map-in-pending_action). |

### `action_type` values & resume value

| `action_type` | UI | Resume with |
|---|---|---|
| `text_input` | Free text field | The typed string |
| `option_selection` | Button list | Selected option string or `"1"` / `"2"` index |
| `permission` | Yes / No | Any affirmative (`"yes"`, `""`, `"confirm"`) |
| `map_interaction` | Interactive map | JSON string — see each step |
| `file_upload` | File picker | Path from `POST /media/upload`, or `"skip"` |
| `campaign_content` | *(not currently emitted by the backend)* Two-panel: **ad-copy picker** + **creative asset**. `UploadCampaignContentUI` (`chat/components/creative/index.tsx`) builds this shape but is wired up only in the `test-chat` component sandbox — no live `pending_action` uses it. | JSON string `{"cta","headline","body","media_ids":[...]}` |
| `campaign_intake_form` | Dynamic **intake** form (business, objective, duration, budget, destination), rendered from `form_schema` | JSON string `{"values":{...}}` — see [Dynamic forms](#dynamic-forms-intake--plan) |
| `campaign_plan_editor` | The full Ads-Manager-style tree editor (`CampaignEditor.tsx`) — Campaign panel · Ad Set tabs · Ad cards, **not** a `form_schema`-driven `DynamicForm`. See its own file-header JSDoc for the exact contract. | JSON string `{"action":"publish"\|"save","spec":{...}}`, or `{"action":"apply_template","campaign_id","spec"[,"adset_ids","ad_ids"]}` |
| `oauth_connect` | OAuth button — `options[0]` is URL | `"connected"` |
| `stepper_input` | Numeric stepper | Number as plain string e.g. `"500"`. **If `steppers` is non-null**, render N steppers in one widget and resume with a JSON string keyed by each `key`, e.g. `"{\"poi_radius_m\":250,\"lookback_days\":14}"`. |

> **`stepper_input` — single vs multi:** dispatch on `steppers`.
> `steppers === null` → single stepper, read `stepper`, resume `"250"`.
> `steppers !== null` → multi: render one control per array entry, ignore `stepper`,
> resume a JSON object string of `{ [key]: number }`.

> **The actual resume transport.** Most widgets wrap the value shown in this doc as
> `` `Q: <prompt>\nA: <payload>` `` before sending it — `ChatContext.tsx` always posts
> `{"value": "<that string>"}` to `/chat/{id}/resume`, and the backend strips the
> wrapper at exactly one point, `wizard_helpers._unwrap_qa`, right where each
> `wizard_interrupt()` call resumes. Everything documented as a bare JSON string
> above is really the `A:` half of that wrapper for most widgets — `WidgetFileUpload`,
> `WidgetOauthConnect`, and `CampaignEditor` are the exceptions and send the bare
> value with no wrapper at all. Either way, a JSON-shaped answer (starts `{`/`[`) is
> routed straight to the confirm lane before the resume classifier ever runs
> (`resume_router.is_sentinel_resume`), so it is not free-form text as far as the
> backend is concerned.

---

## Inline map in `pending_action`

Some interrupts that need to **show a map AND collect a decision** carry the pins
directly on the `pending_action` via an optional **`locations`** array — instead of
emitting a separate `confirm_locations` `map_data` event.

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "geo_plan_confirm",
    "prompt":      "Does this plan look correct? ...",
    "options":     ["Yes, proceed", "No, I'll set it manually"],
    "locations": [
      { "location_name": "Dhaka", "formatted_address": "Dhaka, Bangladesh",
        "latitude": 23.804093, "longitude": 90.4152376, "is_city": true }
    ],
    "progress": []
  }
}
```

**Render rule:** when `pending_action.locations` is present, draw the map **inline,
above the widget**, and let the widget's `options` / confirm drive the response. The
map is **visual only** — the user's answer still comes from the widget, never the map.
Do **not** expect a separate `map_data` event for these steps.

**Why this shape:** `pending_action` is checkpointed to Redis (`map_data` events are
transient), so the map restores on reconnect/refresh. It also removes the old
double-confirm where a `confirm_locations` map and an `option_selection` widget both
demanded a response.

**Where it applies today:** `geo_plan_confirm` (plan review) **only** — it is an
`option_selection` widget. Every other map-bearing step (including
`geo_location_confirmation`, a `permission` widget, and the deterministic / POI flows)
uses a standalone `confirm_locations` / `maid_split_view` `map_data` event (documented
below). Inline `locations` is rendered only for `option_selection` widgets.

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
        "event_end_date":   null,
        "audience_count":   612,
        "visit_stats": {
          "basis":                "visits",
          "total_devices":        612,
          "buckets":              { "1x": 402, "2x": 150, "3_5x": 60, "6plus": 0 },
          "repeat_visitor_count": 210,
          "repeat_visitor_pct":   34,
          "max_seen":             3
        }
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
    "visit_stats": {
      "total_devices":        3842,
      "buckets":              { "1x": 2410, "2x": 890, "3_5x": 420, "6plus": 122 },
      "repeat_visitor_count": 1432,
      "repeat_visitor_pct":   37,
      "max_seen":             11
    },
    "radius_km":         0.5,
    "lookback_days":     7,
    "event_date_ranges": null
  }
}
```

**Frequency reports (added).**

- **Per-POI** — each `pois[]` entry carries `audience_count` (unique devices in that
  geofence) and `visit_stats` (that POI's own frequency breakdown). Render it as a
  **POI-hover report popup**: total devices + the `buckets` distribution + repeat-visitor
  count/pct. This is the primary (and only) report surface.
- **Top-level `visit_stats`** — the same shape aggregated over the whole audience (all
  POIs deduped). Optional overview.
- **`maid_observations`** are coordinates only (map density). They carry **no** per-dot
  counts — the frequency report is per-POI, not per-dot.

**`basis` drives the label — read it:**
- `"visits"` → real repeat visits (distinct days, from timestamped data). Label
  "visits", "repeat visitors", "came back on N days".
- `"sightings"` → no timestamp available; a "sighting" is a raw GPS ping / distinct spot,
  **NOT** a visit. Label ONLY "sightings" / "times detected" — never "visits" or "days".

> Older/cached extractions may omit `visit_stats` — treat as absent (plain dots, no
> report). `buckets` keys: `1x`, `2x`, `3_5x`, `6plus`.

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

### Step 0 — Plan Review *(only when earlier chat pre-filled enough targeting context)*

When intent extraction already inferred a scope / locations / method, the wizard opens
with a consolidated review card instead of asking each question. If locations were
inferred, they ride **inline** on this `pending_action` via `locations` (no separate
`map_data` event — render the map above the buttons). See
[Inline map in `pending_action`](#inline-map-in-pending_action).

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "option_selection",
    "field":       "geo_plan_confirm",
    "prompt":      "Does this plan look correct? If so, I'll apply these settings and we'll move to the next phase.",
    "options":     ["Yes, proceed", "No, I'll set it manually"],
    "locations": [
      { "location_name": "Dhaka", "formatted_address": "Dhaka, Bangladesh",
        "latitude": 23.804093, "longitude": 90.4152376, "is_city": true }
    ],
    "prefill":  null,
    "stepper":  null,
    "progress": []
  }
}
```

> `locations` is **absent** when no location was inferred (e.g. only a method/discovery
> hint was extracted) — render the card with no map.
> Resume: `"Yes, proceed"` → applies the inferred plan. `"No, I'll set it manually"` →
> falls through to Step 1 onward.

---

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
    "prompt":      "Are these the right locations?",
    "options":     [],
    "prefill":     null,
    "stepper":     null,
    "progress":    null
  }
}
```

Resume: `"yes"`

> This confirm runs once during collection and is shared by the programmatic **and**
> deterministic paths — so the location-confirm interrupts later "inside execute" are
> already satisfied and do not re-fire.
> **Skipped entirely** when the user already accepted the plan at
> [Step 0 — Plan Review](#step-0--plan-review-only-when-earlier-chat-pre-filled-enough-targeting-context)
> (those locations were confirmed there via the inline map).

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

Location confirmation already happened once during collection (the shared
`geo_location_confirmation` permission, preceded by a standalone `confirm_locations`
map_data — see [Admin Areas / Granular Local](#programmatic-path--confirmation-interrupts-inside-execute)),
so it does **not** re-fire here. Execute goes straight to POI results.

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

## Dynamic forms (intake) and the plan editor

**Only the intake form is `form_schema`-driven.** An earlier design ran both the
intake step AND the plan-review step through one schema-driven `DynamicForm`
contract (`campaign_plan_form`, `{"action":"publish"|"save","values":{...}}`,
`campaign`/`adsets`/`ads` groups) — that plan-review half was superseded by the
bespoke tree editor documented above as `campaign_plan_editor`
(`CampaignEditor.tsx`, submitting `{"action", "spec"}` instead of `{"action",
"values"}`). Only the intake form still uses what this section describes.

- **`campaign_intake_form`** — business name, context/USP, objective, duration,
  budget type + amount, and the objective-conditional destination (website, or
  App Store / Google Play URLs). One flat group `intake`. Submit
  `{"values":{...}}`. Built by `intake_form.build_intake_schema`.

It carries `form_schema`, `values` (prefill), and `errors` (present only after a
rejected submission). `DynamicForm` renders it.

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "campaign_intake_form",
    "field": "campaign_intake",
    "title": "Campaign Setup",
    "prompt": "Let's set up your campaign — fill in the details below.",
    "form_schema": { "groups": [ /* see below */ ] },
    "values":      { "budget_amount": 3500, "...": "..." },
    "errors":      { "budget_amount": "Input should be greater than or equal to 100" }
  }
}
```

`errors` keys match field keys; `__root__` carries cross-field / form-level errors —
render as a banner, not against an input.

### Field descriptor

Built by `intake_form._field` — every field always carries `editable: true` and
`required` (the client falls back to "every field required" when the flag is
absent, so an optional field omitting it would still block submit):

```jsonc
{
  "key": "objective",                // submission key AND error key
  "label": "Campaign objective",
  "type": "select",                  // text | textarea | select | currency | date — see build_intake_schema's callers for the full set in use
  "options": [{ "value": "OUTCOME_SALES", "label": "Sales", "description": "…" }],
  "suggestion": "OUTCOME_SALES",     // prefill; wins only when `values` doesn't already have an answer
  "help": "One or two lines — your product or service and your edge.",
  "editable": true,
  "required": true,
  "visible_when": { "objective": ["APP_PROMOTION"] },
  "min": 100,                        // currency fields only
  "minor_units": 100                 // currency fields only — how many minor units per whole unit (100 except JPY & co)
}
```

- **`visible_when` semantics.** A dict is **one clause**: every key must match
  (**AND**). Evaluate against live form state so toggling `objective` re-renders
  immediately. Hidden fields are excluded from the submission.
- **`currency` values are integer minor units** (cents, or whatever `minor_units`
  says) — multiply the displayed amount before submitting.
- **`date` fields** submit `"YYYY-MM-DD"` or `null`.

### Submitting

Resume with `{"values":{...}}` — `submitMode="full"`, so send **every visible
key**, including untouched ones seeded from `suggestion`, not just what changed.
A rejected submission re-emits the same pending action with `errors` attached.

JSON payloads bypass the backend's resume intent classifier — no special client handling.

For the plan editor's own submit contract (`{"action","spec"}` /
`{"action":"apply_template",...}`), see `CampaignEditor.tsx`'s file-header JSDoc —
it is the single source of truth for that shape, not this document.

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
| `geo_plan_confirm` | `option_selection` | Geo | When earlier chat pre-filled targeting context — first step. Carries `locations` inline when a location was inferred |
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
| `geo_location_confirmation` | `permission` | Geo | Once during collection for admin_areas / granular_local / country_groups + det types ai_suggested / category / competitor_brand / event_based. Preceded by a standalone `confirm_locations` map_data; shared across programmatic & deterministic (does not re-fire in execute). **Skipped** when the plan was accepted at Step 0 |
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
| `creative_upload` | `campaign_content` | Campaign | Always — copy picker + creative (upload / Punk-generate). Supersedes the legacy per-ad-set `creative_upload_0..N` `file_upload` steps. |
| `meta_oauth_connect` | `oauth_connect` | Media | Only if not connected to Meta |
| `meta_ad_account_id` | `option_selection` | Media | Only if multiple accounts |
| `media_buying_confirm` | `option_selection` | Media | Always |


## Campaign content (final creative + copy) — not currently live

The design below (`action_type: "campaign_content"`) is **not emitted by the
backend** — no step in `builder_node.py` sends it, and no `pending_action`
renderer (`ActiveWidgetRenderer.tsx`, `BlockRenderer.tsx`) has a case for it. Ad
copy and creative are collected inside `CampaignEditor.tsx` (`AdCard.tsx`) today,
as part of the `campaign_plan_editor` spec, not as a separate interrupt.
`UploadCampaignContentUI` (`chat/components/creative/index.tsx`) implements the
shape documented below and is wired up only in the `test-chat` component
sandbox. Kept here in case this surface gets built for real.

### `pending_action` payload

```json
{
  "type": "pending_action",
  "content": {
    "action_type": "campaign_content",
    "field":       "creative_upload",
    "step_key":    "creative_upload",
    "prompt":      "Choose your ad copy and add a creative …",
    "ad_copy": {
      "cta_recommendation":    "SHOP_NOW",
      "cta_options":           ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "..."],
      "headline_suggestions":  ["New season, new standards.", "..."],
      "body_copy_suggestions": ["Shop the spring drop before it's gone.", "..."]
    }
  }
}
```

- **Panel 1 — Ad copy.** CTA (dropdown over `cta_options`, default `cta_recommendation`),
  headline (pick from `headline_suggestions`), body copy (pick from
  `body_copy_suggestions`). The user **chooses** — nothing is generated in this panel.
- **Panel 2 — Campaign assets.** The upload dropzone **plus** a **"Punk ideas"** button
  that generates the creative (endpoints below). Each added asset — uploaded or
  generated — contributes its `MediaFile` UUID.

### Resume value

Resume the interrupt with a JSON string:

```json
{ "cta": "SHOP_NOW",
  "headline": "New season, new standards.",
  "body": "Shop the spring drop before it's gone.",
  "media_ids": ["<MediaFile-UUID>", "..."] }
```

- `media_ids`: empty ⇒ publish ships ad sets without ads; one id ⇒ reused across every
  ad set; N ids ⇒ mapped by ad-set index. Ids must be `MediaFile` UUIDs (from
  `/media/upload` or `/creatives/generate`); anything else is dropped server-side.
- Empty `cta` / `headline` / `body` leave the plan's recommended copy in place.

### Punk-ideas creative generation (REST — NOT the chat graph)

Generation is a **side-channel**: it never advances the LangGraph turn. The widget
calls these directly; the interrupt above is resumed only when the user hits **Add**.

**`POST /creatives/generate`** → `202`
```json
{ "media_type": "image",
  "thread_id": "<session id>",
  "variation_hint": "optional — extra prompt / art direction (also used on Retry)",
  "reference_media_id": "optional — a MediaFile UUID from POST /media/upload to build on" }
```
returns `{ "job_id": "<uuid>", "status": "running" }`. Only image generation is
supported (`media_type` must be `"image"`; any other value ⇒ `422`).

Both extra inputs are **opt-in** and combine (the zero-input "Punk ideas → image"
path is unchanged):
- `variation_hint` — free-text steer ("what you want"); folded into the generation prompt.
- `reference_media_id` — the user uploads a reference (usually a **plain product shot**)
  via `POST /media/upload`, then passes its UUID here. The product becomes the hero of a
  freshly-composed ad scene — kept faithful (shape/label/colours) but placed into a full
  setting, never just reframed. Returns `404` if the id isn't a media file the caller owns.
- **Together** (reference **+** `variation_hint`): the hint drives the scene the product is
  placed into ("put it on a beach", "make it night"). Reference with no hint → the scene is
  drawn from the campaign context.

**`GET /creatives/generate/{job_id}`** → poll (drives the progress modal)
```json
{ "job_id": "<uuid>",
  "status": "running" | "ready" | "failed",
  "media":  { "id": "<MediaFile-UUID>", "file_path": "https://…", "media_type": "image", "...": "..." },
  "error":  null }
```
On `ready`, use `media.id` as a `media_ids` entry in the resume value.

- **Image** (Gemini image — `gemini-2.5-flash-image`) generation is async so one uniform progress modal works.
- **Retry** = `POST /creatives/generate` again (optionally with `variation_hint`); only the
  asset the user "Adds" ever reaches the graph.
