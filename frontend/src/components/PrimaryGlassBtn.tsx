import { cn } from '@/lib/utils'
import { ArrowRight } from 'lucide-react'
import {
  Button,
  mantineHtmlProps,
  type ButtonProps,
  type ElementProps,
} from '@mantine/core'

interface PrimaryGlassBtnProps
  extends ButtonProps, ElementProps<'button', keyof ButtonProps> {
  withArrow?: boolean
}

const PrimaryGlassBtn: React.FC<PrimaryGlassBtnProps> = ({
  children,
  className,
  onClick,
  withArrow,
  rightSection,
  variant,
  ...rest
}) => (
  <Button
    // bg="#FFFFFF1A"
    radius={53}
    className={cn(
      'disabled:bg-button-disabled! border! text-primary-text! disabled:text-primary-text/50! hover:bg-primary-button-hover! active:shadow-plus-minus-button-shadow/20! disabled:shadow-none!',
      variant === 'ghost'
        ? 'border-white/15! bg-transparent! shadow-none!'
        : 'border-white/16! bg-white/10! shadow-plus-minus-button-shadow',
      className,
    )}
    {...mantineHtmlProps}
    onClick={onClick}
    {...rest}
    style={{
      ...(rest.style as React.CSSProperties),
    }}
    rightSection={withArrow ? <ArrowRight size={16} className="-ml-3.5 sm:-ml-1.5" /> : rightSection}
  >
    {children} 
  </Button>
)

export default PrimaryGlassBtn
