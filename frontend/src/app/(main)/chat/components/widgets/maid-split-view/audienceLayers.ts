import type { AudienceFilter, AudienceLayerRequest } from '@/types/chat';

// Pure model behind the audience layer builder. The panel edits a LayerDraft;
// everything here turns a draft into ONE thing the backend understands: a PATCH
// over the session's effective filter (nulls clear keys). The same patch shape
// drives both:
//   - the live PREVIEW (cumulative layers -> per-layer counts), and
//   - the COMMIT (the last layer's patch, byte for byte).
//
// The panel never REBUILDS a filter, it overlays one. Every filter key it does
// not edit (trend, cadence, dwell, anything added later) is therefore carried
// through by construction — preview and commit both apply the patch on top of
// the stored filter on the server, with the same function, so they cannot drift.

export type LayerMode = 'any' | 'all' | 'atLeast';
export type DaysPreset = 'any' | 'weekdays' | 'weekends';
export type VisitsScope = 'total' | 'each';
export type TrendKind = 'any' | 'started' | 'lapsed';

export type LayerDraft = {
  groups: string[]; // include, in layer order (poi group ids)
  mode: LayerMode; // any = union, all = intersection, atLeast = N of the groups
  atLeast: number; // N when mode === 'atLeast'
  exclude: string[];
  excludeEver: boolean; // exclude_window_days 0 ("never been") vs inherit the window
  windowDays: number | null;
  minVisits: number | null;
  visitsScope: VisitsScope;
  days: DaysPreset;
  dwellMin: number | null; // min_dwell_min: minutes on site per visit
  trend: TrendKind; // started = new visitors, lapsed = stopped coming
  trendRecent: number | null; // trend_recent_days (blank = the "Within" window)
  trendPrior: number | null; // trend_prior_days (blank = as long as the recent one)
  cadenceDays: number | null; // cadence_days: "comes every N days"
  cadenceTol: number | null; // cadence_tolerance_days (blank = 20%)
  // Settings the panel shows but has no control for, that the user removed.
  // Removal is all it can say about them: they go out as `null`, never a value.
  dropped: string[];
};

export const EMPTY_DRAFT: LayerDraft = {
  groups: [],
  mode: 'any',
  atLeast: 2,
  exclude: [],
  excludeEver: false,
  windowDays: null,
  minVisits: null,
  visitsScope: 'total',
  days: 'any',
  dwellMin: null,
  trend: 'any',
  trendRecent: null,
  trendPrior: null,
  cadenceDays: null,
  cadenceTol: null,
  dropped: [],
};

// A patch: a key set to null CLEARS it on the backend (its merge keeps any key
// a patch does not mention, so removing a layer must say so explicitly).
export type AudiencePatch = Record<string, unknown>;

// The filter keys the panel edits — it may set, change or clear these. Mirrors
// LAYER_BUILDER_KEYS in maid_store.py; a backend test pins the two together.
// Any other key can only be REMOVED (`dropped`), never given a value.
export const PANEL_KEYS = [
  'groups',
  'op',
  'min_distinct_groups',
  'exclude_groups',
  'exclude_window_days',
  'window_days',
  'min_visits',
  'min_visits_per_group',
  'days_of_week',
  'min_dwell_min',
  'trend',
  'trend_recent_days',
  'trend_prior_days',
  'cadence_days',
  'cadence_tolerance_days',
] as const;

const WEEKDAYS = [0, 1, 2, 3, 4];
const WEEKENDS = [5, 6];
const sameDays = (a: number[] | undefined, b: number[]) =>
  !!a && a.length === b.length && [...a].sort().join() === b.join();

// A filter value as the panel would re-send it: absent, null, [] and the
// default union operator all mean "not set"; day lists compare order-free.
const canon = (key: string, v: unknown): string => {
  if (v === undefined || v === null || (Array.isArray(v) && v.length === 0)) return 'null';
  if (key === 'op' && v === 'union') return 'null';
  if (key === 'days_of_week' && Array.isArray(v)) return JSON.stringify([...v].sort());
  return JSON.stringify(v);
};

// Why the builder cannot faithfully show this filter (null = it can). Rather
// than list the shapes it can't show, it asks the one question that matters:
// would committing what the panel shows CHANGE a value the panel owns? If the
// round trip draft -> patch doesn't reproduce a key exactly (a "first group
// only" operator, a custom set of days, "3+ in total" AND "3+ at each" at once,
// ...) the panel goes read-only instead of silently rewriting it. Keys the
// panel doesn't own can't trip this — they are never in the patch.
export function builderLimit(f: AudienceFilter | null | undefined): string | null {
  if (!f) return null;
  if (f.any_of?.length) return 'This audience combines several either/or conditions.';
  const roundTrip = draftToPatch(draftFromFilter(f));
  const drifted = PANEL_KEYS.filter((k) => canon(k, f[k]) !== canon(k, roundTrip[k]));
  return drifted.length
    ? 'Part of this audience is set in a way the panel can’t show exactly.'
    : null;
}

