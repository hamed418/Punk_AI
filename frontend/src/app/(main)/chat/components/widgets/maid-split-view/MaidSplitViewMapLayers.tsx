import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AdvancedMarker, InfoWindow, useMap } from '@vis.gl/react-google-maps';
import type { PoiItem } from '@/types/chat';
import type { Competitor, FocusLocation } from './types';
import { MaidHumanMarkerIcon } from './MaidSplitViewIcons';
import PoiVisitStatsCard from './PoiVisitStatsCard';
import POILogo from '@/components/POILogo';

export function ZoomListener({
  onZoomChange,
}: {
  onZoomChange: (zoom: number) => void;
}) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const listener = google.maps.event.addListener(map, 'zoom_changed', () => {
      onZoomChange(map.getZoom() || 13);
    });
    return () => google.maps.event.removeListener(listener);
  }, [map, onZoomChange]);
  return null;
}

export function MaidObservationsLayer({
  observations,
  currentZoom,
}: {
  observations: Array<{
    latitude?: number;
    longitude?: number;
    lat?: number;
    lng?: number;
  }>;
  currentZoom: number;
}) {
  const map = useMap();
  const [visibleObs, setVisibleObs] = useState<typeof observations>([]);

  useEffect(() => {
    if (
      !map ||
      currentZoom <= 12 ||
      !observations ||
      observations.length === 0
    ) {
      setTimeout(() => setVisibleObs([]), 0);
      return;
    }

    let timeoutId: NodeJS.Timeout;
    const updateVisible = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        const bounds = map.getBounds();
        if (!bounds) return;

        const filtered = observations.filter((obs) => {
          const lat = obs.lat || obs.latitude || 0;
          const lng = obs.lng || obs.longitude || 0;
          return bounds.contains({ lat, lng });
        });

        // Cap at 1500 to prevent DOM overload, but sample uniformly so dots don't vanish in dense areas
        if (filtered.length > 1500) {
          const step = filtered.length / 1500;
          const sampled = [];
          for (let i = 0; i < 1500; i++) {
            sampled.push(filtered[Math.floor(i * step)]);
          }
          setVisibleObs(sampled);
        } else {
          setVisibleObs(filtered);
        }
      }, 100);
    };

    updateVisible();
    const listener = google.maps.event.addListener(
      map,
      'bounds_changed',
      updateVisible
    );
    return () => {
      google.maps.event.removeListener(listener);
      clearTimeout(timeoutId);
    };
  }, [map, currentZoom, observations]);

  if (currentZoom <= 14) return null;

  return (
    <>
      {visibleObs.map((obs, idx) => {
        const obsKey = `maid-${obs.lat || obs.latitude || 0}-${obs.lng || obs.longitude || 0}-${idx}`;
        return (
          <AdvancedMarker
            key={obsKey}
            position={{
              lat: obs.lat || obs.latitude || 0,
              lng: obs.lng || obs.longitude || 0,
            }}
          >
            <POILogo width={12} height={20} />
          </AdvancedMarker>
        );
      })}
    </>
  );
}

