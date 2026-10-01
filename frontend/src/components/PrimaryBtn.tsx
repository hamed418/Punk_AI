import { cn } from '@/lib/utils'
import {
  Button,
  mantineHtmlProps,
  type ButtonProps,
  type ElementProps,
} from '@mantine/core'

interface PrimaryGlassBtnProps
  extends ButtonProps, ElementProps<'button', keyof ButtonProps> {}

const PrimaryGlassBtn: React.FC<PrimaryGlassBtnProps> = ({
  children,
  className,
  onClick,
  ...rest
}) => (
  <Button
    bg="#FFFFFF1A"
    radius={53}
    className={cn(
      'disabled:bg-primary-button/70! hover:bg-white/20! active:shadow-none! disabled:shadow-none!',
      className,
    )}
    {...mantineHtmlProps}
    onClick={onClick}
    {...rest}
    style={{
      borderTop: '1px solid #FFFFFF29',
      boxShadow: '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1.5px 0px 0px #FFFFFF59 inset',
      ...(rest.style as React.CSSProperties),
    }}
  >
    {children}
  </Button>
)

export default PrimaryGlassBtn
