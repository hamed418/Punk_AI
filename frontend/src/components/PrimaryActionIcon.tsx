import { cn } from '@/lib/utils'
import {
  ActionIcon,
  mantineHtmlProps,
  type ActionIconProps,
  type ElementProps,
} from '@mantine/core'
import React from 'react'

interface PrimaryActionIconProps
  extends ActionIconProps, ElementProps<'button', keyof ActionIconProps> {}

const PrimaryActionIcon: React.FC<PrimaryActionIconProps> = ({
  children,
  className,
  onClick,
  ...props
}) => {
  return (
    <ActionIcon
      bg="var(--mantine-color-button-primary)"
      className={cn(
        'hover:bg-primary-button/70! disabled:bg-primary-button/70! active:shadow-none! disabled:shadow-none!',
        className,
      )}
      {...mantineHtmlProps}
      onClick={onClick}
      {...props}
      style={{
        boxShadow:
          '0px 0.41px 0.81px 0px #0000000D, 0px -3.25px 0px 0px #0000000A inset, 0px -3.25px 0px 0px #0504040A inset, 0px 0.41px 0.81px 0px #FFFFFF0D',
        ...(props.style as React.CSSProperties),
      }}
    >
      {children}
    </ActionIcon>
  )
}

export default PrimaryActionIcon
