export type Conversation = {
  id: string
  blocks: Block[]
}

export type Block =
  | MessageBlock
  | PendingActionBlock
  | MapDataBlock
  | CampaignPlanBlock

export type MessageBlock = {
  id: string
  type: 'message'
  role: 'user' | 'assistant' | 'system' | 'assistant_message'
  content: string
  /**
   * 'failed' is a user message the server never accepted — no row, no
   * checkpoint. It is not rewindable; retrying it re-sends rather than forks.
   */
  status?: 'streaming' | 'complete' | 'failed'
  createdAt?: string
  thinking?: string | null
  /**
   * Address of the checkpoint the turn ended on, carried over from history. A
   * user message is rewindable when an assistant message before it carries both
   * halves. Absent on locally-streamed blocks until the next history refetch.
   *
   * checkpoint_ns '' is a real value and falsy in JS — test for null/undefined.
   */
  checkpoint_id?: string | null
  checkpoint_ns?: string | null
  /** A user answer the user changed and re-sent; shown with an "edited" tag. */
  edited?: boolean
  /**
   * 'rewind_marker' is a transient status line ("Continuing from your edited
   * answer — 3 later messages were removed"), not a chat message: rendered as a
   * divider, never counted as a reply, gone after the history refetch.
   */
  kind?: 'rewind_marker'
}

// --- Pending Actions ---

export type PendingActionType =
  | 'text_input'
  | 'option_selection'
  | 'permission'
  | 'map_interaction'
  | 'file_upload'
  | 'oauth_connect'
  | 'stepper_input'
  | 'question_collection'
  | 'date_range_picker'
  | 'campaign_intake_form'
  | 'campaign_plan_editor'
  | 'campaign_preview'

export type MultiStepperConfig = StepperConfig & {
  key: string
  label: string
  hint?: string
}

// --- Dynamic form contract (shared by the intake + plan forms) ---
// Mirrors backend graph/builder/intake_form.py (the intake form). The plan form
// is now the bespoke CampaignEditor, driven by CampaignEditorSpec + EditorCatalog.

export type FormFieldType =
  | 'select'
  | 'multiselect'
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'datetime'
  | 'readonly'
  | 'dayparting'
  | 'attribution'

export type FormOption = {
  value: string
  label: string
  description?: string
}

// visible_when / required_when: one clause is a dict where every key must match
// (AND); a list of dicts is OR. A key matches when the live value intersects the
// listed values (array values match on intersection, scalars on membership).
export type FormCondition = Record<string, string[]> | Record<string, string[]>[]

export type FormField = {
  key: string
  label: string
  type: FormFieldType
  editable: boolean
  options?: FormOption[]
  options_by_objective?: Record<string, FormOption[]>
  suggestion?: unknown
  help?: string
  locked_reason?: string
  visible_when?: FormCondition
  required_when?: FormCondition
  // What the SERVER actually rejects a submission over. Absent means the schema
  // predates the flag, and DynamicForm falls back to "every editable field is
  // required" — which is why an optional field must send required: false rather
  // than omitting it.
  required?: boolean
  min?: number
  max?: number
  max_length?: number
  // currency field only — the ad account's own symbol/code. Ad accounts are not
  // all USD, so the widget must not hard-code '$'.
  prefix?: string
  // currency field only — minor units per whole unit of that currency. 100
  // normally, 1 for JPY/KRW and the rest of Meta's zero-decimal list.
  minor_units?: number
  // attribution field only
  windows?: { click: number[]; view: number[] }
}

export type FormGroupItem = {
  index: number
  label: string
  fields: FormField[]
}

export type FormGroup = {
  key: string
  label: string
  repeat: boolean
  fields?: FormField[]
  items?: FormGroupItem[]
}

export type FormSchema = {
  groups: FormGroup[]
  errors?: Record<string, string>
}

