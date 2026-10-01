import { cn } from '@/lib/utils'
import {
  ActionIcon,
  mantineHtmlProps,
  type ActionIconProps,
  type ElementProps,
} from '@mantine/core'
import React from 'react'

interface SecondaryActionIconProps
  extends ActionIconProps, ElementProps<'button', keyof ActionIconProps> {}

const SecondaryActionIcon: React.FC<SecondaryActionIconProps> = ({
  children,
  className,
  onClick,
  ...props
}) => {
  return (
    <ActionIcon
      bg="var(--mantine-color-button-secondary)"
      c="var(--mantine-color-text-primary)"
      className={cn(
        'hover:bg-secondary-button/70! disabled:bg-secondary-button/70! active:shadow-none! disabled:shadow-none! disabled:text-primary-text/50!',
        className,
      )}
      {...mantineHtmlProps}
      onClick={onClick}
      {...props}
      style={{
        border: '1px solid var(--mantine-color-button-stroke)',
        boxShadow:
          '0px 0.41px 0.81px 0px #0000000D, 0px -3.25px 0px 0px #0000000A inset, 0px -3.25px 0px 0px #0504040A inset,0px 0.41px 0.81px 0px #FFFFFF0D',
        ...(props.style as React.CSSProperties),
      }}
    >
      {children}
    </ActionIcon>
  )
}

export default SecondaryActionIcon