export function MapBoundsUpdater({
  center,
  pois,
  isAudienceReview,
  initialFocusLocation,
}: {
  center: [number, number];
  pois: PoiItem[];
  maidObservations?: Array<{
    latitude?: number;
    longitude?: number;
    lat?: number;
    lng?: number;
  }>;
  isAudienceReview?: boolean;
  initialFocusLocation?: { lat: number; lng: number } | null;
}) {
  const map = useMap();
  const hasAnimatedInitialZoomOut = useRef(false);

  const boundsKey = useMemo(() => {
    const points: [number, number][] = [
      center,
      ...pois.map(
        (p) =>
          [
            p.lat || p.latitude || p.location?.latitude || 0,
            p.lng || p.longitude || p.location?.longitude || 0,
          ] as [number, number]
      ),
    ].filter(([lat, lng]) => lat !== 0 && lng !== 0);

    return JSON.stringify(points);
  }, [center, pois]);

  useEffect(() => {
    if (!map) return;
    try {
      const allPoints: [number, number][] = JSON.parse(boundsKey);
      if (allPoints.length === 0) return;

      const bounds = new google.maps.LatLngBounds();
      allPoints.forEach(([lat, lng]) => {
        bounds.extend({ lat, lng });
      });

      const isSmallDevice =
        typeof window !== 'undefined' && window.innerWidth < 768;
      const rightPadding = isSmallDevice ? 40 : 350;

      // REVERSED ANIMATION: Start zoomed IN showing device dots, then zoom OUT to full bounds
      if (
        isAudienceReview &&
        initialFocusLocation &&
        !hasAnimatedInitialZoomOut.current
      ) {
        map.setCenter({
          lat: initialFocusLocation.lat,
          lng: initialFocusLocation.lng,
        });
        map.setZoom(16);
        const offset = isSmallDevice ? 90 : 165;
        map.panBy(offset, 0);

        const t = setTimeout(() => {
          hasAnimatedInitialZoomOut.current = true;
          let currentZ = 16;
          const zoomInterval = setInterval(() => {
            currentZ -= 1;
            map.setZoom(currentZ);
            if (currentZ <= 13) {
              clearInterval(zoomInterval);
              if (!bounds.isEmpty()) {
                map.fitBounds(bounds, {
                  top: 40,
                  bottom: 40,
                  left: 40,
                  right: rightPadding,
                });
              }
            }
          }, 150);
        }, 2000);

        return () => clearTimeout(t);
      } else if (
        isAudienceReview &&
        !initialFocusLocation &&
        !hasAnimatedInitialZoomOut.current
      ) {
        return;
      } else {
        if (pois.length <= 1) {
          const [lat, lng] = allPoints[0];
          map.panTo({ lat, lng });
          const zoom = isAudienceReview ? 14 : 15;
          map.setZoom(zoom);
          return;
        }

        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, {
            top: 40,
            bottom: 40,
            left: 40,
            right: rightPadding,
          });
        }
      }
    } catch (e) {
      console.warn('MapBoundsUpdater error', e);
    }
  }, [boundsKey, map, pois.length, isAudienceReview, initialFocusLocation]);

  return null;
}

export function MapFocusUpdater({
  focusLocation,
  isAudienceReview,
}: {
  focusLocation: FocusLocation | null;
  isAudienceReview?: boolean;
}) {
  const map = useMap();
  const lastTimestampRef = useRef<number | null>(null);

  useEffect(() => {
    if (!map || !focusLocation) return;

    if (
      lastTimestampRef.current &&
      lastTimestampRef.current === focusLocation.timestamp
    ) {
      return;
    }

    lastTimestampRef.current = focusLocation.timestamp;

    const isSmallDevice =
      typeof window !== 'undefined' && window.innerWidth < 768;
    const zoom = isAudienceReview ? 14 : isSmallDevice ? 15 : 15;

    map.panTo({
      lat: focusLocation.lat,
      lng: focusLocation.lng,
    });

    if (isSmallDevice) {
      map.setZoom(zoom);
      if (isAudienceReview) {
        map.panBy(40, 0);
      }
      return;
    }

    google.maps.event.addListenerOnce(map, 'idle', () => {
      let currentZ = Math.round(map.getZoom() || 13);
      if (currentZ === zoom) {
        if (isAudienceReview) {
          map.panBy(80, 0);
        }
        return;
      }

      const step = currentZ < zoom ? 1 : -1;
      const zoomInterval = setInterval(() => {
        currentZ += step;
        map.setZoom(currentZ);
        if (
          currentZ === zoom ||
          (step > 0 && currentZ >= zoom) ||
          (step < 0 && currentZ <= zoom) ||
          currentZ > 20 ||
          currentZ < 0
        ) {
          clearInterval(zoomInterval);
          if (isAudienceReview) {
            map.panBy(80, 0);
          }
        }
      }, 150);
    });
  }, [map, focusLocation, isAudienceReview]);

  return null;
}

