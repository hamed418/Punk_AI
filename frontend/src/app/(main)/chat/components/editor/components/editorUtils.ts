import dayjs from 'dayjs';
import type {
  CampaignEditorSpec,
  EditorCarouselCard,
  EditorCatalog,
  EditorCreative,
  EditorMediaRef,
  EditorOption,
  EditorPage,
} from '@/types/chat';

const hasMedia = (m: EditorMediaRef) =>
  Boolean(m.media_id || m.image_hash || m.video_id || m.media_url);

// "image" | "video" for one reference, or null when it says nothing. A post-upload
// reference names its kind outright; a bare media_id only carries the hint the
// picker set from MediaFile.media_type.
export const mediaKindOf = (m: EditorMediaRef): 'image' | 'video' | null =>
  m.video_id ? 'video' : m.image_hash ? 'image' : (m.media_kind ?? null);

// Append media onto a creative: the first reference is the primary (the fields
// live flat on the creative), the rest ride along as extras, and the whole set
// is capped at Meta's per-ad limit. Both the file picker and the AI generate
// overlay go through here so neither one throws away what the other attached.
//
// Combining media on one ad works for IMAGES ONLY. Measured against a live ad
// account: Meta strips `videos` out of an asset_feed_spec every time — any
// ad_formats value, any thumbnail shape, even a feed carrying nothing else — and
// still answers 200, so the ad publishes looking correct and runs one asset. A
// video therefore gets an ad of its own, enforced here rather than at publish.
// ``onRefused`` reports how many picks were turned away; without one it is silent.
export function attachMedia(
  c: EditorCreative,
  picked: EditorMediaRef[],
  cap: number,
  onRefused?: (count: number) => void
): Partial<EditorCreative> {
  if (!picked.length) return {};
  const existing = [c as EditorMediaRef, ...(c.extra_media ?? [])].filter(hasMedia);
  const fields = (m: EditorMediaRef, extras: EditorMediaRef[]) => ({
    media_id: m.media_id ?? null,
    media_url: m.media_url ?? null,
    media_kind: m.media_kind ?? null,
    image_hash: m.image_hash ?? null,
    video_id: m.video_id ?? null,
    extra_media: extras.length ? extras : null,
  });

  // An ad already holding a video is full — nothing may join it.
  if (mediaKindOf(existing[0] ?? {}) === 'video') {
    onRefused?.(picked.length);
    return {};
  }
  // ...and a video landing on an empty ad claims it alone.
  if (!existing.length && mediaKindOf(picked[0]) === 'video') {
    if (picked.length > 1) onRefused?.(picked.length - 1);
    return fields(picked[0], []);
  }

  // Past here the ad is images, so only images may join. An entry naming no kind
  // is unknowable client-side — let it through; CreativeSpec and the publish
  // resolver both re-check it against the real file.
  const wanted = picked.filter((m) => mediaKindOf(m) !== 'video');
  if (wanted.length < picked.length) onRefused?.(picked.length - wanted.length);
  if (!wanted.length) return {};
  const combined = [...existing, ...wanted].slice(0, Math.max(cap, 1));
  const [primary, ...extras] = combined;
  return fields(primary, extras);
}

// The five media fields, off any of the three shapes that carry them (a
// creative itself, an extra_media entry, a carousel card) — the same trio
// switchFormat moves media between below.
const mediaFieldsOf = (m: EditorMediaRef): EditorMediaRef => ({
  media_id: m.media_id ?? null,
  media_url: m.media_url ?? null,
  media_kind: m.media_kind ?? null,
  image_hash: m.image_hash ?? null,
  video_id: m.video_id ?? null,
});

