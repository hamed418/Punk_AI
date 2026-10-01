import PrimaryBtn from '@/components/PrimaryBtn';
import SecondaryBtn from '@/components/secondaryBtn';
import { Mail, MoreVertical, Plus } from 'lucide-react';
import type React from 'react';

interface PlatformCardProps {
  name: string;
  description: string;
  accentColor: string;
  logoUrl: string;
  connected: boolean;
  accountName?: string | null;
  accountEmail?: string | null;
  onConnect: () => void;
  onDisconnect: () => void;
  disabled: boolean;
}

const PlatformCard: React.FC<PlatformCardProps> = ({
  name,
  description,
  accentColor,
  logoUrl,
  connected,
  accountName,
  accountEmail,
  onConnect,
  onDisconnect,
  disabled,
}) => {
  return (
    <div className="bg-primary-widget flex h-full flex-col rounded-2xl p-5">
      {/* Top row: logo + connect button */}
      <div className="mb-4 flex items-center justify-between">
        <div className="border-border flex h-10 w-10 items-center justify-center overflow-hidden rounded-xl border p-2">
          <img
            src={logoUrl}
            alt={name}
            className="h-full w-full object-contain"
          />
        </div>

        {connected ? (
          <PrimaryBtn>Connected</PrimaryBtn>
        ) : (
          <SecondaryBtn
            className="border-profile-stroke! rounded-md! border! px-2! py-1!"
            onClick={onConnect}
            disabled={disabled}
          >
            <Plus size={14} /> Connect
          </SecondaryBtn>
        )}
      </div>

      <h3 className="font-display text-primary-text mb-1 text-lg font-bold">
        {name}
      </h3>

      {connected ? (
        <div className="mt-3 flex items-center gap-3">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white"
            style={{ backgroundColor: accentColor }}
          >
            {accountName ? accountName.charAt(0).toUpperCase() : 'A'}
          </div>

          {/* Account info */}
          <div className="min-w-0 flex-1">
            <p className="font-body text-primary-text truncate text-sm font-semibold">
              {accountName || 'Active Business Account'}
            </p>
            {accountEmail && (
              <p className="font-body text-primary-text flex items-center gap-1 truncate text-xs">
                <Mail size={11} />
                {accountEmail}
              </p>
            )}
          </div>

          <button
            onClick={onDisconnect}
            disabled={disabled}
            className="text-primary-text hover:bg- hover:text-primary-text shrink-0 cursor-pointer rounded-md p-1 transition-colors disabled:opacity-50"
            aria-label="Account options"
          >
            <MoreVertical size={16} />
          </button>
        </div>
      ) : (
        <p className="font-body text-primary-text text-[13px] leading-relaxed">
          {description}
        </p>
      )}
    </div>
  );
};

export default PlatformCard;
