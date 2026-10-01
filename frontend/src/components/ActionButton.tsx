import type { ReactNode, MouseEventHandler } from 'react'

const ActionButton = ({
  children,
  isActive,
  onClick,
}: {
  children: ReactNode
  isActive: boolean
  onClick?: MouseEventHandler<HTMLButtonElement>
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`bg-primary-widget flex h-8 w-8 items-center justify-center rounded-full ${isActive ? 'bg-transparent' : 'bg-primary-widget'}`}
      style={
        isActive
          ? {
              boxShadow: `
                inset -3px -5px 2.5px -5px #FFFFFF,
                inset 2.5px 3.5px 2px -3.5px #FFFFFF
              `,
            }
          : undefined
      }
    >
      {children}
    </button>
  )
}
export default ActionButton