// Single <-> carousel, carrying every attached image/video along either way
// so switching back and forth loses nothing. Pure so it is unit-testable and
// so AdCard and (eventually) a bulk "apply to every ad" action can share it.
export function switchFormat(
  c: EditorCreative,
  next: string,
  limits: {
    carousel_min_cards: number;
    carousel_max_cards: number;
    max_media_per_ad: number;
  }
): Partial<EditorCreative> {
  const current = c.format ?? 'SINGLE';
  if (next === current) return {};

  if (next === 'CAROUSEL') {
    // Media the ad already combined becomes one card each rather than being
    // thrown away — both formats are "several assets on one ad", they just
    // show them differently.
    const attached = [c as EditorMediaRef, ...(c.extra_media ?? [])].filter(hasMedia);
    const seeded: EditorCarouselCard[] = Array.from(
      {
        length: Math.min(
          Math.max(limits.carousel_min_cards, attached.length),
          limits.carousel_max_cards
        ),
      },
      (_, i) => ({
        title: c.title,
        // The card's grey description line, not the ad's primary text — that
        // stays on the creative and is shown once above the whole carousel.
        body: null,
        link: c.link,
        ...mediaFieldsOf(attached[i] ?? {}),
      })
    );
    return {
      format: next,
      cards: seeded,
      ...mediaFieldsOf({}),
      // A carousel cannot publish text variations or combined media —
      // dropping them here keeps the spec honest about what will run.
      title_variants: null,
      body_variants: null,
      extra_media: null,
    };
  }

  // CAROUSEL -> SINGLE: card 0 becomes the primary, exactly like Add Media's
  // own primary/extras split. Cards 1..n that carry media become extra_media
  // (capped at the ad's own media limit) instead of being discarded — the
  // symmetric inverse of the seeding above.
  const [first, ...rest] = c.cards ?? [];
  const extras = rest
    .filter(hasMedia)
    .slice(0, Math.max(limits.max_media_per_ad - 1, 0))
    .map(mediaFieldsOf);
  return {
    format: next,
    cards: null,
    ...mediaFieldsOf(first ?? {}),
    extra_media: extras.length ? extras : null,
  };
}

export const centsToDollars = (c?: number | null) =>
  c == null ? undefined : Math.round(c) / 100;

export const dollarsToCents = (d?: number | string | null) =>
  d == null || d === '' ? null : Math.round(Number(d) * 100);

// Mantine v9 DateTimePicker is controlled by a local wall-clock STRING
// ("YYYY-MM-DD HH:mm:ss"), not a Date. Store as an ISO-8601 string with offset
// (dayjs().format()) so the picked instant reaches Meta correctly.
export const toLocalString = (stored?: string | null) =>
  stored ? dayjs(String(stored)).format('YYYY-MM-DD HH:mm:ss') : null;

export const fromPicker = (v: string | null) => (v ? dayjs(v).format() : null);

export const DEFAULT_FLIGHT_DAYS = 30;

export const defaultEnd = (start?: string | null) =>
  dayjs(start || undefined).add(DEFAULT_FLIGHT_DAYS, 'day').format();

export const selectClassNames = {
  input:
    'bg-transparent! border-primary-text/10! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]! text-primary-text! rounded-[32px]! text-[13px]! px-3.5! pt-2! pb-2.75! h-10!',
  dropdown:
    'bg-[#1C1C1C]/90! light:bg-white/90! backdrop-blur-xl! border border-stroke-widget! shadow-widget! rounded-2xl!',
  option:
    'text-primary-text/80! data-[selected]:text-primary-text! text-[13px]! rounded-lg!',
  label: 'font-medium! text-xs! text-primary-text/80! mb-2!',
  pill:
    'bg-primary-bg! border border-stroke-widget! rounded-full! py-0! h-6.5! flex items-center! gap-1! shadow-[0px_1.5px_3px_#00000040]!',
  pillLabel:
    'text-primary-text! text-[11px]! font-semibold! tracking-wide! leading-none!',
  pillRemoveButton:
    'text-secondary-text! hover:text-red-400! hover:bg-transparent! transition-colors! size-4! p-0! flex items-center justify-center!',
  control:
    'border-b! last:border-b-0! border-primary-text/10! text-primary-text/60! hover:text-primary-text! hover:bg-white/8! transition-colors! cursor-pointer!',
  controls:
    'flex! flex-col! h-full! border-l! border-primary-text/10! rounded-r-[32px]! overflow-hidden! w-7!',
  section:
    'data-[position=right]:rounded-r-[32px]! data-[position=right]:overflow-hidden!',
};

