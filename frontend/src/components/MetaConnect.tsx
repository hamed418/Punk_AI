import { useMouseFollowBlob } from '@/hooks/useMouseFollowBlob'
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn'

interface MetaConnectProps {
  onConnect?: () => void
  disabled?: boolean
  connecting?: boolean
}

function MetaConnect({ onConnect, disabled = false, connecting = false }: MetaConnectProps) {
  const { containerRef, handleMouseMove } =
    useMouseFollowBlob()

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      className="relative max-w-4xl overflow-hidden rounded-[30px] border! border-stroke-widget! bg-primary-widget! shadow-widget! light:shadow-sm!"
      style={{
        backdropFilter: 'blur(75.9px)',
      }}
    >

      <div className="flex w-full items-center justify-between gap-3 px-5 py-4">
        {/* Logo + text */}
        <div className="flex items-center gap-2">
          <div className="max-w-10 min-w-10">
            <img src="/Meta.png" alt="logo" className="h-9 w-9 object-contain" />
          </div>
          <div className="flex flex-col">
            <p className="text-primary-text truncate text-[13.5px] leading-tight font-semibold">
              META ACCOUNT VALIDATION
            </p>
            <p className="text-secondary-text mt-0.5 max-w-56 truncate text-[13px] font-normal">
              {connecting ? 'Waiting for Meta…' : 'Connect Meta Account'}
            </p>
          </div>
        </div>

        {/* Button */}
        <PrimaryGlassBtn
          onClick={onConnect}
          disabled={disabled}
          size="sm"
          className="text-[12px] font-normal!"
          withArrow={true}
        >
          <span className="hidden sm:inline">
            {connecting ? 'Connecting…' : 'Connect'}
          </span>
        </PrimaryGlassBtn>
      </div>
    </div>
  )
}

export default MetaConnect
