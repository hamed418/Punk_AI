// Self-check for attachMedia — the one bit of non-obvious logic in this folder
// (append, cap, primary/extras split). No test runner in this app, so run it
// directly:  node src/app/\(main\)/chat/components/editor/components/editorUtils.check.ts
import assert from 'node:assert/strict';
import {
  attachMedia,
  forValidation,
  restoreFromLocked,
  switchFormat,
  validateSpec,
} from './editorUtils.ts';
import type {
  CampaignEditorSpec,
  EditorCatalog,
  EditorCreative,
  EditorMediaRef,
} from '@/types/chat';

const img = (id: string): EditorMediaRef => ({
  media_id: id,
  media_url: `/${id}.png`,
  media_kind: 'image',
  image_hash: null,
  video_id: null,
});

const vid = (id: string): EditorMediaRef => ({ ...img(id), media_kind: 'video' });

const creative = (over: Partial<EditorCreative> = {}): EditorCreative => ({
  title: 't',
  body: 'b',
  call_to_action: 'LEARN_MORE',
  link: 'https://x.test',
  ...over,
});

// empty ad: first pick becomes the primary, the rest are extras
let p = attachMedia(creative(), [img('a'), img('b')], 10);
assert.equal(p.media_id, 'a');
assert.deepEqual(p.extra_media?.map((m) => m.media_id), ['b']);

// nothing picked: no patch at all
assert.deepEqual(attachMedia(creative(), [], 10), {});

// appends rather than replacing — the generate-twice bug
p = attachMedia(creative({ ...img('a'), extra_media: [img('b')] }), [img('c')], 10);
assert.equal(p.media_id, 'a');
assert.deepEqual(p.extra_media?.map((m) => m.media_id), ['b', 'c']);

// caps at the per-ad limit, keeping what was already attached
p = attachMedia(creative({ ...img('a'), extra_media: [img('b')] }), [img('c'), img('d')], 3);
assert.deepEqual(p.extra_media?.map((m) => m.media_id), ['b', 'c']);

// a creative with no media yet is not counted as an occupied slot
p = attachMedia(creative({ media_id: null, media_url: '/stale.png' }), [img('a')], 10);
assert.equal(p.media_id, 'a');
assert.equal(p.extra_media, null);

// the primary never leaks the creative's copy fields into extra_media
p = attachMedia(creative({ ...img('a') }), [img('b')], 10);
assert.deepEqual(Object.keys(p.extra_media![0]).sort(), [
  'image_hash',
  'media_id',
  'media_kind',
  'media_url',
  'video_id',
]);

// images combine, videos never do: an image ad refuses a picked video and counts it
let refused: number | null = null;
p = attachMedia(creative({ ...img('a') }), [img('b'), vid('v')], 10, (n) => {
  refused = n;
});
assert.deepEqual(p.extra_media?.map((m) => m.media_id), ['b']);
assert.equal(refused, 1);

// an ad already holding a video is full — nothing joins it, and no patch is
// returned, so the caller does not clear the video already there
refused = null;
p = attachMedia(creative({ ...vid('v') }), [img('b'), vid('w')], 10, (n) => {
  refused = n;
});
assert.deepEqual(p, {});
assert.equal(refused, 2);

// a video landing on an empty ad claims it alone
refused = null;
p = attachMedia(creative(), [vid('v'), img('b')], 10, (n) => {
  refused = n;
});
assert.equal(p.media_id, 'v');
assert.equal(p.extra_media, null);
assert.equal(refused, 1);

// every pick refused: no patch at all
refused = null;
p = attachMedia(creative({ ...img('a') }), [vid('v')], 10, (n) => {
  refused = n;
});
assert.deepEqual(p, {});
assert.equal(refused, 1);

// an entry that names no kind is unknowable here — let it through, the server
// and the publish-time resolver both re-check against the real file
p = attachMedia(creative({ ...img('a') }), [{ media_id: 'x' }], 10);
assert.deepEqual(p.extra_media?.map((m) => m.media_id), ['x']);

console.log('attachMedia ok');

// ── switchFormat ─────────────────────────────────────────────────────────────
// Single <-> carousel, carrying every attached image/video along either way —
// the regression this whole plan exists to fix (AdCard used to drop cards 2..n
// on the way back to Single, and only copied media_id/media_url, losing
// image_hash/video_id/media_kind on an already-uploaded asset).

const fmtLimits = { carousel_min_cards: 2, carousel_max_cards: 10, max_media_per_ad: 10 };