export const multiSelectClassNames = {
  ...selectClassNames,
  input:
    'bg-transparent! border-primary-text/10! shadow-[0px_-1px_0px_0px_#00000026_inset,0px_1px_0px_0px_#FFFFFF0F_inset]! text-primary-text! rounded-[32px]! py-2! px-2! pr-8! text-[13px]! min-h-10! h-auto!',
};

export const segmentedControlClassNames = {
  root: 'bg-primary-text/6! border border-stroke-widget! rounded-full! p-1! min-h-[38px]!',
  indicator:
    'bg-primary-text/12! light:bg-white! rounded-full! border border-primary-text/15! shadow-[0px_2px_6px_0px_#00000033,0px_1.5px_0px_0px_#FFFFFF2E_inset]! light:border-black/5!',
  control: 'border-0!',
  label:
    'text-secondary-text! data-[active]:text-primary-text! data-[active]:font-semibold! text-[13px]! py-1.5! px-3!',
};

export const tooltipStyles = {
  tooltip: {
    backgroundColor: 'var(--mantine-color-widget-inner-glass-bg)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    border: '1px solid var(--mantine-color-plus-minus-button-border)',
    borderRadius: '8px',
    padding: '6px 8px',
    lineHeight: 0.9,
    color: 'var(--color-secondary-text)',
  },
};

export const accordionClassNames = {
  item: 'overflow-hidden! border border-underline/15! rounded-[18px]! mb-2! bg-[#00000003]! backdrop-blur-[103.6px]! shadow-[0px_8px_24px_0px_#00000080,0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset]!',
  control: 'text-primary-text! hover:bg-white/5! rounded-none!',
  label: 'py-[15px]! px-1! font-bold!',
  content: 'px-3! pb-3!',
  chevron: 'text-secondary-text!',
};

export function toSelectData(opts?: EditorOption[]) {
  return (opts || []).map((o) => ({ value: o.value, label: o.label }));
}

export function descsOf(opts?: { value: string; help?: string }[]) {
  return Object.fromEntries((opts || []).map((o) => [o.value, o.help]));
}

export const FIELD_HELP: Record<string, string> = {
  objective:
    'What the campaign is for. It decides which conversion locations and optimization goals are available below.',
  conversion_location:
    'Where people go after clicking your ad — your website, an instant form, WhatsApp, a call, etc.',
  optimization_goal:
    'What Meta optimizes delivery toward (link clicks, conversions, reach…). The choices depend on your conversion location.',
  billing_event: 'What you are charged for — impressions shown or link clicks.',
  bid_strategy:
    'How Meta bids in the auction. Lowest cost chases the most results; cost/bid caps trade some volume for a price ceiling.',
  budget_mode:
    'Campaign (CBO) lets Meta shift budget to the best-performing ad sets automatically. Per ad set gives each ad set its own fixed budget.',
  budget_type:
    'Daily spends a set amount each day. Lifetime spends a total across the whole run and needs an end date.',
  special_ad_categories:
    'Required by Meta for ads about credit, employment, housing, or social/political issues — they restrict targeting options.',
  attribution:
    'Which conversions count toward this ad. Click: how many days after someone clicks your link an action still counts (1 or 7). Engage: they watched 5+ seconds of your video, or liked, shared, saved or commented, then converted within a day. View: they saw the ad without interacting and converted within a day. Meta’s default is 7-day click, 1-day engage, 1-day view — leave it alone and that is what runs. Only affects conversion ad sets.',
  frequency:
    'Caps how often one person sees your ad within a time window. Only available on the Reach optimization goal.',
};