export type PendingActionBlock = {
  id: string
  type: 'pending_action'
  content: {
    action_type: PendingActionType
    field?: string
    title?: string
    subtitle?: string
    prompt: string
    options?: string[]
    prefill?: string
    stepper?: StepperConfig | null
    steppers?: MultiStepperConfig[]
    progress?: ProgressItem[] | null
    locations?: LocationItem[]
    // Which wizard step this widget collects. The SSE handler replaces a
    // pending_action with the SAME step_key in place instead of pushing a new
    // block, so an off-path re-ask does not remount the widget and wipe input.
    step_key?: string | null
    // Deterministic ways out of an off-path loop, attached by the backend from
    // the 2nd off-path reply onward. Submitting one of these strings verbatim is
    // what triggers it (wizard_helpers._match_escape matches exactly).
    escape_menu?: string[] | null
    // 0-4 tappable one-tap answers, grounded in session context.
    suggestions?: string[] | null
    // dynamic form payload (campaign_intake_form)
    form_schema?: FormSchema
    values?: Record<string, unknown>
    errors?: Record<string, string>
    // bespoke campaign editor payload (campaign_plan_editor)
    spec?: CampaignEditorSpec
    catalog?: EditorCatalog
    // Which stage of the persistent editor shell this is. "intake" — no spec
    // yet, the Campaign pane renders form_schema instead; "plan" (default,
    // omitted for every non-express mode) — the real tree; "preview" — the
    // campaign is already built in Meta and PAUSED, the pane renders the ad
    // previews (`ads`/`summary`/`tracking` below) instead of `spec`. See
    // CampaignEditor.
    phase?: 'intake' | 'plan' | 'preview'
    // The chosen publish mode ('self' | 'guide' | 'express'), told explicitly
    // rather than inferred from `locks`' shape — inference breaks the moment
    // express_unlocked (below) collapses locks to the same shape guide mode
    // ships, which is exactly the case a re-lock control has to tell apart.
    publish_mode?: string
    // Express only: whether the user has hit "Unlock & edit" on a previous
    // save. Seeds the editor's local unlock state so it survives the save's
    // round trip instead of resetting to locked on every remount.
    express_unlocked?: boolean
    // Server-owned sections the editor must not let the user change. geo +
    // audience are always locked (they ARE the product); campaign + adset are
    // locked in "do it for me" mode, which reduces the editor to ad copy and
    // creative — everything else was answered on the intake form or defaulted.
    locks?: EditorLocks
    // campaign_plan_editor, alongside the spec rather than inside it: how
    // conversions reach Meta is a Punk setting, and CampaignSpec is extra=forbid
    // with every field in it published. Submitted back the same way.
    tracking_method?: string
    // Same: the intake form's ad-creative answer ('ai' | 'existing_post' |
    // 'existing_ad'). Decides whether an untouched ad card opens on composed
    // copy or on the post picker, and which tab of it.
    creative_source?: string
    // Preview & Publish payload (campaign_preview)
    campaign_id?: string
    ad_account_id?: string
    ads?: PreviewAd[]
    summary?: PreviewSummary
    tracking?: PreviewTracking
    audience_notice?: PreviewAudienceNotice
    // Shipped on both the plan editor and Preview & Publish: prerequisites only
    // the user can satisfy, on a Meta screen. See builder_node._remediation_extra.
    remediation?: MetaRemediation[]
  }
}

export type EditorLocks = {
  geo?: boolean
  audience?: boolean
  campaign?: boolean
  adset?: boolean
}

// --- Preview & Publish (campaign_preview) ---
// The campaign already exists in Meta, PAUSED. The iframes are NOT in this
// payload — their URLs expire, so the widget fetches them from /ads/ad-previews.

export type PreviewAd = { ad_id: string; name: string }

export type PreviewSummary = {
  campaign_name?: string
  objective?: string
  placements?: { platform: string; positions: string[] }[]
  budget?: { type: 'daily' | 'lifetime'; amount: number; currency: string }
  start_date?: string
  end_date?: string
}

// Conversion tracking, present only when the plan promotes a Pixel. A null
// last_fired_time means Meta has never seen an event from it — the campaign will
// publish and deliver, but optimize toward an event that never arrives, so the
// preview warns before offering to go live.
export type PreviewTracking = {
  pixel_id: string
  pixel_name: string
  last_fired_time: string | null
  created_by_punk: boolean
  events_manager_url: string
  // The business portfolio the dataset belongs to. '' for one that sits on the ad
  // account itself, which is what a personal account gets. It is always the
  // advertiser's own — Punk owns no dataset.
  business_id?: string
  // Meta's Event Match Quality, 0-10. Null when it could not be read. A dataset
  // that fires constantly but matches nobody optimizes almost as badly as one
  // that never fires, so it belongs next to last_fired_time.
  event_match_quality?: number | null
  // What delivery is optimized toward — a standard event, or the name of the
  // advertiser's own custom conversion.
  conversion_event?: string
  // How the user said conversions would reach Meta, from the intake form. Lets
  // the gate say whether the server half is expected at all.
  tracking_method?: string
  // The install helper itself, for the halves this method actually uses — so the
  // snippet is on the screen the user is already looking at rather than behind
  // directions to a settings page. Absent when there is nothing to install.
  setup?: TrackingSetup
}

// The paste-in half of conversion tracking. Built by TrackingService.snippet,
// which returns only what the chosen tracking_method uses: a CRM setup gets no
// browser snippet, a pixel-only setup gets no key.
export type TrackingSetup = {
  pixel_snippet?: string
  server_example?: string
  ingest_url?: string
  ingest_key?: string
  instructions?: string[]
}

