import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import { useMap } from '@vis.gl/react-google-maps'
import { BoundaryGeoJSON } from '@/utils/boundaryUtils'
import type { ExcludedArea } from '@/types/chat'

interface CircleProps extends Omit<google.maps.CircleOptions, 'onClick'> {
  center: google.maps.LatLngLiteral
  radius: number
  onClick?: () => void
  // `editable: true` already gives the circle Google's native resize handle
  // on its edge; `draggable: true` lets the whole circle (and so its center)
  // be dragged. These two callbacks are how a pin+radius confirm location
  // reads those native edits back into React state — no custom hit-testing.
  onRadiusChanged?: (radiusMeters: number) => void
  onCenterChanged?: (center: { lat: number; lng: number }) => void
}

export const Circle = forwardRef((props: CircleProps, ref) => {
  const map = useMap()
  const circleRef = useRef<google.maps.Circle | null>(null)
  const { onClick, onRadiusChanged, onCenterChanged, ...circleOptions } = props

  useEffect(() => {
    if (!map) return

    const circle = new google.maps.Circle({
      map,
    })
    circleRef.current = circle

    return () => {
      circle.setMap(null)
    }
  }, [map])

  useEffect(() => {
    if (!circleRef.current) return
    circleRef.current.setOptions(circleOptions)
  }, [circleOptions])

  useEffect(() => {
    if (!circleRef.current || !onClick) return
    const listener = circleRef.current.addListener('click', onClick)
    return () => {
      google.maps.event.removeListener(listener)
    }
  }, [onClick])

  useEffect(() => {
    if (!circleRef.current || !onRadiusChanged) return
    const listener = circleRef.current.addListener('radius_changed', () => {
      const r = circleRef.current?.getRadius()
      if (r != null) onRadiusChanged(r)
    })
    return () => {
      google.maps.event.removeListener(listener)
    }
  }, [onRadiusChanged])

  useEffect(() => {
    if (!circleRef.current || !onCenterChanged) return
    const listener = circleRef.current.addListener('center_changed', () => {
      const c = circleRef.current?.getCenter()
      if (c) onCenterChanged({ lat: c.lat(), lng: c.lng() })
    })
    return () => {
      google.maps.event.removeListener(listener)
    }
  }, [onCenterChanged])

  useImperativeHandle(ref, () => circleRef.current)

  return null
})
Circle.displayName = 'Circle'

// Parts of the targeted area the user left out — grey, not clickable. The box is
// the geocoder's bounds (an approximation of the shape the backend filters by);
// with no bounds, a 1 km circle, the same fallback the backend uses.
export function ExcludedAreas({ areas }: { areas?: ExcludedArea[] }) {
  const map = useMap()

  useEffect(() => {
    if (!map || !areas?.length) return
    const shapes = areas.map((a) => {
      const style = {
        map,
        strokeColor: '#6B7280',
        strokeOpacity: 0.9,
        strokeWeight: 2,
        fillColor: '#6B7280',
        fillOpacity: 0.35,
        clickable: false,
      }
      return a.bounds
        ? new google.maps.Rectangle({
            ...style,
            bounds: { north: a.bounds.lat_max, south: a.bounds.lat_min, east: a.bounds.lng_max, west: a.bounds.lng_min },
          })
        : new google.maps.Circle({ ...style, center: { lat: a.lat, lng: a.lng }, radius: 1000 })
    })
    return () => shapes.forEach((s) => s.setMap(null))
  }, [map, areas])

  return null
}