// Why a plan ships with two ad sets, in the user's terms. The roles are
// deterministic (builder.py assigns seed / lookalike / broad), so this copy is
// static — nothing here is generated, and nothing here can drift from the plan.
export const AUDIENCE_ROLE_COPY: Record<
  string,
  { label: string; help: string }
> = {
  seed: {
    label: 'Real Visitor Audience',
    help: 'The actual people our data caught at your locations. Highest intent, smallest pool — this is the audience you paid to collect.',
  },
  lookalike: {
    label: 'Expanded Visitor Audience',
    help: 'Meta models this from your visitor list: people who look and behave like your real visitors but have never heard of you. It is how the campaign keeps finding new customers once the visitor list has seen the ads.',
  },
  broad: {
    label: 'New Prospects — Expanded Reach',
    help: 'Not enough visitor data for a lookalike yet, so this one prospects on location and demographics. It upgrades to a visitor-modelled audience once the list grows.',
  },
};

export const pixelEventsOf = (catalog: EditorCatalog): string[] =>
  catalog.pixel_events ?? ['PURCHASE', 'LEAD', 'COMPLETE_REGISTRATION'];

export const PREREQUISITE_FIXES: Record<string, string> = {
  website_url:
    'Clicks currently go to your Facebook Page — we never got a website. Put your site in Website URL above if you want them to land there instead.',
  app_store_url:
    'We need your store link — fill in App store URL above, one ad set per store.',
  page_whatsapp:
    'This Page has no WhatsApp Business account linked, so there is no number for the ad to open a chat with. Pick a different Page under Campaign, or link one in your Page settings and reconnect.',
};

// Whether the Page these ads run as can receive a Click-to-WhatsApp chat.
// `undefined` means the Meta token could not read the field — NOT that the Page
// is unlinked. See EditorPage.whatsapp.
export const pageWhatsAppLinked = (
  page?: EditorPage
): boolean | undefined =>
  page?.whatsapp === undefined ? undefined : page.whatsapp !== null;

// The identities hanging off one Page, for the picker's option line. WhatsApp is
// named only when the token could read it, so an unreadable field reads as
// silence rather than as bad news about the Page.
export const pageSubtitle = (page: EditorPage): string => {
  const parts = [
    page.instagram?.username
      ? `Instagram: @${page.instagram.username}`
      : 'No linked Instagram account',
  ];
  const wa = pageWhatsAppLinked(page);
  if (wa === true)
    parts.push(`WhatsApp: ${page.whatsapp?.number || 'linked'}`);
  else if (wa === false) parts.push('No linked WhatsApp');
  return parts.join(' · ');
};

export const appPlatformsOf = (catalog: EditorCatalog): EditorOption[] =>
  catalog.app_platforms ?? [
    { value: 'iOS', label: 'iOS' },
    { value: 'Android', label: 'Android' },
  ];

export const frequencyCapOf = (catalog: EditorCatalog) =>
  catalog.frequency_cap ?? {
    event: 'IMPRESSIONS',
    interval_days: 7,
    max_frequency: 1,
    max_interval_days: 90,
  };

// Whether a creative/card/extra carries any media at all. The same three fields
// the submit stripper and the server's resolver walk.
export const hasAnyMedia = (m: EditorMediaRef) =>
  Boolean(m.media_id || m.image_hash || m.video_id || m.media_url);

/**
 * The slice of the spec the editor actually renders, which is the only slice it
 * may validate. Express ("do it for me") shows ad set 0 alone and the server
 * copies its ads onto the rest on submit (`_mirror_first_ad`). Validating the
 * hidden ad sets flags their brief-seeded, media-less ads, and CampaignEditor's
 * `adsets[n]` → `adsets[0]` error remap then pins an unclearable "no image" on
 * the one card the user already filled — and blocks submit forever.
 *
 * Submit still sends the whole tree: the server restores the locked geo/audience
 * per ad set from it.
 */
