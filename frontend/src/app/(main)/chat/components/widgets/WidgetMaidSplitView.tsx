'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { InfoIcon, Loader2 } from 'lucide-react';
import { APIProvider, Map } from '@vis.gl/react-google-maps';
import { Box, Popover, useMantineColorScheme } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useChat } from '@/contexts/ChatContext';
import type { MaidSplitViewData } from '@/types/chat';
import MapWidgetGlassIconButton, {
  MapWidgetGlassPopoverDropdown,
  MapWidgetInfoPopover,
} from '@/components/MapWidgetGlassIconButton';
import { ExcludedAreas } from '@/components/MapGeoJsonFeatures';
import WidgetLayout from './WidgetLayout';
import POISearch, { type PlaceItem } from './WidgetMapAddressSearch';
import {
  type Competitor,
  type FocusLocation,
  type SortOption,
  type WidgetMaidSplitViewProps,
  buildConfirmPayload,
  buildInitialCompetitors,
  findHighestTargetLocation,
  getPoiId,
  MaidObservationsLayer,
  MaidSplitViewMarkers,
  MaidSplitViewSidePanel,
  MapBoundsUpdater,
  MapFocusUpdater,
  mergeAndSortCompetitors,
  parseUserResponse,
  ZoomListener,
} from './maid-split-view';
import type { AudiencePatch } from './maid-split-view/audienceLayers';
import { trackEvent } from '@/lib/analytics';

