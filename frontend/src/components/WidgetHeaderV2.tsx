import type React from 'react'
import { getWidgetHeader, getWidgetSubheader } from '../utils'
import { Box, Text } from '@mantine/core'

interface WidgetHeaderProps {
  /** Icon rendered inside the rounded icon container. Can be an <img> or a lucide icon element. */
  icon: React.ReactNode
  /** Primary title text */
  title?: React.ReactNode
  /** Secondary subtitle text */
  subtitle?: React.ReactNode
  /** Optional field key to automatically resolve title and subtitle */
  field?: string
  /** Optional content rendered on the right side of the header (e.g. a badge, button, or live indicator) */
  rightContent?: React.ReactNode
  /** Shape of the icon container: 'circle' (default) or 'square' */
  iconShape?: 'circle' | 'square'
  /** Size of the icon container in px. Defaults to 44 */
  iconSize?: number
  /** Extra className applied to the outer header card */
  className?: string
}

/**
 * Reusable header card for all widgets.
 *
 * Usage:
 * ```tsx
 * <WidgetHeader
 *   icon={<img src="/locationIcon.svg" alt="Location" className="light:invert" />}
 *   title="Shawarma Palace"
 *   subtitle="456 Elm Street"
 * />
 * ```
 */
export default function WidgetHeaderV2({
  icon,
  title,
  subtitle,
  field,
  rightContent,
  className = '',
}: WidgetHeaderProps) {
  const resolvedTitle = title ?? (field ? getWidgetHeader(field) : '')
  const resolvedSubtitle = subtitle ?? (field ? getWidgetSubheader(field) : '')

  return (
    <div
      className={`flex items-center justify-between bg-transparent ${className}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        {/* Icon container */}
        <Box
          className={`flex h-8 w-8 shrink-0 bg-primary-text/7 items-center justify-center rounded-full`}
          style={{
            // background: 'transparent',
            boxShadow: `
                      inset -3px -5px 2.5px -5px #FFFFFF,
                      inset 2.5px 3.5px 2px -3.5px #FFFFFF
            `,
          }}
        >
          {icon}
        </Box>

        {/* Text */}
        <div className="ml-1 min-w-0">
          <Text
            fz={15}
            fw={600}
            className="text-primary-text! truncate leading-tight tracking-wide"
          >
            {resolvedTitle}
          </Text>
          {resolvedSubtitle && (
            <Text
              component="span"
              fw={400}
              fz={11}
              className="block text-secondary-text/60 max-w-72 truncate"
              title={typeof resolvedSubtitle === 'string' ? resolvedSubtitle : undefined}
            >
              {resolvedSubtitle}
            </Text>
          )}
        </div>
      </div>

      {/* Optional right slot */}
      {rightContent && <div className="ml-3 shrink-0">{rightContent}</div>}
    </div>
  )
}
