import { describe, expect, it } from 'vitest';
import type { AudienceFilter } from '@/types/chat';
import {
  EMPTY_DRAFT,
  PANEL_KEYS,
  builderLimit,
  cadenceSentence,
  draftFromFilter,
  draftToPatch,
  isDirty,
  layersFor,
  rescueOptions,
  visitsSentence,
  type LayerDraft,
} from './audienceLayers';

const G = ['category:gym', 'category:cafe', 'category:salon'];
const d = (over: Partial<LayerDraft>): LayerDraft => ({ ...EMPTY_DRAFT, ...over });

// The backend fold, in miniature: a patch key set to null CLEARS it, any other
// key overwrites, and every key the patch doesn't mention is left as it was.
const overlay = (base: AudienceFilter, patch: Record<string, unknown>) => {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(patch)) {
    if (v === null) delete out[k];
    else out[k] = v;
  }
  return out;
};

describe('draft <-> filter', () => {
  it('round-trips the filter keys the builder owns', () => {
    const f = {
      groups: G,
      min_distinct_groups: 2,
      exclude_groups: ['category:bar'],
      exclude_window_days: 0,
      window_days: 30,
      min_visits_per_group: 3,
      days_of_week: [5, 6],
    };
    const draft = draftFromFilter(f);
    expect(draft).toMatchObject({ mode: 'atLeast', atLeast: 2, excludeEver: true, visitsScope: 'each', days: 'weekends' });
    const nonNull = Object.fromEntries(Object.entries(draftToPatch(draft)).filter(([, v]) => v !== null));
    expect(nonNull).toEqual(f);
  });

  it('round-trips dwell, trend (with its windows) and cadence (with its tolerance)', () => {
    const f = {
      groups: [G[0]],
      min_dwell_min: 45,
      trend: 'lapsed',
      trend_recent_days: 14,
      trend_prior_days: 60,
      cadence_days: 7,
      cadence_tolerance_days: 1,
    };
    const draft = draftFromFilter(f);
    expect(draft).toMatchObject({ dwellMin: 45, trend: 'lapsed', trendRecent: 14, trendPrior: 60, cadenceDays: 7, cadenceTol: 1 });
    const nonNull = Object.fromEntries(Object.entries(draftToPatch(draft)).filter(([, v]) => v !== null));
    expect(nonNull).toEqual(f);
  });

  it('"no pattern" clears the trend; a blank field clears its key', () => {
    const patch = draftToPatch(d({ groups: [G[0]], trend: 'any', dwellMin: null, cadenceDays: null }));
    expect(patch).toMatchObject({ trend: null, min_dwell_min: null, cadence_days: null, cadence_tolerance_days: null });
  });

  it('a patch names every owned key, null = cleared', () => {
    const patch = draftToPatch(d({ groups: [G[0]], windowDays: 30 }));
    expect(Object.keys(patch).sort()).toEqual([...PANEL_KEYS].sort());
    expect(patch).toMatchObject({
      groups: [G[0]],
      window_days: 30,
      op: null,
      min_distinct_groups: null,
      exclude_groups: null,
      exclude_window_days: null,
      min_visits: null,
      min_visits_per_group: null,
      days_of_week: null,
    });
  });

  it('never sends an operator that would silently be a union', () => {
    // intersection over ONE group is meaningless and the backend degrades it
    expect(draftToPatch(d({ groups: [G[0]], mode: 'all' })).op).toBeNull();
    expect(draftToPatch(d({ groups: [], mode: 'all' })).op).toBeNull();
    expect(draftToPatch(d({ groups: G.slice(0, 2), mode: 'all' })).op).toBe('intersection');
  });

  it('"at each place" is only sent across 2+ groups (elsewhere it is a no-op)', () => {
    const one = draftToPatch(d({ groups: [G[0]], minVisits: 3, visitsScope: 'each' }));
    expect(one).toMatchObject({ min_visits: 3, min_visits_per_group: null });
    const two = draftToPatch(d({ groups: G.slice(0, 2), minVisits: 3, visitsScope: 'each' }));
    expect(two).toMatchObject({ min_visits: null, min_visits_per_group: 3 });
  });

  it('clamps "at least N" into 2..number of groups', () => {
    expect(draftToPatch(d({ groups: G, mode: 'atLeast', atLeast: 9 })).min_distinct_groups).toBe(3);
    expect(draftToPatch(d({ groups: G, mode: 'atLeast', atLeast: 1 })).min_distinct_groups).toBe(2);
  });

  it('exclude_window_days: absent inherits, 0 means ever', () => {
    const inherit = draftToPatch(d({ exclude: ['category:bar'], excludeEver: false }));
    const ever = draftToPatch(d({ exclude: ['category:bar'], excludeEver: true }));
    expect(inherit.exclude_window_days).toBeNull();
    expect(ever.exclude_window_days).toBe(0);
    // no exclusion -> no window either
    expect(draftToPatch(d({ excludeEver: true })).exclude_window_days).toBeNull();
  });

  it('isDirty ignores no-op differences', () => {
    const f = { groups: [G[0]], window_days: 7 };
    expect(isDirty(f, draftFromFilter(f))).toBe(false);
    expect(isDirty(f, d({ groups: [G[0]], windowDays: 30 }))).toBe(true);
    expect(isDirty(null, EMPTY_DRAFT)).toBe(false);
  });
});