// SINGLE -> CAROUSEL: the primary and every extra become one card each, each
// keeping its full media reference, not just media_id/media_url.
const threeMedia = creative({
  ...img('a'),
  extra_media: [
    { media_id: 'b', media_url: '/b.png', media_kind: 'image', image_hash: 'hash-b', video_id: null },
    vid('c'),
  ],
});
let f = switchFormat(threeMedia, 'CAROUSEL', fmtLimits);
assert.equal(f.format, 'CAROUSEL');
assert.equal(f.cards?.length, 3);
assert.deepEqual(f.cards?.map((c) => c.media_id), ['a', 'b', 'c']);
assert.equal(f.cards?.[1].image_hash, 'hash-b');
assert.equal(f.cards?.[2].media_kind, 'video');
assert.equal(f.media_id, null);
assert.equal(f.extra_media, null);

// CAROUSEL -> SINGLE: card 0 becomes the primary, cards 1..n with media become
// extra_media — nothing silently dropped, unlike the old inline changeFormat.
const fiveCards = creative({
  format: 'CAROUSEL',
  cards: [
    { title: 'A', link: 'https://x.test', media_id: 'a', media_kind: 'image' },
    { title: 'B', link: 'https://x.test', media_id: 'b', media_kind: 'image' },
    { title: 'C', link: 'https://x.test', media_id: 'c', media_kind: 'image' },
    { title: 'D', link: 'https://x.test', media_id: 'd', media_kind: 'image' },
    { title: 'E', link: 'https://x.test', media_id: 'e', media_kind: 'image' },
  ],
});
f = switchFormat(fiveCards, 'SINGLE', fmtLimits);
assert.equal(f.format, 'SINGLE');
assert.equal(f.cards, null);
assert.equal(f.media_id, 'a');
assert.deepEqual(f.extra_media?.map((m) => m.media_id), ['b', 'c', 'd', 'e']);

// round trip: SINGLE -> CAROUSEL -> SINGLE loses no media
const toCarousel = switchFormat(threeMedia, 'CAROUSEL', fmtLimits);
const backToSingle = switchFormat({ ...threeMedia, ...toCarousel }, 'SINGLE', fmtLimits);
assert.equal(backToSingle.media_id, 'a');
assert.deepEqual(backToSingle.extra_media?.map((m) => m.media_id), ['b', 'c']);

// switching to the format already active is a no-op patch
assert.deepEqual(switchFormat(creative({ format: 'SINGLE' }), 'SINGLE', fmtLimits), {});

console.log('switchFormat ok');

// ── validateSpec ─────────────────────────────────────────────────────────────
// Keys must match the paths the server's errors_to_form_keys emits, because that
// is what every `error={err('<path>')}` binding in the editor is written against.

const WEBSITE = {
  value: 'WEBSITE',
  label: 'Website',
  optimization_goals: [],
  billing_events: [],
  call_to_actions: [],
  ad_formats: [],
  promoted_object_kind_by_goal: { LINK_CLICKS: 'none', OFFSITE_CONVERSIONS: 'pixel' },
  requires_lead_form: false,
  required_user_info: ['website_url'],
};

// Routes without a URL, so no website_url prerequisite and no link to check.
const MESSENGER = {
  ...WEBSITE,
  value: 'MESSENGER',
  label: 'Messenger',
  required_user_info: [],
};

// Dials the number on the Page, so its prerequisite is answered per Page.
const WHATSAPP = {
  ...WEBSITE,
  value: 'WHATSAPP',
  label: 'WhatsApp',
  required_user_info: ['page_whatsapp'],
};

const PAGES = [
  { id: '998877665544', name: 'Linked', whatsapp: { number: '+15550101' } },
  { id: 'pg_unlinked', name: 'Unlinked', whatsapp: null },
  // No `whatsapp` key at all: the token could not read the field.
  { id: 'pg_unknown', name: 'Unknown' },
];

const catalog = {
  objectives: [],
  destinations_by_objective: { OUTCOME_TRAFFIC: [WEBSITE, MESSENGER, WHATSAPP] },
  special_ad_categories: [],
  categories_blocking_demographics: [],
  bid_strategies: [],
  bid_strategies_by_objective: {},
  bid_strategies_requiring_amount: ['COST_CAP'],
  genders: [],
  placements: { publisher_platforms: [], positions: {}, position_field_by_platform: {} },
  attribution: { click_windows: [], view_windows: [] },
  call_to_actions: [],
  ad_formats: [],
  creative_limits: {
    title_max: 255,
    title_recommended: 40,
    body_max: 2200,
    body_recommended: 125,
    description_max: 255,
    description_recommended: 30,
    carousel_min_cards: 2,
    carousel_max_cards: 10,
    max_text_variants: 5,
    max_media_per_ad: 10,
  },
  lead_form: { question_types: [], default_questions: [], candidates: [] },
  min_budget_cents: 100,
  pixel_candidates: [],
  page_candidates: PAGES,
} as unknown as EditorCatalog;

