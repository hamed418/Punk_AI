"use client";
import PrimaryBtn from '@/components/PrimaryBtn'
import WidgetLayout from './WidgetLayout'

// --- Simple Card & Button Components (no shadcn needed) ---
function Card({
  children,
  className = '',
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={`border-stroke-widget bg-primary-widget border ${className}`}
    >
      {children}
    </div>
  )
}

function CardContent({
  children,
  className = '',
}: {
  children: React.ReactNode
  className?: string
}) {
  return <div className={className}>{children}</div>
}

export default function CampaignDirection({
  widget,
  businessName = 'Campaign Direction',
  businessAddress = '456 Elm Street.',
  onConfirm,
  isLatest = true,
}: {
  widget: {
    id: string
    type: string
    content: string
    [key: string]: unknown
  }[]
  businessName?: string
  businessAddress?: string
  onConfirm?: () => void
  isLatest?: boolean
}) {
  return (
    <WidgetLayout mode="single">
      <div className="mx-auto mb-10 w-full max-w-4xl pl-2">
        <Card className="shadow-professional w-full rounded-[10px]">
          <CardContent className="p-1">
            <div className="bg-secondary-widget mb-4 flex items-center justify-between rounded-lg p-4">
              <div className="flex items-center gap-3">
                <div className="border-stroke-widget bg-primary-widget flex h-10 w-10 items-center justify-center rounded-full border">
                  <img
                    src="/locationIcon.svg"
                    alt="Location"
                    className="light:invert"
                  />
                </div>
                <div>
                  <p className="font-inter text-primary-text text-md font-semibold">
                    {businessName}
                  </p>
                  <p className="text-secondary-text text-sm">
                    {businessAddress}
                  </p>
                </div>
              </div>
            </div>

            <div className="px-4 pb-4">
              <div className="overflow-hidden rounded-[10px]">
                {widget.map((opt) => (
                  <label
                    key={opt.id}
                    className={`border-stroke-widget flex items-center gap-3 border-b border-dashed p-3 ${isLatest ? 'hover:bg-secondary-bg/30 cursor-pointer' : ''}`}
                  >
                    <input
                      type="checkbox"
                      name="campaign"
                      disabled={!isLatest}
                      className="accent-primary-button h-5 w-5 cursor-pointer"
                    />
                    <p className="text-secondary-text text-sm">
                      {' '}
                      <span className="text-primary-text font-semibold">
                        {opt.type}
                      </span>{' '}
                      <span className="text-secondary-text text-sm">
                        {opt.content}
                      </span>
                    </p>
                  </label>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between gap-4 px-2">
                <p className="font-inter text-secondary-text text-sm font-normal">
                  Which one feels right for you, or do you want to stick with
                  Pin Point?
                </p>
                <PrimaryBtn
                  onClick={() => isLatest && onConfirm?.()}
                  disabled={!onConfirm || !isLatest}
                >
                  Confirm
                </PrimaryBtn>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </WidgetLayout>
  )
}
