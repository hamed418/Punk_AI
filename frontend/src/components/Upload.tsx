import type { ReactNode } from 'react'
import PrimaryBtn from './PrimaryBtn'
import { cn } from '@/lib/utils'

// --------------USAGE EXAMPLE:------------------

{
  /* <Upload 
  imgSrc="/logo.svg" 
  title="Powered by" 
  text="My Company"
  btnLabel="Learn More"
  btnLeftSection={<IconComponent />}
  btnOnClick={() => console.log('clicked')}
/> */
}

interface UploadProps {
  imgSrc: string
  title: string | ReactNode
  text: string | ReactNode
  className?: string
  btnLabel?: string
  btnOnClick?: () => void
  btnClassName?: string
  btnLeftSection?: ReactNode
  disabled?: boolean
}

function Upload({
  imgSrc,
  title,
  text,
  className,
  btnLabel,
  btnOnClick,
  btnClassName,
  btnLeftSection,
  disabled = false,
}: UploadProps) {
  return (
    <div
      className={cn(
        'flex w-full items-center justify-between gap-3 rounded-2xl p-2',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <div className="max-w-10 min-w-10">
          <img src={imgSrc} alt="logo" className="h-9 w-9 object-contain" />
        </div>

        <div className="flex flex-col">
          <p className="text-primary-text truncate text-[13.5px] leading-tight font-semibold">
            {title}
          </p>
          <p className="text-secondary-text mt-0.5 max-w-56 truncate text-[13px] font-normal">
            {text}
          </p>
        </div>
      </div>

      {btnLabel && (
        <PrimaryBtn
          onClick={btnOnClick}
          className={cn(btnClassName)}
          leftSection={btnLeftSection}
          disabled={disabled}
        >
          {btnLabel}
        </PrimaryBtn>
      )}
    </div>
  )
}

export default Upload
