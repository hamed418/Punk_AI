"use client";
import { ActionIcon, Box, TextInput, useMantineColorScheme } from '@mantine/core'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2, MapPin, Search, Minus, Plus } from 'lucide-react'
import type React from 'react'
import { useEffect, useRef, useState } from 'react'
import { useMap, AdvancedMarker, InfoWindow } from '@vis.gl/react-google-maps'
import { getMapSuggestionsAction, getNearbyPlacesAction, searchMapAction } from '@/actions/map.actions'
import { useChat } from '@/contexts/ChatContext'
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn'
import { useMediaQuery } from '@mantine/hooks';

const CustomPin = ({ isSelected }: { isSelected: boolean }) => {
  return (
    <div
      className={`relative flex h-10 w-10 transform items-center justify-center transition-all duration-300 ${
        isSelected ? 'z-50 scale-125' : 'hover:scale-110'
      }`}
    >
      <div
        className={`absolute flex h-8 w-8 -rotate-45 items-center justify-center rounded-full rounded-bl-none bg-[#D62575] shadow-md ${
          isSelected ? 'border-2 border-white' : 'border border-white'
        }`}
      ></div>

      <div className="absolute h-2 w-2 rounded-full bg-white"></div>

      {isSelected && (
        <div className="absolute h-10 w-10 animate-ping rounded-full bg-[#D62575]/30"></div>
      )}
    </div>
  )
}
const widgetPanelStyle = {
  boxShadow: '0px 2px 3px 0px #0000000F',
}

// const widgetPanelClassName =
//   'border-stroke-widget border bg-black/80 relative overflow-hidden backdrop-blur-[1.7px]'

// const widgetNoiseBackground = `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`

const widgetIconGlassStyle = {
  background: 'transparent',
  boxShadow: `
    inset -3px -5px 2.5px -5px #FFFFFF,
    inset 2.5px 3.5px 2px -3.5px #FFFFFF
  `,
}

type SuggestionItem = {
  placePrediction?: {
    text?: { text?: string }
    structuredFormat?: {
      mainText?: { text?: string }
      secondaryText?: { text?: string }
    }
    placeId?: string
  }
}

export type PlaceItem = {
  id?: string
  location?: { latitude?: number; longitude?: number }

  displayName?: { text?: string }
  formattedAddress?: string
  rating?: number
  userRatingCount?: number
  types?: string[]
}
interface ApiResponse {
  places?: PlaceItem[]
}