describe('builderLimit — the panel edits only what it can reproduce exactly', () => {
  it('is editable for filters it can round-trip', () => {
    expect(builderLimit(null)).toBeNull();
    expect(builderLimit({})).toBeNull();
    expect(builderLimit({ groups: G, min_distinct_groups: 2 })).toBeNull();
    expect(builderLimit({ groups: G.slice(0, 2), op: 'intersection', min_visits_per_group: 3, window_days: 30 })).toBeNull();
    expect(builderLimit({ groups: [G[0]], exclude_groups: ['category:bar'], exclude_window_days: 0 })).toBeNull();
    expect(builderLimit({ days_of_week: [6, 5] })).toBeNull(); // order-free
    expect(builderLimit({ op: 'union', groups: G })).toBeNull(); // explicit default
  });

  it('a filter with keys the panel does not own stays EDITABLE — they ride through, they are not rewritten', () => {
    expect(builderLimit({ hours: [6, 9], min_share_in_scope: 0.5, dwell_bound: 'upper' })).toBeNull();
    expect(builderLimit({ min_weekly_hours: 30, invert: true, some_future_key: { nested: 1 } })).toBeNull();
  });

  it('dwell, trend and cadence are the panel’s own now, so they are editable too', () => {
    expect(builderLimit({ groups: [G[0]], trend: 'lapsed', window_days: 60 })).toBeNull();
    expect(builderLimit({ min_dwell_min: 180, cadence_days: 14, cadence_tolerance_days: 2 })).toBeNull();
    expect(builderLimit({ trend: 'started', trend_recent_days: 7, trend_prior_days: 90 })).toBeNull();
  });

  it('goes read-only when committing would CHANGE a value the panel owns', () => {
    const unshowable: AudienceFilter[] = [
      { any_of: [{ groups: G }] },
      { op: 'difference', groups: G.slice(0, 2) }, // "first group only"
      { days_of_week: [1, 3] }, // custom days
      { exclude_groups: ['category:bar'], exclude_window_days: 14 }, // custom exclusion window
      { groups: G, min_visits: 3, min_visits_per_group: 3 }, // both scopes at once
      { groups: G, op: 'intersection', min_distinct_groups: 2 }, // both operators at once
      { groups: G.slice(0, 2), min_distinct_groups: 5 }, // N larger than the group list
      { groups: [G[0]], op: 'intersection' }, // intersection over one group
      { trend: 'sideways' }, // a trend the panel has no option for
    ];
    for (const f of unshowable) expect(builderLimit(f), JSON.stringify(f)).toBeTruthy();
  });

  it('for every editable filter, committing what the panel shows is a no-op on the whole filter', () => {
    const editable: AudienceFilter[] = [
      { groups: G, min_distinct_groups: 2, window_days: 30, trend: 'lapsed', trend_recent_days: 14 },
      { groups: G.slice(0, 2), op: 'intersection', min_visits_per_group: 3, min_confidence: 'confirmed' },
      { exclude_groups: ['category:bar'], exclude_window_days: 0, min_dwell_min: 60, days_of_week: [0, 1, 2, 3, 4] },
      { min_visits: 4, cadence_days: 7, cadence_tolerance_days: 1, invert: true },
      { hours: [6, 9], min_weekly_hours: 30, exclude_flags: 4, dwell_bound: 'upper' },
    ];
    for (const f of editable) {
      expect(builderLimit(f), JSON.stringify(f)).toBeNull();
      // overlaying the patch the panel would send leaves the filter unchanged,
      // unowned keys included — this is the property that closes the hole.
      const after = overlay(f, draftToPatch(draftFromFilter(f)));
      expect(after, JSON.stringify(f)).toEqual(f);
    }
  });

  it('an edit changes only what the user changed and carries every other key', () => {
    const f: AudienceFilter = { groups: [G[0]], trend: 'lapsed', min_dwell_min: 180 };
    const next = overlay(f, draftToPatch({ ...draftFromFilter(f), windowDays: 30 }));
    expect(next).toEqual({ groups: [G[0]], trend: 'lapsed', min_dwell_min: 180, window_days: 30 });
  });

  it('PANEL_KEYS is exactly the set of keys a patch carries', () => {
    expect(Object.keys(draftToPatch(EMPTY_DRAFT)).sort()).toEqual([...PANEL_KEYS].sort());
  });
});

