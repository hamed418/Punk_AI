import React, { useState } from 'react';
import { useRevokePendingSession, useCompleteLogin } from '@/hooks/api/useAuthApi';
import type { SessionListResponse } from '@/lib/api/auth';
import { Box, Text } from '@mantine/core';
import {
  Smartphone,
  Tablet,
  Laptop,
  Monitor,
  Check,
  Loader2,
  AlertCircle,
  ShieldAlert,
  LogOut,
  ArrowLeft,
} from 'lucide-react';

interface DeviceLimitModalProps {
  data: SessionListResponse & { pending_login_token: string };
  onClose: () => void;
  onSuccess: () => void;
  asModal?: boolean;
}

export const DeviceLimitModal: React.FC<DeviceLimitModalProps> = ({
  data,
  onClose,
  onSuccess,
  asModal = false,
}) => {
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const revokePendingSessionMutation = useRevokePendingSession();
  const completeLoginMutation = useCompleteLogin();

  const handleToggleSession = (id: string) => {
    setSelectedSessionIds((prev) =>
      prev.includes(id) ? prev.filter((sId) => sId !== id) : [...prev, id]
    );
  };

  const handleRemoveDevice = async () => {
    if (selectedSessionIds.length === 0) return;

    setLoading(true);
    setError(null);
    try {
      // 1. Revoke the selected sessions
      for (const sessionId of selectedSessionIds) {
        await revokePendingSessionMutation.mutateAsync({
          pendingToken: data.pending_login_token,
          sessionId: sessionId,
        });
      }

      // 2. Complete login
      await completeLoginMutation.mutateAsync(data.pending_login_token);

      onSuccess();
    } catch (err: unknown) {
      const errObj = err as Error;
      setError(errObj.message || 'Failed to remove devices or complete login.');
    } finally {
      setLoading(false);
    }
  };

  const getDeviceIcon = (deviceType?: string | null) => {
    switch (deviceType?.toLowerCase()) {
      case 'mobile':
        return <Smartphone size={18} />;
      case 'tablet':
        return <Tablet size={18} />;
      case 'desktop':
        return <Monitor size={18} />;
      default:
        return <Laptop size={18} />;
    }
  };

  const formatLastActive = (dateString?: string | null) => {
    if (!dateString) return null;
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return null;
    }
  };

  const content = (
    <div className="flex flex-col gap-4 px-6 py-8 sm:px-8 sm:py-10">
      {/* Header */}
      <Box className="text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl border border-[#D62575]/30 bg-[#D62575]/10 text-[#D62575] shadow-[0_0_20px_rgba(214,37,117,0.2)]">
          <ShieldAlert size={24} />
        </div>
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Device limit reached
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          You are currently logged in on{' '}
          <span className="font-semibold text-white">
            {data.active_devices} device{data.active_devices > 1 ? 's' : ''}
          </span>
          . Select at least one device to log out and continue.
        </Text>
      </Box>

      {/* Error alert */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
          <AlertCircle className="size-4 shrink-0 text-red-400" />
          <span className="leading-tight">{error}</span>
        </div>
      )}

      {/* Device sessions list */}
      <div className="flex flex-col gap-2 max-h-[38vh] sm:max-h-[44vh] overflow-y-auto pr-1">
        {data.sessions.map((session) => {
          const isSelected = selectedSessionIds.includes(session.id);
          const lastActiveFormatted = formatLastActive(session.last_active_at);

          return (
            <div
              key={session.id}
              onClick={() => handleToggleSession(session.id)}
              className={`group flex cursor-pointer items-center justify-between gap-3 rounded-2xl border p-3 sm:p-3.5 transition-all duration-150 select-none ${
                isSelected
                  ? 'border-[#D62575]/70 bg-[#D62575]/15 shadow-[0_0_16px_rgba(214,37,117,0.18)]'
                  : 'border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/8'
              }`}
            >
              <div className="flex min-w-0 items-center gap-3">
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border transition-colors ${
                    isSelected
                      ? 'border-[#D62575]/50 bg-[#D62575]/25 text-white'
                      : 'border-white/10 bg-white/5 text-white/70 group-hover:text-white'
                  }`}
                >
                  {getDeviceIcon(session.device_type)}
                </div>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-white">
                    {session.device_name || 'Unknown Device'}
                  </p>
                  <p className="truncate text-xs text-white/60">
                    {[session.browser, session.operating_system]
                      .filter(Boolean)
                      .join(' • ') || 'Active Session'}
                  </p>
                  {lastActiveFormatted && (
                    <p className="mt-0.5 text-[11px] text-white/40">
                      Active: {lastActiveFormatted}
                    </p>
                  )}
                </div>
              </div>

              {/* Checkbox indicator */}
              <div
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all duration-150 ${
                  isSelected
                    ? 'border-[#D62575] bg-[#D62575] text-white'
                    : 'border-white/30 bg-transparent group-hover:border-white/50'
                }`}
              >
                {isSelected && <Check size={12} strokeWidth={3} />}
              </div>
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <Box className="flex flex-col gap-2.5 pt-1">
        <button
          type="button"
          onClick={handleRemoveDevice}
          disabled={selectedSessionIds.length === 0 || loading}
          className="flex h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            boxShadow:
              '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
          }}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <>
              <LogOut size={16} />
              <span>
                {selectedSessionIds.length > 0
                  ? `Log out ${selectedSessionIds.length} device${selectedSessionIds.length > 1 ? 's' : ''} & continue`
                  : 'Select devices to log out'}
              </span>
            </>
          )}
        </button>

        <button
          type="button"
          onClick={onClose}
          disabled={loading}
          className="flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-white/10 bg-white/5 text-sm font-medium text-white/80 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-50"
        >
          <ArrowLeft size={14} />
          <span>Cancel & Back to login</span>
        </button>
      </Box>
    </div>
  );

  if (asModal) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-md">
        <div className="relative w-full max-w-110 overflow-hidden rounded-[40px] border border-white/10 bg-[#00000095] shadow-2xl backdrop-blur-[18px]">
          {content}
        </div>
      </div>
    );
  }

  return content;
};
