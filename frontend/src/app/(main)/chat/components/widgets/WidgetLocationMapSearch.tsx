'use client';
import {
  ActionIcon,
  Box,
  TextInput,
  useMantineColorScheme,
} from '@mantine/core';
import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, MapPin, Search } from 'lucide-react';
import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { useMap } from '@vis.gl/react-google-maps';
import {
  getMapSuggestionsAction,
  getNearbyPlacesAction,
  searchMapAction,
} from '@/actions/map.actions';
import { useChat } from '@/contexts/ChatContext';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import { useMediaQuery } from '@mantine/hooks';

const widgetIconGlassStyle = {
  background: 'transparent',
  boxShadow: `
    inset -3px -5px 2.5px -5px #FFFFFF,
    inset 2.5px 3.5px 2px -3.5px #FFFFFF
  `,
};

const widgetPanelStyle = {
  boxShadow: '0px 2px 3px 0px #0000000F',
};

type SuggestionItem = {
  placePrediction?: {
    text?: { text?: string };
    structuredFormat?: {
      mainText?: { text?: string };
      secondaryText?: { text?: string };
    };
    placeId?: string;
  };
};

export type PlaceItem = {
  id?: string;
  location?: { latitude?: number; longitude?: number };

  displayName?: { text?: string };
  formattedAddress?: string;
  rating?: number;
  userRatingCount?: number;
  types?: string[];
};
interface ApiResponse {
  places?: PlaceItem[];
}