export function GeoJsonFeatures({ geoJsons, onClick }: { geoJsons: BoundaryGeoJSON[], onClick?: (id: string, lat: number, lng: number) => void }) {
  const map = useMap()

  useEffect(() => {
    if (!map) return

    const dataLayer = new google.maps.Data({ map })
    const googleStyledPlaceIds = new Set<string>()
    const osmFallbackGeos: BoundaryGeoJSON[] = []
    const featureLayerTypes = new Set<string>()

    geoJsons.forEach((geo) => {
      if (!geo || geo.properties?.isCircle) return

      const hasPolygonGeometry = geo.type === 'Polygon' || geo.type === 'MultiPolygon' || geo.geometry?.type === 'Polygon' || geo.geometry?.type === 'MultiPolygon'
      const isOsmFallback = geo.properties?.isOsmFallback
      const hasFeatureType = Boolean(geo.properties?.featureType && geo.properties?.placeId)

      // 1st Priority: Apply Google Vector FeatureLayer styling for ALL geos with featureType+placeId
      if (hasFeatureType && typeof map.getFeatureLayer === 'function') {
        try {
          const ft = geo.properties!.featureType as google.maps.FeatureType
          featureLayerTypes.add(ft as string)
          const featureLayer = map.getFeatureLayer(ft)
          if (featureLayer) {
            const targetPlaceId = geo.properties!.placeId as string
            featureLayer.style = (options: google.maps.FeatureStyleFunctionOptions) => {
              const feat = options.feature as { placeId?: string }
              if (feat?.placeId === targetPlaceId) {
                googleStyledPlaceIds.add(targetPlaceId)
                return {
                  strokeColor: '#D62575',
                  strokeOpacity: 1,
                  strokeWeight: 2,
                  fillColor: '#D62575',
                  fillOpacity: 0.15,
                }
              }
              return null
            }
          }
        } catch (e) {
          console.warn('Google FeatureLayer styling failed', e)
        }
      }

      // Queue OSM polygon for delayed fallback rendering (only after checking Google Vector)
      if (hasPolygonGeometry && isOsmFallback) {
        osmFallbackGeos.push(geo)
        return
      }

      // Non-OSM polygon geometry: render immediately on DataLayer
      if (hasPolygonGeometry && !isOsmFallback) {
        try {
          const feature = {
            type: 'Feature',
            properties: { id: geo.id },
            geometry: geo.type === 'Feature' ? geo.geometry : geo,
          }
          dataLayer.addGeoJson(feature)
        } catch (e) {
          console.error('Failed to add GeoJSON to Data layer', e)
        }
      }
    })

    // 2nd Priority: Wait for map to finish rendering, then render OSM for locations
    // where Google Vector did NOT style. Uses map 'idle' event + small buffer.
    const timers: ReturnType<typeof setTimeout>[] = []
    let idleListener: google.maps.MapsEventListener | null = null
    let osmRendered = false

    if (osmFallbackGeos.length > 0) {
      const renderOsmFallbacks = () => {
        if (osmRendered) return
        osmRendered = true
        osmFallbackGeos.forEach((geo) => {
          const placeId = geo.properties?.placeId as string
          if (placeId && googleStyledPlaceIds.has(placeId)) return
          try {
            const feature = {
              type: 'Feature',
              properties: { id: geo.id },
              geometry: geo.type === 'Feature' ? geo.geometry : geo,
            }
            dataLayer.addGeoJson(feature)
          } catch (e) {
            console.error('Failed to add OSM fallback GeoJSON to Data layer', e)
          }
        })
      }

      // Wait for map idle (tiles + features loaded), then check after 200ms buffer
      idleListener = google.maps.event.addListenerOnce(map, 'idle', () => {
        timers.push(setTimeout(renderOsmFallbacks, 200))
      })

      // Safety: if idle never fires within 3s, render anyway
      timers.push(setTimeout(renderOsmFallbacks, 3000))
    }

    dataLayer.setStyle({
      strokeColor: '#D62575',
      fillColor: '#D62575',
      fillOpacity: 0.15,
      strokeWeight: 2,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: '#D62575',
        fillOpacity: 1,
        strokeColor: '#FFFFFF',
        strokeWeight: 1,
        scale: 6,
      }
    })

    let listener: google.maps.MapsEventListener | undefined;
    if (onClick) {
      listener = dataLayer.addListener('click', (event: google.maps.Data.MouseEvent) => {
        const id = event.feature.getProperty('id') as string
        if (id && event.latLng) {
          const lat = event.latLng.lat()
          const lng = event.latLng.lng()
          onClick(id, lat, lng)
        }
      })
    }

    return () => {
      timers.forEach(clearTimeout)
      if (idleListener) google.maps.event.removeListener(idleListener)
      if (listener) {
        google.maps.event.removeListener(listener)
      }
      // Clear Google FeatureLayer styles
      featureLayerTypes.forEach((ft) => {
        try {
          const layer = map.getFeatureLayer(ft as google.maps.FeatureType)
          if (layer) layer.style = null
        } catch {}
      })
      dataLayer.setMap(null)
    }
  }, [map, geoJsons, onClick])

  return null
}