export default function WidgetMaidSplitViewV2({
  content,
  onConfirm,
  aiText,
  showLogo = false,
  isLatest = true,
  userResponse,
}: WidgetMaidSplitViewProps) {
  const center: [number, number] = useMemo(
    () => [
      content.center.lat || content.center.latitude || 0,
      content.center.lng || content.center.longitude || 0,
    ],
    [content.center]
  );

  const { selectedPoiAddress, setSelectedPoiAddress, activeThreadId } = useChat();
  const isSmallOrMediumScreen = useMediaQuery('(max-width: 1023px)');
  const { colorScheme } = useMantineColorScheme();
  const mapColorScheme =
    colorScheme === 'auto'
      ? 'FOLLOW_SYSTEM'
      : colorScheme === 'dark'
        ? 'DARK'
        : 'LIGHT';

  // Category/brand tabs (poi_categories) — picking a tab filters the displayed
  // location list in the widget without modifying global widget metrics or title.
  const categories = useMemo(
    () => content.poi_categories || [],
    [content.poi_categories]
  );
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null);
  const activeCategory = useMemo(
    () => categories.find((c) => c.id === activeCategoryId) || null,
    [categories, activeCategoryId]
  );

  const points = useMemo(
    () => content.pois || [],
    [content.pois]
  );
  const pendingAction = content.pending_action;
  const isEditable = !!content.editable;
  const isAudienceReview =
    (content.maid_count !== null && content.maid_count !== 0) ||
    !!content.visit_stats;

  const hasTrackedAudienceRef = React.useRef(false);

  useEffect(() => {
    if (isAudienceReview && !hasTrackedAudienceRef.current) {
      hasTrackedAudienceRef.current = true;
      const categoryNames = categories.map((c) => c.key || c.kind || c.id);
      trackEvent('Audience Generated', {
        maid_count: content.maid_count,
        poi_count: points.length,
        categories: categoryNames,
        center_lat: center[0],
        center_lng: center[1],
      });
      trackEvent('audience_generated', {
        maid_count: content.maid_count,
        poi_count: points.length,
        categories: categoryNames,
        center_lat: center[0],
        center_lng: center[1],
      });
    }
  }, [isAudienceReview, content.maid_count, points.length, categories, center]);

  const parsedUserResponse = useMemo(
    () => parseUserResponse(userResponse),
    [userResponse]
  );

  const initialCompetitors = useMemo(
    () => buildInitialCompetitors(points, parsedUserResponse),
    [points, parsedUserResponse]
  );

  const [currentZoom, setCurrentZoom] = useState<number>(
    isAudienceReview ? 14 : 13
  );
  const [targetZoom, setTargetZoom] = useState<number>(
    isAudienceReview ? 14 : 13
  );
  const [isRenderingData, setIsRenderingData] = useState<boolean>(false);
  const [focusLocation, setFocusLocation] = useState<FocusLocation | null>(
    null
  );
  const [sortBy, setSortBy] = useState<SortOption>('total_devices');

  useEffect(() => {
    if (targetZoom !== currentZoom) {
      const crossedThreshold =
        (currentZoom <= 14 && targetZoom > 14) ||
        (currentZoom > 14 && targetZoom <= 14);
      if (crossedThreshold) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setIsRenderingData(true);
        const t = setTimeout(() => {
          setCurrentZoom(targetZoom);
          requestAnimationFrame(() => {
            setTimeout(() => setIsRenderingData(false), 50);
          });
        }, 50);
        return () => clearTimeout(t);
      } else {
        setCurrentZoom(targetZoom);
      }
    }
  }, [targetZoom, currentZoom]);

  const [selectedPlace, setSelectedPlace] = useState<PlaceItem[]>([]);
  const [selectedCompetitors, setSelectedCompetitors] =
    useState<Competitor[]>(initialCompetitors);
  const [prevInitialCompetitors, setPrevInitialCompetitors] =
    useState(initialCompetitors);
  const [selectedPoiId, setSelectedPoiId] = useState<string | null>(null);
  const [selectedPoiType, setSelectedPoiType] = useState<
    'human' | 'location' | null
  >(null);
  const [prevColorScheme, setPrevColorScheme] = useState(colorScheme);

  // Close any open POI InfoWindow when the theme changes to prevent stale state
  if (colorScheme !== prevColorScheme) {
    setPrevColorScheme(colorScheme);
    setSelectedPoiId(null);
    setSelectedPoiType(null);
  }

  if (initialCompetitors !== prevInitialCompetitors) {
    setPrevInitialCompetitors(initialCompetitors);
    setSelectedCompetitors(initialCompetitors);
  }

  const [stepperValue, setStepperValue] = useState(
    pendingAction?.stepper?.default ?? pendingAction?.stepper?.min ?? 0
  );
  const [prevPendingAction, setPrevPendingAction] = useState(pendingAction);

  if (pendingAction !== prevPendingAction) {
    setPrevPendingAction(pendingAction);
    if (pendingAction?.stepper) {
      setStepperValue(
        pendingAction.stepper.default ?? pendingAction.stepper.min ?? 0
      );
    }
  }

  const [open, setOpen] = useState(isLatest);
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest);
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest);
    if (!isLatest) {
      setOpen(false);
    }
  }

  const handleRemove = useCallback(
    (id: string) => {
      setSelectedCompetitors((prev) => prev.filter((c) => c.id !== id));
      setSelectedPoiAddress((prev) =>
        prev.filter((item, idx) => item.id !== id && getPoiId(item, idx) !== id)
      );
      setSelectedPlace((prev) =>
        prev.filter((item, idx) => item.id !== id && getPoiId(item, idx) !== id)
      );
      if (selectedPoiId === id) {
        setSelectedPoiId(null);
        setSelectedPoiType(null);
      }
    },
    [setSelectedPoiAddress, setSelectedPlace, selectedPoiId]
  );

  const buildConfirmValue = useCallback((): string => {
    return buildConfirmPayload({
      isEditable: content.editable,
      prompt: content.pending_action?.prompt,
      selectedPoiAddress,
      selectedPlace,
      points,
      selectedCompetitors,
    });
  }, [
    content.editable,
    content.pending_action?.prompt,
    selectedPoiAddress,
    selectedPlace,
    points,
    selectedCompetitors,
  ]);

  const visibleCompetitors = useMemo(() => {
    const all = mergeAndSortCompetitors(
      selectedCompetitors,
      selectedPoiAddress,
      selectedPlace,
      sortBy
    );
    if (!activeCategory) return all;
    const catPoiIds = new Set(
      activeCategory.pois.map((p, idx) => getPoiId(p, idx))
    );
    const catPlaceIds = new Set(
      activeCategory.pois
        .map((p) => p.id || p.location?.place_id || (p as { place_id?: string }).place_id)
        .filter(Boolean)
        .map(String)
    );
    return all.filter((c) => {
      if (catPoiIds.has(c.id)) return true;
      if (catPlaceIds.has(c.id)) return true;
      return activeCategory.pois.some(
        (p) =>
          typeof p.lat === 'number' &&
          typeof p.lng === 'number' &&
          Math.abs(c.lat - p.lat) < 0.0001 &&
          Math.abs(c.lng - p.lng) < 0.0001
      );
    });
  }, [selectedCompetitors, selectedPoiAddress, selectedPlace, sortBy, activeCategory]);

  const highestTargetLocation = useMemo(() => {
    return findHighestTargetLocation(
      content.maid_count,
      visibleCompetitors,
      content.maid_observations
    );
  }, [
    content.maid_count,
    visibleCompetitors,
    content.maid_observations,
  ]);

  const handleSelectPoi = useCallback(
    (competitor: Competitor, type: 'human' | 'location') => {
      if (isSmallOrMediumScreen) {
        setOpen(false);
      }
      setSelectedPoiId(competitor.id);
      setSelectedPoiType(type);
      setFocusLocation({
        lat: competitor.lat,
        lng: competitor.lng,
        timestamp: Date.now(),
      });
    },
    [isSmallOrMediumScreen]
  );

  const handleFocusCompetitor = useCallback(
    (competitor: Competitor) => {
      if (isSmallOrMediumScreen) {
        setOpen(false);
      }
      setFocusLocation({
        lat: competitor.lat,
        lng: competitor.lng,
        timestamp: Date.now(),
      });
      setSelectedPoiId(competitor.id);
      setSelectedPoiType(isAudienceReview ? 'human' : 'location');
    },
    [isAudienceReview, isSmallOrMediumScreen]
  );

  const handleCloseInfoWindow = useCallback(() => {
    setSelectedPoiId(null);
    setSelectedPoiType(null);
  }, []);

  const handleConfirmAction = useCallback(() => {
    setOpen(false);
    handleCloseInfoWindow();
    onConfirm?.(buildConfirmValue());
  }, [onConfirm, buildConfirmValue, handleCloseInfoWindow]);

  // Layer builder "Apply": one structured audience_filter patch. It goes through
  // the same resume channel as a typed reply, and the backend applies it with
  // the same edit path — so chat and panel edit one stored filter. The map
  // stays open: the edit re-emits it with the new filter and counts.
  const handleCommitAudience = useCallback(
    (patch: AudiencePatch) => {
      onConfirm?.(JSON.stringify({ action: 'audience_filter_patch', patch }));
    },
    [onConfirm]
  );

  const handleConfirmStepper = useCallback(
    (value: number, unit?: string, prompt?: string) => {
      setOpen(false);
      handleCloseInfoWindow();
      onConfirm?.(
        `Q: ${prompt || 'Review and proceed'}\nA: ${value}${unit ? ' ' + unit : ''}`
      );
    },
    [onConfirm, handleCloseInfoWindow]
  );

  const loaderOverlay = isRenderingData && (
    <div className="absolute inset-0 z-2000 flex flex-col items-center justify-center bg-black/40 backdrop-blur-sm transition-all duration-300">
      <Loader2 className="mb-2 h-8 w-8 animate-spin text-white" />
      <span className="text-sm font-medium text-white">
        {targetZoom > 14 ? 'Loading detailed view...' : 'Loading POI view...'}
      </span>
    </div>
  );

  return (
    <WidgetLayout mode="full" aiText={aiText} showLogo={showLogo}>
      <Box className="border-stroke-widget light:border-[#00000033] relative h-[64dvh] w-full overflow-hidden rounded-lg border-2 md:h-150 lg:h-[64dvh] xl:h-[68dvh] 2xl:h-140">
        {loaderOverlay}
        <APIProvider
          apiKey={
            process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ||
            process.env.GOOGLE_MAPS_API_KEY ||
            process.env.VITE_GOOGLE_MAPS_API_KEY ||
            ''
          }
        >
          <div className="google-map-wrapper h-full w-full">
            <Map
              defaultCenter={{ lat: center[0], lng: center[1] }}
              defaultZoom={isAudienceReview ? 16 : 13}
              disableDefaultUI={true}
              zoomControl={true}
              fullscreenControl={false}
              gestureHandling="greedy"
              className="z-0 h-full w-full"
              mapId="maid-split-view-map"
              colorScheme={mapColorScheme}
            >
              <MapBoundsUpdater
                center={center}
                pois={points}
                maidObservations={content.maid_observations}
                isAudienceReview={isAudienceReview}
                initialFocusLocation={highestTargetLocation}
              />
              <ZoomListener onZoomChange={setTargetZoom} />
              <ExcludedAreas areas={content.excluded_areas} />
              <MapFocusUpdater
                focusLocation={focusLocation}
                isAudienceReview={isAudienceReview}
              />

              {!isAudienceReview && (
                <POISearch
                  setSelectedPlace={setSelectedPlace}
                  selectedPlace={selectedPlace}
                  placeHolderText="search for more locations"
                  searchEnabled={isEditable}
                  onExpandChange={setIsSearchExpanded}
                />
              )}

              {/* POI Markers */}
              <MaidSplitViewMarkers
                competitors={visibleCompetitors}
                currentZoom={currentZoom}
                isAudienceReview={isAudienceReview}
                selectedPoiId={selectedPoiId}
                selectedPoiType={selectedPoiType}
                onSelectPoi={handleSelectPoi}
                onCloseInfoWindow={handleCloseInfoWindow}
                isEditable={isEditable}
                isLatest={isLatest}
                onRemoveCompetitor={handleRemove}
              />

              {/* MAID Observations (Heatmap dots) */}
              {content.maid_count != null && (
                <MaidObservationsLayer
                  observations={content.maid_observations || []}
                  currentZoom={currentZoom}
                />
              )}
            </Map>
          </div>
        </APIProvider>

        <MapWidgetInfoPopover
          key={isAudienceReview ? 'audience' : 'locations'}
          defaultOpened
        >
          <Popover.Target>
            <MapWidgetGlassIconButton title="Information">
              <InfoIcon size={16} />
            </MapWidgetGlassIconButton>
          </Popover.Target>
          <MapWidgetGlassPopoverDropdown
            maw={333}
            className={`${isAudienceReview ? 'p-1!' : 'p-3!'} w-auto max-w-[calc(100vw-3.5rem)]! sm:max-w-83.25!`}
            style={{ padding: isAudienceReview ? 4 : 12 }}
          >
            {isAudienceReview && (
              <video
                src="/videos/info.mp4"
                autoPlay
                loop
                muted
                playsInline
                className="h-auto w-full max-w-full rounded-lg object-contain"
              />
            )}
            <p
              className={`text-primary-text text-sm ${isAudienceReview ? 'px-1 pt-1 pb-3' : ''}`}
            >
              {isAudienceReview
                ? 'This is who your ad will reach. Zoom in. Note: Pin counts can add up to more than the final total because visitors to multiple locations are counted on each pin, but only once overall.'
                : "These are places we think your customers spend time. Add or remove any, and we'll target the people who've been there."}
            </p>
          </MapWidgetGlassPopoverDropdown>
        </MapWidgetInfoPopover>

        {/* Floating Collapsible Widget — category/brand tabs live inside its
            "Locations Found"/"Audience Summary" header. */}
        <MaidSplitViewSidePanel
          content={content}
          sessionId={activeThreadId}
          onCommitAudience={handleCommitAudience}
          isLatest={isLatest}
          open={open}
          setOpen={setOpen}
          isSearchExpanded={isSearchExpanded}
          visibleCompetitors={visibleCompetitors}
          sortBy={sortBy}
          setSortBy={setSortBy}
          stepperValue={stepperValue}
          setStepperValue={setStepperValue}
          onFocusCompetitor={handleFocusCompetitor}
          onRemoveCompetitor={handleRemove}
          onConfirmAction={handleConfirmAction}
          onConfirmStepper={handleConfirmStepper}
          categories={categories}
          allCount={selectedCompetitors.length}
          activeCategoryId={activeCategoryId}
          onSelectCategory={setActiveCategoryId}
        />

        <style>
          {`
          .google-map-wrapper {
            height: 100%;
            width: 100%;
          }
          .google-map-wrapper > div {
            background: var(--bg-chat) !important;
          }
          .google-map-wrapper .gm-fullscreen-control {
            display: none !important;
          }
          .google-map-wrapper .gm-style-iw-c:has(.custom-poi-iw),
          .google-map-wrapper .custom-poi-iw {
            margin-bottom: 0px !important;
          }
        `}
        </style>
      </Box>
      {isAudienceReview && (
        <p className="text-secondary-text mt-1.5 px-1 text-xs">
          Note: Pin counts may add up to more than the final total because visitors to multiple locations are counted at each pin, but only once in the overall audience.
        </p>
      )}
    </WidgetLayout>
  );
}