// GET /tracking/health — the live answer to "is tracking working?", for the
// Something Meta will not let Punk do on the user's behalf — accepting a Terms
// of Service, adding a payment method, linking an Instagram account. There is no
// API for any of it, so the only useful answer is instructions. Backend source of
// truth: services/meta_remediation.py.
export type MetaRemediation = {
  key: string
  title: string
  // Why Meta refused, in plain words. Says out loud that the API cannot do it.
  cause: string
  steps: string[]
  // Deep link to the exact Meta screen. Empty when we lacked an id to build it —
  // render no button rather than a link that lands nowhere.
  url: string
  // What Punk does meanwhile, so nobody has to guess whether money is moving.
  effect: string
  // blocks   — cannot proceed until a human does this
  // degrades — Punk proceeds with less
  // warns    — proceeds fully, but something is being lost
  severity: 'blocks' | 'degrades' | 'warns'
  scope?: string
  // Punk has no way to read this one from Meta, so it is listed for the user to
  // confirm rather than reported as missing. Only present when true.
  unverified?: boolean
}

// connection settings card. Same shape as the backend TrackingHealthResponse.
export type TrackingHealth = {
  dataset_id: string
  dataset_name: string
  business_id: string
  last_fired_time: string | null
  event_match_quality: number | null
  // What the dataset actually received in the last 7 days, biggest first. Empty
  // when the read failed OR when nothing arrived — the two look the same here.
  events?: { name: string; count: number }[]
  // The event delivery optimizes toward, in Meta's wire spelling ("Lead").
  conversion_event?: string
  server_events_seen: boolean
  events_manager_url: string
  // How conversions reach Meta. '' until a campaign has resolved one.
  tracking_method?: TrackingMethod | ''
  status: 'ok' | 'no_dataset' | 'never_fired' | 'token_invalid'
  remediation?: MetaRemediation[]
}

// The four setups Punk knows how to instruct. Publish derives one from the shape
// of the campaign; POST /tracking/method is how a user moves off it.
export type TrackingMethod =
  | 'pixel_and_server'
  | 'pixel_only'
  | 'lead_forms'
  | 'offline_crm'

// GET /tracking/datasets — what this ad account can actually write to. Read live,
// so a Pixel just created in Events Manager shows up without a republish.
export type TrackingDatasets = {
  datasets: { id: string; name: string; last_fired_time: string }[]
  selected: string
}

// GET /tracking/snippet — the install helper.
export type TrackingSnippet = {
  dataset_id: string
  // The event the snippet fires — the account's own conversion event unless one
  // was asked for. A Purchase snippet under a Leads campaign installs the one
  // event the ad set never learns from.
  event_name: string
  // Meta's standard events, for the picker. Anything else is a custom event.
  event_names: string[]
  pixel_snippet: string
  server_example: string
  // The same conversion posted straight to Meta on a token the advertiser holds.
  // Punk never sees those requests. Offered beside server_example so where the
  // data goes is their call.
  server_direct_example: string
  ingest_url: string
  // The ad account's own currency — the one Meta reads a conversion value in.
  currency: string
  // Treat as a password: anyone holding it can report conversions to the dataset.
  ingest_key: string
  instructions: string[]
  // Decides which blocks above are populated at all — a pixel-only setup gets no
  // key or endpoint, a CRM setup no snippet.
  tracking_method?: TrackingMethod | ''
}

// Present only when the visitor audience was built but never attached — Meta
// refuses a customer-list audience on an ad account outside a Business, and the
// publish degrades to Advantage+ automatically. Nobody chose that, so it is
// stated here, before anything can go live. See builder_node._audience_notice.
export type PreviewAudienceNotice = {
  dropped: boolean
  reason: string
  fix: string
}

// One placement's rendering, from GET /ads/ad-previews.
export type AdPreview = { format: string; label: string; src: string }

// --- Bespoke campaign editor (campaign_plan_editor) ---
// `spec` is a serialized CampaignSpec (backend meta_spec/models.py); `catalog`
// is the option vocabulary (meta_spec/catalog.py). The editor renders the tree
// directly and submits the whole edited spec: { action: 'save'|'publish', spec }.

export type EditorOption = { value: string; label: string; help?: string }

// Meta's form is two-dimensional: the objective decides which conversion
// locations exist, and the conversion location decides everything below it.
// Every option list therefore hangs off one of these, not off the objective.
export type EditorDestination = {
  value: string
  label: string
  help?: string
  optimization_goals: EditorOption[]
  billing_events: EditorOption[]
  call_to_actions: EditorOption[]
  ad_formats: EditorOption[]
  promoted_object_kind_by_goal: Record<string, string>
  requires_lead_form: boolean
  // '' for a normal composed ad; 'post' | 'video' | 'event' when the ad promotes
  // something that already exists on the Page.
  object_story_kind?: string
  // Whether an existing post is PERMITTED here (object_story_kind means it is
  // required). Measured per objective+destination on the server, so the editor
  // only offers it where Meta is known to accept it.
  allows_existing_post?: boolean
  required_user_info: string[]
}

