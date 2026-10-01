import type React from 'react'
import { getWidgetHeader, getWidgetSubheader } from '../utils'

interface WidgetHeaderProps {
  icon: React.ReactNode
  title?: React.ReactNode
  subtitle?: React.ReactNode
  field?: string
  rightContent?: React.ReactNode
  iconShape?: 'circle' | 'square'
  iconSize?: number
  className?: string
}

export default function WidgetHeader({
  icon,
  title,
  subtitle,
  field,
  rightContent,
  iconShape = 'circle',
  iconSize = 36,
  className = '',
}: WidgetHeaderProps) {
  const shapeClass = iconShape === 'circle' ? 'rounded-full' : 'rounded-xl'

  const resolvedTitle = title ?? (field ? getWidgetHeader(field) : '')
  const resolvedSubtitle = subtitle ?? (field ? getWidgetSubheader(field) : '')

  return (
    <div
      className={`bg-secondary-widget flex items-center justify-between rounded-md p-3 ${className}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        {/* Icon container */}
        <div
          className={`bg-primary-widget flex shrink-0 items-center justify-center ${shapeClass}`}
          style={{ width: iconSize, height: iconSize }}
        >
          {icon}
        </div>

        {/* Text */}
        <div className="min-w-0">
          <p className="text-primary-text truncate text-[15px] leading-tight font-semibold">
            {resolvedTitle}
          </p>
          {resolvedSubtitle && (
            <p
              className="text-secondary-text hover: max-w-56 truncate text-xs font-normal"
              title={resolvedSubtitle.toString()}
            >
              {resolvedSubtitle}
            </p>
          )}
        </div>
      </div>

      {/* Optional right slot */}
      {rightContent && <div className="ml-3 shrink-0">{rightContent}</div>}
    </div>
  )
}