const okSpec = (): CampaignEditorSpec => ({
  name: 'Summer push',
  objective: 'OUTCOME_TRAFFIC',
  special_ad_categories: [],
  page_id: '998877665544',
  adsets: [
    {
      name: 'Cafe Visitors',
      optimization_goal: 'LINK_CLICKS',
      billing_event: 'IMPRESSIONS',
      destination_type: 'WEBSITE',
      bid_strategy: 'LOWEST_COST_WITHOUT_CAP',
      daily_budget: 3500,
      targeting: {},
      start_time: '2026-08-01T00:00:00Z',
      ads: [
        {
          name: 'Ad 1',
          creative: {
            title: 'Fresh roast',
            body: 'Roasted two blocks away.',
            call_to_action: 'LEARN_MORE',
            link: 'https://beanthere.example',
            format: 'SINGLE',
            media_id: 'm1',
            media_kind: 'image',
          },
        },
      ],
    },
  ],
});

const v = (mutate: (s: CampaignEditorSpec) => void = () => {}) => {
  const s = okSpec();
  mutate(s);
  return validateSpec(s, catalog, s.page_id);
};

// a plan with everything filled in passes — the guard against over-eager rules
assert.deepEqual(v(), {});

// the reported case: a Website conversion location whose link is still the Page
// fallback the plan builder writes when no website was ever collected
assert.deepEqual(Object.keys(v((s) => {
  s.adsets[0].ads[0].creative.link = 'https://www.facebook.com/998877665544';
})), ['adsets[0].ads[0].creative.link']);

// ...and the same field when it is simply empty
assert.deepEqual(Object.keys(v((s) => {
  s.adsets[0].ads[0].creative.link = '';
})), ['adsets[0].ads[0].creative.link']);

// a Page URL is fine when the destination does not route by URL at all
assert.deepEqual(
  v((s) => {
    s.adsets[0].destination_type = 'MESSENGER';
    s.adsets[0].ads[0].creative.link = 'https://www.facebook.com/998877665544';
  }),
  {}
);

// an ad carrying no media at all: publish silently SKIPS it, so it has to be
// caught here or the user gets an ad set quietly short one ad
assert.deepEqual(Object.keys(v((s) => {
  const c = s.adsets[0].ads[0].creative;
  c.media_id = null;
  c.media_kind = null;
})), ['adsets[0].ads[0].creative.media']);

// required copy
assert.deepEqual(Object.keys(v((s) => { s.adsets[0].ads[0].creative.title = ' '; })),
  ['adsets[0].ads[0].creative.title']);
assert.deepEqual(Object.keys(v((s) => { s.adsets[0].ads[0].creative.body = ''; })),
  ['adsets[0].ads[0].creative.body']);
assert.deepEqual(Object.keys(v((s) => { s.name = ''; })), ['name']);
assert.deepEqual(Object.keys(v((s) => { s.adsets[0].name = ''; })), ['adsets[0].name']);

// budget floor, at whichever level owns the money
assert.deepEqual(Object.keys(v((s) => { s.adsets[0].daily_budget = 50; })),
  ['adsets[0].daily_budget']);
assert.deepEqual(Object.keys(v((s) => { s.adsets[0].daily_budget = null; })),
  ['adsets[0].daily_budget']);
assert.deepEqual(Object.keys(v((s) => {
  s.daily_budget = 50;
  s.adsets[0].daily_budget = null;
})), ['daily_budget']);
// a campaign budget means the ad set is not supposed to carry one
assert.deepEqual(v((s) => {
  s.daily_budget = 5000;
  s.adsets[0].daily_budget = null;
}), {});

// lifetime budget needs an end date, and it has to be after the start
assert.deepEqual(Object.keys(v((s) => {
  s.adsets[0].daily_budget = null;
  s.adsets[0].lifetime_budget = 50000;
})), ['adsets[0].end_time']);
assert.deepEqual(Object.keys(v((s) => {
  s.adsets[0].end_time = '2026-07-01T00:00:00Z';
})), ['adsets[0].end_time']);

// a declared special ad category needs the country whose rules apply
assert.deepEqual(Object.keys(v((s) => { s.special_ad_categories = ['HOUSING']; })),
  ['special_ad_category_country']);