// One Facebook Page the connection can advertise under. `instagram` is the
// account Instagram placements run as; `lead_forms` are that Page's instant
// forms, carried per Page so switching Page does not leave the form dropdown
// showing another Page's forms.
export type EditorPage = {
  id: string
  name?: string
  instagram?: { id: string; username?: string } | null
  lead_forms?: { id: string; name?: string; status?: string }[]
  // Click-to-WhatsApp dials the number linked to this Page, and Meta refuses the
  // ad set outright when there is none. THREE states, not two: `{number}` linked,
  // `null` provably not linked, **absent** when the token could not read the
  // field at all. Only `null` blocks — treating absent as "no number" would
  // refuse a campaign that would have published fine.
  whatsapp?: { number?: string } | null
  // Same three states as `whatsapp`: `true`/`false` when Meta answered, **absent**
  // when the token could not read it. Only `false` is a problem; absent is unknown.
  is_published?: boolean
  // An Advertiser or Admin role on this Page — creating ads under it needs one.
  can_advertise?: boolean
}

export type EditorCatalog = {
  current_objective?: string | null
  objectives: EditorOption[]
  destinations_by_objective: Record<string, EditorDestination[]>
  special_ad_categories: EditorOption[]
  // ISO 3166-1 alpha-2 codes only — the editor resolves names with
  // Intl.DisplayNames. Optional: threads checkpointed before this key existed
  // fall back to US/CA rather than rendering an empty dropdown.
  special_ad_category_countries?: string[]
  categories_blocking_demographics: string[]
  bid_strategies: EditorOption[]
  // Bid strategy is set at campaign level, so it stays per-objective.
  bid_strategies_by_objective: Record<string, EditorOption[]>
  bid_strategies_requiring_amount: string[]
  // The third rule layer: what the optimization goal itself decides. Narrows the
  // destination's lists further — a value must satisfy both.
  goal_rules?: Record<
    string,
    {
      billing_events: string[]
      bid_strategies: string[]
      // null means either kind is fine; 'video' means the ad must be a video.
      media_kind?: 'image' | 'video' | null
      ad_formats?: string[] | null
      allows_frequency_control: boolean
      allows_attribution_spec: boolean
    }
  >
  // The ROAS goal takes its target in bid_constraints (scaled by `scale`), not
  // in bid_amount, and Meta rejects the two together.
  roas_goal?: {
    bid_strategy: string
    scale: number
    min: number
    max: number
  }
  genders: EditorOption[]
  placements: {
    publisher_platforms: EditorOption[]
    positions: Record<string, EditorOption[]>
    position_field_by_platform: Record<string, string>
  }
  // Three windows, as in Ads Manager: click-through, engage-through
  // (ENGAGED_VIDEO_VIEW on the wire) and view-through. `default` is Meta's own
  // combination — DISPLAY only, the editor writes nothing until the user changes
  // a select. Both new keys optional: threads checkpointed before they existed
  // fall back to the literals in AttributionField.
  attribution: {
    click_windows: number[]
    view_windows: number[]
    engaged_view_windows?: number[]
    default?: {
      event_type: 'CLICK_THROUGH' | 'ENGAGED_VIDEO_VIEW' | 'VIEW_THROUGH'
      window_days: number
    }[]
  }
  // What a frequency cap starts at on a goal that allows one — the same values
  // the server seeds, so the field is never two blank boxes. Optional: threads
  // checkpointed before this key existed fall back in FrequencyCapField.
  frequency_cap?: {
    event: string
    interval_days: number
    max_frequency: number
    max_interval_days: number
  }
  // targeting.user_os values for an app campaign. Meta takes one store URL per
  // ad set, so both stores means one ad set each.
  app_platforms?: EditorOption[]
  // Supersets — used to label a value mid-cascade, never to populate a select.
  call_to_actions: EditorOption[]
  ad_formats: EditorOption[]
  creative_limits: {
    // `*_max` is the hard ceiling — typing stops there and the backend rejects
    // past it. `*_recommended` is Meta's design guidance (where the feed
    // truncates); it drives an advisory counter only, never a blocked keystroke.
    title_max: number
    title_recommended: number
    body_max: number
    body_recommended: number
    description_max: number
    description_recommended: number
    carousel_min_cards: number
    carousel_max_cards: number
    // Meta's cap on published text variations per ad.
    max_text_variants: number
    // How many images/videos one ad may combine before the user has to fan them
    // out into separate ads instead.
    max_media_per_ad: number
  }
  lead_form: {
    question_types: EditorOption[]
    default_questions: string[]
    candidates: { id: string; name?: string }[]
    // Meta refuses a form without one, so the builder prefills the advertiser's
    // site rather than making them retype it. Null when the run has no website.
    privacy_policy_url?: string | null
    label_max?: number
    max_options?: number
    intro_title_max?: number
    max_intro_lines?: number
  }
  // The ad account's IANA zone, e.g. "America/Toronto". Meta reads dayparting
  // start/end minutes in THIS zone, not the viewer's, so the control says so.
  // "" when the lookup failed or the catalog predates the field.
  ad_account_timezone?: string
  // Ads Manager's "high demand periods" — a temporary raise on a *daily*
  // budget. Lifetime budgets use ad scheduling instead.
  budget_schedule?: {
    max_multiplier: number
    multiplier_scale: number
    value_types: EditorOption[]
  }
  page_id?: string | null
  // Every Page this Meta connection can publish as, with the Instagram account
  // and instant forms that belong to each. Optional: checkpointed threads replay
  // catalogs built before the Page picker existed.
  page_candidates?: EditorPage[]
  min_budget_cents: number
  pixel_candidates: { id: string; name?: string; last_fired_time?: string }[]
  // The ad account's custom audiences, for the ad set include/exclude pickers.
  // Optional: threads checkpointed before audience targeting existed replay a
  // catalog without it.
  audience_candidates?: EditorAudience[]
  // Standard pixel conversion events, and the one each objective defaults to.
  pixel_events?: string[]
  default_pixel_event_by_objective?: Record<string, string>
  // The account's own custom conversions — rules the advertiser defined over
  // their dataset ("URL contains /thank-you"). Offered beside the standard events
  // because for someone with the base pixel and no event code, one of these is
  // the only conversion they can actually optimize toward.
  custom_conversions?: { id: string; name: string; custom_event_type?: string }[]
  // What "Create one for me" submits. Server-owned so the editor's picker and the
  // intake form agree on one string.
  create_dataset_value?: string
  // How conversions reach Meta. Campaign-level, so it renders in the Campaign
  // panel — not per ad set like the dataset and the event.
  tracking_methods?: { value: string; label: string; description?: string }[]
  // Whether the run collected each prerequisite a destination can require
  // (keys match EditorDestination.required_user_info). Lets the editor warn that
  // a conversion location has nowhere to send people, instead of failing at publish.
  user_info_present?: Record<string, boolean>
  // The account's own campaigns, offered as "start from a previous campaign".
  // Applying one is a server round-trip, not a local swap: the old campaign's
  // setup has to be read from Meta.
  previous_campaigns?: {
    id: string
    name: string
    objective?: string | null
    created_time?: string | null
  }[]
}