export const forValidation = (
  spec: CampaignEditorSpec,
  adsOnly: boolean
): CampaignEditorSpec =>
  adsOnly ? { ...spec, adsets: spec.adsets.slice(0, 1) } : spec;

/**
 * Autopilot toggle's restore: rebuild the campaign and ad-set settings from
 * the plan the server last sent, keeping the one thing express actually asks
 * the user for — ad set 0's ad copy and creative — from whatever they had
 * unlocked and changed. Pure so CampaignEditor's relock() and this module's
 * self-check agree on the same behavior; see editorUtils.check.ts.
 *
 * ponytail: restores to the last SERVER-SENT spec, not a true pristine
 * snapshot — if a publish failed and the server re-emitted with the user's
 * unlocked edits folded in, `serverSpec` is that, not the original
 * brief-generated plan. Upgrade to a bs-side stash (express_base_spec) on
 * generate_meta_json only if that gap actually bites someone.
 */
export function restoreFromLocked(
  serverSpec: CampaignEditorSpec,
  currentSpec: CampaignEditorSpec
): CampaignEditorSpec {
  const base = structuredClone(serverSpec);
  if (base.adsets[0] && currentSpec.adsets[0]) {
    base.adsets[0].ads = structuredClone(currentSpec.adsets[0].ads);
  }
  return base;
}

// The link the plan builder writes when the run never collected a website
// (meta_spec/builder.py: `https://www.facebook.com/{page_id}`). It is a valid
// URL, so nothing downstream objects — the ad just sends every click to the
// advertiser's own Page instead of their site.
export const isPageFallbackLink = (link: string, pageId?: string | null) =>
  !!pageId && link.includes(`facebook.com/${pageId}`);

/**
 * Everything the server would reject, decided locally, keyed by the SAME spec
 * paths `errors_to_form_keys` produces server-side
 * (`adsets[0].ads[1].creative.title`). That is what makes this free to render:
 * every control in the editor already binds `error={err('<path>')}`.
 *
 * Why here and not only server-side: `CampaignSpec`'s cross-field rules live in
 * `@model_validator(mode="after")`, which raises on the FIRST problem — so
 * fixing a plan meant one round trip per mistake. These run all at once, before
 * the trip.
 *
 * Only rules that are decidable from the spec + catalog. Whether a host resolves,
 * whether the ad account may bill per click, whether a Page has WhatsApp linked —
 * those stay server-side and come back as `content.errors`.
 *
 * `action` is what separates the two kinds of rule here. Most of these the server
 * enforces too, so a Save carrying one fails either way and may as well be marked
 * now. Two are ours alone — an ad with no media, and a link still pointing at the
 * Page — and they only cost anything at publish. Blocking a Save on them would
 * refuse to hold half-finished work, which is what Save is for.
 */
