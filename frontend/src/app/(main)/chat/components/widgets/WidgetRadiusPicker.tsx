'use client';
import { Box, Flex, Popover, useMantineColorScheme } from '@mantine/core';
import WidgetLayout from './WidgetLayout';
import React, {
  useState,
  useEffect,
  useRef,
  forwardRef,
  useImperativeHandle,
} from 'react';
import {
  APIProvider,
  Map as GoogleMap,
  useMap,
  AdvancedMarker,
} from '@vis.gl/react-google-maps';
import { IndicatorSvg } from '@/components/Indicator';
import type { RadiusPickerData } from '@/types/chat';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown,
  ChevronUp,
  InfoIcon,
  MapPinned,
  Minus,
  Plus,
} from 'lucide-react';
import MapWidgetGlassIconButton, {
  MapWidgetGlassPopoverDropdown,
  MapWidgetInfoPopover,
} from '@/components/MapWidgetGlassIconButton';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import PrimaryActionIcon from '@/components/PrimaryActionIcon';
import WidgetHeaderV2 from '@/components/WidgetHeaderV2';

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

function MapRadiusUpdater({
  center,
  radius,
  isMeters,
}: {
  center: [number, number];
  radius: number;
  isMeters: boolean;
}) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    try {
      const radiusInMeters = isMeters ? radius : radius * 1000;

      const bounds = new google.maps.LatLngBounds();
      const latOffset = radiusInMeters / 111320;
      const lngOffset =
        radiusInMeters / (111320 * Math.cos((center[0] * Math.PI) / 180) || 1);

      bounds.extend({ lat: center[0] - latOffset, lng: center[1] - lngOffset });
      bounds.extend({ lat: center[0] + latOffset, lng: center[1] + lngOffset });

      const isPhone = typeof window !== 'undefined' && window.innerWidth < 768;
      const rightPadding = isPhone ? 40 : 350;

      const timeoutId = setTimeout(() => {
        if (!map) return;
        map.fitBounds(bounds, { top: 40, bottom: 40, left: 40, right: rightPadding });
      }, 200);
      return () => clearTimeout(timeoutId);
    } catch (e) {
      console.warn('MapRadiusUpdater error', e);
    }
  }, [center, radius, map, isMeters]);
  return null;
}

const mapStyles = `
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
`;

interface WidgetRadiusPickerProps {
  content: RadiusPickerData;
  onConfirm?: (value: string | number) => void;
  aiText?: React.ReactNode;
  showLogo?: boolean;
  children?: React.ReactNode;
  isLatest?: boolean;
  userResponse?: string | null;
}