// One previous campaign's structure, read on demand by the editor's "what to
// copy" picker (GET /ads/campaign-tree). Names only — the settings themselves
// never reach the browser, the overlay happens server-side.
export type CampaignTreeAdSet = {
  id: string
  name: string
  ads: { id: string; name: string }[]
}

// One image or video. The same four fields wherever media is referenced — on the
// ad itself, on each of its extra media, and on each carousel card — which is
// what lets the submit strip and the server's resolver walk all three the same way.
export type EditorMediaRef = {
  media_kind?: 'image' | 'video' | null
  media_id?: string | null
  image_hash?: string | null
  video_id?: string | null
  // client-only preview (never sent — stripped on submit)
  media_url?: string | null
}

export type EditorCarouselCard = EditorMediaRef & {
  title: string
  body?: string | null
  link: string
}

export type EditorCreative = EditorMediaRef & {
  // The single, published copy the user chose (and may have edited).
  title: string
  body: string
  call_to_action: string
  link: string
  // The grey line under the headline. Optional; Meta shows it only where the
  // placement has room.
  description?: string | null
  // The AI's other ideas — the dropdown on the headline and body fields.
  // Picking one replaces the published value; nothing here reaches Meta.
  title_suggestions?: string[] | null
  body_suggestions?: string[] | null
  description_suggestions?: string[] | null
  // Extra options the user added by hand. On a single image or video ad these
  // publish alongside the primary as Meta text variations and Meta optimizes the
  // combination per viewer (Ads Manager's "Add another option"). A carousel and
  // a boosted post cannot carry them, so the editor does not offer them there.
  title_variants?: string[] | null
  body_variants?: string[] | null
  // URL parameters appended on click (e.g. "utm_source=facebook&utm_medium=paid").
  url_tags?: string | null
  // 'SINGLE' uses the media refs below; 'CAROUSEL' uses `cards` instead. Which
  // formats are offered comes from the ad set's destination entry.
  format?: string
  cards?: EditorCarouselCard[] | null
  // Instant Form id — required when the destination has requires_lead_form.
  lead_gen_form_id?: string | null
  // '<page_id>_<post_id>' — the existing Page post this ad boosts.
  object_story_id?: string | null
  // The same thing from Instagram: an IG post promoted as the ad, keeping its own
  // caption and engagement. Mutually exclusive with object_story_id.
  source_instagram_media_id?: string | null
  // The other media on this ad, beside the primary one on the fields above.
  // Several media on one ad publish as combinations Meta picks between per
  // viewer — Ads Manager's "select up to 10 media in a Single image or video ad".
  // The alternative is one ad per image, which the editor still offers; neither
  // replaces the other. A carousel and a boosted post cannot carry these.
  extra_media?: EditorMediaRef[] | null
}

