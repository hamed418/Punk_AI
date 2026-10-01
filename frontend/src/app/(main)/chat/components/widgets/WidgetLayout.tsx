interface WidgetLayoutProps {
  children?: React.ReactNode
  leftContent?: React.ReactNode
  rightContent?: React.ReactNode
  aiText?: React.ReactNode
  mode?: 'single' | 'split' | 'full'
  className?: string
  showLogo?: boolean
  showSpace?: boolean
}

const WidgetLayout: React.FC<WidgetLayoutProps> = ({
  children,
  leftContent,
  rightContent,
  aiText,
  mode = 'single',
  className = '',
  showLogo = false,
  showSpace = false,
}) => {
  // Logo component
  const logoBlock = showLogo && (
    <div className="mr-4 flex shrink-0 items-center justify-center transition-all">
      <div className="bg-secondary-bg/10 shadow-professional flex items-center gap-[9.17px] rounded-full pt-2.75 pr-2.75 pb-2.75 pl-1.25">
        <img
          src="/logo.svg"
          alt="Logo Icon"
          className="h-8 w-8 rounded-full transition-transform duration-500 group-hover:scale-110"
        />
      </div>
    </div>
  )
  // here create same space like logoBlock without image
  const logoSpace = <div className="h-0 w-0"></div>

  if (mode === 'split') {
    return (
      <div className="relative mx-auto mb-6 flex w-full max-w-4xl flex-col-reverse gap-3 px-2 lg:flex lg:flex-row lg:items-stretch">
        {/* Left Panel */}
        <div className="z-10 flex h-full w-full shrink-0 flex-col gap-2 rounded-xl lg:w-100 xl:w-102.5">
          {aiText && (
            <div className="flex w-full shrink-0 items-start">
              {showSpace ? logoSpace : logoBlock}
              <div className="min-w-0 flex-1">{aiText}</div>
            </div>
          )}

          {(leftContent || children || aiText) && (
            <div className="flex min-h-0 w-full flex-1 flex-col gap-6">
              {leftContent && (
                <div className="custom-scrollbar border-stroke-widget bg-card flex h-full w-full flex-col overflow-hidden overflow-y-auto rounded-xl border shadow-sm">
                  {leftContent}
                </div>
              )}
              {children && (
                <div className="flex w-full shrink-0 flex-col gap-6">
                  {children}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Panel: Map or Visuals */}
        {rightContent && (
          <div className="split-right-section sticky top-2 z-30 w-full overflow-hidden lg:top-0 lg:flex-1 lg:self-stretch">
            <div className="h-full w-full">{rightContent}</div>
          </div>
        )}
      </div>
    )
  }

  if (mode === 'full') {
    return (
      <div
        className={`font-body mx-auto flex w-full ${className.includes('max-w-') ? '' : 'max-w-206.75'} justify-start ${className}`}
      >
        <div className="w-full">
          <div className={`animate-fade-up flex w-full flex-col gap-4`}>
            {(aiText || children || leftContent) && (
              <div className="flex items-start">
                {showSpace ? logoSpace : logoBlock}
                <div className="min-w-0 flex-1 space-y-4">
                  {aiText}
                  {(children || leftContent) && (
                    <div className="w-full">{children || leftContent}</div>
                  )}
                </div>
              </div>
            )}
            {rightContent && (
              <div className="border-stroke-widget bg-primary-widget min-h-75 w-full overflow-hidden rounded-xl border">
                {rightContent}
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // Default Single Logic
  // ?w-600px
  return (
    <div
      className={`font-body mx-auto flex w-full max-w-4xl justify-start ${className}`}
    >
      <div className="w-full">
        <div className={`animate-fade-up flex w-full flex-col gap-4`}>
          {(aiText || children || leftContent) && (
            <div className="flex items-start">
              {showSpace ? logoSpace : logoBlock}
              <div className="min-w-0 flex-1 space-y-4">
                {aiText}
                {(children || leftContent) && (
                  <div className="w-full">{children || leftContent}</div>
                )}
              </div>
            </div>
          )}
          {rightContent && (
            <div className="border-stroke-widget bg-primary-widget min-h-75 w-full overflow-hidden rounded-xl border">
              {rightContent}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default WidgetLayout
