import React from 'react';
import { Lock } from 'lucide-react';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';

interface LockedOverlayProps {
  children: React.ReactNode;
  onUnlock: () => void;
  message?: string;
}

export default function LockedOverlay({
  children,
  onUnlock,
  message = 'This section is locked for Beginner user. You can unlock this to understand how punk creates your Ad',
}: LockedOverlayProps) {
  return (
    <div className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
      {/* Blurred background form */}
      <div className="custom-scrollbar flex min-h-0 w-full flex-1 flex-col gap-4 overflow-y-hidden p-5 filter blur-[6px] pointer-events-none select-none opacity-30">
        {children}
      </div>

      {/* Centered Locked Overlay matching Figma design */}
      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center p-6 text-center">
        <p className="text-secondary-text/80 mb-3.5 max-w-110 text-[13px] leading-relaxed">
          {message}
        </p>
        <PrimaryGlassBtn onClick={onUnlock} rightSection={<Lock />}>
          <span>Unlock and View</span>
        </PrimaryGlassBtn>
      </div>
    </div>
  );
}
