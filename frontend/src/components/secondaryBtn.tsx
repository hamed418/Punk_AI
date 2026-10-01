import { cn } from '@/lib/utils'
import {
  Button,
  mantineHtmlProps,
  type ButtonProps,
  type ElementProps,
} from '@mantine/core'
import React from 'react'

interface SecondaryBtnProps
  extends ButtonProps, ElementProps<'button', keyof ButtonProps> {}

const SecondaryBtn: React.FC<SecondaryBtnProps> = ({
  children,
  className,
  onClick,
  ...rest
}) => (
  <Button
    bg="var(--mantine-color-button-secondary)"
    c="var(--mantine-color-text-primary)"
    className={cn(
      'hover:bg-secondary-button/70! disabled:bg-secondary-button/70! active:shadow-none! disabled:shadow-none! disabled:text-primary-text/50!',
      className,
    )}
    {...mantineHtmlProps}
    onClick={onClick}
    {...rest}
    style={{
      border: '1px solid var(--mantine-color-button-stroke)',
      boxShadow:
        '0px 0.5px 1px 0px #FFFFFF0D, 0px -4px 0px 0px #0504040A inset',
      ...(rest.style as React.CSSProperties),
    }}
  >
    {children}
  </Button>
)

export default SecondaryBtn
