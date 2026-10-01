"use client";
import {
  ChevronDown,
  ChevronUp,
  InfoIcon,
  LocateFixed,
  MapPin as MapPinIcon,
  Minus,
  Plus,
} from 'lucide-react'
import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  APIProvider,
  Map as GoogleMap,
  useMap,
  AdvancedMarker,
  Pin,
  type MapMouseEvent,
} from '@vis.gl/react-google-maps'
import type { ConfirmLocationsData, PendingActionBlock } from '@/types/chat'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import PrimaryBtn from '@/components/PrimaryBtn'
import PrimaryActionIcon from '@/components/PrimaryActionIcon'
import WidgetLayout from './WidgetLayout'
import { motion, AnimatePresence } from 'framer-motion'
import { Box, Popover, ScrollArea, Flex, Text, useMantineColorScheme } from '@mantine/core'
import MapWidgetGlassIconButton, {
  MapWidgetGlassPopoverDropdown,
  MapWidgetInfoPopover,
} from '@/components/MapWidgetGlassIconButton'
import WidgetHeaderV2 from '@/components/WidgetHeaderV2'
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn'
// import SecondaryBtn from '@/components/secondaryBtn'
import { PlaceItem } from './WidgetMapAddressSearch'
import LocationMapSearch from './WidgetLocationMapSearch'

import { Circle, ExcludedAreas } from '@/components/MapGeoJsonFeatures'
import SecondaryActionIcon from '@/components/SecondaryActionIcon';

// Fallback default ring for a brand-new manual pin (the "drop pin" toggle)
// when no existing pin_radius location on the map has its own
// server-derived default to borrow (see PinRadiusLocation's usage below).
// Mirrors the backend's own flat fallback (settings.GEO_PIN_RADIUS_FALLBACK_KM).
const MANUAL_PIN_DEFAULT_RADIUS_KM = 10

// Stable identity for a confirm-map location across renders/edits. `place_id`
// is the normal case (a real geocoded place); a pin+radius location the user
// dragged, or a manual pin the backend hasn't assigned a place_id to, falls
// back to its internal source name, then its display name — always
// non-empty for anything the backend actually sent.
function getLocId(loc: { place_id?: string; _source_name?: string; location_name?: string; name?: string }): string {
  return loc.place_id || loc._source_name || loc.location_name || loc.name || ''
}

function formatRadius(km: number): string {
  if (km < 1) return `${Math.round(km * 1000)}m`
  return Math.abs(km - Math.round(km)) < 0.05 ? `${Math.round(km)}km` : `${km.toFixed(1)}km`
}

type PinRadiusOverride = { lat: number; lng: number; radius_km: number }
type ManualPin = { tempId: string; lat: number; lng: number; radius_km: number }

function MapBoundsUpdater({
  locations,
}: {
  locations: Array<{
    lat: number
    lng: number
    radius_km?: number
    bounds?: { lat_min: number; lat_max: number; lng_min: number; lng_max: number }
  }>
}) {
  const map = useMap()
  const locKey = useMemo(
    () => locations.map((l) => `${l.lat.toFixed(4)},${l.lng.toFixed(4)},${l.radius_km ?? 0}`).join(';'),
    [locations],
  )
  const lastKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (!map || locations.length === 0) return
    if (lastKeyRef.current === locKey) return
    lastKeyRef.current = locKey

    try {
      const bounds = new google.maps.LatLngBounds()

      locations.forEach((loc) => {
        if (loc.lat !== 0 || loc.lng !== 0) {
          const rKm = loc.radius_km || 5
          const rMeters = rKm * 1000
          const latOffset = rMeters / 111320
          const lngOffset = rMeters / (111320 * Math.cos((loc.lat * Math.PI) / 180) || 1)
          bounds.extend({ lat: loc.lat - latOffset, lng: loc.lng - lngOffset })
          bounds.extend({ lat: loc.lat + latOffset, lng: loc.lng + lngOffset })
        }
        if (loc.bounds) {
          bounds.extend({ lat: loc.bounds.lat_min, lng: loc.bounds.lng_min })
          bounds.extend({ lat: loc.bounds.lat_max, lng: loc.bounds.lng_max })
        }
      })

      const isPhone = typeof window !== 'undefined' && window.innerWidth < 768
      const rightPadding = isPhone ? 40 : 350

      const timeoutId = setTimeout(() => {
        if (!map) return
        if (bounds.isEmpty()) return

        if (isPhone && bounds.getNorthEast().equals(bounds.getSouthWest())) {
          map.panTo(bounds.getCenter())
          map.setZoom(14)
          return
        }

        map.fitBounds(bounds, { top: 40, bottom: 40, left: 40, right: rightPadding })

        const listener = google.maps.event.addListenerOnce(map, 'idle', () => {
          const currentZoom = map.getZoom()
          const maxZoom = isPhone ? 14 : 13
          if (currentZoom !== undefined && currentZoom > maxZoom) {
            map.setZoom(maxZoom)
          }
        })

        return () => google.maps.event.removeListener(listener)
      }, 300)

      return () => clearTimeout(timeoutId)
    } catch (e) {
      console.warn('MapBoundsUpdater error', e)
    }
  }, [locKey, map, locations])
  return null
}

type AddedLocationItem = {
  name?: string
  lat: number
  lng: number
  radius_km?: number
  parent_location?: string
  parent_poi_type?: string
}