const LocationMapSearch = ({
  setSelectedPlace,
  selectedPlace,
  rightAction,
  searchEnabled,
  onExpandChange,
  placeHolderText,
}: {
  setSelectedPlace?: (places: PlaceItem[]) => void;
  selectedPlace?: PlaceItem[];
  rightAction?: React.ReactNode;
  searchEnabled?: boolean;
  onExpandChange?: (expanded: boolean) => void;
  placeHolderText?: string;
  existingLocations?: string[];
}) => {
  const chatContext = useChat();
  const { colorScheme } = useMantineColorScheme();
  const showShadow = colorScheme === 'dark';
  const activeSelectedPlace = selectedPlace ?? chatContext.selectedPoiAddress;
  const activeSetSelectedPlace =
    setSelectedPlace ?? chatContext.setSelectedPoiAddress;
  const map = useMap();
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [, setNearbyPlaces] = useState<PlaceItem[]>([]);

  const [showSuggestions, setShowSuggestions] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeQueryRef = useRef(query);
  const hideSuggestionsRef = useRef(false);

  const isSmallScreen = useMediaQuery('(max-width: 1023px)');
  const [isMobileExpanded, setIsMobileExpanded] = useState(false);
  const isExpanded = !isSmallScreen || isMobileExpanded;
  const [maxListHeight, setMaxListHeight] = useState<number>(320);

  useEffect(() => {
    if (onExpandChange) {
      onExpandChange(!!isSmallScreen && isMobileExpanded);
    }
  }, [isSmallScreen, isMobileExpanded, onExpandChange]);

  // Dynamically calculate max height for suggestions list so it never overflows the map container
  useEffect(() => {
    if (!containerRef.current) return;
    const parent = containerRef.current.parentElement;
    if (!parent) return;

    const updateMaxHeight = () => {
      if (!containerRef.current || !parent) return;
      const parentRect = parent.getBoundingClientRect();
      const searchRect = containerRef.current.getBoundingClientRect();
      const available = parentRect.bottom - (searchRect.top + 56) - 12;
      setMaxListHeight(Math.max(120, Math.min(360, Math.floor(available))));
    };

    updateMaxHeight();

    const resizeObserver = new ResizeObserver(updateMaxHeight);
    resizeObserver.observe(parent);
    window.addEventListener('resize', updateMaxHeight);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', updateMaxHeight);
    };
  }, [showSuggestions, isExpanded]);

  // Suggestions fetching with debounce
  useEffect(() => {
    activeQueryRef.current = query;
    const fetchSuggestions = async () => {
      if (query.length < 3) {
        setSuggestions([]);
        return;
      }

      try {
        const result = await getMapSuggestionsAction(query, chatContext.activeThreadId ?? undefined);
        if (
          result.success &&
          activeQueryRef.current === query &&
          !hideSuggestionsRef.current
        ) {
          setSuggestions((result.data as SuggestionItem[]) || []);
          setShowSuggestions(true);
        }
      } catch (error) {
        console.error('Error fetching suggestions:', error);
        if (activeQueryRef.current === query) {
          setIsLoading(false);
        }
      }
    };

    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(fetchSuggestions, 400);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [query, chatContext.activeThreadId]);

  // Close suggestions on outside click and ESC key
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setShowSuggestions(false);
        setIsMobileExpanded(false);
      }
    };
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowSuggestions(false);
        setIsMobileExpanded(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEsc);
    };
  }, []);

  const fetchNearbyPlaces = async (lat: number, lng: number) => {
    try {
      const result = await getNearbyPlacesAction(lat, lng, 2000, chatContext.activeThreadId ?? undefined);

      setNearbyPlaces((prev) => [
        ...prev,
        ...((result.data as ApiResponse)?.places || []).filter(
          (place: PlaceItem) => !prev.some((p) => p.id === place.id)
        ),
      ]);
    } catch (error) {
      console.error('Nearby search failed:', error);
    }
  };

  const handleSearch = async (searchText: string) => {
    if (!searchText.trim()) return;

    setIsLoading(true);
    setShowSuggestions(false);
    try {
      const result = await searchMapAction(searchText, chatContext.activeThreadId ?? undefined);
      const places: PlaceItem[] = (result.data as ApiResponse)?.places || [];
      setNearbyPlaces((prev) => [
        ...prev,
        ...places.filter(
          (place: PlaceItem) => !prev.some((p) => p.id === place.id)
        ),
      ]);

      if (places.length > 0) {
        const validPlaces = places.filter(
          (p: PlaceItem) => p.location?.latitude && p.location?.longitude
        );
        const lat = validPlaces[0]?.location?.latitude;
        const lng = validPlaces[0]?.location?.longitude;
        if (lat != null && lng != null) {
          fetchNearbyPlaces(lat, lng);
        }

        const newPlaces = validPlaces.filter(
          (place) =>
            !activeSelectedPlace.some((p: PlaceItem) => p.id === place.id)
        );
        if (newPlaces.length > 0) {
          activeSetSelectedPlace([...activeSelectedPlace, ...newPlaces]);
        }

        if (validPlaces.length === 1) {
          const loc = validPlaces[0].location;
          if (loc?.latitude != null && loc?.longitude != null) {
            map?.panTo({ lat: loc.latitude, lng: loc.longitude });
            map?.setZoom(14);
          }
        } else if (validPlaces.length > 1) {
          if (map) {
            const bounds = new google.maps.LatLngBounds();
            validPlaces.forEach((p) => {
              bounds.extend({
                lat: p.location!.latitude!,
                lng: p.location!.longitude!,
              });
            });
            map.fitBounds(bounds, 50);
          }
        }
      }
    } catch (error) {
      console.error('Search failed:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectSuggestion = (item: SuggestionItem) => {
    const text = item.placePrediction?.text?.text || '';
    hideSuggestionsRef.current = true;
    setQuery(text);
    handleSearch(text);
  };

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
              className="light:border-white/20! light:border! light:backdrop-blur-[57px] light:rounded-full relative h-10 w-full origin-top-left"
            >
              <div
                className={`absolute inset-0 transition-opacity duration-300 ${isExpanded ? 'opacity-100 delay-100' : 'pointer-events-none opacity-0'}`}
              >
                <TextInput
                  ref={searchInputRef}
                  placeholder={placeHolderText || 'Search'}
                  value={query}
                  onChange={(e) => {
                    hideSuggestionsRef.current = false;
                    setQuery(e.currentTarget.value);
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
                      boxShadow: showShadow
                        ? 'var(--shadow-info)'
                        : 'var(--shadow-widget)',
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
                    },
                  }}
                  classNames={{
                    input:
                      'placeholder:text-primary-text/70! placeholder:opacity-70! font-normal! focus:outline-none text-primary-text',
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
                  setIsMobileExpanded(true);
                  setTimeout(() => searchInputRef.current?.focus(), 100);
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
                  maxHeight: `${maxListHeight}px`,
                  backdropFilter: 'blur(75.9px)',
                  WebkitBackdropFilter: 'blur(75.9px)',
                }}
                className="border-stroke-widget! bg-primary-widget! shadow-widget! light:shadow-sm! absolute top-full right-0 left-0 z-1050 mt-2 flex flex-col overflow-hidden rounded-2xl border!"
              >
                {/* <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 z-0 rounded-2xl opacity-15 mix-blend-overlay"
                  style={{ backgroundImage: widgetNoiseBackground }}
                /> */}
                <div
                  style={{ maxHeight: `${maxListHeight}px` }}
                  className="scrollbar-thumb-divider relative z-10 flex-1 min-h-0 scrollbar-thin overflow-y-auto py-2"
                >
                  {suggestions.map((item, idx) => {
                    const prediction = item.placePrediction;
                    const mainText =
                      prediction?.structuredFormat?.mainText?.text ||
                      prediction?.text?.text;
                    const secondaryText =
                      prediction?.structuredFormat?.secondaryText?.text;

                    return (
                      <motion.div
                        key={
                          prediction?.placeId || `${mainText}-${secondaryText}`
                        }
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: idx * 0.03 }}
                        onClick={() => handleSelectSuggestion(item)}
                        className="group/item border-underline/20 hover:bg-primary-text/5 flex cursor-pointer items-start gap-4 border-b px-5 py-3.5 transition-all duration-200 last:border-none"
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
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        {rightAction && <div className="shrink-0">{rightAction}</div>}
      </div>
    </>
  );
};

export default LocationMapSearch;
