import { useMotionValue, useSpring } from 'framer-motion'
import { useEffect, useRef } from 'react'

export const BLOB_RADIUS = 70

export function useMouseFollowBlob() {
  const containerRef = useRef<HTMLDivElement>(null)
  const rawX = useMotionValue(0)
  const rawY = useMotionValue(0)
  const rawOpacity = useMotionValue(0)

  const blobX = useSpring(rawX, { stiffness: 120, damping: 22, mass: 0.5 })
  const blobY = useSpring(rawY, { stiffness: 120, damping: 22, mass: 0.5 })
  const opacity = useSpring(rawOpacity, { stiffness: 150, damping: 25 })

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const handleMove = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect()
      rawX.set(e.clientX - rect.left)
      rawY.set(e.clientY - rect.top)
    }

    const handleEnter = () => {
      rawOpacity.set(1)
    }

    const handleLeave = () => {
      rawOpacity.set(0)
    }

    el.addEventListener('mousemove', handleMove)
    el.addEventListener('mouseenter', handleEnter)
    el.addEventListener('mouseleave', handleLeave)

    return () => {
      el.removeEventListener('mousemove', handleMove)
      el.removeEventListener('mouseenter', handleEnter)
      el.removeEventListener('mouseleave', handleLeave)
    }
  }, [rawX, rawY, rawOpacity])

  return { containerRef, blobX, blobY, opacity, handleMouseMove: () => {} }
}