describe('removing a setting the panel has no control for', () => {
  const carried: AudienceFilter = { groups: [G[0]], hours: [6, 9], min_weekly_hours: 30, min_dwell_min: 20 };

  it('sends a null for exactly the removed keys and nothing else new', () => {
    const patch = draftToPatch({ ...draftFromFilter(carried), dropped: ['hours'] });
    expect(patch.hours).toBeNull();
    expect('min_weekly_hours' in patch).toBe(false); // kept: not mentioned, so it rides through
    expect(overlay(carried, patch)).toEqual({ groups: [G[0]], min_weekly_hours: 30, min_dwell_min: 20 });
  });

  it('a removal can never override a key the panel owns', () => {
    const draft = d({ groups: [G[0]], windowDays: 30, dropped: ['window_days', 'groups'] });
    const patch = draftToPatch(draft);
    expect(patch).toMatchObject({ window_days: 30, groups: [G[0]] });
    expect(Object.keys(patch).sort()).toEqual([...PANEL_KEYS].sort()); // no extra key from `dropped`
  });

  it('makes the draft dirty, and Reset (a fresh draft) makes it clean again', () => {
    expect(isDirty(carried, { ...draftFromFilter(carried), dropped: ['hours'] })).toBe(true);
    expect(isDirty(carried, draftFromFilter(carried))).toBe(false);
  });

  it('is applied in EVERY layer, so no step still counts what the user removed', () => {
    const draft = { ...d({ groups: G, mode: 'all', windowDays: 30 }), dropped: ['hours'] };
    const layers = layersFor(draft);
    expect(layers.length).toBeGreaterThan(1);
    for (const l of layers) expect(l.patches[0].hours, l.label).toBeNull();
    expect(layers[layers.length - 1].patches).toEqual([draftToPatch(draft)]);
  });

  it('a rescue option keeps the removals', () => {
    const opts = rescueOptions({ ...d({ groups: G, mode: 'all' }), dropped: ['hours'] });
    for (const o of opts) expect(draftToPatch(o.draft).hours).toBeNull();
  });
});

describe('dwell, trend and cadence in layers and rescues', () => {
  it('appear only in the final layer, so the earlier steps stay the plain place funnel', () => {
    const draft = d({ groups: G, mode: 'all', dwellMin: 30, trend: 'lapsed', cadenceDays: 7 });
    const layers = layersFor(draft);
    for (const l of layers.slice(0, -1)) {
      expect(l.patches[0]).toMatchObject({ min_dwell_min: null, trend: null, cadence_days: null });
    }
    expect(layers[layers.length - 1].patches[0]).toMatchObject({ min_dwell_min: 30, trend: 'lapsed', cadence_days: 7 });
  });

  it('offers to drop each, as a free re-filter', () => {
    const opts = rescueOptions(d({ groups: [G[0]], dwellMin: 30, trend: 'lapsed', trendRecent: 14, cadenceDays: 7, cadenceTol: 1 }));
    const by = Object.fromEntries(opts.map((o) => [o.key, o.draft]));
    expect(by['no-trend']).toMatchObject({ trend: 'any', trendRecent: null, trendPrior: null });
    expect(by['no-cadence']).toMatchObject({ cadenceDays: null, cadenceTol: null });
    expect(by['no-dwell']).toMatchObject({ dwellMin: null });
  });

  it('cadenceSentence says the visits number is reused, and by how much', () => {
    expect(cadenceSentence(d({}))).toBeNull();
    expect(cadenceSentence(d({ cadenceDays: 7 }))).toBe('Needs at least 2 gaps of about 7 days between visits');
    expect(cadenceSentence(d({ cadenceDays: 7, minVisits: 4 }))).toContain('at least 3 gaps');
    expect(cadenceSentence(d({ cadenceDays: 7, minVisits: 1 }))).toContain('at least 1 gap ');
  });
});

