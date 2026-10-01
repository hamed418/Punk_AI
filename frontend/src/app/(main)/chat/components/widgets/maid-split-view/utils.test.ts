import { describe, expect, it } from 'vitest';
import type { MaidSplitViewData } from '@/types/chat';
import type { Competitor } from './types';
import { computeDynamicMetric, mergeAndSortCompetitors } from './utils';

// Regression: the "Unique Visitors" headline used to be a client-side sum of
// per-POI audience_count, which double-counts a device seen at two POIs
// sharing one purchase (same coordinates+radius) — the sum grows past the
// backend's deduped maid_count with every POI on screen, and drifted from
// the number the narrator quoted in chat for the exact same audience.

const content = (over: Partial<MaidSplitViewData>) =>
  ({
    action_type: 'maid_split_view',
    pois: [],
    maid_observations: [],
    center: { lat: 0, lng: 0 },
    maid_count: 0,
    ...over,
  }) as MaidSplitViewData;

describe('computeDynamicMetric', () => {
  it('total_devices reads content.maid_count, never a sum over POIs', () => {
    // Two POIs whose audience_count sums to 1,900 — well past the backend's
    // deduped total of 1,240 (they share visitors).
    const c = content({ maid_count: 1240 });
    expect(computeDynamicMetric(c, 'total_devices')).toEqual({
      value: '1,240',
      label: 'Unique Visitors',
    });
  });

  it('falls back to visit_stats.total_devices only when maid_count is absent', () => {
    const c = content({
      maid_count: undefined as unknown as number,
      visit_stats: { basis: 'visits', total_devices: 420, buckets: {}, repeat_visitor_count: 0, repeat_visitor_pct: 0, max_seen: 0 },
    });
    expect(computeDynamicMetric(c, 'total_devices').value).toBe('420');
  });

  it('repeat_visitor_count reads the whole-audience visit_stats, not a per-POI sum', () => {
    const c = content({
      maid_count: 1240,
      visit_stats: { basis: 'visits', total_devices: 1240, buckets: {}, repeat_visitor_count: 420, repeat_visitor_pct: 34, max_seen: 6 },
    });
    expect(computeDynamicMetric(c, 'repeat_visitor_count')).toEqual({
      value: '420',
      label: 'Repeat Visitors',
    });
  });

  it('repeat_visitor_pct reads the backend percentage, not an unweighted mean of per-POI percentages', () => {
    const c = content({
      maid_count: 1240,
      visit_stats: { basis: 'visits', total_devices: 1240, buckets: {}, repeat_visitor_count: 420, repeat_visitor_pct: 34, max_seen: 6 },
    });
    expect(computeDynamicMetric(c, 'repeat_visitor_pct')).toEqual({
      value: '34%',
      label: 'Repeat Percentage',
    });
  });

  it('max_seen reads the backend max, defaulting to 0x when absent', () => {
    expect(computeDynamicMetric(content({}), 'max_seen')).toEqual({
      value: '0x',
      label: 'Max Frequency',
    });
  });

  it('total_devices renders an em dash when neither field is present', () => {
    const c = content({ maid_count: undefined as unknown as number });
    expect(computeDynamicMetric(c, 'total_devices').value).toBe('—');
  });
});

describe('mergeAndSortCompetitors', () => {
  // Regression: attribute_audience stamps audience_count on EVERY call but
  // visit_stats only when stamp_stats=True, so a POI can legitimately carry
  // a real audience_count with no visit_stats at all (legacy data, a partial
  // recompute). The row itself displays audience_count ?? visit_stats?.
  // total_devices — the sort must use the exact same fallback, or a POI with
  // a real, large audience_count sorts to the bottom as if it were empty.
  const c = (over: Partial<Competitor>): Competitor => ({
    id: over.id ?? 'x',
    type: 'POI',
    content: '',
    lat: 0,
    lng: 0,
    ...over,
  });

  it('total_devices sort falls back to audience_count when visit_stats is absent', () => {
    const busy = c({ id: 'busy', audience_count: 900 }); // no visit_stats at all
    const quiet = c({
      id: 'quiet',
      visit_stats: { basis: 'visits', total_devices: 5, buckets: {}, repeat_visitor_count: 0, repeat_visitor_pct: 0, max_seen: 0 },
    });
    const sorted = mergeAndSortCompetitors([quiet, busy], [], [], 'total_devices');
    expect(sorted.map((x) => x.id)).toEqual(['busy', 'quiet']);
  });

  it('total_devices sort prefers audience_count over visit_stats.total_devices when both are present', () => {
    // audience_count and visit_stats.total_devices are normally the same
    // number for one POI's own rows — when they somehow differ, the sort
    // must agree with what the row displays (audience_count first).
    const a = c({
      id: 'a', audience_count: 50,
      visit_stats: { basis: 'visits', total_devices: 10, buckets: {}, repeat_visitor_count: 0, repeat_visitor_pct: 0, max_seen: 0 },
    });
    const b = c({
      id: 'b', audience_count: 20,
      visit_stats: { basis: 'visits', total_devices: 30, buckets: {}, repeat_visitor_count: 0, repeat_visitor_pct: 0, max_seen: 0 },
    });
    const sorted = mergeAndSortCompetitors([b, a], [], [], 'total_devices');
    expect(sorted.map((x) => x.id)).toEqual(['a', 'b']);
  });
});
