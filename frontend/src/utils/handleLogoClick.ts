/**
 * Global Punk Logo Color Store
 *
 * Persists the active color variant index in localStorage so it survives
 * page refreshes. Uses a custom DOM event ("punkColorChange") to broadcast
 * changes to every mounted logo instance across the entire app without
 * requiring a global state-management library.
 */

import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'punk_logo_color_index'
const EVENT_NAME = 'punkColorChange'

export interface PunkColorVariant {
  hearDarkFill: string
  hearLightFill: string
  faceBodyFill: string
  bodyDarkFill: string
  bodyLightFill: string
}

export const PUNK_COLOR_VARIANTS: PunkColorVariant[] = [
  {
    // default – warm pink / orange
    hearDarkFill: '#ce1c66',
    hearLightFill: '#f54397',
    faceBodyFill: '#ee9b59',
    bodyDarkFill: '#733016',
    bodyLightFill: '#843818',
  },
  {
    // ocean blue / silver
    hearDarkFill: '#1784A7',
    hearLightFill: '#26A2C1',
    faceBodyFill: '#FFE8C7',
    bodyLightFill: '#D5D5D5',
    bodyDarkFill: '#BEBEBE',
  },
  {
    // electric green / purple
    hearDarkFill: '#50B820',
    hearLightFill: '#83EF39',
    faceBodyFill: '#8563A2',
    bodyLightFill: '#2E1936',
    bodyDarkFill: '#2B1732',
  },
  {
    // crimson / forest green
    hearDarkFill: '#B40B28',
    hearLightFill: '#ED134F',
    faceBodyFill: '#FFE8C7',
    bodyDarkFill: '#07510C',
    bodyLightFill: '#107138',
  },
  {
    // silver / grey
    hearDarkFill: '#EDEDED',
    hearLightFill: '#8C8C8C',
    faceBodyFill: '#8C8C8C',
    bodyDarkFill: '#2C2C2C',
    bodyLightFill: '#3F3F3F',
  },
]

/** Read the persisted index (defaults to 0). */
export function getColorIndex(): number {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored !== null) {
      const parsed = parseInt(stored, 10)
      if (!Number.isNaN(parsed) && parsed >= 0 && parsed < PUNK_COLOR_VARIANTS.length) {
        return parsed
      }
    }
  } catch {
    // localStorage may be unavailable in some environments
  }
  return 0
}

/** Read the current color variant object. */
export function getCurrentColorVariant(): PunkColorVariant {
  return PUNK_COLOR_VARIANTS[getColorIndex()]
}

/**
 * Advance to the next color variant, persist the new index, and broadcast the
 * change to every subscriber registered via `onPunkColorChange`.
 */
export function handleLogoClick(): void {
  const nextIndex = (getColorIndex() + 1) % PUNK_COLOR_VARIANTS.length
  try {
    localStorage.setItem(STORAGE_KEY, String(nextIndex))
  } catch {
    // ignore write errors
  }

  // Dispatch a global custom event so all mounted logo instances re-render
  const event = new CustomEvent(EVENT_NAME, { detail: { index: nextIndex } })
  window.dispatchEvent(event)
}

/**
 * Subscribe to color-change events.
 *
 * @param callback  Called with the new color variant whenever the logo is clicked.
 * @returns         Unsubscribe function — call it in your cleanup / useEffect return.
 */
export function onPunkColorChange(
  callback: (variant: PunkColorVariant) => void,
): () => void {
  const listener = (e: Event) => {
    const detail = (e as CustomEvent<{ index: number }>).detail
    callback(PUNK_COLOR_VARIANTS[detail.index])
  }
  window.addEventListener(EVENT_NAME, listener)
  return () => window.removeEventListener(EVENT_NAME, listener)
}

export const subscribePunkColor = (callback: () => void) => {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(EVENT_NAME, callback)
  return () => window.removeEventListener(EVENT_NAME, callback)
}

export const getPunkColorServerSnapshot = () => 0

/**
 * React hook to subscribe to punk color variant changes with useSyncExternalStore
 */
export function usePunkColor() {
  const colorIndex = useSyncExternalStore(
    subscribePunkColor,
    getColorIndex,
    getPunkColorServerSnapshot,
  )
  const colorVariant = PUNK_COLOR_VARIANTS[colorIndex] ?? PUNK_COLOR_VARIANTS[0]
  return { colorIndex, colorVariant }
}