describe('layersFor', () => {
  it('an "all" draft builds up one group at a time, ending on the whole draft', () => {
    const draft = d({ groups: G, mode: 'all', windowDays: 30 });
    const layers = layersFor(draft, (id) => id.split(':')[1]);
    expect(layers.map((l) => l.label)).toEqual(['gym', '+ cafe', '+ salon', 'With your visit rules']);
    expect(layers[0].patches[0]).toMatchObject({ groups: [G[0]], op: null });
    expect(layers[1].patches[0]).toMatchObject({ groups: G.slice(0, 2), op: 'intersection' });
  });

  it('the LAST layer is the commit patch, byte for byte — preview and Apply cannot disagree', () => {
    const drafts = [
      d({ groups: G, mode: 'all', windowDays: 30 }),
      d({ groups: G, mode: 'atLeast', atLeast: 2, minVisits: 3, visitsScope: 'each', days: 'weekends' }),
      d({ groups: [G[0]], exclude: ['category:bar'], excludeEver: true }),
      d({}),
    ];
    for (const draft of drafts) {
      const layers = layersFor(draft);
      expect(layers[layers.length - 1].patches).toEqual([draftToPatch(draft)]);
    }
  });

  it('an N-of-M draft is one layer, never a misleading "any 3 of 2"', () => {
    const layers = layersFor(d({ groups: G, mode: 'atLeast', atLeast: 2 }));
    expect(layers).toHaveLength(1);
    expect(layers[0].label).toBe('Any 2 of 3 places');
    expect(layers[0].patches[0]).toMatchObject({ groups: G, min_distinct_groups: 2 });
  });

  it('adds an exclusion layer that carries its own window', () => {
    const layers = layersFor(d({ groups: [G[0]], exclude: ['category:bar'], excludeEver: true }));
    const excl = layers.find((l) => l.label.startsWith('Excluding'));
    expect(excl?.patches[0]).toMatchObject({ exclude_groups: ['category:bar'], exclude_window_days: 0 });
  });

  it('layers CLEAR the owned keys they leave out, so each is the filter up to that step', () => {
    const [first] = layersFor(d({ groups: G, mode: 'all', windowDays: 30, minVisits: 3 }));
    expect(first.patches[0]).toMatchObject({ window_days: null, min_visits: null, days_of_week: null });
  });

  it('an empty draft is one layer that clears every owned key', () => {
    expect(layersFor(EMPTY_DRAFT)).toEqual([{ label: 'All places', patches: [draftToPatch(EMPTY_DRAFT)] }]);
  });

  it('never exceeds the backend cost cap of 8 layers', () => {
    const many = Array.from({ length: 12 }, (_, i) => `category:g${i}`);
    expect(layersFor(d({ groups: many, mode: 'all', windowDays: 7, exclude: ['category:x'] })).length).toBeLessThanOrEqual(8);
  });
});

describe('rescueOptions', () => {
  it('offers "any N-1 of N" first when an all-of-3 collapses', () => {
    const opts = rescueOptions(d({ groups: G, mode: 'all' }), (id) => id.split(':')[1]);
    expect(opts[0]).toMatchObject({ key: 'n-1', label: 'Any 2 of the 3' });
    expect(opts[0].draft).toMatchObject({ mode: 'atLeast', atLeast: 2 });
    expect(opts.map((o) => o.label)).toContain('Drop salon');
  });

  it('only offers re-filters of data already bought — never a paid "add places" rung', () => {
    const opts = rescueOptions(d({ groups: G, mode: 'all', windowDays: 30, minVisits: 3, days: 'weekends', exclude: ['category:bar'] }));
    expect(opts).toHaveLength(4);
    for (const o of opts) expect(o.label).not.toMatch(/add|widen|metro|more places/i);
  });

  it('has nothing to relax on an already-minimal draft', () => {
    expect(rescueOptions(d({ groups: [G[0]] }))).toEqual([]);
  });
});

describe('visitsSentence', () => {
  it('says which count the number is', () => {
    expect(visitsSentence(d({ minVisits: 3 }))).toBe('3+ visits to the same place');
    expect(visitsSentence(d({ groups: G, minVisits: 3 }))).toBe('3+ visits in total across these places');
    expect(visitsSentence(d({ groups: G, minVisits: 3, visitsScope: 'each' }))).toBe('3+ visits at each of these places');
    expect(visitsSentence(d({}))).toBeNull();
  });
});