const POISearch = ({
  setSelectedPlace,
  selectedPlace,
  rightAction,
  searchEnabled,
  onExpandChange,
  placeHolderText,
}: {
  setSelectedPlace?: (places: PlaceItem[]) => void
  selectedPlace?: PlaceItem[]
  rightAction?: React.ReactNode
  searchEnabled?: boolean
  onExpandChange?: (expanded: boolean) => void
  placeHolderText?: string
}) => {
  const chatContext = useChat()
  const { colorScheme } = useMantineColorScheme()
  const showShadow = colorScheme === 'dark'
  const activeSelectedPlace = selectedPlace ?? chatContext.selectedPoiAddress
  const activeSetSelectedPlace =
    setSelectedPlace ?? chatContext.setSelectedPoiAddress
  const map = useMap()
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [nearbyPlaces, setNearbyPlaces] = useState<PlaceItem[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const [openInfoWindowId, setOpenInfoWindowId] = useState<string | null>(null)

  const isSmallScreen = useMediaQuery('(max-width: 1023px)')
  const [isMobileExpanded, setIsMobileExpanded] = useState(false)
  const isExpanded = !isSmallScreen || isMobileExpanded

  useEffect(() => {
    if (onExpandChange) {
      onExpandChange(!!isSmallScreen && isMobileExpanded)
    }
  }, [isSmallScreen, isMobileExpanded, onExpandChange])

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeQueryRef = useRef(query)
  const hideSuggestionsRef = useRef(false)

  // Suggestions fetching with debounce
  useEffect(() => {
    activeQueryRef.current = query
    const fetchSuggestions = async () => {
      if (query.length < 3) {
        setSuggestions([])
        return
      }

      if (hideSuggestionsRef.current) return

      setIsLoading(true)
      try {
        const result = await getMapSuggestionsAction(query, chatContext.activeThreadId ?? undefined)
        if (result.success && activeQueryRef.current === query && !hideSuggestionsRef.current) {
          setSuggestions((result.data as SuggestionItem[]) || [])
          setShowSuggestions(true)
        }
      } catch (error) {
        console.error('Error fetching suggestions:', error)
      } finally {
        if (activeQueryRef.current === query) {
          setIsLoading(false)
        }
      }
    }

    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(fetchSuggestions, 400)

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [query])

  // Close suggestions on outside click and ESC key
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setShowSuggestions(false)
        setIsMobileExpanded(false)
      }
    }
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowSuggestions(false)
        setIsMobileExpanded(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEsc)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEsc)
    }
  }, [])

  const fetchNearbyPlaces = async (lat: number, lng: number) => {
    try {
      const result = await getNearbyPlacesAction(lat, lng, 2000, chatContext.activeThreadId ?? undefined)

      setNearbyPlaces((prev) => [
        ...prev,
        ...((result.data as ApiResponse)?.places || []).filter(
          (place: PlaceItem) => !prev.some((p) => p.id === place.id),
        ),
      ])
    } catch (error) {
      console.error('Nearby search failed:', error)
    }
  }

  const handleSearch = async (searchText: string) => {
    if (!searchText.trim()) return

    setIsLoading(true)
    setShowSuggestions(false)
    try {
      const result = await searchMapAction(searchText, chatContext.activeThreadId ?? undefined)
      const places: PlaceItem[] = (result.data as ApiResponse)?.places || []
      setNearbyPlaces((prev) => [
        ...prev,
        ...places.filter((place: PlaceItem) => !prev.some((p) => p.id === place.id)),
      ])

      if (places.length > 0) {
        const validPlaces = places.filter(
          (p: PlaceItem) => p.location?.latitude && p.location?.longitude,
        )
        const lat = validPlaces[0].location?.latitude
        const lng = validPlaces[0].location?.longitude
        if (lat != null && lng != null) {
          fetchNearbyPlaces(lat, lng)
        }
        if (validPlaces.length === 1) {
          const loc = validPlaces[0].location
          if (loc?.latitude != null && loc?.longitude != null) {
            map?.panTo({ lat: loc.latitude, lng: loc.longitude })
            map?.setZoom(14)
          }
        } else if (validPlaces.length > 1) {
          if (map) {
            const bounds = new google.maps.LatLngBounds()
            validPlaces.forEach((p) => {
              bounds.extend({
                lat: p.location!.latitude!,
                lng: p.location!.longitude!,
              })
            })
            map.fitBounds(bounds, 50)
          }
        }
      }
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectSuggestion = (item: SuggestionItem) => {
    const text = item.placePrediction?.text?.text || ''
    hideSuggestionsRef.current = true
    setQuery(text)
    handleSearch(text)
  }

  const handleSelectPlace = (e: React.MouseEvent, place: PlaceItem) => {
    e.preventDefault()
    e.stopPropagation()
    const currentSelection = activeSelectedPlace || []
    if (currentSelection.some((p: PlaceItem) => p.id === place.id)) {
      activeSetSelectedPlace(
        currentSelection.filter((p: PlaceItem) => p.id !== place.id),
      )
    } else {
      activeSetSelectedPlace([...currentSelection, place])
    }
  }

  // useEffect(() => {
  //   setSelectedPoiAddress(selectedPlace)
  // }, [selectedPlace])

  return (
    <>
      <div
        ref={containerRef}
        className={`absolute top-2 left-0 z-1000 flex w-full items-start gap-3 px-2 ${isExpanded ? '' : 'justify-start lg:justify-center'}`}
      >
        <div className="group relative max-w-73 flex-1">
          {/* Search Bar */}
          {searchEnabled && (
            <motion.div
              layout
              initial={false}
              animate={{ width: isExpanded ? '100%' : '45px' }}
              transition={{ type: 'spring', bounce: 0.1, duration: 0.4 }}
              className="relative h-10 w-full origin-top-left light:border-white/20! light:border! light:backdrop-blur-[57px] light:rounded-full"
            >
              <div
                className={`absolute inset-0 transition-opacity duration-300 ${isExpanded ? 'opacity-100 delay-100' : 'pointer-events-none opacity-0'}`}
              >
                <TextInput
                  ref={searchInputRef}
                  placeholder={placeHolderText || "Search"}
                  value={query}
                  onChange={(e) => {
                    hideSuggestionsRef.current = false
                    setQuery(e.currentTarget.value)
                  }}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch(query)}
                  onFocus={() => query.length >= 3 && setShowSuggestions(true)}
                  variant="unstyled"
                  styles={{
                    root: {
                      width: '100%',
                    },
                    wrapper: {
                      width: '100%',
                      position: 'relative',
                       height: '40px',
                      borderRadius: '9999px',
                      backgroundColor: '#FFFFFF03',
                      backdropFilter: 'blur(75.9000015258789px)',
                      boxShadow: showShadow ? 'var(--shadow-info)' : 'var(--shadow-widget)',
                    },
                    input: {
                      color: '#fff',
                      fontSize: '15px',
                      fontWeight: 500,
                      height: '40px', 
                      lineHeight: '40px',  
                      width: '100%',
                      paddingTop: 0,
                      paddingBottom: '3px',
                      paddingLeft: '24px',
                      paddingRight: '80px',
                      backgroundColor: 'transparent',
                      border: 'none',
                    },
                    section: {
                      position: 'absolute',
                      top: '50%',
                      transform: 'translateY(-50%)',
                       right: '3px',
                      left: 'auto',
                      width: 'auto',
                      height: 'auto',
                      display: 'flex',
                      alignItems: 'center',
                      pointerEvents: 'all',
                    }
                  }}
                  classNames={{
                    input:
                      'placeholder:text-primary-text/70! placeholder:opacity-70! font-normal! focus:outline-none text-primary-text!',
                  }}
                  rightSectionPointerEvents="all"
                  rightSection={
                    <PrimaryGlassBtn
                      onClick={() => handleSearch(query)}
                      className="flex cursor-pointer items-center justify-center rounded-full transition-all duration-200 hover:bg-white/20 active:scale-95"
                      style={{
                        height: '33px',
                        width: '62px',
                        minWidth: '62px',
                        padding: 0,
                      }}
                    >
                      {isLoading ? (
                        <Loader2 className="h-4.5 w-4.5 animate-spin" />
                      ) : (
                        <Search className="h-4.5 w-4.5" />
                      )}
                    </PrimaryGlassBtn>
                  }
                />
              </div>

              <ActionIcon
                unstyled
                onClick={() => {
                  setIsMobileExpanded(true)
                  setTimeout(() => searchInputRef.current?.focus(), 100)
                }}
                className={`absolute inset-0 flex items-center justify-center rounded-full transition-all duration-300 ${isExpanded ? 'pointer-events-none opacity-0' : 'opacity-100 delay-100'} cursor-pointer`}
                style={{
                  backgroundColor: '#FFFFFF03',
                  backdropFilter: 'blur(75.9000015258789px)',
                  WebkitBackdropFilter: 'blur(75.9000015258789px)',
                  boxShadow: showShadow ? 'var(--shadow-info)' : 'none',
                }}
              >
                {/* <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 z-0 rounded-full opacity-15 mix-blend-overlay"
                  style={{ backgroundImage: widgetNoiseBackground }}
                /> */}
                <Search className="text-primary-text relative z-10 h-5 w-5" />
              </ActionIcon>
            </motion.div>
          )}

          {/* Suggestions List */}
          <AnimatePresence>
            {isExpanded && showSuggestions && suggestions.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 15, scale: 0.98 }}
                animate={{ opacity: 1, y: 8, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.98 }}
                style={{
                  ...widgetPanelStyle,
                  backdropFilter: 'blur(75.9px)',
                  WebkitBackdropFilter: 'blur(75.9px)',
                }}
                className="absolute top-full right-0 left-0 z-1000 mt-2 overflow-hidden rounded-2xl border! border-stroke-widget! bg-primary-widget! shadow-widget! light:shadow-sm!"
              >
                {/* <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 z-0 rounded-2xl opacity-15 mix-blend-overlay"
                  style={{ backgroundImage: widgetNoiseBackground }}
                /> */}
                <div className="scrollbar-thumb-divider relative z-10 max-h-87.5 lg:max-h-75.5! xl:max-h-87.5! scrollbar-thin overflow-y-auto py-2">
                  {suggestions.map((item, idx) => {
                    const prediction = item.placePrediction
                    const mainText =
                      prediction?.structuredFormat?.mainText?.text ||
                      prediction?.text?.text
                    const secondaryText =
                      prediction?.structuredFormat?.secondaryText?.text

                    return (
                      <motion.div
                        key={
                          prediction?.placeId || `${mainText}-${secondaryText}`
                        }
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: idx * 0.03 }}
                        onClick={() => handleSelectSuggestion(item)}
                        className="group/item border-underline/20 flex cursor-pointer items-start gap-4 border-b px-5 py-3.5 transition-all duration-200 last:border-none hover:bg-primary-text/5"
                      >
                        <div className="mt-1 shrink-0">
                          <Box
                            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                            style={widgetIconGlassStyle}
                          >
                            <MapPin className="text-primary-text h-4 w-4" />
                          </Box>
                        </div>
                        <div className="flex min-w-0 flex-col pr-2">
                          <span className="text-primary-text truncate text-[15px] leading-tight font-semibold">
                            {mainText}
                          </span>
                          {secondaryText && (
                            <span className="text-secondary-text/60 mt-0.5 truncate text-[12px]">
                              {secondaryText}
                            </span>
                          )}
                        </div>
                      </motion.div>
                    )
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        {rightAction && <div className="shrink-0">{rightAction}</div>}
      </div>

      {/* Render Search Result Markers */}
      {nearbyPlaces.map((place, idx) => {
        const { latitude, longitude } = place.location || {}
        // console.log(place, "===")
        const isSelect = activeSelectedPlace.some(
          (item) => item.id === place.id,
        )
        if (!latitude || !longitude) return null
        const markerId = place.id || idx.toString()

        return (
          <AdvancedMarker
            key={markerId}
            position={{ lat: latitude, lng: longitude }}
            onClick={() => setOpenInfoWindowId(markerId)}
            className="cursor-pointer"
          >
            <CustomPin isSelected={isSelect} />
            {openInfoWindowId === markerId && (
              <InfoWindow
                position={{ lat: latitude, lng: longitude }}
                onCloseClick={() => setOpenInfoWindowId(null)}
                headerDisabled
                className="poi-popup"
                pixelOffset={[0, -30]}
              >
                <div className="max-w-72 min-w-60 p-4 pb-0 pr-0">
                  <div className="mb-1 flex items-start justify-between gap-3">
                    <h3 className="text-primary-text! text-sm leading-tight font-bold">
                      {place.displayName?.text}
                    </h3>
                  </div>
                  <p className="text-secondary-text/60 mb-4 text-xs leading-relaxed">
                    {place.formattedAddress}
                  </p>
                  <PrimaryGlassBtn
                    className="w-full! shadow-lg!"
                    leftSection={
                      isSelect ? <Minus size={16} /> : <Plus size={16} />
                    }
                    onClick={(e) => handleSelectPlace(e, place)}
                  >
                    {isSelect ? 'Remove place' : 'Add place'}
                  </PrimaryGlassBtn>
                </div>
              </InfoWindow>
            )}
          </AdvancedMarker>
        )
      })}
    </>
  )
}

export default POISearch
