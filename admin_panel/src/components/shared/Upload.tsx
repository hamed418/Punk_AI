import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import PrimaryBtn from "./PrimaryBtn";

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
  imgSrc: string;
  title: string | ReactNode;
  text: string | ReactNode;
  className?: string;
  btnLabel?: string;
  btnOnClick?: () => void;
  btnClassName?: string;
  btnLeftSection?: ReactNode;
  disabled?: boolean;
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
        "flex items-center w-full justify-between gap-3 p-2 rounded-2xl",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <div className="min-w-4">
          <img src={imgSrc} alt="logo" className="h-10 w-10 object-contain" />
        </div>

        <div className="flex flex-col">
          <p className="text-sm font-semibold font-inter">{title}</p>
          <p className="text-[12px] font-normal  text-[#62646A]">{text}</p>
        </div>
      </div>

      {btnLabel && (
        <PrimaryBtn
          onClick={btnOnClick}
          className={cn(btnClassName!)}
          leftSection={btnLeftSection}
          disabled={disabled}
        >
          {btnLabel}
        </PrimaryBtn>
      )}
    </div>
  );
}

export default Upload;
