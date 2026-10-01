'use client';

import { TextShimmer } from './TextShimmer';
import { cn } from '@/lib/utils';
import { ChevronRight } from 'lucide-react';
import { useState } from 'react';

type ThinkingBarProps = {
  className?: string;
  text?: string;
  onClick?: () => void;
};

export function ThinkingBar({
  className,
  text = 'Thinking',
  onClick,
}: ThinkingBarProps) {
  const [clicked, setClicked] = useState(false);

  return (
    <div className={cn('flex w-full items-center justify-between', className)}>
      {onClick ? (
        <button
          type="button"
          onClick={() => setClicked(!clicked)}
          className="flex cursor-pointer items-center gap-1 text-sm transition-opacity hover:opacity-80"
        >
          <TextShimmer className="font-medium">{text}</TextShimmer>
          <ChevronRight
            className="text-primary-text size-7 transition-transform duration-150"
            style={{ rotate: clicked ? '90deg' : '0deg' }}
          />
        </button>
      ) : (
        <TextShimmer className="cursor-default font-medium">{text}</TextShimmer>
      )}
    </div>
  );
}
