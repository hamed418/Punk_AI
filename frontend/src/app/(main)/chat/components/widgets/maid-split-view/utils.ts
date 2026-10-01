import type { MaidSplitViewData, PoiItem } from '@/types/chat';
import type { PlaceItem } from '../WidgetMapAddressSearch';
import type { Competitor, ParsedUserResponse, SortOption } from './types';

export function getPoiId(
  p: {
    id?: string | number;
    place_id?: string;
    name?: string;
    type?: string;
    displayName?: { text?: string };
    formattedAddress?: string;
    formatted_address?: string;
    lat?: number;
    latitude?: number;
    lng?: number;
    longitude?: number;
    location?: { latitude?: number; longitude?: number };
  },
  fallbackIdx?: number
): string {
  if (p.id !== undefined && p.id !== null && p.id !== '') return String(p.id);
  if (p.place_id !== undefined && p.place_id !== null && p.place_id !== '')
    return String(p.place_id);
  const lat = p.lat ?? p.latitude ?? p.location?.latitude;
  const lng = p.lng ?? p.longitude ?? p.location?.longitude;
  const rawName =
    p.name ||
    p.displayName?.text ||
    p.type ||
    p.formattedAddress ||
    p.formatted_address ||
    '';
  const name = rawName.trim().toLowerCase().replace(/\s+/g, '-');

  if (
    typeof lat === 'number' &&
    typeof lng === 'number' &&
    (lat !== 0 || lng !== 0)
  ) {
    const coordStr = `${lat.toFixed(5)}-${lng.toFixed(5)}`;
    return name ? `poi-${name}-${coordStr}` : `poi-${coordStr}`;
  }
  return `poi-idx-${fallbackIdx ?? 0}`;
}

// `basis` comes from visit_stats.basis: 'visits' means timestamped (distinct
// days = real visits); 'sightings' means raw GPS pings, where six pings can be
// one afternoon — so it must not claim six visits.
export function getRangeText(
  minIdx: number,
  maxIdx: number,
  basis?: string
): string {
  const labels = ['1', '2', '3-5', '6+'];
  const verb = basis === 'sightings' ? 'WERE SEEN' : 'VISITED';
  const minL = labels[minIdx];
  const maxL = labels[maxIdx];
  if (minL === maxL) {
    return `PEOPLE WHO ${verb} ${minL} TIME${minL === '1' ? '' : 'S'}`;
  }
  return `PEOPLE WHO ${verb} ${minL} TO ${maxL} TIMES`;
}

export function parseUserResponse(
  userResponse: string | null | undefined
): ParsedUserResponse | null {
  if (!userResponse) return null;
  try {
    let answerStr = userResponse;
    if (userResponse.includes('\nA: ')) {
      answerStr = userResponse.split('\nA: ')[1];
    } else if (userResponse.includes('A: ')) {
      answerStr = userResponse.split('A: ')[1];
    }
    answerStr = answerStr.trim();
    if (answerStr.startsWith('{')) {
      return JSON.parse(answerStr) as ParsedUserResponse;
    }
  } catch (e) {
    console.error('Failed to parse userResponse in WidgetMaidSplitView', e);
  }
  return null;
}

export function buildInitialCompetitors(
  points: PoiItem[],
  parsedUserResponse: ParsedUserResponse | null
): Competitor[] {
  let base: Competitor[] = points.map((p, idx) => ({
    id: getPoiId(p, idx),
    type: p.name || 'POI',
    content: p.parent_location || 'Point of Interest',
    lat: Number(p.lat ?? p.latitude ?? p.location?.latitude ?? 0),
    lng: Number(p.lng ?? p.longitude ?? p.location?.longitude ?? 0),
    audience_count: p.audience_count,
    visit_stats: p.visit_stats,
  }));

  if (parsedUserResponse?.removed && parsedUserResponse.removed.length > 0) {
    const removedSet = parsedUserResponse.removed;
    base = base.filter((c) => {
      return !removedSet.some((r) => {
        if (r.id && (c.id === String(r.id) || String(c.id) === String(r.id)))
          return true;
        if (
          typeof r.lat === 'number' &&
          typeof r.lng === 'number' &&
          typeof c.lat === 'number' &&
          typeof c.lng === 'number' &&
          Math.abs(c.lat - r.lat) < 0.00001 &&
          Math.abs(c.lng - r.lng) < 0.00001
        ) {
          return true;
        }
        return false;
      });
    });
  }

  if (parsedUserResponse?.added && parsedUserResponse.added.length > 0) {
    const addedItems: Competitor[] = parsedUserResponse.added.map(
      (a, idx) => ({
        id: a.id ? String(a.id) : getPoiId(a, idx),
        type: a.name || 'POI',
        content: a.parent_location || 'Selected location',
        lat: Number(a.lat || 0),
        lng: Number(a.lng || 0),
      })
    );
    base = [...base, ...addedItems];
  }

  return base;
}