export function draftFromFilter(f: AudienceFilter | null | undefined): LayerDraft {
  if (!f) return { ...EMPTY_DRAFT };
  const groups = f.groups ?? [];
  const mode: LayerMode = f.min_distinct_groups
    ? 'atLeast'
    : f.op === 'intersection'
      ? 'all'
      : 'any';
  const each = !!f.min_visits_per_group;
  return {
    groups: [...groups],
    mode,
    atLeast: f.min_distinct_groups ?? Math.min(2, Math.max(groups.length, 2)),
    exclude: [...(f.exclude_groups ?? [])],
    excludeEver: f.exclude_window_days === 0,
    windowDays: f.window_days ?? null,
    minVisits: (each ? f.min_visits_per_group : f.min_visits) ?? null,
    visitsScope: each ? 'each' : 'total',
    days: sameDays(f.days_of_week, WEEKDAYS) ? 'weekdays' : sameDays(f.days_of_week, WEEKENDS) ? 'weekends' : 'any',
    dwellMin: f.min_dwell_min ?? null,
    // any other value ("sideways") reads as none, so the round trip flags it
    trend: f.trend === 'started' || f.trend === 'lapsed' ? f.trend : 'any',
    trendRecent: f.trend_recent_days ?? null,
    trendPrior: f.trend_prior_days ?? null,
    cadenceDays: f.cadence_days ?? null,
    cadenceTol: f.cadence_tolerance_days ?? null,
    dropped: [],
  };
}

const clampAtLeast = (d: LayerDraft) => Math.max(2, Math.min(d.atLeast, d.groups.length));

const OWNED: readonly string[] = PANEL_KEYS;

// The keys the builder owns, every one present (null = cleared), plus a null for
// each setting the user removed — the COMMIT.
export function draftToPatch(d: LayerDraft): AudiencePatch {
  const multi = d.groups.length > 1;
  // "at each place" only means something across 2+ named groups; with one (or
  // none) it is the same as a plain total, and the backend would ignore it.
  const each = d.visitsScope === 'each' && multi;
  // Removals first, so an owned key can never be overridden by one of them.
  const removed = Object.fromEntries(d.dropped.filter((k) => !OWNED.includes(k)).map((k) => [k, null]));
  return {
    ...removed,
    groups: d.groups.length ? d.groups : null,
    op: d.mode === 'all' && multi ? 'intersection' : null,
    min_distinct_groups: d.mode === 'atLeast' && multi ? clampAtLeast(d) : null,
    exclude_groups: d.exclude.length ? d.exclude : null,
    exclude_window_days: d.exclude.length && d.excludeEver ? 0 : null,
    window_days: d.windowDays,
    min_visits: d.minVisits && !each ? d.minVisits : null,
    min_visits_per_group: d.minVisits && each ? d.minVisits : null,
    days_of_week: d.days === 'weekdays' ? WEEKDAYS : d.days === 'weekends' ? WEEKENDS : null,
    min_dwell_min: d.dwellMin || null,
    trend: d.trend === 'any' ? null : d.trend,
    trend_recent_days: d.trendRecent || null,
    trend_prior_days: d.trendPrior || null,
    cadence_days: d.cadenceDays || null,
    cadence_tolerance_days: d.cadenceTol || null,
  };
}

export const isDirty = (current: AudienceFilter | null | undefined, d: LayerDraft) =>
  JSON.stringify(draftToPatch(draftFromFilter(current))) !== JSON.stringify(draftToPatch(d));

export const groupLabel = (id: string, keyOf?: (id: string) => string | undefined) =>
  keyOf?.(id) ?? (id.includes(':') ? id.slice(id.indexOf(':') + 1) : id);