export function validateSpec(
  spec: CampaignEditorSpec,
  catalog: EditorCatalog,
  pageId?: string | null,
  action: 'save' | 'publish' = 'publish'
): Record<string, string> {
  const publishing = action === 'publish';
  const e: Record<string, string> = {};
  const roasGoal = roasGoalOf(catalog);
  const needsAmount = catalog.bid_strategies_requiring_amount ?? [];
  const minCents = catalog.min_budget_cents || 100;
  const minLabel = `$${(minCents / 100).toFixed(2)}`;
  const limits = catalog.creative_limits;
  const destinations = catalog.destinations_by_objective?.[spec.objective] ?? [];
  const selectedPage = (catalog.page_candidates ?? []).find(
    (pg) => pg.id === (spec.page_id ?? pageId)
  );

  // ── campaign ──────────────────────────────────────────────────────────────
  if (!spec.name?.trim()) e.name = 'Give the campaign a name.';
  if (spec.special_ad_categories?.length && !spec.special_ad_category_country?.length)
    e.special_ad_category_country =
      'Pick the country whose rules apply — Meta needs it with a special ad category.';

  const campaignOwnsBudget = spec.daily_budget != null || spec.lifetime_budget != null;
  if (campaignOwnsBudget) {
    const cents = spec.daily_budget ?? spec.lifetime_budget ?? 0;
    if (cents < minCents)
      e[spec.daily_budget != null ? 'daily_budget' : 'lifetime_budget'] =
        `Meta's minimum is ${minLabel}.`;
  }

  spec.adsets.forEach((as, i) => {
    const p = `adsets[${i}]`;
    const dest = destinations.find((d) => d.value === as.destination_type) ?? destinations[0];
    const required = dest?.required_user_info ?? [];
    const promotedKind = dest?.promoted_object_kind_by_goal?.[as.optimization_goal] ?? 'none';
    const po = (as.promoted_object ?? {}) as Record<string, unknown>;

    // ── ad set ──────────────────────────────────────────────────────────────
    if (!as.name?.trim()) e[`${p}.name`] = 'Give the ad set a name.';

    if (as.bid_strategy === roasGoal.bid_strategy) {
      // The per-ad-set bid strategy Select seeds nothing (unlike the campaign
      // control, which fills every ad set in), so switching one ad set to a cap
      // leaves an empty box nothing forces you to fill. No default is invented:
      // a cap is a spend ceiling, the number has to be the user's.
      if (!as.bid_constraints?.roas_average_floor)
        e[`${p}.bid_constraints`] = 'Enter a minimum ROAS.';
    } else if (needsAmount.includes(as.bid_strategy) && !as.bid_amount) {
      e[`${p}.bid_amount`] =
        'Enter a bid amount, or pick a strategy that does not need one.';
    }

    if (!campaignOwnsBudget) {
      const cents = as.daily_budget ?? as.lifetime_budget ?? 0;
      if (!cents) e[`${p}.daily_budget`] = 'Set a budget for this ad set.';
      else if (cents < minCents)
        e[as.daily_budget != null ? `${p}.daily_budget` : `${p}.lifetime_budget`] =
          `Meta's minimum is ${minLabel}.`;
    }

    const isLifetime = campaignOwnsBudget
      ? spec.lifetime_budget != null
      : as.lifetime_budget != null;
    if (isLifetime && !as.end_time)
      e[`${p}.end_time`] = 'A lifetime budget needs an end date.';
    else if (as.end_time && as.start_time && !(new Date(as.end_time) > new Date(as.start_time)))
      e[`${p}.end_time`] = 'The end date has to be after the start date.';

    if (promotedKind === 'pixel') {
      if (!po.pixel_id) e[`${p}.promoted_object.pixel_id`] = 'Pick the pixel that tracks this.';
      // A custom conversion IS the event definition, so it answers this on its
      // own; a bare pixel still has to name which event to optimize toward.
      if (!po.custom_event_type && !po.custom_conversion_id)
        e[`${p}.promoted_object.custom_event_type`] = 'Pick the conversion event to optimize for.';
    }
    if (promotedKind === 'application' && !String(po.object_store_url ?? '').trim())
      e[`${p}.promoted_object.object_store_url`] = 'Paste the app store listing this ad set sends people to.';

    // Instagram-profile destinations declare this; the ad creative carries the
    // account, and Meta rejects the AD (subcode 3907008) once the campaign and
    // ad set already exist — a half-built campaign for a blank field.
    if (required.includes('meta_instagram_user_id') && !spec.instagram_user_id)
      e.instagram_user_id = 'Pick the Instagram account this ad runs as.';

    // Click-to-WhatsApp dials the number linked to the Page, so the Page picker
    // is the control that fixes this — not anything inside the ad set. Meta
    // refuses it at preflight ("Your Page is not linked to a WhatsApp account"),
    // which creates nothing but costs the user the whole publish.
    //
    // Only a definite `false` blocks. `undefined` is a token that could not read
    // the field, and guessing "unlinked" there would refuse a campaign that
    // publishes fine — the preflight message still covers that case.
    if (
      publishing &&
      required.includes('page_whatsapp') &&
      pageWhatsAppLinked(selectedPage) === false
    )
      e.page_id = `${selectedPage?.name || 'This Page'} has no WhatsApp account linked — pick a Page that does.`;

    // ── ads ─────────────────────────────────────────────────────────────────
    as.ads.forEach((ad, j) => {
      const c = ad.creative;
      const ap = `${p}.ads[${j}]`;
      const isCarousel = c.format === 'CAROUSEL';
      const isBoost = !!dest?.object_story_kind;

      // Either platform's post satisfies it — the ad IS the post either way.
      const promotesPost = !!(c.object_story_id || c.source_instagram_media_id);

      if (isBoost && !promotesPost)
        e[`${ap}.creative.object_story_id`] =
          `Pick the ${dest?.object_story_kind} you want to promote.`;
      if (c.object_story_id && c.source_instagram_media_id)
        e[`${ap}.creative.object_story_id`] =
          'An ad promotes one post — pick either the Facebook or the Instagram one.';

      // A promoted post carries its own copy, media and link — Meta ignores
      // anything composed beside it, so none of the checks below apply.
      if (promotesPost) return;

      if (!c.title?.trim()) e[`${ap}.creative.title`] = 'Write a headline.';
      if (!c.body?.trim()) e[`${ap}.creative.body`] = 'Write the primary text.';

      if (isCarousel) {
        const cards = c.cards ?? [];
        const min = limits?.carousel_min_cards ?? 2;
        const max = limits?.carousel_max_cards ?? 10;
        if (cards.length < min || cards.length > max) {
          e[`${ap}.creative.cards`] = `A carousel needs between ${min} and ${max} cards.`;
        } else {
          cards.forEach((card, k) => {
            const cp = `${ap}.creative.cards[${k}]`;
            // Unlike the single-ad media check below, this one is not gated on
            // `publishing`: CarouselCard._card_has_media (backend) rejects a
            // card with no media on EVERY submit, save included, so a Save
            // that passed here only bounced off the server with no field to
            // point at (EditorNav's path regex does not descend into cards).
            if (!hasAnyMedia(card))
              e[`${cp}.media`] = 'Add an image or video to this card.';
            if (!card.title?.trim()) e[`${cp}.title`] = 'Write a headline for this card.';
            if (!card.link?.trim()) e[`${cp}.link`] = 'Where should this card send people?';
          });
        }
      } else if (publishing && !hasAnyMedia(c)) {
        e[`${ap}.creative.media`] =
          'Upload an image or video to preview.';
      }

      // The link the user can see and fix. `required_user_info` naming
      // website_url is how a destination says "clicks need somewhere to land";
      // destinations that route without a URL (WhatsApp, instant forms) do not.
      if (required.includes('website_url')) {
        const link = c.link?.trim() ?? '';
        if (!link) e[`${ap}.creative.link`] = 'Where should clicks land?';
        else if (publishing && isPageFallbackLink(link, pageId))
          e[`${ap}.creative.link`] =
            'This sends clicks to your Facebook Page, not your website. Put your site here.';
      }
    });
  });

  return e;
}

export const countryNames = new Intl.DisplayNames(['en'], { type: 'region' });

export const roasGoalOf = (catalog: EditorCatalog) =>
  catalog.roas_goal ?? {
    bid_strategy: 'LOWEST_COST_WITH_MIN_ROAS',
    scale: 10000,
    min: 100,
    max: 10000000,
  };

export function summarizeGeo(t: Record<string, unknown>): string {
  const geo = (t.geo_locations as Record<string, unknown>) || {};
  const zips = (geo.zips as { key: string }[]) || [];
  const cities = (geo.cities as { name: string }[]) || [];
  if (zips.length) return `${zips.length} ZIP code(s) targeted`;
  if (cities.length) return cities.map((c) => c.name).join(', ');
  return 'Geo targeting from the map step';
}