export function mergeAndSortCompetitors(
  selectedCompetitors: Competitor[],
  selectedPoiAddress: PlaceItem[],
  selectedPlace: PlaceItem[],
  sortBy: SortOption
): Competitor[] {
  const searchItems: Competitor[] = [...selectedPoiAddress, ...selectedPlace]
    .filter((item) => item.location?.latitude && item.location?.longitude)
    .map((item, idx): Competitor => {
      return {
        id: getPoiId(item, idx),
        type: item?.displayName?.text || 'POI',
        content: item?.formattedAddress || 'Selected location',
        lat: item?.location?.latitude || 0,
        lng: item?.location?.longitude || 0,
      };
    });

  const seenSearchIds = new Set<string>();
  const filteredSearchItems = searchItems.filter((sItem) => {
    if (seenSearchIds.has(sItem.id)) return false;
    if (
      selectedCompetitors.some(
        (c) =>
          c.id === sItem.id ||
          (Math.abs(c.lat - sItem.lat) < 0.00001 &&
            Math.abs(c.lng - sItem.lng) < 0.00001)
      )
    )
      return false;
    seenSearchIds.add(sItem.id);
    return true;
  });

  const seenIds = new Set<string>();
  const arr: Competitor[] = [
    ...selectedCompetitors,
    ...filteredSearchItems,
  ].filter((c) => {
    if (seenIds.has(c.id)) return false;
    seenIds.add(c.id);
    return true;
  });

  if (sortBy === 'repeat_visitor_count') {
    arr.sort(
      (a, b) =>
        (b.visit_stats?.repeat_visitor_count || 0) -
        (a.visit_stats?.repeat_visitor_count || 0)
    );
  } else if (sortBy === 'repeat_visitor_pct') {
    arr.sort(
      (a, b) =>
        (b.visit_stats?.repeat_visitor_pct || 0) -
        (a.visit_stats?.repeat_visitor_pct || 0)
    );
  } else if (sortBy === 'max_seen') {
    arr.sort(
      (a, b) =>
        (b.visit_stats?.max_seen || 0) - (a.visit_stats?.max_seen || 0)
    );
  } else if (sortBy === 'total_devices') {
    // Same fallback chain the row itself displays (MaidSplitViewFloatingWidget's
    // per-row value) and findHighestTargetLocation already use — audience_count
    // is stamped on EVERY attribute_audience call, visit_stats only on a
    // stamp_stats=True one, so a POI can carry a real audience_count with no
    // visit_stats (legacy data, a partial recompute). Sorting on visit_stats
    // alone put such a POI at the bottom of "Unique Visitors" while its row
    // showed a real, often large, number.
    arr.sort(
      (a, b) =>
        (b.audience_count ?? b.visit_stats?.total_devices ?? 0) -
        (a.audience_count ?? a.visit_stats?.total_devices ?? 0)
    );
  }
  return arr;
}