// Layers shown down the panel: each is the FULL filter up to that point, so its
// count is exactly what the audience would be if the user stopped there — the
// user watches the number fall (or grow, for "any") as they build, instead of
// discovering zero at the end. The last layer is always the whole draft.
export function layersFor(
  d: LayerDraft,
  label: (id: string) => string = (id) => groupLabel(id)
): AudienceLayerRequest[] {
  const layers: AudienceLayerRequest[] = [];
  const push = (name: string, spec: AudiencePatch) => {
    const prev = layers[layers.length - 1];
    if (prev && JSON.stringify(prev.patches[0]) === JSON.stringify(spec)) return;
    layers.push({ label: name, patches: [spec] });
  };

  // Removed settings are gone from EVERY layer — they are not part of the
  // audience being built, so no step's count may still include them.
  const bare: LayerDraft = { ...EMPTY_DRAFT, mode: d.mode, atLeast: d.atLeast, days: 'any', dropped: d.dropped };
  // Progressive group steps only read honestly for any/all: "any 3 of 2 groups"
  // is not a thing, so an N-of-M draft is one layer over every group.
  const progressive = d.mode !== 'atLeast' && d.groups.length > 1 && d.groups.length <= 5;
  if (progressive) {
    d.groups.forEach((_, i) => {
      const sub = d.groups.slice(0, i + 1);
      push(
        i === 0 ? label(sub[0]) : `${d.mode === 'all' ? '+' : 'or'} ${label(sub[i])}`,
        draftToPatch({ ...bare, groups: sub })
      );
    });
  } else if (d.groups.length) {
    push(
      d.mode === 'atLeast' && d.groups.length > 1
        ? `Any ${clampAtLeast(d)} of ${d.groups.length} places`
        : d.groups.map((g) => label(g)).join(d.mode === 'all' ? ' + ' : ' or '),
      draftToPatch({ ...bare, groups: d.groups })
    );
  } else {
    push('All places', draftToPatch(bare));
  }

  if (d.exclude.length) {
    push(
      `Excluding ${d.exclude.map((g) => label(g)).join(', ')}`,
      draftToPatch({ ...bare, groups: d.groups, exclude: d.exclude, excludeEver: d.excludeEver })
    );
  }
  push('With your visit rules', draftToPatch(d));
  return layers;
}

export type RescueOption = { key: string; label: string; draft: LayerDraft };

// What to offer when the audience collapses below what can run. Every option is
// a FREE re-filter of rows already bought — there is deliberately no "add more
// places" rung here: that is a new vendor purchase against the shared budget,
// and the panel must not present it as free like the others.
export function rescueOptions(
  d: LayerDraft,
  label: (id: string) => string = (id) => groupLabel(id)
): RescueOption[] {
  const out: RescueOption[] = [];
  const n = d.groups.length;
  if (d.mode === 'all' && n >= 3) {
    out.push({ key: 'n-1', label: `Any ${n - 1} of the ${n}`, draft: { ...d, mode: 'atLeast', atLeast: n - 1 } });
  } else if (d.mode === 'all' && n === 2) {
    out.push({ key: 'either', label: 'Either one', draft: { ...d, mode: 'any' } });
  }
  if (n >= 2) {
    const last = d.groups[n - 1];
    out.push({ key: 'drop-last', label: `Drop ${label(last)}`, draft: { ...d, groups: d.groups.slice(0, -1) } });
  }
  if (d.windowDays) {
    out.push({ key: 'no-window', label: `Any time, not just ${d.windowDays} days`, draft: { ...d, windowDays: null } });
  }
  if (d.minVisits && d.minVisits > 1) {
    out.push({ key: 'fewer-visits', label: `${d.minVisits - 1}+ visits instead of ${d.minVisits}`, draft: { ...d, minVisits: d.minVisits - 1 } });
  } else if (d.minVisits === 1) {
    out.push({ key: 'no-visits', label: 'Drop the visit minimum', draft: { ...d, minVisits: null } });
  }
  if (d.days !== 'any') {
    out.push({ key: 'any-day', label: 'Any day of the week', draft: { ...d, days: 'any' } });
  }
  if (d.trend !== 'any') {
    out.push({ key: 'no-trend', label: 'Ignore who started or stopped visiting', draft: { ...d, trend: 'any', trendRecent: null, trendPrior: null } });
  }
  if (d.cadenceDays) {
    out.push({ key: 'no-cadence', label: `Drop the every-${d.cadenceDays}-days pattern`, draft: { ...d, cadenceDays: null, cadenceTol: null } });
  }
  if (d.dwellMin) {
    out.push({ key: 'no-dwell', label: 'Any time on site', draft: { ...d, dwellMin: null } });
  }
  if (d.exclude.length) {
    out.push({ key: 'no-exclude', label: 'Keep the visitors I excluded', draft: { ...d, exclude: [], excludeEver: false } });
  }
  return out.slice(0, 4);
}

// The one-line, human sentence for a visits rule — the same number means a
// different thing depending on whether places are named, and the panel must
// say which (a bare "3+ visits" hides a real difference).
export function visitsSentence(d: LayerDraft): string | null {
  if (!d.minVisits) return null;
  if (d.groups.length === 0) return `${d.minVisits}+ visits to the same place`;
  if (d.groups.length > 1 && d.visitsScope === 'each') return `${d.minVisits}+ visits at each of these places`;
  return `${d.minVisits}+ visits in total across these places`;
}

// A repeat interval borrows the visits number: it needs (visits - 1) gaps close
// to the interval, defaulting to 2. Say so, because the same field means
// something else without an interval.
export function cadenceSentence(d: LayerDraft): string | null {
  if (!d.cadenceDays) return null;
  const gaps = Math.max(1, (d.minVisits ?? 3) - 1);
  return `Needs at least ${gaps} ${gaps === 1 ? 'gap' : 'gaps'} of about ${d.cadenceDays} days between visits${d.minVisits ? ` (your ${d.minVisits}+ visits, minus one)` : ''}`;
}
