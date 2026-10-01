'use client';
import React, {
  useEffect,
  useState,
  useRef,
  forwardRef,
  useImperativeHandle,
} from 'react';
import WidgetLayout from './WidgetLayout';
import {
  Box,
  Flex,
  Popover,
  Text,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import {
  APIProvider,
  Map,
  useMap,
  AdvancedMarker,
} from '@vis.gl/react-google-maps';
import {
  InfoIcon,
  ChevronDown,
  ChevronUp,
  Minus,
  Plus,
  Info,
  Target,
} from 'lucide-react';
import type { PoiRadiusPickerData } from '@/types/chat';
import { IndicatorSvg } from '@/components/Indicator';
import { motion, AnimatePresence } from 'framer-motion';
import MapWidgetGlassIconButton, {
  MapWidgetGlassPopoverDropdown,
  MapWidgetInfoPopover,
} from '@/components/MapWidgetGlassIconButton';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
// import ReactMarkdown from 'react-markdown'
// import remarkGfm from 'remark-gfm'
import PrimaryActionIcon from '@/components/PrimaryActionIcon';

// Module-level cache: persists radius/day values across chat switches (remounts)
const widgetStateCache: Record<
  string,
  { radius: number; lookbackDays: number }
> = {};

interface WidgetPoiRadiusPickerProps {
  content: PoiRadiusPickerData;
  onConfirm?: (displayMessage: string) => void;
  aiText?: React.ReactNode;
  showLogo?: boolean;
  isLatest?: boolean;
  userResponse?: string | null;
  widgetId?: string;
}

interface CircleProps extends google.maps.CircleOptions {
  center: google.maps.LatLngLiteral;
  radius: number;
}

const Circle = forwardRef((props: CircleProps, ref) => {
  const map = useMap();
  const circleRef = useRef<google.maps.Circle | null>(null);

  useEffect(() => {
    if (!map) return;

    const circle = new google.maps.Circle({
      map,
    });
    circleRef.current = circle;

    return () => {
      circle.setMap(null);
    };
  }, [map]);

  useEffect(() => {
    if (!circleRef.current) return;
    circleRef.current.setOptions(props);
  }, [props]);

  useImperativeHandle(ref, () => circleRef.current);

  return null;
});
Circle.displayName = 'Circle';

function MapBoundsUpdater({
  center,
  pois,
  radius,
  isMeters,
}: {
  center: [number, number];
  pois: {
    lat?: number;
    latitude?: number;
    lng?: number;
    longitude?: number;
    name?: string;
  }[];
  radius: number;
  isMeters: boolean;
}) {
  const map = useMap();

  // Only used to decide WHEN to re-fit — deliberately excludes radius/isMeters
  const structuralKey = React.useMemo(() => {
    return JSON.stringify({
      center,
      pois: pois.map(
        (p) =>
          [p.lat || p.latitude || 0, p.lng || p.longitude || 0] as [
            number,
            number,
          ]
      ),
    });
  }, [center, pois]);

  const lastFitKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!map) return;
    if (lastFitKeyRef.current === structuralKey) return;
    lastFitKeyRef.current = structuralKey;

    try {
      const radiusInMeters = isMeters ? radius : radius * 1000;

      const bounds = new google.maps.LatLngBounds();
      if (center[0] !== 0 || center[1] !== 0) {
        bounds.extend({ lat: center[0], lng: center[1] });
      }

      pois.forEach((poi) => {
        const poiLat = poi.lat || poi.latitude || 0;
        const poiLng = poi.lng || poi.longitude || 0;
        if (poiLat === 0 && poiLng === 0) return;
        const latOffset = radiusInMeters / 111320;
        const lngOffset =
          radiusInMeters / (111320 * Math.cos((poiLat * Math.PI) / 180) || 1);

        bounds.extend({ lat: poiLat - latOffset, lng: poiLng - lngOffset });
        bounds.extend({ lat: poiLat + latOffset, lng: poiLng + lngOffset });
      });

      const isPhone = typeof window !== 'undefined' && window.innerWidth < 768;
      const rightPadding = isPhone ? 40 : 350;

      const timeoutId = setTimeout(() => {
        if (!map) return;
        if (pois.length === 0) {
          map.panTo({ lat: center[0], lng: center[1] });
          map.setZoom(16);
        } else {
          if (!bounds.isEmpty()) {
            map.fitBounds(bounds, {
              top: 40,
              bottom: 40,
              left: 40,
              right: rightPadding,
            });
            if (isPhone) {
              google.maps.event.addListenerOnce(map, 'idle', () => {
                const currentZoom = map.getZoom();
                if (currentZoom !== undefined && currentZoom > 17) {
                  map.setZoom(17);
                }
              });
            }
          }
        }
      }, 200);

      return () => clearTimeout(timeoutId);
    } catch (e) {
      console.warn('MapBoundsUpdater error', e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structuralKey, map]);

  return null;
}