// a pixel-promoting goal needs both halves of the promoted object
assert.deepEqual(
  Object.keys(v((s) => { s.adsets[0].optimization_goal = 'OFFSITE_CONVERSIONS'; })).sort(),
  [
    'adsets[0].promoted_object.custom_event_type',
    'adsets[0].promoted_object.pixel_id',
  ]
);

// a custom conversion answers the event on its own — it names the dataset AND
// the rule, so demanding custom_event_type beside it would block the only
// conversion an advertiser with no event code can optimize toward
assert.deepEqual(
  Object.keys(v((s) => {
    s.adsets[0].optimization_goal = 'OFFSITE_CONVERSIONS';
    s.adsets[0].promoted_object = { pixel_id: 'px1', custom_conversion_id: 'cc9' };
  })),
  []
);

// an ad promotes ONE post — naming a Facebook and an Instagram one is rejected
// here rather than at publish, where the campaign already exists
assert.deepEqual(
  Object.keys(v((s) => {
    const c = s.adsets[0].ads[0].creative;
    c.object_story_id = '1_2';
    c.source_instagram_media_id = 'ig9';
  })),
  ['adsets[0].ads[0].creative.object_story_id']
);

// an Instagram post satisfies a promoted-post ad on its own: the composed copy
// checks must not fire, because Meta ignores anything composed beside the post
assert.deepEqual(
  Object.keys(v((s) => {
    const c = s.adsets[0].ads[0].creative;
    c.source_instagram_media_id = 'ig9';
    c.title = '';
    c.body = '';
    c.media_id = null;
  })),
  []
);

// a capped bid strategy with no amount, and the ROAS floor keyed at the number
// the control renders rather than at the whole bid_constraints object
assert.deepEqual(Object.keys(v((s) => { s.adsets[0].bid_strategy = 'COST_CAP'; })),
  ['adsets[0].bid_amount']);

// carousel: card count, and every card's own media/headline/link
assert.deepEqual(Object.keys(v((s) => {
  const c = s.adsets[0].ads[0].creative;
  c.format = 'CAROUSEL';
  c.media_id = null;
  c.cards = [{ title: 'One', link: 'https://x.test', media_id: 'm1' }];
})), ['adsets[0].ads[0].creative.cards']);

assert.deepEqual(Object.keys(v((s) => {
  const c = s.adsets[0].ads[0].creative;
  c.format = 'CAROUSEL';
  c.media_id = null;
  c.cards = [
    { title: 'One', link: 'https://x.test', media_id: 'm1' },
    { title: '', link: '', media_id: null },
  ];
})).sort(), [
  'adsets[0].ads[0].creative.cards[1].link',
  'adsets[0].ads[0].creative.cards[1].media',
  'adsets[0].ads[0].creative.cards[1].title',
]);

// a boosted post carries its own copy, media and link — none of that applies
assert.deepEqual(v((s) => {
  const c = s.adsets[0].ads[0].creative;
  c.object_story_id = '998877665544_123';
  c.title = '';
  c.body = '';
  c.link = '';
  c.media_id = null;
}), {});

// ── Click-to-WhatsApp ────────────────────────────────────────────────────────
// Meta refuses the ad set at preflight when the Page has no number, creating
// nothing but costing the whole publish. Three states, and only one of them
// blocks — treating "could not read" as "no number" would refuse a campaign that
// publishes fine.
const onWhatsApp = (pageId: string) =>
  v((s) => {
    s.page_id = pageId;
    s.adsets[0].destination_type = 'WHATSAPP';
  });

assert.deepEqual(onWhatsApp('998877665544'), {});
assert.deepEqual(Object.keys(onWhatsApp('pg_unlinked')), ['page_id']);
assert.deepEqual(onWhatsApp('pg_unknown'), {});

// ...and an unlinked Page is fine everywhere the destination does not need it
assert.deepEqual(v((s) => { s.page_id = 'pg_unlinked'; }), {});

// Save is not blocked by it either — Meta only charges for this at publish
assert.deepEqual(
  validateSpec(
    (() => {
      const s = okSpec();
      s.page_id = 'pg_unlinked';
      s.adsets[0].destination_type = 'WHATSAPP';
      return s;
    })(),
    catalog,
    'pg_unlinked',
    'save'
  ),
  {}
);