export type EditorAd = {
  name: string
  creative: EditorCreative
  status?: string
}

// AdSet.frequency_control_specs entry (Reach only). Mirrors backend
// meta_spec/models.py FrequencyControlSpec.
// AdSet.budget_schedule_specs entry. budget_value is read per
// budget_value_type: ABSOLUTE is cents, MULTIPLIER is scaled by
// catalog.budget_schedule.multiplier_scale (200 = 2x).
export type BudgetScheduleSpec = {
  time_start: string
  time_end: string
  budget_value: number
  budget_value_type: 'ABSOLUTE' | 'MULTIPLIER'
}

export type FrequencyControlSpec = {
  event: string
  interval_days: number
  max_frequency: number
}

// One custom audience as the editor's pickers show it. `usable` is Meta's own
// delivery verdict — an audience it will not serve is still listed (hiding the
// user's own audience reads as a bug) but it is not silently selectable.
export type EditorAudience = {
  id: string
  name: string
  subtype?: string
  size?: number | null
  usable?: boolean
  status?: string
}

export type EditorAdSet = {
  name: string
  audience_role?: string
  // Audiences the user picked, by id. Separate from audience_role: that is an
  // intent publish resolves (the MAID list and its lookalike, which do not exist
  // at plan time), these are ids for audiences that already exist.
  attached_audience_ids?: string[]
  excluded_audience_ids?: string[]
  optimization_goal: string
  billing_event: string
  // Required by the server — it is the key that resolves every rule below it.
  destination_type: string
  bid_strategy: string
  bid_amount?: number | null
  bid_constraints?: { roas_average_floor: number } | null
  daily_budget?: number | null
  lifetime_budget?: number | null
  targeting: Record<string, unknown>
  start_time: string
  end_time?: string | null
  promoted_object?: Record<string, unknown> | null
  adset_schedule?: unknown[] | null
  attribution_spec?: unknown[] | null
  // Reach-only frequency cap: how often one person may see the ad in a window.
  budget_schedule_specs?: BudgetScheduleSpec[] | null
  frequency_control_specs?: FrequencyControlSpec[] | null
  ads: EditorAd[]
  // An Instant Form to create at publish, when the user designed one here
  // instead of picking an existing one. Mutually exclusive with the ads'
  // lead_gen_form_id — the server rejects both being set.
  lead_form_draft?: LeadFormDraft | null
  status?: string
}

export type LeadFormQuestion = {
  // One of catalog.lead_form.question_types, or "CUSTOM" with a label.
  type: string
  label?: string | null
  options?: string[] | null
}

export type LeadFormDraft = {
  name: string
  questions: LeadFormQuestion[]
  privacy_policy_url: string
  intro_title?: string | null
  intro_body?: string[] | null
  follow_up_url?: string | null
  // Meta's review step before submission: fewer leads, better ones.
  higher_intent?: boolean
}

export type CampaignEditorSpec = {
  name: string
  objective: string
  special_ad_categories: string[]
  // Required by Meta whenever a category is declared.
  special_ad_category_country?: string[]
  buying_type?: string
  status?: string
  daily_budget?: number | null
  lifetime_budget?: number | null
  bid_strategy?: string | null
  // Per-ad-set budgets only. Meta rejects the campaign without an explicit value.
  is_adset_budget_sharing_enabled?: boolean
  // "High demand periods" under a campaign (Advantage+) budget. The campaign
  // owns the money there, so it owns the schedule — an ad set carries neither.
  budget_schedule_specs?: BudgetScheduleSpec[] | null
  adsets: EditorAdSet[]
  // Who the ads run as. Chosen here rather than at connect time, because the
  // connection stores only one Page and an advertiser may manage several.
  page_id?: string | null
  instagram_user_id?: string | null
  estimated_reach?: Record<string, unknown>
  // What a declared special ad category forced the plan to drop (ZIP targeting,
  // the lookalike, detailed targeting). Display-only.
  compliance_notes?: string[]
}

// What the picker is listing. 'instagram' reads the Page's linked Instagram
// account instead of the Page itself; the answers come back in the same shape.
export type PageObjectKind = 'post' | 'video' | 'event' | 'instagram'

// One boostable Page object (post / video / event / Instagram media), or the
// post behind an ad the account already ran.
export type PageObject = {
  id: string
  label: string
  image?: string | null
  created_time?: string | null
  permalink?: string | null
  // Which creative field this pick lands on. Only /ads/ad-posts sets it — a
  // Page listing already knows its platform from the tab that asked.
  source?: 'facebook' | 'instagram'
}

export type TargetingSuggestion = {
  id: string
  name: string
  audience_size?: number | null
  path?: string[] | null
  flex_field: 'interests' | 'behaviors'
}