// Stepper moves by `step`, except inside the first step-unit where it moves by 1
// (e.g. step 5 -> 1,2,3,4,5,10,15...). A step of 1 makes both branches identical.
const stepDown = (v: number, min: number, step: number) =>
  Math.max(min, v - (v <= step ? 1 : step));
const stepUp = (v: number, max: number, step: number) =>
  Math.min(max, v + (v < step ? 1 : step));

const WidgetPoiRadiusPickerV2 = ({
  content,
  onConfirm,
  aiText,
  showLogo = false,
  isLatest = true,
  userResponse,
  widgetId,
}: WidgetPoiRadiusPickerProps) => {
  const { colorScheme } = useMantineColorScheme();
  const mapColorScheme =
    colorScheme === 'auto'
      ? 'FOLLOW_SYSTEM'
      : colorScheme === 'dark'
        ? 'DARK'
        : 'LIGHT';

  const stepper = content.pending_action?.stepper;
  const steppers = content.pending_action?.steppers;

  // Find radius config
  const radiusConfig =
    steppers?.find(
      (s) =>
        s.key === 'poi_radius_m' ||
        s.key === 'radius_km' ||
        s.unit?.toLowerCase() === 'm' ||
        s.unit?.toLowerCase() === 'km'
    ) ||
    (stepper &&
    !(
      (stepper as unknown as { key: string; unit?: string }).key ===
        'lookback_days' ||
      ['days', 'day', 'time'].includes(
        (
          stepper as unknown as { key: string; unit?: string }
        ).unit?.toLowerCase() || ''
      )
    )
      ? stepper
      : undefined);

  // Find lookback config
  const lookbackConfig =
    steppers?.find(
      (s) =>
        s.key === 'lookback_days' ||
        ['days', 'day', 'time'].includes(s.unit?.toLowerCase() || '')
    ) ||
    (stepper &&
    ((stepper as unknown as { key: string; unit?: string }).key ===
      'lookback_days' ||
      ['days', 'day', 'time'].includes(
        (
          stepper as unknown as { key: string; unit?: string }
        ).unit?.toLowerCase() || ''
      ))
      ? stepper
      : undefined);

  const isMeters = radiusConfig
    ? radiusConfig.unit?.toLowerCase() === 'm'
    : false;
  const isDayOrTime = !radiusConfig && !!lookbackConfig;

  const getRadiusFromResponse = (response: string | null | undefined) => {
    if (!response) return null;
    const parts = response.includes('A:')
      ? response.split('A:')[1].trim()
      : response.trim();
    if (parts.startsWith('{')) {
      try {
        const obj = JSON.parse(parts);
        if (obj.poi_radius_m !== undefined) return obj.poi_radius_m;
      } catch {
        // ignore JSON parsing errors
      }
    }
    // Parse from human-readable format, e.g. "Radius selected 50m..." or "Radius selected 100 m..." or "Radius selected 1.5km..."
    const match = parts.match(/Radius selected\s+([\d.]+)\s*([a-zA-Z]+)?/i);
    if (match) {
      const val = parseFloat(match[1]);
      const unit = match[2]?.toLowerCase();
      if (!isNaN(val)) {
        if (unit === 'km' && isMeters) {
          return val * 1000;
        }
        if (unit === 'm' && !isMeters) {
          return val / 1000;
        }
        return val;
      }
    }
    const parsed = parseFloat(parts);
    return isNaN(parsed) ? null : parsed;
  };

  const getLookbackFromResponse = (response: string | null | undefined) => {
    if (!response) return null;
    const parts = response.includes('A:')
      ? response.split('A:')[1].trim()
      : response.trim();
    if (parts.startsWith('{')) {
      try {
        const obj = JSON.parse(parts);
        if (obj.lookback_days !== undefined) return obj.lookback_days;
      } catch {
        // ignore JSON parsing errors
      }
    }
    // Parse from human-readable format, e.g. "Lookback days: 5"
    const match = parts.match(/Lookback days:\s*([\d.]+)/i);
    if (match) {
      const val = parseFloat(match[1]);
      if (!isNaN(val)) {
        return val;
      }
    }
    return null;
  };

  const [radius, setRadius] = useState<number>(() => {
    const responseVal = getRadiusFromResponse(userResponse);
    if (responseVal !== null) {
      return responseVal;
    }
    if (widgetId && widgetStateCache[widgetId]) {
      return widgetStateCache[widgetId].radius;
    }
    if (radiusConfig) {
      return radiusConfig.default ?? radiusConfig.min ?? (isMeters ? 500 : 0.5);
    }

    if (content.default_radius_km) {
      return content.default_radius_km * (isMeters ? 1000 : 1);
    }

    return isMeters ? 500 : 0.5;
  });

  const [lookbackDays, setLookbackDays] = useState<number>(() => {
    const responseVal = getLookbackFromResponse(userResponse);
    if (responseVal !== null) {
      return responseVal;
    }
    if (widgetId && widgetStateCache[widgetId]) {
      return widgetStateCache[widgetId].lookbackDays;
    }
    if (lookbackConfig) {
      return lookbackConfig.default ?? lookbackConfig.min ?? 7;
    }
    return 7;
  });

  useEffect(() => {
    if (widgetId) {
      widgetStateCache[widgetId] = { radius, lookbackDays };
    }
  }, [widgetId, radius, lookbackDays]);

  const [prevUserResponse, setPrevUserResponse] = useState(userResponse);

  if (userResponse !== prevUserResponse) {
    setPrevUserResponse(userResponse);
    const responseVal = getRadiusFromResponse(userResponse);
    if (responseVal !== null) {
      setRadius(responseVal);
    }
    const responseLVal = getLookbackFromResponse(userResponse);
    if (responseLVal !== null) {
      setLookbackDays(responseLVal);
    }
  }
  useEffect(() => {
    if (!userResponse && radiusConfig?.default !== undefined) {
      const defaultRadius = radiusConfig.default;
      setTimeout(() => {
        setRadius(defaultRadius);
      }, 0);
    }
  }, [radiusConfig?.default, userResponse]);

  useEffect(() => {
    if (!userResponse && lookbackConfig?.default !== undefined) {
      const defaultLookback = lookbackConfig.default;
      setTimeout(() => {
        setLookbackDays(defaultLookback);
      }, 0);
    }
  }, [lookbackConfig?.default, userResponse]);

  // Lookback-only mode (radius already answered): draw the ring at the real
  // radius in force, not a guess. prefill_radius_m is always METERS — scale
  // it the same way default_radius_km (always KM) is scaled just below, so
  // mapRadius stays in whichever unit `isMeters` says regardless of source.
  // default_radius_km is the pre-prefill_radius_m fallback shape; 500 is the
  // last resort when neither is present.
  const mapRadius = isDayOrTime
    ? content.prefill_radius_m != null
      ? content.prefill_radius_m * (isMeters ? 1 : 0.001)
      : content.default_radius_km
        ? content.default_radius_km * (isMeters ? 1000 : 1)
        : 500
    : radius;

  const center: [number, number] = [
    content.center.lat || content.center.latitude || 0,
    content.center.lng || content.center.longitude || 0,
  ];

  const [open, setOpen] = useState(isLatest);
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest);

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest);
    if (!isLatest) {
      setOpen(false);
    }
  }

  // What backend actually wants — poi_radius_m must always be in metres
  const radiusInMeters = isMeters
    ? Math.round(radius)
    : Math.round(radius * 1000);

  const confirmPayloadObj: Record<string, number> = {};
  if (radiusConfig) confirmPayloadObj.poi_radius_m = radiusInMeters;
  if (lookbackConfig)
    confirmPayloadObj.lookback_days = Math.round(lookbackDays);

  // Sent to the backend as bare JSON (matches is_sentinel_resume's fast path
  // and builder_node._parse_json_value — no LLM re-extraction needed). The
  // chat transcript's friendly line ("Radius selected 250m and Lookback 14
  // days") is rendered from this same shape by MessageBlockUI, not built here.
  const confirmPayload = JSON.stringify(confirmPayloadObj);
  return (
    <WidgetLayout mode="full" aiText={aiText} showLogo={showLogo}>
      <Box className="border-stroke-widget light:border-[#00000033] relative h-[64dvh] w-full overflow-hidden rounded-lg border-2 md:h-150 lg:h-[64dvh] xl:h-[68dvh] 2xl:h-140">
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
              defaultZoom={14}
              disableDefaultUI={true}
              zoomControl={true}
              gestureHandling="greedy"
              className="z-0 h-full w-full"
              mapId="poi-radius-picker-map"
              colorScheme={mapColorScheme}
            >
              <MapBoundsUpdater
                center={center}
                pois={content.pois}
                radius={mapRadius}
                isMeters={isMeters}
              />
              {content.pois.map((poi, idx) => (
                <AdvancedMarker
                  key={idx}
                  position={{
                    lat: poi.lat || poi.latitude || 0,
                    lng: poi.lng || poi.longitude || 0,
                  }}
                  title={poi.name}
                >
                  <div className="relative flex items-center justify-center bg-transparent">
                    <IndicatorSvg />
                  </div>
                </AdvancedMarker>
              ))}
              {!isDayOrTime &&
                content.pois.map((poi, idx) => (
                  <Circle
                    key={`${idx}-${mapRadius}`}
                    center={{
                      lat: poi.lat || poi.latitude || 0,
                      lng: poi.lng || poi.longitude || 0,
                    }}
                    radius={isMeters ? mapRadius : mapRadius * 1000}
                    strokeColor="#D62575"
                    fillColor="#D62575"
                    fillOpacity={0.2}
                    strokeWeight={2}
                    clickable={false}
                  />
                ))}
            </Map>
          </div>
        </APIProvider>

        <MapWidgetInfoPopover>
          <Popover.Target>
            <MapWidgetGlassIconButton title="Information">
              <InfoIcon size={16} />
            </MapWidgetGlassIconButton>
          </Popover.Target>
          <MapWidgetGlassPopoverDropdown>
            <p className="text-primary-text text-[13px]">
              {isDayOrTime
                ? `The range around each location determines the search area.`
                : `Set how close someone had to be to count as a customer worth
              targeting. A tighter circle means stronger intent, a wider one
              reaches more people.`}
            </p>
          </MapWidgetGlassPopoverDropdown>
        </MapWidgetInfoPopover>

        {/* Floating Collapsible Widget */}
        <AnimatePresence>
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            transition={{ duration: 0.2 }}
            className="absolute top-2 right-2 z-1000 w-80 max-w-[calc(100%-2rem)] origin-top-right scale-72 md:scale-100 lg:scale-68 xl:scale-88 2xl:scale-100"
          >
            <motion.div
              layout
              transition={{
                type: 'spring',
                damping: 20,
                stiffness: 300,
                mass: 1,
              }}
              style={{
                backdropFilter: 'blur(75.9px)',
                WebkitBackdropFilter: 'blur(75.9px)',
              }}
              className="bg-primary-bg/1! light:border-white/90! light:border! light:backdrop-blur-[57px] shadow-widget relative overflow-hidden rounded-[30px] dark:backdrop-blur-[75.9px]"
            >
              <button
                type="button"
                onClick={() => setOpen(!open)}
                className="relative z-10 w-full text-left"
              >
                <WidgetHeaderV2
                  className={`cursor-pointer border-b bg-transparent px-4 py-3.5 transition-colors duration-150 ease-out ${open ? 'border-primary-text/5' : 'border-transparent'}`}
                  icon={
                    <div className="text-primary-text flex items-center justify-center rounded-full">
                      <Target size={16} />
                    </div>
                  }
                  title={
                    <span className="text-primary-text text-[15px]! font-semibold!">
                      {isDayOrTime ? 'Look Back Window' : 'Audience Builder'}
                    </span>
                  }
                  // subtitle={
                  //   <span className="text-primary-text/65">
                  //     {content.center.formatted_address || 'Target Area'}
                  //   </span>
                  // }
                  iconSize={40}
                  rightContent={
                    <div className="text-secondary-text my-auto shrink-0">
                      {open ? (
                        <ChevronUp size={20} />
                      ) : (
                        <ChevronDown size={20} />
                      )}
                    </div>
                  }
                />
              </button>
              <AnimatePresence initial={false}>
                {open && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: 'easeInOut' }}
                    className="relative z-10 overflow-hidden"
                  >
                    <Box className="flex flex-col pt-3 pb-3">
                      {/* Status Card */}
                      <Box className="px-4">
                        {/* <div
                          className="relative overflow-hidden rounded-md p-3 bg-widget-inner-glass-bg! light:backdrop-blur-[15.2px] light:border-none"
                        >
                          <Flex align="center" gap={16}>
                            <Text
                              fz={31}
                              fw={700}
                              className="text-primary-text leading-none"
                            >
                              {content.pois.length}
                            </Text>
                            <Box>
                              <Text
                                fz={13}
                                fw={600}
                                className="text-primary-text leading-tight"
                              >
                                Locations Identified
                              </Text>
                              <Text
                                fz={10}
                                className="text-secondary-text/80 mt-0.5 leading-tight"
                              >
                                Updates as you adjust below
                              </Text>
                            </Box>
                          </Flex>
                        </div> */}
                        <Text
                          fz={12}
                          fw={600}
                          className="text-primary-text/90!"
                        >
                          Choose the area and visit window used to include
                          people in your audience.
                        </Text>
                      </Box>

                      {/* Steppers container */}
                      <div className="flex flex-col">
                        {/* Radius Stepper */}
                        <div className="mt-5" />
                        {radiusConfig && (
                          <div className="flex flex-col gap-1.5 px-4 pb-2">
                            <div className="mb-0.5 flex items-center gap-1.5">
                              <span className="text-primary-text text-[9px] font-semibold tracking-wider uppercase">
                                Ring Radius
                              </span>
                              {(radiusConfig as unknown as { hint?: string })
                                .hint && (
                                <Tooltip
                                  transitionProps={{
                                    transition: 'fade',
                                    duration: 200,
                                  }}
                                  zIndex={100000}
                                  multiline
                                  w={200}
                                  label={
                                    <span className="text-secondary-text text-[11px]!">
                                      {
                                        (
                                          radiusConfig as unknown as {
                                            hint?: string;
                                          }
                                        ).hint
                                      }
                                    </span>
                                  }
                                  position="right-end"
                                  withArrow
                                  styles={{
                                    tooltip: {
                                      backgroundColor:
                                        'var(--mantine-color-widget-inner-glass-bg)',
                                      backdropFilter: 'blur(16px)',
                                      WebkitBackdropFilter: 'blur(16px)',
                                      border:
                                        '1px solid var(--mantine-color-plus-minus-button-border)',
                                      borderRadius: '8px',
                                      padding: '6px 8px',
                                      lineHeight: 0.9,
                                    },
                                    arrow: {
                                      backgroundColor:
                                        'var(--mantine-color-widget-inner-glass-bg)',
                                      border:
                                        '1px solid var(--mantine-color-plus-minus-button-border)',
                                    },
                                  }}
                                >
                                  <Info
                                    size={12}
                                    className="text-secondary-text mt-0.5 cursor-help"
                                  />
                                </Tooltip>
                              )}
                            </div>
                            <Flex align="center" justify="center" gap={8}>
                              <PrimaryActionIcon
                                bg="transparent"
                                disabled={
                                  !isLatest || radius <= (radiusConfig.min ?? 1)
                                }
                                size="lg"
                                onClick={() => {
                                  if (isLatest) {
                                    setRadius((prev) =>
                                      stepDown(
                                        prev,
                                        radiusConfig.min ?? 1,
                                        radiusConfig.step ?? 5
                                      )
                                    );
                                  }
                                }}
                                className="border-plus-minus-button-border! text-primary-text! bg-plus-minus-button-bg! hover:bg-plus-minus-button-hover! rounded-[14px]! active:bg-white/5! disabled:cursor-not-allowed disabled:bg-white/3!"
                                style={{
                                  borderTop: '1px solid',
                                  boxShadow:
                                    'var(--shadow-plus-minus-button-shadow)',
                                  borderImageSource: `linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),
                                    linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))`,
                                }}
                              >
                                <Minus size={16} />
                              </PrimaryActionIcon>

                              <Box
                                size="lg"
                                className="text-primary-text! flex h-9 w-fit! flex-1 cursor-default! items-center justify-center px-3! text-[13px]! font-bold! backdrop-blur-[15.2px]!"
                                style={{
                                  borderRadius: '8px',
                                  background: '#0000004D',
                                }}
                                aria-readonly
                              >
                                {Math.round(radius)} {radiusConfig.unit || 'm'}
                              </Box>

                              <PrimaryActionIcon
                                bg="transparent"
                                disabled={
                                  !isLatest ||
                                  radius >= (radiusConfig.max ?? 5000)
                                }
                                size="lg"
                                onClick={() => {
                                  if (isLatest) {
                                    setRadius((prev) =>
                                      stepUp(
                                        prev,
                                        radiusConfig.max ?? 5000,
                                        radiusConfig.step ?? 5
                                      )
                                    );
                                  }
                                }}
                                className="border-plus-minus-button-border! text-primary-text! bg-plus-minus-button-bg! hover:bg-plus-minus-button-hover! rounded-[14px]! active:bg-white/5! disabled:cursor-not-allowed disabled:bg-white/3!"
                                style={{
                                  borderTop: '1px solid',
                                  boxShadow:
                                    'var(--shadow-plus-minus-button-shadow)',
                                  borderImageSource: `linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),
                                    linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))`,
                                }}
                              >
                                <Plus size={16} />
                              </PrimaryActionIcon>
                            </Flex>
                          </div>
                        )}

                        {/* Divider between steppers if both exist */}
                        {radiusConfig && lookbackConfig && (
                          <div className="border-primary-text/10 my-1.5 border-t" />
                        )}

                        {/* Lookback Stepper */}
                        {lookbackConfig && (
                          <div className="flex flex-col gap-1.5 px-4 py-2">
                            <div className="mb-0.5 flex items-center gap-1.5">
                              <span className="text-primary-text text-[9px] font-semibold tracking-wider uppercase">
                                Look Back Window
                              </span>
                              {(lookbackConfig as unknown as { hint?: string })
                                .hint && (
                                <Tooltip
                                  transitionProps={{
                                    transition: 'fade',
                                    duration: 200,
                                  }}
                                  zIndex={100000}
                                  multiline
                                  w={160}
                                  label={
                                    <span className="text-secondary-text text-[11px]!">
                                      {
                                        (
                                          lookbackConfig as unknown as {
                                            hint?: string;
                                          }
                                        ).hint
                                      }
                                    </span>
                                  }
                                  position="right-end"
                                  withArrow
                                  styles={{
                                    tooltip: {
                                      backgroundColor:
                                        'var(--mantine-color-widget-inner-glass-bg)',
                                      backdropFilter: 'blur(16px)',
                                      WebkitBackdropFilter: 'blur(16px)',
                                      border:
                                        '1px solid var(--mantine-color-plus-minus-button-border)',
                                      borderRadius: '8px',
                                      padding: '6px 8px',
                                      lineHeight: 0.9,
                                    },
                                    arrow: {
                                      backgroundColor:
                                        'var(--mantine-color-widget-inner-glass-bg)',
                                      border:
                                        '1px solid var(--mantine-color-plus-minus-button-border)',
                                    },
                                  }}
                                >
                                  <Info
                                    size={12}
                                    className="text-secondary-text mt-0.5 cursor-help"
                                  />
                                </Tooltip>
                              )}
                            </div>
                            <Flex align="center" justify="center" gap={8}>
                              <PrimaryActionIcon
                                bg="transparent"
                                disabled={
                                  !isLatest ||
                                  lookbackDays <= (lookbackConfig.min ?? 1)
                                }
                                size="lg"
                                onClick={() => {
                                  if (isLatest) {
                                    setLookbackDays((prev) =>
                                      Math.max(
                                        lookbackConfig.min ?? 1,
                                        prev - (lookbackConfig.step ?? 1)
                                      )
                                    );
                                  }
                                }}
                                className="border-plus-minus-button-border! text-primary-text! bg-plus-minus-button-bg! hover:bg-plus-minus-button-hover! rounded-[14px]! active:bg-white/5! disabled:cursor-not-allowed disabled:bg-white/3!"
                                style={{
                                  borderTop: '1px solid',
                                  boxShadow:
                                    'var(--shadow-plus-minus-button-shadow)',
                                  borderImageSource: `linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),
                                    linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))`,
                                }}
                              >
                                <Minus size={16} />
                              </PrimaryActionIcon>

                              <Box
                                className="text-primary-text! flex h-9 w-fit! flex-1 cursor-default! items-center justify-center px-3! text-[13px]! font-bold! backdrop-blur-[15.2px]!"
                                style={{
                                  borderRadius: '8px',
                                  background: '#0000004D',
                                }}
                                aria-readonly
                              >
                                {Math.round(lookbackDays)}{' '}
                                {lookbackConfig.unit || 'days'}
                              </Box>

                              <PrimaryActionIcon
                                bg="transparent"
                                disabled={
                                  !isLatest ||
                                  lookbackDays >= (lookbackConfig.max ?? 90)
                                }
                                size="lg"
                                onClick={() => {
                                  if (isLatest) {
                                    setLookbackDays((prev) =>
                                      Math.min(
                                        lookbackConfig.max ?? 90,
                                        prev + (lookbackConfig.step ?? 1)
                                      )
                                    );
                                  }
                                }}
                                className="border-plus-minus-button-border! text-primary-text! bg-plus-minus-button-bg! hover:bg-plus-minus-button-hover! rounded-[14px]! active:bg-white/5! disabled:cursor-not-allowed disabled:bg-white/3!"
                                style={{
                                  borderTop: '1px solid',
                                  boxShadow:
                                    'var(--shadow-plus-minus-button-shadow)',
                                  borderImageSource: `linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),
                                    linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))`,
                                }}
                              >
                                <Plus size={16} />
                              </PrimaryActionIcon>
                            </Flex>
                          </div>
                        )}
                        <div className="border-primary-text/10 my-2 border-t" />
                      </div>

                      {/* Bottom Confirm/No section */}
                      {content.pending_action && (
                        <div className="pt-2 pb-1">
                          <div className="px-4">
                            <div className="">
                              {/*  <Text className="text-[13px]! font-medium! text-primary-text!">
                                {promptText}
                              </Text>
                            </div>
                            <div className="pb-1">
                              <button
                                type="button"
                                disabled={!isLatest}
                                onClick={() => {
                                  if (isLatest && onConfirm) {
                                    onConfirm(
                                      `Q: ${promptText}\nA: no`,
                                      JSON.stringify({ confirmed: false }),
                                    )
                                  }
                                }}
                                className="text-primary-text cursor-pointer border-0 bg-transparent p-0 text-[12px]! disabled:text-primary-text/60! disabled:hover:no-underline disabled:cursor-not-allowed font-semibold hover:underline pl-3! -mb-1.5"
                              >
                                No
                              </button> */}
                              <PrimaryGlassBtn
                                className="w-full! text-[13px]!"
                                onClick={() => {
                                  if (isLatest && onConfirm) {
                                    onConfirm(confirmPayload);
                                  }
                                }}
                                disabled={!isLatest}
                              >
                                Generate Audience
                              </PrimaryGlassBtn>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Fallback Confirm Section when no pending_action */}
                      {!content.pending_action && (
                        <div className="mt-4 px-4 pb-3">
                          <PrimaryGlassBtn
                            className="w-full"
                            onClick={() => {
                              if (isLatest && onConfirm) {
                                onConfirm(confirmPayload);
                              }
                            }}
                            disabled={!isLatest}
                          >
                            Confirm Settings
                          </PrimaryGlassBtn>
                        </div>
                      )}
                    </Box>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </motion.div>
        </AnimatePresence>
      </Box>
    </WidgetLayout>
  );
};

export default WidgetPoiRadiusPickerV2;
