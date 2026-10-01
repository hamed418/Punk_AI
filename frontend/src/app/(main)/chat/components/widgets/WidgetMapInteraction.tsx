"use client";
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn'
import type { PendingActionBlock } from '@/types/chat'
import { Check, InfoIcon, MapPin, ChevronDown, ChevronUp } from 'lucide-react'
import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  APIProvider,
  Map as GoogleMap,
  AdvancedMarker,
} from '@vis.gl/react-google-maps'
import WidgetLayout from './WidgetLayout'
import WidgetHeaderV2 from '@/components/WidgetHeaderV2'
import MapWidgetGlassIconButton, {
  MapWidgetGlassPopoverDropdown,
  MapWidgetInfoPopover,
} from '@/components/MapWidgetGlassIconButton'
import { Box, Popover, useMantineColorScheme } from '@mantine/core'
import { motion, AnimatePresence } from 'framer-motion'

const mapStyles = `
  .google-map-wrapper {
    height: 100%;
    width: 100%;
  }
  .google-map-wrapper > div {
    background: var(--bg-chat) !important;
  }
  .google-map-wrapper.confirmed {
    cursor: default !important;
  }
`

export default function WidgetMapInteraction({
  content,
  onConfirm,
  isLatest = true,
  userResponse = null,
}: {
  content: PendingActionBlock['content']
  onConfirm?: (val: string) => void
  isLatest?: boolean
  userResponse?: string | null
}) {
  const { colorScheme } = useMantineColorScheme()
  const mapColorScheme =
    colorScheme === 'auto'
      ? 'FOLLOW_SYSTEM'
      : colorScheme === 'dark'
        ? 'DARK'
        : 'LIGHT'

  const parsedResponse = useMemo(() => {
    if (!userResponse) return null
    try {
      const jsonStr = userResponse.includes('A: ')
        ? userResponse.split('A: ')[1].trim()
        : userResponse.trim()
      const parsed = JSON.parse(jsonStr)
      if (
        typeof parsed === 'object' &&
        parsed !== null &&
        'lat' in parsed &&
        'lng' in parsed
      ) {
        return parsed as { lat: number; lng: number; place?: string }
      }
    } catch (e) {
      console.error('Failed to parse userResponse json', e)
    }
    return null
  }, [userResponse])

  const initialCenter = parsedResponse
    ? { lat: parsedResponse.lat, lng: parsedResponse.lng }
    : { lat: 20, lng: 0 }
  const initialZoom = parsedResponse ? 13 : 2

  const [markerPos, setMarkerPos] = useState<{
    lat: number
    lng: number
  } | null>(
    parsedResponse
      ? { lat: parsedResponse.lat, lng: parsedResponse.lng }
      : null,
  )
  const [confirmed, setConfirmed] = useState(!!userResponse || !isLatest)
  const [open, setOpen] = useState(isLatest)
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest)
  const [placeName, setPlaceName] = useState<string | null>(
    parsedResponse?.place || null,
  )
  const [geocoding, setGeocoding] = useState(false)

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest)
    if (!isLatest) {
      setOpen(false)
    }
  }

  const handleLocationSelect = useCallback(
    (latLng: { lat: number; lng: number }) => {
      if (!isLatest || confirmed) return
      setMarkerPos({ lat: latLng.lat, lng: latLng.lng })
      setPlaceName(null)
      setGeocoding(true)
    },
    [isLatest, confirmed],
  )

  // Reverse-geocode via Google Geocoding API
  useEffect(() => {
    if (!markerPos) return
    let cancelled = false
    const { lat, lng } = markerPos

    // Skip geocoding if it matches the restored response from history
    if (
      parsedResponse &&
      lat === parsedResponse.lat &&
      lng === parsedResponse.lng &&
      placeName === parsedResponse.place
    ) {
      return
    }

    const apiKey =
      process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ||
      process.env.GOOGLE_MAPS_API_KEY ||
      process.env.VITE_GOOGLE_MAPS_API_KEY ||
      ''

    // Small debounce so rapid clicks don't spam Google
    const timer = setTimeout(() => {
      const keyParam = apiKey ? `&key=${apiKey}` : ''
      fetch(
        `https://maps.googleapis.com/maps/api/geocode/json?latlng=${lat},${lng}${keyParam}`,
      )
        .then((res) => res.json())
        .then((data) => {
          if (cancelled) return
          if (data && data.results && data.results[0]) {
            setPlaceName(data.results[0].formatted_address)
          } else {
            setPlaceName(`${lat.toFixed(4)}, ${lng.toFixed(4)}`)
          }
        })
        .catch(() => {
          if (!cancelled) setPlaceName(`${lat.toFixed(4)}, ${lng.toFixed(4)}`)
        })
        .finally(() => {
          if (!cancelled) setGeocoding(false)
        })
    }, 300)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [markerPos, parsedResponse, placeName])

  const handleConfirm = useCallback(() => {
    if (markerPos) {
      const name =
        placeName ?? `${markerPos.lat.toFixed(6)}, ${markerPos.lng.toFixed(6)}`
      setConfirmed(true)
      onConfirm?.(
        `Q: Pin your target location on the map\nA: ${JSON.stringify({ lat: markerPos.lat, lng: markerPos.lng, place: name })}`,
      )
    }
  }, [markerPos, placeName, onConfirm])

  return (
    <>
      <WidgetLayout mode="full">
        <Box className="border-stroke-widget light:border-[#00000033] relative h-[64dvh] w-full overflow-hidden rounded-lg border-2 md:h-150 lg:h-[64dvh] xl:h-[68dvh] 2xl:h-140">
          <APIProvider
            apiKey={
              process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ||
              process.env.GOOGLE_MAPS_API_KEY ||
              process.env.VITE_GOOGLE_MAPS_API_KEY ||
              ''
            }
          >
            <div
              className={`google-map-wrapper h-full w-full ${confirmed ? 'confirmed' : ''}`}
            >
              <GoogleMap
                defaultCenter={initialCenter}
                defaultZoom={initialZoom}
                disableDefaultUI={true}
                zoomControl={true}
                gestureHandling="greedy"
                className="z-0 h-full w-full"
                mapId="radius-picker-map"
                colorScheme={mapColorScheme}
                onClick={(e) => {
                  if (e.detail.latLng) {
                    handleLocationSelect(e.detail.latLng)
                  }
                }}
              >
                {markerPos && (
                  <AdvancedMarker position={markerPos}>
                    <div className="relative flex items-center justify-center bg-transparent">
                      {!confirmed && (
                        <div className="absolute h-12 w-12 animate-ping rounded-full bg-[#D62575]/20"></div>
                      )}
                      <svg
                        width="27"
                        height="32"
                        viewBox="0 0 27 32"
                        fill="none"
                        xmlns="http://www.w3.org/2000/svg"
                        className="relative z-10 drop-shadow-md"
                      >
                        <path
                          d="M13.125 0C5.88794 0 0 5.88794 0 13.125C0 18.96 3.845 24.0756 9.40256 25.7141L12.2864 31.4817C12.3642 31.6375 12.4839 31.7685 12.632 31.86C12.7801 31.9516 12.9508 32.0001 13.1249 32.0001C13.299 32.0001 13.4697 31.9516 13.6178 31.86C13.7659 31.7685 13.8856 31.6375 13.9634 31.4817L16.8471 25.7144C22.405 24.0759 26.25 18.9602 26.25 13.125C26.25 5.88794 20.3621 0 13.125 0ZM13.125 16.875C11.0571 16.875 9.375 15.1929 9.375 13.125C9.375 11.0571 11.0571 9.375 13.125 9.375C15.1929 9.375 16.875 11.0571 16.875 13.125C16.875 15.1929 15.1929 16.875 13.125 16.875Z"
                          fill="#D62575"
                        />
                      </svg>
                    </div>
                  </AdvancedMarker>
                )}
              </GoogleMap>
            </div>
          </APIProvider>

          {/* Map Info Popover */}
          <MapWidgetInfoPopover>
            <Popover.Target>
              <MapWidgetGlassIconButton title="Information">
                <InfoIcon size={16} />
              </MapWidgetGlassIconButton>
            </Popover.Target>
            <MapWidgetGlassPopoverDropdown>
              <p className="text-primary-text text-sm">
                {content.prompt ||
                  'Click anywhere on the map to drop a pin. This will be the center of your campaign geofence.'}
              </p>
            </MapWidgetGlassPopoverDropdown>
          </MapWidgetInfoPopover>

          {/* Floating Collapsible Widget — top-right */}
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
                  className="relative z-10 w-full text-left"
                  onClick={() => setOpen(!open)}
                >
                  <WidgetHeaderV2
                    className={`cursor-pointer border-b bg-transparent p-0 px-4 py-3.5 transition-colors duration-150 ease-out ${open ? 'border-primary-text/5' : 'border-transparent'}`}
                    icon={
                      <svg
                        width="12"
                        height="15"
                        viewBox="0 0 12 15"
                        fill="none"
                        className="text-primary-text"
                        xmlns="http://www.w3.org/2000/svg"
                      >
                        <path
                          d="M9.81095 1.36686C9.11933 0.800567 8.31066 0.394825 7.44325 0.178896C6.57585 -0.0370333 5.67133 -0.0577661 4.79495 0.118193C3.6681 0.349219 2.63141 0.899294 1.80837 1.70289C0.98533 2.50649 0.410635 3.52973 0.152741 4.65074C-0.105152 5.77174 -0.0353736 6.94325 0.353766 8.02572C0.742905 9.10819 1.435 10.056 2.34761 10.7562C3.38957 11.5188 4.27671 12.4729 4.96161 13.5675L5.42828 14.3435C5.48755 14.4421 5.57131 14.5237 5.67142 14.5803C5.77154 14.6369 5.8846 14.6666 5.99961 14.6666C6.11463 14.6666 6.22769 14.6369 6.3278 14.5803C6.42792 14.5237 6.51168 14.4421 6.57095 14.3435L7.01828 13.5982C7.61469 12.5498 8.4279 11.6407 9.40361 10.9315C10.1687 10.4051 10.801 9.70818 11.2506 8.89561C11.7002 8.08305 11.9548 7.17712 11.9944 6.2493C12.0339 5.32149 11.8573 4.39717 11.4785 3.54928C11.0997 2.70139 10.5291 1.95313 9.81161 1.36353L9.81095 1.36686ZM5.99895 8.66753C5.47153 8.66753 4.95596 8.51113 4.51743 8.21811C4.0789 7.92509 3.7371 7.50862 3.53527 7.02135C3.33343 6.53408 3.28063 5.9979 3.38352 5.48062C3.48641 4.96334 3.74039 4.48818 4.11333 4.11524C4.48627 3.7423 4.96142 3.48833 5.47871 3.38543C5.99599 3.28254 6.53217 3.33535 7.01944 3.53718C7.50671 3.73901 7.92318 4.08081 8.2162 4.51934C8.50922 4.95787 8.66561 5.47344 8.66561 6.00086C8.66561 6.7081 8.38466 7.38638 7.88456 7.88648C7.38447 8.38657 6.70619 8.66753 5.99895 8.66753Z"
                          fill="currentColor"
                        />
                      </svg>
                    }
                    title="Pinned Location"
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
                      <Box className="flex flex-col pb-3 pt-4">
                        {!confirmed ? (
                          <Box className="px-4">
                            {/* Status */}
                            <div className="mb-3 space-y-2">
                              <div
                                className={`flex items-center gap-2 text-[13px] font-semibold transition-colors ${markerPos ? 'text-emerald-500' : 'text-secondary-text'}`}
                              >
                                <Check size={14} strokeWidth={3} />
                                {markerPos ? 'Location Selected' : 'Waiting for Pin'}
                              </div>
                            </div>

                            {/* Prompt */}
                            <p className="text-secondary-text mb-3 text-[13px] leading-relaxed">
                              {content.prompt ||
                                'Click anywhere on the map to drop a pin.'}
                            </p>

                            {/* Location card */}
                            {markerPos && (
                              <div className="border-stroke-widget bg-widget-inner-glass-bg! light:backdrop-blur-[15.2px] light:border-none relative mb-3 overflow-hidden rounded-md border p-3">
                                <p className="text-secondary-text mb-0.5 text-[10px] font-black tracking-widest uppercase">
                                  Location
                                </p>
                                {geocoding ? (
                                  <p className="text-secondary-text animate-pulse text-[12px] italic">
                                    Resolving location…
                                  </p>
                                ) : (
                                  <p className="text-primary-text text-[12px] leading-snug font-semibold">
                                    {placeName}
                                  </p>
                                )}
                                {/* Raw coords */}
                                <p className="text-secondary-text mt-1 font-mono text-[10px]">
                                  {markerPos.lat.toFixed(6)},{' '}
                                  {markerPos.lng.toFixed(6)}
                                </p>
                              </div>
                            )}
                          </Box>
                        ) : (
                          markerPos && (
                            <Box className="px-4 pb-4">
                              <div className="border-stroke-widget backdrop-blur-[15.2px]! light:border-none relative overflow-hidden rounded-md border p-3"
                                style={{
                                  background: '#0000004D',
                                }}
                              >
                                <p className="text-secondary-text mb-0.5 text-[10px] font-black tracking-widest uppercase">
                                  Pinned Location
                                </p>
                                <p className="text-primary-text text-[12px] leading-snug font-semibold">
                                  {placeName ??
                                    `${markerPos.lat.toFixed(4)}, ${markerPos.lng.toFixed(4)}`}
                                </p>
                              </div>
                            </Box>
                          )
                        )}

                        <Box className="border-primary-text/10 flex w-full flex-wrap items-center justify-end gap-3 border-t px-4">
                          <Box className="flex w-full items-center justify-center pt-4 pb-1">
                            <PrimaryGlassBtn
                              className="w-full!"
                              onClick={handleConfirm}
                              disabled={
                                confirmed || !markerPos || !onConfirm || !isLatest || geocoding
                              }
                            >
                              {confirmed
                                ? 'Location Confirmed'
                                : geocoding
                                  ? 'Resolving…'
                                  : 'Confirm Pin'}
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

          {/* "Click map" hint — hidden once pinned or confirmed */}
          <AnimatePresence>
            {!markerPos && !confirmed && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.25, ease: 'easeOut' }}
                className="pointer-events-none absolute top-1/2 left-1/2 z-50 -translate-x-1/2 -translate-y-1/2"
              >
                <div className="border-primary-text/10 bg-primary-bg/80 text-primary-text flex items-center gap-3 rounded-full border px-6 py-3 shadow-widget backdrop-blur-md">
                  <MapPin size={20} />
                  <span className="text-sm font-bold tracking-widest whitespace-nowrap uppercase">
                    Click map to start
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <style>{mapStyles}</style>
        </Box>
      </WidgetLayout>
    </>
  )
}

