import { cn } from '@/lib/utils';

export default function Stat({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex min-w-0 flex-col border-r border-[#FFFFFF12]',
        className
      )}
    >
      <span className="text-secondary-text/60 text-[11px]">{label}</span>
      <span className="text-primary-text truncate text-[13px] font-medium">
        {value}
      </span>
    </div>
  );
}