// Save holds half-finished work: the two rules the server does not share (no
// media, link still on the Page) must not refuse it. Everything the server also
// enforces still does, because a Save carrying one fails either way.
const save = (mutate: (s: CampaignEditorSpec) => void) => {
  const s = okSpec();
  mutate(s);
  return validateSpec(s, catalog, s.page_id, 'save');
};
assert.deepEqual(save((s) => { s.adsets[0].ads[0].creative.media_id = null; }), {});
assert.deepEqual(save((s) => {
  s.adsets[0].ads[0].creative.link = 'https://www.facebook.com/998877665544';
}), {});
// ...but an empty link is a plain required field, and still blocks a Save
assert.deepEqual(Object.keys(save((s) => { s.adsets[0].ads[0].creative.link = ''; })),
  ['adsets[0].ads[0].creative.link']);
assert.deepEqual(Object.keys(save((s) => { s.name = ''; })), ['name']);

// UNLIKE the single-ad media check above, a carousel card with no media DOES
// block a Save — CarouselCard._card_has_media (backend) rejects it on every
// submit, save included, so letting the client wave it through only bought a
// round trip to the same error with no field to point it at.
assert.deepEqual(Object.keys(save((s) => {
  const c = s.adsets[0].ads[0].creative;
  c.format = 'CAROUSEL';
  c.media_id = null;
  c.cards = [
    { title: 'One', link: 'https://x.test', media_id: 'm1' },
    { title: 'Two', link: 'https://x.test', media_id: null },
  ];
})), ['adsets[0].ads[0].creative.cards[1].media']);

// Ads-only ("do it for me"): the editor renders ad set 0 alone and the server
// copies its ads onto the rest at submit. The hidden ad sets still carry the
// brief's media-less seed ads, so validating them flags a card that is not on
// screen — and CampaignEditor remaps `adsets[n]` onto `adsets[0]`, pinning an
// unclearable "no image" on the ad the user just filled and killing Continue.
const express = (() => {
  const s = okSpec();
  const hidden = structuredClone(s.adsets[0]);
  hidden.name = 'Acme | Broader Audience';
  hidden.ads[0].name = 'Acme | Broader Audience Ad 1';
  hidden.ads[0].creative.media_id = null;
  hidden.ads[0].creative.media_kind = null;
  s.adsets.push(hidden);
  return s;
})();

// the trap, spelled out: unsliced, the filled ad set 0 is fine and ad set 1 is not
assert.deepEqual(Object.keys(validateSpec(express, catalog, express.page_id)), [
  'adsets[1].ads[0].creative.media',
]);

// sliced to what is rendered, nothing blocks
assert.deepEqual(
  validateSpec(forValidation(express, true), catalog, express.page_id),
  {}
);

// guide/manual mode is untouched — same object, every ad set still checked
assert.equal(forValidation(express, false), express);

console.log('validateSpec ok');

// ── restoreFromLocked (the Autopilot toggle's re-lock) ──────────────────────
const adset = (n: number, adCount: number): CampaignEditorSpec['adsets'][number] => ({
  name: `Ad Set ${n}`,
  optimization_goal: 'goal',
  billing_event: 'IMPRESSIONS',
  destination_type: 'WEBSITE',
  bid_strategy: 'LOWEST_COST_WITHOUT_CAP',
  targeting: { original: true },
  start_time: '2026-01-01T00:00:00Z',
  ads: Array.from({ length: adCount }, (_, i) => ({
    name: `Ad ${i + 1}`,
    creative: creative({ title: `original ${i}` }),
  })),
});
const relockSpec = (adsetCount: number, adCount = 1): CampaignEditorSpec => ({
  name: 'Campaign',
  objective: 'OUTCOME_SALES',
  special_ad_categories: [],
  adsets: Array.from({ length: adsetCount }, (_, i) => adset(i, adCount)),
});

// Restores the server's campaign/ad-set shape (name, targeting, ad-set count)
// but keeps the LOCAL ad set 0's ads — the one thing express asks the user for.
const server = relockSpec(2);
const local = relockSpec(3);
local.name = 'Renamed while unlocked';
local.adsets[0].targeting = { edited: true };
local.adsets[0].ads[0].creative.title = 'edited copy';
const restored = restoreFromLocked(server, local);
assert.equal(restored.name, 'Campaign');
assert.equal(restored.adsets.length, 2);
assert.deepEqual(restored.adsets[0].targeting, { original: true });
assert.equal(restored.adsets[0].ads[0].creative.title, 'edited copy');

// Never mutates either input.
assert.equal(server.adsets[0].ads[0].creative.title, 'original 0');
assert.equal(local.adsets.length, 3);

console.log('restoreFromLocked ok');