export interface LangchainData {
  map_data?:
    | RadiusPickerData
    | ConfirmLocationsData
    | MaidSplitViewData
    | PoiRadiusPickerData
  pending_action?: PendingActionBlock['content']
  campaign_plan?: CampaignPlanContent
}

export type StepperConfig = {
  default: number
  min: number
  max: number
  step: number
  unit: string
}

export type ProgressItem = {
  label: string
  value: string
}

// --- Map Data ---

export type MapDataType =
  | 'radius_picker'
  | 'confirm_locations'
  | 'maid_split_view'
  | 'poi_radius_picker'

export type MapDataBlock = {
  id: string
  type: 'map_data'
  content:
    | RadiusPickerData
    | ConfirmLocationsData
    | MaidSplitViewData
    | PoiRadiusPickerData
}

export type RadiusPickerData = {
  action_type: 'radius_picker'
  center: LatLng
  locations?: LocationItem[]
  default_radius_miles?: number | null
  default_radius_km?: number | null
  pending_action?: PendingActionBlock['content']
}

// A part of a targeted area the user asked to leave out ("everywhere except
// downtown"): drawn grey on the maps; spots inside it are not searched.
export type ExcludedArea = {
  label: string
  lat: number
  lng: number
  bounds?: { lat_min: number; lat_max: number; lng_min: number; lng_max: number } | null
}

export type ConfirmLocationsData = {
  action_type: 'confirm_locations'
  locations: LocationItem[]
  editable?: boolean
  excluded_areas?: ExcludedArea[]
  pending_action?: PendingActionBlock['content']
  prompt?: string
}

// Backend maid_store.AudienceFilter. Only the keys the layer builder edits are
// typed; every other key (trend, cadence, dwell, ...) rides through untouched.
// `groups`/`exclude_groups` are resolved poi group ids ("category:gym").
export type AudienceFilter = {
  groups?: string[]
  op?: 'union' | 'intersection' | 'difference'
  min_distinct_groups?: number
  exclude_groups?: string[]
  // Absent = the exclusion inherits the selection's window; 0 = "ever".
  exclude_window_days?: number
  window_days?: number
  min_visits?: number
  min_visits_per_group?: number
  days_of_week?: number[]
  min_dwell_min?: number
  // "started" | "lapsed"; kept a string so an unknown value reaches the guard.
  trend?: string
  trend_recent_days?: number
  trend_prior_days?: number
  cadence_days?: number
  cadence_tolerance_days?: number
  any_of?: AudienceFilter[]
  [key: string]: unknown
}

// One row of the layer builder as sent to POST /chat/{id}/audience/preview:
// patches OVERLAID on the session's stored filter (a null value clears a key),
// so every filter key the builder doesn't edit carries through untouched.
export type AudienceLayerRequest = { label: string; patches: Record<string, unknown>[] }

export type AudiencePreviewLayer = {
  label: string
  filter: AudienceFilter
  chips: string[]
  // null = the evaluator refused this layer (see `unevaluable`) — never a zero.
  count: number | null
  deviations: string[]
  unevaluable: string | null
}

export type AudiencePreviewResponse = {
  total_devices: number
  // Fewest devices worth running a campaign on (backend publish gate).
  min_deliverable: number
  // Filter parts in force that the builder has no control for ("12+ hrs/week").
  // Already included in every layer's count, so the panel must show them — one
  // per filter key, so removing one clears exactly that key.
  carried: { key: string; label: string }[]
  layers: AudiencePreviewLayer[]
}

export type MaidSplitViewData = {
  action_type: 'maid_split_view'
  pois: PoiItem[]
  maid_observations: LatLng[]
  center: LocationItem
  // The FILTERED, actually-publishable audience — matches the dots/tabs/
  // per-POI counts below. `unfiltered_maid_count` is the raw superset
  // before the active audience_filter (if any) narrowed it — present so a
  // narrowing filter can be shown as "N of M" instead of just the smaller
  // number with no context for where it came from.
  maid_count: number
  unfiltered_maid_count?: number
  // One tab per category/brand set (coffee shops, Starbucks, ...), each with
  // its own pois/maid_observations/maid_count — the top-level fields above
  // are the "combined/All" tab. Absent or empty on older events/single-angle
  // searches — callers should treat that as "no tabs to show".
  poi_categories?: PoiCategoryGroup[]
  visit_stats?: VisitStats
  radius_km?: number | null
  lookback_days?: number | null
  event_date_ranges?: string[] | null
  editable?: boolean
  excluded_areas?: ExcludedArea[]
  // Human-readable summary of the active audience_filter ("3+ visits",
  // "weekends", "excluding: 30+ hrs/week") — empty/absent when no layering
  // is applied. See maid_store.describe_audience_filter on the backend.
  audience_filter_chips?: string[]
  // The structured spec behind the chips — what the audience layer builder
  // edits. Null/absent when no layering is applied.
  audience_filter?: AudienceFilter | null
  // Present only when the active filter is a ROLE predicate (owners/staff,
  // not customers — min_weekly_hours or a presence-pattern field). NEVER
  // affects which audience is returned; it's a caveat on what the numbers
  // above MEAN, not a narrowing. "low"/"medium"/"high" — see backend
  // maid_query.role_confidence. Rides map_data, which IS persisted, so this
  // survives a reload unlike a transient "thinking"/"update" event.
  role_confidence?: 'low' | 'medium' | 'high'
  role_basis?: 'presence pattern' | 'dwell'
  pending_action?: PendingActionBlock['content']
}