export interface MaidSplitViewMarkersProps {
  competitors: Competitor[];
  currentZoom: number;
  isAudienceReview: boolean;
  selectedPoiId: string | null;
  selectedPoiType: 'human' | 'location' | null;
  onSelectPoi: (competitor: Competitor, type: 'human' | 'location') => void;
  onCloseInfoWindow: () => void;
  isEditable?: boolean;
  isLatest?: boolean;
  onRemoveCompetitor?: (id: string) => void;
}

export function MaidSplitViewMarkers({
  competitors,
  currentZoom,
  isAudienceReview,
  selectedPoiId,
  selectedPoiType,
  onSelectPoi,
  onCloseInfoWindow,
  isEditable = true,
  isLatest = true,
  onRemoveCompetitor,
}: MaidSplitViewMarkersProps) {
  return (
    <>
      {competitors.map((competitor, idx) => {
        const poiKey = `poi-${competitor.type || ''}-${competitor.lat || 0}-${competitor.lng || 0}-${idx}`;
        const position = {
          lat: competitor.lat || 0,
          lng: competitor.lng || 0,
        };

        if (isAudienceReview) {
          if (currentZoom <= 14) {
            return (
              <React.Fragment key={`fragment-${poiKey}`}>
                <AdvancedMarker
                  key={`marker-${poiKey}`}
                  position={position}
                  title={competitor.type || ''}
                  onClick={() => onSelectPoi(competitor, 'human')}
                >
                  <div className="relative flex flex-col items-center">
                    {competitor.audience_count !== undefined && (
                      <div className="absolute bottom-full mb-0.5 rounded-md bg-[#D62575] px-2 py-0.5 text-[10px] font-bold whitespace-nowrap text-white shadow-md">
                        {competitor.audience_count.toLocaleString()}
                      </div>
                    )}
                    <MaidHumanMarkerIcon />
                  </div>
                </AdvancedMarker>

                {selectedPoiId === competitor.id &&
                  selectedPoiType === 'human' &&
                  competitor.visit_stats && (
                    <InfoWindow
                      position={position}
                      onCloseClick={onCloseInfoWindow}
                      headerDisabled
                      className="custom-poi-iw"
                      pixelOffset={[0, -10]}
                    >
                      <PoiVisitStatsCard
                        competitor={competitor}
                        onClose={onCloseInfoWindow}
                        isEditable={isEditable}
                        isLatest={isLatest}
                        onRemoveCompetitor={onRemoveCompetitor}
                      />
                    </InfoWindow>
                  )}
              </React.Fragment>
            );
          }
          return null;
        }

        return (
          <React.Fragment key={`fragment-${poiKey}`}>
            <AdvancedMarker
              key={`circle-${poiKey}`}
              position={position}
              title={competitor.type || ''}
              onClick={() => onSelectPoi(competitor, 'location')}
            >
              <div className="relative flex flex-col items-center">
                {competitor.audience_count !== undefined && (
                  <div className="absolute bottom-full mb-0.5 rounded-md bg-[#D62575] px-2 py-0.5 text-[10px] font-bold whitespace-nowrap text-white shadow-md">
                    {competitor.audience_count.toLocaleString()}
                  </div>
                )}
                <div
                  style={{
                    width: '10px',
                    height: '10px',
                    backgroundColor: '#FFFFFF',
                    border: '2px solid #D62575',
                    borderRadius: '50%',
                    cursor: 'default',
                  }}
                />
              </div>
            </AdvancedMarker>

            {selectedPoiId === competitor.id &&
              selectedPoiType === 'location' &&
              competitor.visit_stats && (
                <InfoWindow
                  position={position}
                  onCloseClick={onCloseInfoWindow}
                  headerDisabled
                  className="custom-poi-iw"
                  pixelOffset={[0, -10]}
                >
                  <PoiVisitStatsCard
                    competitor={competitor}
                    onClose={onCloseInfoWindow}
                    isEditable={isEditable}
                    isLatest={isLatest}
                    onRemoveCompetitor={onRemoveCompetitor}
                  />
                </InfoWindow>
              )}
          </React.Fragment>
        );
      })}
    </>
  );
}
