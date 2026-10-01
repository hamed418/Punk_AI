export type BoundaryGeoJSON = {
  type: string
  id?: string
  geometry?: {
    type: string
    coordinates: unknown
    [key: string]: unknown
  }
  coordinates?: unknown[]
  properties?: {
    isCircle?: boolean
    radius?: number
    bbox?: number[]
    id?: string
    placeId?: string
    featureType?: google.maps.FeatureType
    [key: string]: unknown
  }
}

const boundaryFetchPromises = new Map<string, Promise<BoundaryGeoJSON | null>>()

let lastNominatimRequestTime = 0
const fetchNominatim = async (url: string) => {
  const now = Date.now()
  const timeSinceLast = now - lastNominatimRequestTime
  if (timeSinceLast < 1000) {
    await new Promise((r) => setTimeout(r, 1000 - timeSinceLast))
  }
  lastNominatimRequestTime = Date.now()
  return fetch(url)
}

export const fetchBoundaryForPlace = async (
  placeId: string | undefined,
  address: string | undefined,
  placeType: string | undefined,
  lat?: number,
  lng?: number
): Promise<BoundaryGeoJSON | null> => {
  const apiKey =
    process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ||
    process.env.GOOGLE_MAPS_API_KEY ||
    process.env.VITE_GOOGLE_MAPS_API_KEY ||
    ''

  const cacheKey = placeId || address || `${lat},${lng}`
  if (!cacheKey) return null

  let fetchPromise = boundaryFetchPromises.get(cacheKey)

  if (!fetchPromise) {
    fetchPromise = (async () => {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let googleResult: any = null

        // Priority 1: Try Google Geocoding (place_id -> address -> latlng)
        if (placeId && apiKey) {
          try {
            const resp = await fetch(`https://maps.googleapis.com/maps/api/geocode/json?place_id=${encodeURIComponent(placeId)}&key=${apiKey}`)
            if (resp.ok) {
              const data = await resp.json()
              if (data?.results?.[0]) {
                googleResult = data.results[0]
              }
            }
          } catch (e) {
            console.warn('Geocoding place_id failed', e)
          }
        }

        if (!googleResult && address && apiKey) {
          try {
            const resp = await fetch(`https://maps.googleapis.com/maps/api/geocode/json?address=${encodeURIComponent(address)}&key=${apiKey}`)
            if (resp.ok) {
              const data = await resp.json()
              if (data?.results?.[0]) {
                googleResult = data.results[0]
              }
            }
          } catch (e) {
            console.warn('Geocoding address failed', e)
          }
        }

        if (!googleResult && lat !== undefined && lng !== undefined && apiKey) {
          try {
            const resp = await fetch(`https://maps.googleapis.com/maps/api/geocode/json?latlng=${lat},${lng}&key=${apiKey}`)
            if (resp.ok) {
              const data = await resp.json()
              if (data?.results?.[0]) {
                googleResult = data.results[0]
              }
            }
          } catch (e) {
            console.warn('Geocoding latlng failed', e)
          }
        }

        const resolvedPlaceId = googleResult?.place_id || placeId || `${lat}-${lng}`
        const bounds = googleResult?.geometry?.bounds || googleResult?.geometry?.viewport
        const latRes = googleResult?.geometry?.location?.lat ?? lat
        const lngRes = googleResult?.geometry?.location?.lng ?? lng
        const searchName = googleResult?.formatted_address || address || ''

        // Priority 1 Google Data-Driven Vector FeatureType
        let featureType: google.maps.FeatureType | undefined
        const types: string[] = googleResult?.types || (placeType ? [placeType] : ['locality'])
        
        if (types.includes('country')) {
          featureType = 'COUNTRY' as google.maps.FeatureType
        } else if (types.includes('administrative_area_level_1')) {
          featureType = 'ADMINISTRATIVE_AREA_LEVEL_1' as google.maps.FeatureType
        } else if (types.includes('administrative_area_level_2')) {
          featureType = 'ADMINISTRATIVE_AREA_LEVEL_2' as google.maps.FeatureType
        } else if (types.includes('locality') || types.includes('colloquial_area')) {
          featureType = 'LOCALITY' as google.maps.FeatureType
        } else if (types.includes('postal_code')) {
          featureType = 'POSTAL_CODE' as google.maps.FeatureType
        } else if (types.includes('neighborhood')) {
          featureType = 'NEIGHBORHOOD' as google.maps.FeatureType
        } else {
          featureType = 'LOCALITY' as google.maps.FeatureType
        }

        const bbox: number[] | undefined = bounds ? [
          bounds.southwest.lat,
          bounds.northeast.lat,
          bounds.southwest.lng,
          bounds.northeast.lng,
        ] : (latRes !== undefined && lngRes !== undefined ? [latRes - 0.001, latRes + 0.001, lngRes - 0.001, lngRes + 0.001] : undefined)

        // Return Google Vector Boundary feature definition if Place ID & FeatureType are present
        if (resolvedPlaceId && featureType) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          let osmGeojson: any = null
          try {
            const queryTerms = Array.from(new Set([
              searchName,
              searchName.split(',')[0],
              address,
              address ? address.split(',')[0] : '',
            ])).filter(Boolean) as string[]

            for (const queryTerm of queryTerms) {
              const polyUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(queryTerm)}&format=json&polygon_geojson=1&limit=5&email=hello@usepunk.ai`
              const osmResponse = await fetchNominatim(polyUrl)
              if (osmResponse.ok) {
                const osmData = await osmResponse.json()
                const validPolygons = osmData?.filter(
                  (item: { geojson?: { type?: string } }) =>
                    item.geojson &&
                    (item.geojson.type === 'Polygon' || item.geojson.type === 'MultiPolygon')
                )
                if (validPolygons && validPolygons.length > 0) {
                  osmGeojson = validPolygons[0].geojson
                  break
                }
              }
            }
          } catch (e) {
            console.warn('OSM boundary fetch fallback failed', e)
          }

          if (osmGeojson) {
            osmGeojson.id = resolvedPlaceId
            return {
              ...osmGeojson,
              properties: {
                bbox,
                types,
                placeId: resolvedPlaceId,
                featureType,
                isOsmFallback: true,
              },
            } as BoundaryGeoJSON
          }

          return {
            type: 'Feature',
            id: resolvedPlaceId,
            properties: {
              bbox,
              types,
              placeId: resolvedPlaceId,
              featureType,
            },
            geometry: latRes !== undefined && lngRes !== undefined ? {
              type: 'Point',
              coordinates: [lngRes, latRes],
            } : undefined,
          } as BoundaryGeoJSON
        }

        // Priority 2: Fetch OSM polygon ONLY if Google Geocoding/FeatureType is not available
        try {
          const queryTerms = Array.from(new Set([
            searchName,
            searchName.split(',')[0],
            address,
            address ? address.split(',')[0] : '',
          ])).filter(Boolean) as string[]

          for (const queryTerm of queryTerms) {
            const polyUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(queryTerm)}&format=json&polygon_geojson=1&limit=5&email=hello@usepunk.ai`
            const osmResponse = await fetchNominatim(polyUrl)
            if (osmResponse.ok) {
              const osmData = await osmResponse.json()
              const validPolygons = osmData?.filter(
                (item: { geojson?: { type?: string } }) =>
                  item.geojson &&
                  (item.geojson.type === 'Polygon' || item.geojson.type === 'MultiPolygon')
              )
              if (validPolygons && validPolygons.length > 0) {
                const osmGeojson = validPolygons[0].geojson
                osmGeojson.id = resolvedPlaceId
                return {
                  ...osmGeojson,
                  properties: {
                    bbox,
                    types,
                    placeId: resolvedPlaceId,
                    isOsmFallback: true,
                  },
                } as BoundaryGeoJSON
              }
            }
          }
        } catch (e) {
          console.warn('OSM boundary fetch fallback failed', e)
        }

        return null
      } catch (error) {
        console.error('Error fetching boundary:', error)
        return null
      }
    })()
    boundaryFetchPromises.set(cacheKey, fetchPromise)
  }

  return fetchPromise
}

function isPointInPolygon(point: [number, number], vs: number[][]) {
  const x = point[0], y = point[1];
  let inside = false;
  for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
    const xi = vs[i][0], yi = vs[i][1];
    const xj = vs[j][0], yj = vs[j][1];
    const intersect = ((yi > y) != (yj > y))
        && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function isPointInMultiPolygon(point: [number, number], coordinates: number[][][][]) {
  return coordinates.some((polygon) => {
    return polygon.some((ring) => isPointInPolygon(point, ring));
  });
}

export function checkPointInGeoJSON(lat: number, lng: number, geojson: BoundaryGeoJSON | null): boolean {
  if (!geojson) return false;
  
  const geometry = geojson.type === 'Feature' ? geojson.geometry : geojson;
  if (!geometry || !geometry.coordinates) return false;
  
  if (geometry.type === 'Polygon') {
    return (geometry.coordinates as number[][][]).some((ring) => isPointInPolygon([lng, lat], ring));
  } else if (geometry.type === 'MultiPolygon') {
    return isPointInMultiPolygon([lng, lat], geometry.coordinates as number[][][][]);
  }
  
  return true; 
}