export type PoiRadiusPickerData = {
  action_type: 'poi_radius_picker'
  pois: PoiItem[]
  center: LocationItem
  default_radius_km: number
  // The radius actually in force when only the lookback stepper is shown
  // (builder_node.py's _emit_radius_slot_map, poi_radius_m already answered
  // earlier). Always meters — draw the ring at this value, not a guess.
  prefill_radius_m?: number | null
  pending_action?: PendingActionBlock['content']
}

// --- Campaign plan (v2 structured card) ---
// Mirrors backend brief_to_plan_payload (executors/campaign.py).

export type PlanSection =
  | { key: string; label: string; type: 'metrics'; items: { label: string; value: string }[] }
  | { key: string; label: string; type: 'kv'; rows: { label: string; value: string }[] }
  | { key: string; label: string; type: 'text'; text: string }
  | { key: string; label: string; type: 'list'; items: string[] }
  | { key: string; label: string; type: 'table'; columns: string[]; rows: string[][] }

export type CampaignPlanContent = {
  version: 2
  title: string
  subtitle: string
  sections: PlanSection[]
  pending_action?: PendingActionBlock['content']
}

export type CampaignPlanBlock = {
  id: string
  type: 'campaign_plan'
  content: CampaignPlanContent
}

// --- Shared Types ---

export type LatLng = {
  lat: number
  lng: number
  latitude?: number
  longitude?: number
}

export type LocationItem = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [x: string]: any
  id?: string
  location_name?: string
  name?: string // Some events use 'name' instead of 'location_name'
  formatted_address?: string
  latitude?: number
  longitude?: number
  lat?: number // Some events use 'lat'/'lng'
  lng?: number
  is_city?: boolean
  radius_km?: number | null
  parent_location?: string
  place_type?: string
  place_id?: string
  // Confirm-map render mode: 'boundary' (country/state — political shape)
  // vs 'pin_radius' (city/town/metro, or a manual/dragged pin — a
  // draggable marker + resizable ring). Absent on an old checkpoint reads
  // as 'boundary' for back-compat with the pre-existing render path.
  ui_mode?: 'boundary' | 'pin_radius'
  // 'pin_radius' mode only: the current/confirmed search ring, and the
  // server-derived default (for a reset control). Both km.
  search_radius_km?: number
  default_radius_km?: number
}

export type VisitStats = {
  basis: string
  total_devices: number
  buckets: {
    '1x'?: number
    '2x'?: number
    '3_5x'?: number
    '6plus'?: number
    [key: string]: number | undefined
  }
  repeat_visitor_count: number
  repeat_visitor_pct: number
  max_seen: number
  // Raw observation count; total_visits == distinct-day visits when basis === 'visits'.
  total_pings?: number
  total_visits?: number
}

export type PoiItem = {
  location?: LocationItem
  id?: string
  name: string
  lat?: number
  lng?: number
  latitude?: number
  longitude?: number
  radius_km?: number | null
  parent_location?: string
  types?: string[]
  brand?: string | null
  event_start_date?: string | null
  event_end_date?: string | null
  audience_count?: number
  visit_stats?: VisitStats
  formatted_address?: string
  postal_code?: string
  country_code?: string
  // Which search strategy found this POI ("category", "competitor_brand",
  // "event_based", ...) and the literal search term/brand/event name — the
  // pair `poi_categories` groups on. See PoiCategoryGroup.
  source_angle?: string
  parent_poi_type?: string
}

// One category/brand set from a search — "all coffee shops", "all Starbucks",
// etc. — with its own redacted audience slice, so the UI can show a tab per
// set plus a combined "All" tab (the top-level pois/maid_observations/maid_count
// on MaidSplitViewData) without recomputing anything client-side.
export type PoiCategoryGroup = {
  id: string
  key: string
  kind: string
  source_angle: string
  count: number
  pois: PoiItem[]
  maid_observations: LatLng[]
  maid_count: number
  // This group's OWN repeat-visitor summary (maid_query.
  // group_pois_by_category_with_audience) — read this for a per-tab
  // headline, never the top-level MaidSplitViewData.visit_stats (that's the
  // whole build's).
  visit_stats?: VisitStats
}

// ---Block Type---

export type CompetitorListWidget = {
  items: {
    id: string
    name: string
    distance: string
    selected: boolean
  }[]
}