const WidgetRadiusPickerV2 = ({
  content,
  onConfirm,
  aiText,
  showLogo = false,
  isLatest = true,
  userResponse,
}: WidgetRadiusPickerProps) => {
  const { colorScheme } = useMantineColorScheme();
  const mapColorScheme =
    colorScheme === 'auto'
      ? 'FOLLOW_SYSTEM'
      : colorScheme === 'dark'
        ? 'DARK'
        : 'LIGHT';

  const stepper = content.pending_action?.stepper;
  const isMeters = stepper?.unit?.toLowerCase() === 'm';

  const getRadiusFromResponse = (response: string | null | undefined) => {
    if (!response) return null;
    const parts = response.includes('A:')
      ? response.split('A:')[1].trim()
      : response.trim();
    const parsed = parseFloat(parts);
    return isNaN(parsed) ? null : parsed;
  };

  const [radius, setRadius] = useState(() => {
    const responseVal = getRadiusFromResponse(userResponse);
    if (responseVal !== null) {
      return responseVal;
    }

    if (stepper) {
      return stepper.default ?? stepper.min;
    }
    return content.default_radius_km || content.default_radius_miles || 1;
  });

  const [prevUserResponse, setPrevUserResponse] = useState(userResponse);

  if (userResponse !== prevUserResponse) {
    setPrevUserResponse(userResponse);
    const responseVal = getRadiusFromResponse(userResponse);
    if (responseVal !== null) {
      setRadius(responseVal);
    }
  }

  useEffect(() => {
    if (!userResponse && stepper?.default !== undefined) {
      const defaultRadius = stepper.default;
      setTimeout(() => {
        setRadius(defaultRadius);
      }, 0);
    }
  }, [stepper?.default, userResponse]);
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

  return (
    <>
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
              <GoogleMap
                defaultCenter={{ lat: center[0], lng: center[1] }}
                defaultZoom={14}
                disableDefaultUI={true}
                zoomControl={true}
                gestureHandling="greedy"
                className="z-0 h-full w-full"
                mapId="radius-picker-map"
                colorScheme={mapColorScheme}
              >
                <MapRadiusUpdater
                  center={center}
                  radius={radius}
                  isMeters={isMeters}
                />
                <AdvancedMarker
                  position={{ lat: center[0], lng: center[1] }}
                  title={
                    content.locations?.[0]?.location_name ||
                    content.locations?.[0]?.name ||
                    'Location'
                  }
                >
                  <div className="relative flex items-center justify-center bg-transparent">
                    <IndicatorSvg />
                  </div>
                </AdvancedMarker>
                <Circle
                  center={{ lat: center[0], lng: center[1] }}
                  radius={isMeters ? radius : radius * 1000}
                  strokeColor="#FFFFFF"
                  strokeOpacity={0.8}
                  fillColor="#B1B1B1"
                  fillOpacity={0.1}
                  strokeWeight={1}
                  clickable={false}
                />
              </GoogleMap>
            </div>
          </APIProvider>

          <MapWidgetInfoPopover>
            <Popover.Target>
              <MapWidgetGlassIconButton title="Information">
                <InfoIcon className='mb-0!' size={16} />
              </MapWidgetGlassIconButton>
            </Popover.Target>
            <MapWidgetGlassPopoverDropdown>
              <p className="text-primary-text text-[13px]">
                {`Set how wide to search around this point. We'll find places
                inside it and target the people who go there.`}
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
                    className={`cursor-pointer border-b bg-transparent p-0 px-4 py-3.5 transition-colors duration-150 ease-out ${open ? 'border-primary-text/5' : 'border-transparent'}`}
                    icon={<MapPinned size={16} className="text-primary-text" />}
                    title={'Radius Selection'}
                    // subtitle={
                    //   <Text
                    //     fz={11}
                    //     className="text-primary-text/65! max-w-60! truncate! text-[11px]!"
                    //   >
                    //     {content.locations?.[0]?.formatted_address ||
                    //       `${radius} ${isMeters ? 'm' : 'km'} zone`}
                    //   </Text>
                    // }
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
                      <Box>
                        <div className="font-inter text-primary-text px-4 py-4 text-[13px] font-normal">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {content?.pending_action?.prompt}
                          </ReactMarkdown>
                        </div>
                        <Box className="flex w-full flex-col items-center justify-center">
                          <Flex
                            align="center"
                            className="border-primary-text/10 w-full border-b px-4 pb-4"
                            justify="center"
                            gap={8}
                          >
                            <PrimaryActionIcon
                              bg="transparent"
                              disabled={!isLatest}
                              size="lg"
                              onClick={() =>
                                isLatest &&
                                setRadius((v) => {
                                  const s = stepper?.step || 0.1;
                                  const m = stepper?.min || 0.1;
                                  return Number(Math.max(m, v - s).toFixed(2));
                                })
                              }
                              className="border-plus-minus-button-border! text-primary-text! bg-plus-minus-button-bg! hover:bg-plus-minus-button-hover! rounded-[14px]! active:bg-white/5! disabled:cursor-not-allowed disabled:bg-white/3!"
                              style={{
                                borderTop: '1px solid',
                                boxShadow:
                                  'var(--color-plus-minus-button-shadow)',
                                borderImageSource: `linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),
                                    linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))`,
                              }}
                            >
                              <Minus size={16} />
                            </PrimaryActionIcon>
                            <Box
                              size="lg"
                              className="py-2.5! text-center! text-primary-text! w-fit! flex-1 cursor-default! px-3! text-[13px]! font-bold! backdrop-blur-[15.2px]!"
                              style={{
                                borderRadius: '8px',
                                background: '#0000004D',
                              }}
                              aria-readonly
                            >
                              {['days', 'm'].includes(
                                stepper?.unit?.toLowerCase() || ''
                              )
                                ? Math.round(Number(radius))
                                : radius}{' '}
                              {stepper?.unit ?? (isMeters ? 'm' : 'km')}
                            </Box>
                            <PrimaryActionIcon
                              bg="transparent"
                              disabled={!isLatest}
                              size="lg"
                              onClick={() =>
                                isLatest &&
                                setRadius((v) => {
                                  const s = stepper?.step || 0.1;
                                  const mx = stepper?.max || 50;
                                  return Number(Math.min(mx, v + s).toFixed(2));
                                })
                              }
                              className="border-plus-minus-button-border! text-primary-text! bg-plus-minus-button-bg! hover:bg-plus-minus-button-hover! rounded-[14px]! active:bg-white/5! disabled:cursor-not-allowed disabled:bg-white/3!"
                              style={{
                                borderTop: '1px solid',
                                boxShadow:
                                  'var(--color-plus-minus-button-shadow)',
                                borderImageSource: `linear-gradient(0deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.08)),
                                    linear-gradient(0deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.12))`,
                              }}
                            >
                              <Plus size={16} />
                            </PrimaryActionIcon>
                          </Flex>
                          <Box className='p-4 w-full! flex items-center justify-center'>
                            <PrimaryGlassBtn
                              className="w-full!"
                              disabled={!isLatest}
                              onClick={() =>
                                isLatest &&
                                onConfirm?.(
                                  `Q: ${content?.pending_action?.prompt || 'Radius Selection'}\nA: ${radius} ${stepper?.unit || 'km'}`
                                )
                              }
                            >
                              Confirm
                            </PrimaryGlassBtn>
                          </Box>
                        </Box>
                      </Box>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            </motion.div>
          </AnimatePresence>

          <style>{mapStyles}</style>
        </Box>
      </WidgetLayout>
    </>
  );
};

export default WidgetRadiusPickerV2;