export function findHighestTargetLocation(
  maidCount: number | null | undefined,
  visibleCompetitors: Competitor[],
  maidObservations?: Array<{
    latitude?: number;
    longitude?: number;
    lat?: number;
    lng?: number;
  }>
): { lat: number; lng: number } | null {
  if (maidCount === null || maidCount === 0 || visibleCompetitors.length === 0) {
    return null;
  }

  const validCompetitors = visibleCompetitors.filter(
    (c) =>
      typeof c.lat === 'number' &&
      typeof c.lng === 'number' &&
      (c.lat !== 0 || c.lng !== 0)
  );

  const highest = [...validCompetitors].sort((a, b) => {
    const countA = a.audience_count ?? a.visit_stats?.total_devices ?? 0;
    const countB = b.audience_count ?? b.visit_stats?.total_devices ?? 0;
    return countB - countA;
  })[0];

  const highestCount =
    highest?.audience_count ?? highest?.visit_stats?.total_devices ?? 0;

  if (highest && highestCount > 0) {
    return { lat: highest.lat, lng: highest.lng };
  } else if (maidObservations && maidObservations.length > 0) {
    const obs = maidObservations;
    const sumLat = obs.reduce(
      (sum, o) => sum + Number(o.lat ?? o.latitude ?? 0),
      0
    );
    const sumLng = obs.reduce(
      (sum, o) => sum + Number(o.lng ?? o.longitude ?? 0),
      0
    );
    return { lat: sumLat / obs.length, lng: sumLng / obs.length };
  }
  return null;
}

export type DynamicMetric = { value: string; label: string };

// The side panel's whole-audience headline — always the backend's own
// aggregate (content.maid_count / content.visit_stats), never a client-side
// sum or mean over the visible POI list. POIs at the same coordinates+radius
// share one purchase, so a device seen at two of them is stamped onto BOTH
// (maid_query.attribute_audience: "per-POI counts may sum to more than the
// returned total, which is the deduped union") — summing per-POI
// audience_count/repeat_visitor_count here used to inflate this headline
// past what the narrator says in chat, worse with every POI added.
export function computeDynamicMetric(
  content: Pick<MaidSplitViewData, 'maid_count' | 'visit_stats'>,
  sortBy: SortOption
): DynamicMetric {
  switch (sortBy) {
    case 'repeat_visitor_count':
      return {
        value: (content.visit_stats?.repeat_visitor_count ?? 0).toLocaleString(),
        label: 'Repeat Visitors',
      };
    case 'repeat_visitor_pct':
      return {
        value: `${content.visit_stats?.repeat_visitor_pct ?? 0}%`,
        label: 'Repeat Percentage',
      };
    case 'max_seen':
      return {
        value: `${content.visit_stats?.max_seen ?? 0}x`,
        label: 'Max Frequency',
      };
    case 'total_devices':
    default: {
      const count = content.maid_count ?? content.visit_stats?.total_devices;
      return {
        value: count != null ? count.toLocaleString() : '—',
        label: 'Unique Visitors',
      };
    }
  }
}

export function buildConfirmPayload({
  isEditable,
  prompt,
  selectedPoiAddress,
  selectedPlace,
  points,
  selectedCompetitors,
}: {
  isEditable?: boolean;
  prompt?: string;
  selectedPoiAddress: PlaceItem[];
  selectedPlace: PlaceItem[];
  points: PoiItem[];
  selectedCompetitors: Competitor[];
}): string {
  if (!isEditable) {
    return `Q: ${prompt || 'Locations Found'}\nA: confirmed`;
  }
  const added = [...selectedPoiAddress, ...selectedPlace]
    .filter(
      (
        pl
      ): pl is PlaceItem & {
        location: { latitude: number; longitude: number };
      } => !!(pl.location?.latitude && pl.location?.longitude)
    )
    .map((pl, idx) => ({
      id: getPoiId(pl, idx),
      name:
        pl.displayName?.text || pl.formattedAddress || 'Selected location',
      lat: pl.location.latitude,
      lng: pl.location.longitude,
      types: pl.types,
      parent_location: pl.formattedAddress,
      parent_poi_type: 'map_pick',
    }));

  const pointsWithIds = points.map((p, idx) => ({
    p,
    stableId: getPoiId(p, idx),
  }));

  const removed = pointsWithIds
    .filter(
      ({ stableId }) => !selectedCompetitors.some((c) => c.id === stableId)
    )
    .map(({ p, stableId }) => ({
      id: stableId,
      name: p.name,
      lat: p.lat ?? p.latitude,
      lng: p.lng ?? p.longitude,
    }));

  const payload = JSON.stringify({ confirm: true, added, removed });
  return `Q: ${prompt || 'Locations Found'}\nA: ${payload}`;
}