type RemovedLocationItem = {
  name?: string
  lat?: number
  lng?: number
}

type UpdatedLocationItem = {
  name?: string
  lat: number
  lng: number
  radius_km: number
}

type ParsedLocationsPayload = {
  confirm?: boolean
  added?: AddedLocationItem[]
  removed?: RemovedLocationItem[]
  updated?: UpdatedLocationItem[]
}

type DraftLocationsState = {
  selectedPlaces?: PlaceItem[]
  removedLocationIds?: string[]
  pinOverrides?: Record<string, PinRadiusOverride>
  locationRadii?: Record<string, number>
  manualPins?: ManualPin[]
}

function parseUserResponse(res?: string | null): ParsedLocationsPayload | null {
  if (!res) return null
  try {
    let s = res
    if (typeof s !== 'string') return s as ParsedLocationsPayload
    if (s.includes('\nA: ')) s = s.split('\nA: ')[1]
    else if (s.includes('\nA:')) s = s.split('\nA:')[1]
    else if (s.includes('A: ')) s = s.split('A: ')[1]
    else if (s.includes('A:')) s = s.split('A:')[1]
    s = s.trim()
    if (s.startsWith('{')) {
      return JSON.parse(s) as ParsedLocationsPayload
    }
  } catch (e) {
    console.error('Failed to parse userResponse in WidgetLocationMap', e)
  }
  return null
}

export default function LocationMapWidget({
  onConfirm,
  content,
  isLatest = true,
  userResponse,
}: {
  onConfirm?: (val: string) => void
  content: ConfirmLocationsData
  isLatest?: boolean
  userResponse?: string | null
}) {
  const { colorScheme } = useMantineColorScheme()
  const mapColorScheme = colorScheme === 'auto' ? 'FOLLOW_SYSTEM' : colorScheme === 'dark' ? 'DARK' : 'LIGHT'

  // const [selectedOption, setSelectedOption] = useState<string | null>(null)

  // const currentSelection = useMemo(() => {
  //   if (userResponse) {
  //     const parsedResponse = userResponse.includes('A:')
  //       ? userResponse.split('A:')[1].trim()
  //       : userResponse.trim()
  //     return parsedResponse
  //   }
  //   return selectedOption
  // }, [userResponse, selectedOption])
  const locations = useMemo(
    () =>
      content.locations.map((loc) => ({
        ...loc,
        lat: loc.lat ?? loc.latitude ?? 0,
        lng: loc.lng ?? loc.longitude ?? 0,
        name: loc.location_name || loc.name || 'Location',
        address: loc.formatted_address || '',
        place_type: loc.place_type || '',
        place_id: loc.place_id || '',
        bounds: loc.bounds,
      })),
    [content.locations],
  )

  const parsedResponse = useMemo(() => parseUserResponse(userResponse), [userResponse])

  const initialRadii = useMemo(() => {
    const res: Record<string, number> = {}
    if (parsedResponse?.updated && Array.isArray(parsedResponse.updated)) {
      for (const u of parsedResponse.updated) {
        const loc = locations.find(
          (l) => l.name === u.name || (Math.abs(l.lat - u.lat) < 0.001 && Math.abs(l.lng - u.lng) < 0.001)
        )
        if (loc && typeof u.radius_km === 'number') {
          res[getLocId(loc)] = u.radius_km
        }
      }
    }
    if (parsedResponse?.added && Array.isArray(parsedResponse.added)) {
      parsedResponse.added.forEach((a, idx) => {
        if (typeof a.radius_km === 'number') {
          res[`added-${idx}`] = a.radius_km
        }
      })
    }
    return res
  }, [parsedResponse, locations])

  const initialOverrides = useMemo(() => {
    const res: Record<string, PinRadiusOverride> = {}
    if (parsedResponse?.updated && Array.isArray(parsedResponse.updated)) {
      for (const u of parsedResponse.updated) {
        const loc = locations.find(
          (l) => l.name === u.name || (Math.abs(l.lat - u.lat) < 0.001 && Math.abs(l.lng - u.lng) < 0.001)
        )
        if (loc && typeof u.lat === 'number' && typeof u.lng === 'number') {
          res[getLocId(loc)] = { lat: u.lat, lng: u.lng, radius_km: u.radius_km }
        }
      }
    }
    return res
  }, [parsedResponse, locations])

  const initialManualPins = useMemo(() => {
    if (!parsedResponse?.added || !Array.isArray(parsedResponse.added)) return []
    return parsedResponse.added
      .filter((a) => !a.name && !a.parent_location)
      .map((a, idx) => ({
        tempId: `pin-${idx}`,
        lat: a.lat,
        lng: a.lng,
        radius_km: a.radius_km ?? MANUAL_PIN_DEFAULT_RADIUS_KM,
      }))
  }, [parsedResponse])

  const storageKey = useMemo(() => {
    const path = typeof window !== 'undefined' ? window.location.pathname : ''
    const locSig = locations.map((l) => `${getLocId(l)}_${l.lat}_${l.lng}`).join(';')
    return `punk_loc_${path}_${locSig}`
  }, [locations])

  const draftState = useMemo<DraftLocationsState | null>(() => {
    if (typeof window === 'undefined') return null
    try {
      const raw = sessionStorage.getItem(storageKey)
      return raw ? (JSON.parse(raw) as DraftLocationsState) : null
    } catch {
      return null
    }
  }, [storageKey])

  const [open, setOpen] = useState(isLatest)
  const [prevIsLatest, setPrevIsLatest] = useState(isLatest)

  const [selectedPlaces, setSelectedPlaces] = useState<PlaceItem[]>([])
  const [removedLocationIds, setRemovedLocationIds] = useState<string[]>([])
  const [isSearchExpanded, setIsSearchExpanded] = useState(false)

  // Pin+radius editing: all locations now use radius circles (no boundary polygons).
  const [pinOverrides, setPinOverrides] = useState<Record<string, PinRadiusOverride>>(
    () => (parsedResponse ? initialOverrides : draftState?.pinOverrides) ?? {}
  )
  const [locationRadii, setLocationRadii] = useState<Record<string, number>>(
    () => (parsedResponse ? initialRadii : draftState?.locationRadii) ?? {}
  )
  const [manualPins, setManualPins] = useState<ManualPin[]>(
    () => (parsedResponse ? initialManualPins : draftState?.manualPins) ?? []
  )
  const [dropPinMode, setDropPinMode] = useState(false)
  const [expandedLocId, setExpandedLocId] = useState<string | null>(null)

  const activeLocations = useMemo(
    () => locations.filter((loc) => !removedLocationIds.includes(getLocId(loc))),
    [locations, removedLocationIds],
  )
  // What a freshly dropped manual pin starts at — borrow an existing
  // location's server-derived default so the ring reads consistently;
  // fall back to the flat default only when none has one.
  const manualPinDefaultRadiusKm =
    activeLocations.find((l) => l.default_radius_km)?.default_radius_km || MANUAL_PIN_DEFAULT_RADIUS_KM

  // Helper: get the effective radius for any location
  const getLocRadius = (loc: (typeof locations)[0]): number => {
    const id = getLocId(loc)
    return locationRadii[id] ?? pinOverrides[id]?.radius_km ?? loc.search_radius_km ?? loc.default_radius_km ?? loc.radius_km ?? MANUAL_PIN_DEFAULT_RADIUS_KM
  }

  if (isLatest !== prevIsLatest) {
    setPrevIsLatest(isLatest)
    if (!isLatest) {
      setOpen(false)
    }
  }

  const initialCenter = useMemo(() => {
    if (locations.length === 0) return { lat: 0, lng: 0 }
    const lat =
      locations.reduce((sum, loc) => sum + loc.lat, 0) / locations.length
    const lng =
      locations.reduce((sum, loc) => sum + loc.lng, 0) / locations.length
    return { lat, lng }
  }, [locations])

  const initialZoom = locations.length > 1 ? 12 : 15

  // Aggressive Shadow DOM piercing interval to forcefully style any POI popups
  useEffect(() => {
    const forceWhiteText = (node: Node) => {
      if (node instanceof HTMLElement) {
        // Skip images, svgs, and buttons
        const tagName = node.tagName.toLowerCase()
        if (tagName !== 'img' && tagName !== 'svg' && !node.closest('button')) {
          // If it's a title/header, use #faf9f5, else #e3e3e3
          const isTitle = tagName === 'h1' || tagName === 'h2' || tagName === 'h3' || node.classList.contains('title') || node.classList.contains('gm-title')
          
          // Check for light mode
          const isLight = document.documentElement.classList.contains('light') || 
                          document.documentElement.getAttribute('data-mantine-color-scheme') === 'light' || 
                          document.documentElement.getAttribute('data-theme') === 'light'
          
          let targetColor = isTitle ? '#faf9f5' : '#e3e3e3'
          if (isLight) {
            targetColor = isTitle ? '#000000' : '#333333'
          }
          
          // Convert target color to RGB for exact comparison
          let targetRgb = targetColor
          if (targetColor === '#faf9f5') targetRgb = 'rgb(250, 249, 245)'
          if (targetColor === '#e3e3e3') targetRgb = 'rgb(227, 227, 227)'
          if (targetColor === '#000000') targetRgb = 'rgb(0, 0, 0)'
          if (targetColor === '#333333') targetRgb = 'rgb(51, 51, 51)'
          
          if (node.style.color !== targetColor && node.style.color !== targetRgb) {
            node.style.setProperty('color', targetColor, 'important')
            node.style.setProperty('-webkit-text-fill-color', targetColor, 'important')
          }
        }
      }

      // Pierce shadow root if it exists
      if (node instanceof Element && node.shadowRoot) {
        node.shadowRoot.childNodes.forEach(forceWhiteText)
      }

      // Traverse children
      node.childNodes.forEach(forceWhiteText)
    }

    const interval = setInterval(() => {
      // Find standard InfoWindows and new Advanced Web Component InfoWindows
      const iws = document.querySelectorAll(
        '.gm-style-iw-c, .gm-style-iw, .poi-info-window, gmp-info-window'
      )
      if (iws.length > 0) {
        iws.forEach((iw) => {
          forceWhiteText(iw)
        })
      }
    }, 150)

    return () => clearInterval(interval)
  }, [])

  const promptText =
    content.pending_action?.prompt ||
    content.prompt ||
    'Is this the right location?'

  const handleActionConfirm = () => {
    if (onConfirm) {
      const added = [
        ...selectedPlaces.map(place => {
          const spId = place.id || `sp-${place.displayName?.text}`
          const spRadius = locationRadii[spId] ?? MANUAL_PIN_DEFAULT_RADIUS_KM
          return {
            name: place.displayName?.text || place.formattedAddress || 'Unknown Location',
            lat: place.location?.latitude || 0,
            lng: place.location?.longitude || 0,
            parent_location: place.formattedAddress || '',
            parent_poi_type: 'locality',
            radius_km: spRadius,
          }
        }),
        // A manually dropped pin (the "drop pin" toggle) carries no name —
        // the backend reverse-geocodes it for a label instead of geocoding
        // a name (see _new_manual_pin).
        ...manualPins.map(pin => ({
          lat: pin.lat, lng: pin.lng, radius_km: pin.radius_km,
        })),
      ]

      const removed = locations
        .filter(loc => removedLocationIds.includes(getLocId(loc)))
        .map(loc => ({
          name: loc.name || loc.location_name || 'Unknown Location',
          lat: loc.lat || loc.latitude || 0,
          lng: loc.lng || loc.longitude || 0
        }))

      // Any location whose radius or center has been edited.
      const updated = activeLocations
        .map((loc) => {
          const locId = getLocId(loc)
          const override = pinOverrides[locId]
          const currentRadius = getLocRadius(loc)
          const origRadius = loc.search_radius_km ?? loc.default_radius_km ?? loc.radius_km ?? MANUAL_PIN_DEFAULT_RADIUS_KM
          if (!override && currentRadius === origRadius) return null
          return {
            name: loc.name,
            lat: override?.lat ?? loc.lat,
            lng: override?.lng ?? loc.lng,
            radius_km: override?.radius_km ?? currentRadius,
          }
        })
        .filter((u): u is { name: string; lat: number; lng: number; radius_km: number } => u !== null)

      const payload = {
        confirm: true,
        added,
        removed,
        updated,
      }

      onConfirm(`Q: ${promptText}\nA: ${JSON.stringify(payload)}`)
    }
  }

  const actionFooter = content.pending_action && (
    <WidgetActionFooter
      pendingAction={content.pending_action}
      onConfirm={handleActionConfirm}
      isLatest={isLatest}
    />
  )

  // "Drop pin" toggle: while armed, the next map click(s) drop a new
  // pin+radius location at that point (see manualPins). Explicit toggle
  // rather than click-anywhere, so ordinary map panning/clicking never
  // creates an accidental location.
  const handleMapClick = (e: MapMouseEvent) => {
    if (!dropPinMode || !isLatest) return
    const lat = e.detail.latLng?.lat
    const lng = e.detail.latLng?.lng
    if (lat == null || lng == null) return
    setManualPins((prev) => [
      ...prev,
      { tempId: `pin-${Date.now()}-${prev.length}`, lat, lng, radius_km: manualPinDefaultRadiusKm },
    ])
  }

  // Build a list of all locations for the map (radius circles)
  const allMapLocations = useMemo(() => {
    const list: Array<{ id: string; lat: number; lng: number; radius_km: number }> = []
    activeLocations.forEach((loc) => {
      const id = getLocId(loc)
      const override = pinOverrides[id]
      list.push({
        id,
        lat: override?.lat ?? loc.lat,
        lng: override?.lng ?? loc.lng,
        radius_km: getLocRadius(loc),
      })
    })
    selectedPlaces.forEach((place) => {
      const spId = place.id || `sp-${place.displayName?.text}`
      list.push({
        id: spId,
        lat: place.location?.latitude || 0,
        lng: place.location?.longitude || 0,
        radius_km: locationRadii[spId] ?? MANUAL_PIN_DEFAULT_RADIUS_KM,
      })
    })
    manualPins.forEach((pin) => {
      list.push({
        id: pin.tempId,
        lat: pin.lat,
        lng: pin.lng,
        radius_km: pin.radius_km,
      })
    })
    return list
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLocations, selectedPlaces, manualPins, pinOverrides, locationRadii])

  return (
    <WidgetLayout mode="full" className="pointer-events-auto w-full">
      <Box className="border-stroke-widget light:border-[#00000033] relative h-[64dvh] w-full overflow-hidden rounded-lg border-2 md:h-150 lg:h-[64dvh] xl:h-[68dvh] 2xl:h-140">
        <APIProvider apiKey={process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || ''}>
          <div className="google-map-wrapper h-full w-full">
            <GoogleMap
              defaultCenter={initialCenter}
              defaultZoom={initialZoom}
              disableDefaultUI={true}
              zoomControl={true}
              gestureHandling="greedy"
              className={`z-0 h-full w-full ${dropPinMode ? 'cursor-crosshair' : ''}`}
              colorScheme={mapColorScheme}
              mapId="71cf4089bc742721a6237533"
              onClick={handleMapClick}
            >
              <MapBoundsUpdater locations={allMapLocations} />
              <ExcludedAreas areas={content.excluded_areas} />
              <LocationMapSearch
                searchEnabled={isLatest}
                selectedPlace={selectedPlaces}
                setSelectedPlace={setSelectedPlaces}
                placeHolderText="Search and add locations..."
                existingLocations={locations.map((loc) => loc.place_id)}
                onExpandChange={setIsSearchExpanded}
              />

              {/* All locations render as radius circles + pin markers */}
              {allMapLocations.map((item) => {
                const isManual = item.id.startsWith('pin-')
                const color = '#D62575'
                return (
                  <Fragment key={item.id}>
                    <Circle
                      center={{ lat: item.lat, lng: item.lng }}
                      radius={item.radius_km * 1000}
                      editable={isLatest}
                      draggable={isLatest}
                      strokeColor={color}
                      fillColor={color}
                      fillOpacity={0.12}
                      strokeWeight={2}
                      onCenterChanged={(c) => {
                        if (isManual) {
                          setManualPins((prev) => prev.map(
                            (p) => (p.tempId === item.id ? { ...p, lat: c.lat, lng: c.lng } : p),
                          ))
                        } else {
                          setPinOverrides((prev) => ({
                            ...prev,
                            [item.id]: { lat: c.lat, lng: c.lng, radius_km: prev[item.id]?.radius_km ?? item.radius_km },
                          }))
                        }
                      }}
                      onRadiusChanged={(rMeters) => {
                        const rKm = Math.max(0.1, Number((rMeters / 1000).toFixed(1)))
                        if (isManual) {
                          setManualPins((prev) => prev.map(
                            (p) => (p.tempId === item.id ? { ...p, radius_km: rKm } : p),
                          ))
                        } else {
                          setLocationRadii((prev) => ({ ...prev, [item.id]: rKm }))
                          setPinOverrides((prev) => ({
                            ...prev,
                            [item.id]: {
                              lat: prev[item.id]?.lat ?? item.lat,
                              lng: prev[item.id]?.lng ?? item.lng,
                              radius_km: rKm,
                            },
                          }))
                        }
                      }}
                    />
                    <AdvancedMarker position={{ lat: item.lat, lng: item.lng }}>
                      <Pin background={color} borderColor={color} glyphColor={'#FFF'} scale={0.8} />
                    </AdvancedMarker>
                  </Fragment>
                )
              })}
            </GoogleMap>
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
              Each location has a search radius. Drag the circle&apos;s edge to
              resize, or use the slider in the card. Drag the circle to move it.
            </p>
          </MapWidgetGlassPopoverDropdown>
        </MapWidgetInfoPopover>


        {/* Floating Collapsible Widget */}
        <AnimatePresence>
          {!isSearchExpanded && (
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
              className="relative overflow-hidden rounded-[30px] bg-primary-bg/1! dark:backdrop-blur-[75.9px] light:border-white/90! light:border! light:backdrop-blur-[57px] shadow-widget"
            >
              <button
                type="button"
                onClick={() => setOpen(!open)}
                className="relative z-10 w-full text-left"
              >
                <WidgetHeaderV2
                  className={`cursor-pointer items-center! border-b bg-transparent px-4 py-3.5 transition-colors duration-150 ease-out ${open ? 'border-primary-text/5' : 'border-transparent'}`}
                  icon={
                    <div className="flex items-center justify-center rounded-full text-primary-text">
                      <LocateFixed size={20} />
                    </div>
                  }
                  title={<Text span className="text-primary-text! text-[15px]! font-semibold!">Targeting Zone</Text>}
                  // subtitle={
                  //   address ||
                  //   (locations.length === 1 ? (
                  //     <Text span className="text-primary-text/65! text-[11px]!">
                  //       {locations[0].address}
                  //     </Text>
                  //   ) : (
                  //     <Text span className="text-primary-text/65! text-[11px]!"></Text>
                  //   ))
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
                    <Box className="flex flex-col pt-4">
                      <Box className="px-4">
                        <div>
                          <div className="mb-2.5 flex items-center gap-3">
                            <Text span className="text-primary-text! text-[15px]! font-semibold!">
                              Area Found
                              {/* {locations.length > 1 ? 's' : ''} */}
                            </Text>
                          </div>

                          <div
                            style={{
                              background: '#00000018',
                              backdropFilter: 'blur(7.7px)',
                              WebkitBackdropFilter: 'blur(7.7px)',
                            }}
                            className="rounded-md light:backdrop-blur-[7.7px]"
                          >
                            <ScrollArea
                              scrollbars="y"
                              mah={200}
                              type="auto"
                              scrollbarSize={2}
                              className="rounded-none bg-transparent"
                            >
                              {locations.filter(loc => !removedLocationIds.includes(getLocId(loc))).length === 0
                                && selectedPlaces.length === 0 && manualPins.length === 0 ? (
                                <div className="flex items-center justify-between gap-3 border-b border-primary-text/10 px-3 py-3 last:border-none">
                                  <div className="flex flex-col items-start justify-center">
                                    <Text span className="text-sm! font-normal text-primary-text">
                                      No Locations Found
                                    </Text>
                                  </div>
                                </div>
                              ) : (
                                [
                                  ...activeLocations.map((loc) => {
                                    const locId = getLocId(loc)
                                    const radiusKm = getLocRadius(loc)
                                    return {
                                      key: locId || loc.name,
                                      name: loc.name,
                                      address: loc.address || loc.name,
                                      radiusKm,
                                      maxRadius: Math.max(5, Math.ceil(radiusKm)),
                                      onRadiusChange: (r: number) => {
                                        setLocationRadii(prev => ({ ...prev, [locId]: r }))
                                        setPinOverrides(prev => ({
                                          ...prev,
                                          [locId]: {
                                            lat: prev[locId]?.lat ?? loc.lat,
                                            lng: prev[locId]?.lng ?? loc.lng,
                                            radius_km: r,
                                          },
                                        }))
                                      },
                                      onRemove: () => setRemovedLocationIds(prev => [...prev, locId]),
                                    }
                                  }),
                                  ...selectedPlaces.map((place, i) => {
                                    const spId = place.id || `sp-${place.displayName?.text}`
                                    const spKey = `sp-${place.id || i}`
                                    const spRadius = locationRadii[spId] ?? MANUAL_PIN_DEFAULT_RADIUS_KM
                                    return {
                                      key: spKey,
                                      name: place.displayName?.text || place.formattedAddress || 'Unknown Location',
                                      address: place.formattedAddress || '',
                                      radiusKm: spRadius,
                                      maxRadius: Math.max(5, Math.ceil(spRadius)),
                                      onRadiusChange: (r: number) => {
                                        setLocationRadii(prev => ({ ...prev, [spId]: r }))
                                      },
                                      onRemove: () => setSelectedPlaces(prev => prev.filter((_, pi) => pi !== i)),
                                    }
                                  }),
                                  ...manualPins.map((pin) => ({
                                    key: pin.tempId,
                                    name: 'Dropped pin',
                                    address: `${pin.lat.toFixed(3)}, ${pin.lng.toFixed(3)}`,
                                    radiusKm: pin.radius_km,
                                    maxRadius: Math.max(5, Math.ceil(pin.radius_km)),
                                    onRadiusChange: (r: number) => {
                                      setManualPins(prev => prev.map(p => p.tempId === pin.tempId ? { ...p, radius_km: r } : p))
                                    },
                                    onRemove: () => setManualPins(prev => prev.filter(p => p.tempId !== pin.tempId)),
                                  })),
                                ].map((row) => {
                                  const isRowExpanded = expandedLocId === row.key
                                  return (
                                  <div
                                    key={row.key}
                                    className="border-b border-primary-text/10 px-3 py-3 last:border-none"
                                  >
                                    <div className="flex items-center justify-between gap-2">
                                      <div className="flex flex-col items-start justify-center min-w-0 overflow-hidden">
                                        <Text span
                                          className="text-primary-text! truncate! w-full! text-xs! font-semibold!"
                                          title={row.name}
                                        >
                                          {row.name}
                                        </Text>
                                        <Text span className="text-primary-text/65! truncate! w-full! text-[11px]!">
                                          {row.address}
                                        </Text>
                                      </div>
                                      <div className="flex items-center gap-1.5 shrink-0">
                                        {/* Radius pill with expand toggle */}
                                        <button
                                          type="button"
                                          onClick={() => setExpandedLocId(isRowExpanded ? null : row.key)}
                                          className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/15 active:bg-white/20 text-primary-text text-[11px] font-medium transition cursor-pointer select-none whitespace-nowrap"
                                        >
                                          <span>{formatRadius(row.radiusKm)}</span>
                                          {isRowExpanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                                        </button>
                                        <SecondaryActionIcon
                                          className="bg-white/10! hover:bg-white/7! active:bg-white/7! disabled:bg-white/5! disabled:cursor-not-allowed disabled:opacity-50"
                                          disabled={!isLatest}
                                          onClick={() => isLatest && row.onRemove()}
                                        >
                                          <Minus size={12} strokeWidth={3} />
                                        </SecondaryActionIcon>
                                      </div>
                                    </div>
                                    {/* Expandable radius stepper */}
                                    <AnimatePresence initial={false}>
                                      {isRowExpanded && (
                                        <motion.div
                                          initial={{ height: 0, opacity: 0 }}
                                          animate={{ height: 'auto', opacity: 1 }}
                                          exit={{ height: 0, opacity: 0 }}
                                          transition={{ duration: 0.18, ease: 'easeInOut' }}
                                          className="overflow-hidden"
                                        >
                                          <div className="pt-3 pb-1">
                                            <div className="flex justify-between items-center mb-2">
                                              <Text span className="text-primary-text/80! text-[11px]!">Search radius</Text>
                                            </div>
                                            <Flex align="center" justify="center" gap={8}>
                                              <PrimaryActionIcon
                                                disabled={!isLatest || row.radiusKm <= 0.1}
                                                bg="transparent"
                                                size="lg"
                                                onClick={() => {
                                                  if (!isLatest) return
                                                  const step = row.radiusKm >= 1 ? 0.5 : 0.1
                                                  const next = Math.max(0.1, Number((row.radiusKm - step).toFixed(1)))
                                                  row.onRadiusChange(next)
                                                }}
                                                className="hover:bg-transparent! active:bg-transparent!"
                                                style={{
                                                  border: '1px solid rgba(255, 255, 255, 0.12)',
                                                  borderRadius: '14px',
                                                  boxShadow: '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                                                }}
                                              >
                                                <Minus size={16} />
                                              </PrimaryActionIcon>
                                              <PrimaryActionIcon
                                                bg="transparent"
                                                size="lg"
                                                className="w-fit! cursor-default! bg-[#00000008] px-3! text-[11px]! font-normal! hover:bg-transparent! active:transform-none! active:bg-transparent!"
                                                style={{
                                                  border: '1px solid rgba(255, 255, 255, 0.12)',
                                                  borderRadius: '14px',
                                                  boxShadow: '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                                                  backdropFilter: 'blur(15px)',
                                                }}
                                                aria-readonly
                                              >
                                                {formatRadius(row.radiusKm)}
                                              </PrimaryActionIcon>
                                              <PrimaryActionIcon
                                                disabled={!isLatest}
                                                bg="transparent"
                                                size="lg"
                                                onClick={() => {
                                                  if (!isLatest) return
                                                  const step = row.radiusKm >= 1 ? 0.5 : 0.1
                                                  const next = Number((row.radiusKm + step).toFixed(1))
                                                  row.onRadiusChange(next)
                                                }}
                                                className="hover:bg-transparent! active:bg-transparent!"
                                                style={{
                                                  border: '1px solid rgba(255, 255, 255, 0.12)',
                                                  borderRadius: '14px',
                                                  boxShadow: '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                                                }}
                                              >
                                                <Plus size={16} />
                                              </PrimaryActionIcon>
                                            </Flex>
                                          </div>
                                        </motion.div>
                                      )}
                                    </AnimatePresence>
                                  </div>
                                )})
                              )}
                            </ScrollArea>
                          </div>
                        </div>
                      </Box>

                      {/* Add location button inside widget */}
                      {isLatest && (
                        <div className="px-4 pt-2.5">
                          <button
                            type="button"
                            onClick={() => setDropPinMode((v) => !v)}
                            className={`flex w-full items-center justify-center gap-1.5 rounded-full px-3 py-2 text-[11px] font-medium transition-all duration-150 cursor-pointer select-none whitespace-nowrap ${
                              dropPinMode
                                ? 'bg-white/15 text-primary-text'
                                : 'bg-white/7 text-primary-text/60 hover:bg-white/12 hover:text-primary-text/80'
                            }`}
                          >
                            {dropPinMode ? (
                              <>
                                <MapPinIcon size={12} className="text-primary-text/80 shrink-0" />
                                <span>Tap on map to pin</span>
                                <span className="text-[10px] text-primary-text/50 hover:text-primary-text/80 ml-0.5 shrink-0">
                                  (Cancel)
                                </span>
                              </>
                            ) : (
                              <>
                                <Plus size={12} className="shrink-0" />
                                <span>Add location</span>
                              </>
                            )}
                          </button>
                        </div>
                      )}

                      {actionFooter && (
                        <div className="px-4 pb-4 mt-4 border-t border-primary-text/5">
                          <div className="pt-4">
                            {/* <div className="font-inter text-primary-text mb-2 text-xs font-medium">
                              {promptText}
                            </div> */}
                            {/* <Flex className="items-center! pb-1.5! justify-between! pt-4"> */}
                              {/* <button
                                className="text-primary-text cursor-pointer border-0 bg-transparent pl-3 text-[12px]! disabled:text-primary-text/60! disabled:hover:no-underline disabled:cursor-not-allowed font-semibold hover:underline -mb-2"
                                disabled={!isLatest}
                                onClick={() => {
                                  if (isLatest) {
                                    // setSelectedOption('No')
                                    onConfirm?.(`Q: ${promptText}\nA: No`)
                                  }
                                }}
                              >
                                No
                              </button> */}
                              <PrimaryGlassBtn
                              className='w-full! text-[13px]!'
                                onClick={() => {
                                  if (isLatest) {
                                    handleActionConfirm()
                                  }
                                }}
                                disabled={!isLatest}
                              >
                                Use Zone
                              </PrimaryGlassBtn>
                            {/* </Flex> */}
                          </div>
                        </div>
                      )}
                    </Box>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </motion.div>
          )}
        </AnimatePresence>

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
          
          /* Force all text inside Google Maps InfoWindow/POI popups to use specific hex colors */
          .gm-style .gm-style-iw-c,
          .gm-style .gm-style-iw-d,
          .gm-style .gm-style-iw-d *,
          .gm-style .poi-info-window,
          .gm-style .poi-info-window *,
          .gm-style .poi-info-window div,
          .gm-style .poi-info-window span,
          .gm-style .poi-info-window a,
          .gm-style .poi-info-window p {
            color: #e3e3e3 !important;
          }
          
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .gm-style-iw-c,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .gm-style-iw-d,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .gm-style-iw-d *,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window *,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window div,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window span,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window a,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window p {
            color: #333333 !important;
          }
          
          .gm-style .poi-info-window h1,
          .gm-style .poi-info-window h2,
          .gm-style .poi-info-window h3,
          .gm-style .poi-info-window .title {
            color: #faf9f5 !important;
          }

          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window h1,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window h2,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window h3,
          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style .poi-info-window .title {
            color: #000000 !important;
          }
          
          /* Extra robust selector for deeply nested text */
          .gm-style-iw-c :not(img):not(button):not(svg) {
            color: #e3e3e3 !important;
          }

          :where(.light, [data-mantine-color-scheme="light"], [data-theme="light"]) .gm-style-iw-c :not(img):not(button):not(svg) {
            color: #333333 !important;
          }
        `}
        </style>
      </Box>
    </WidgetLayout>
  )
}

interface WidgetActionFooterProps {
  pendingAction: PendingActionBlock['content']
  onConfirm?: (value: string) => void
  isLatest?: boolean
  value?: number
  onChange?: (val: number) => void
  step?: number
  min?: number
  max?: number
  confirmText?: string
  showPrompt?: boolean
}

function WidgetActionFooter({
  pendingAction,
  onConfirm,
  isLatest = true,
  value,
  onChange,
  step,
  min,
  max,
  confirmText,
  showPrompt = true,
}: WidgetActionFooterProps) {
  const isDays = pendingAction.stepper?.unit?.toLowerCase() === 'days'

  const [localStepperValue, setLocalStepperValue] = useState(
    pendingAction.stepper?.default ?? pendingAction.stepper?.min ?? 0,
  )

  const stepperValue =
    value !== undefined && !isDays ? value : localStepperValue
  const setStepperValue = (val: number | ((v: number) => number)) => {
    if (typeof val === 'function') {
      const nextVal = val(stepperValue)
      if (onChange && !isDays) onChange(nextVal)
      else setLocalStepperValue(nextVal)
    } else {
      if (onChange && !isDays) onChange(val)
      else setLocalStepperValue(val)
    }
  }

  const handleConfirm = () => {
    if (pendingAction.action_type === 'stepper_input') {
      onConfirm?.(stepperValue.toString())
    } else {
      onConfirm?.(confirmText || 'Confirm')
    }
  }

  return (
    <div>
      <div className="flex flex-col gap-2">
        {pendingAction.progress && pendingAction.progress.length > 0 && (
          <div className="bg-secondary-widget mt-3 overflow-hidden rounded-sm last:border-none">
            {pendingAction.progress.length === 1 ? (
              <Box className="border-underline/30 w-full border-b px-3 py-2">
                <p className="text-primary-text w-full text-[13px] font-semibold uppercase">
                  {pendingAction.progress[0].label}
                </p>
                <p className="text-primary-text text-[11px]">
                  {pendingAction.progress[0].value}
                </p>
              </Box>
            ) : (
              pendingAction.progress.map((p) => {
                let displayValue = p.value
                if (typeof p.value === 'string') {
                  const numMatch = p.value.match(/^(\d+\.?\d*)\s*(.*)$/)
                  if (numMatch) {
                    const num = parseFloat(numMatch[1])
                    const unit = numMatch[2].toLowerCase()
                    if (unit === 'days' || unit === 'm') {
                      displayValue = `${Math.round(num)} ${numMatch[2]}`
                    } else if (unit === 'km' || unit === 'miles') {
                      displayValue = `${num.toFixed(1)} ${numMatch[2]}`
                    }
                  }
                }

                return (
                  <Box
                    key={`progress-${p.label}`}
                    className="border-underline/30 w-full border-b px-3 py-2 last:border-none"
                  >
                    <p className="text-primary-text w-full text-[13px] font-semibold uppercase">
                      {p.label}
                    </p>
                    <p className="text-primary-text text-[11px]">{displayValue}</p>
                  </Box>
                )
              })
            )}
          </div>
        )}
        {/* Prompt Section */}
        {showPrompt && (
          <div className="flex items-start gap-2 px-1 py-2 md:gap-3">
            <div className="w-full space-y-4">
              <div className="font-inter text-primary-text text-[13px]">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {pendingAction.prompt}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}
        {/* Action Buttons */}
        {pendingAction.action_type === 'stepper_input' ? (
          <Box className="flex w-full flex-wrap items-center justify-between gap-2 pt-3">
            <Flex align="center" justify="center" gap={8}>
              <PrimaryActionIcon
                disabled={!isLatest}
                bg="transparent"
                size="lg"
                onClick={() =>
                  isLatest &&
                  setStepperValue((v) => {
                    const s = step ?? pendingAction.stepper?.step ?? 1
                    const m = min ?? pendingAction.stepper?.min ?? 0
                    return Number(Math.max(m, v - s).toFixed(2))
                  })
                }
                className="hover:bg-transparent! active:bg-transparent!"
                style={{
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '14px',
                  boxShadow:
                    '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                }}
              >
                <Minus size={16} />
              </PrimaryActionIcon>
              <PrimaryActionIcon
                bg="transparent"
                size="lg"
                className="w-fit! cursor-default! bg-[#00000008] px-3! text-[11px]! font-normal! hover:bg-transparent! active:transform-none! active:bg-transparent!"
                style={{
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '14px',
                  boxShadow:
                    '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                  backdropFilter: 'blur(15px)',
                }}
                aria-readonly
              >
                {['days', 'm'].includes(
                  pendingAction.stepper?.unit?.toLowerCase() || '',
                )
                  ? Math.round(Number(stepperValue))
                  : stepperValue}{' '}
                {pendingAction.stepper?.unit}
              </PrimaryActionIcon>
              <PrimaryActionIcon
                disabled={!isLatest}
                bg="transparent"
                size="lg"
                onClick={() =>
                  isLatest &&
                  setStepperValue((v) => {
                    const s = step ?? pendingAction.stepper?.step ?? 1
                    const mx = max ?? pendingAction.stepper?.max ?? 9999
                    return Number(Math.min(mx, v + s).toFixed(2))
                  })
                }
                className="hover:bg-transparent! active:bg-transparent!"
                style={{
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  borderRadius: '14px',
                  boxShadow:
                    '0px 2px 12px 0px #00000040, 0px 1px 0px 0px #FFFFFF40 inset',
                }}
              >
                <Plus size={16} />
              </PrimaryActionIcon>
            </Flex>
            <PrimaryBtn onClick={handleConfirm} disabled={!isLatest}>
              {confirmText || 'Confirm'}
            </PrimaryBtn>
          </Box>
        ) : (
          <div className="flex w-full flex-col items-start justify-between gap-4 px-1">
            <Box className="flex w-full items-center justify-between pb-2">
              <Box>
                <Text fz={13} className="text-secondary-text">
                  Review and proceed
                </Text>
              </Box>
              <PrimaryBtn onClick={handleConfirm} disabled={!isLatest}>
                {confirmText || 'Confirm'}
              </PrimaryBtn>
            </Box>
          </div>
        )}
      </div>
    </div>
  )
}
