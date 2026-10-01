'use client';

import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import ProfileHeader from '@/components/ProfileHeader';
import { Box, PasswordInput, Loader } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { changePasswordAction } from '@/actions/auth.actions';
import type React from 'react';
import { useState, useMemo } from 'react';
import { useGetSessions, useRevokeSession } from '@/hooks/api/useAuthApi';
import type { SessionData } from '@/lib/api/auth';
import { validatePassword } from '@/lib/auth/passwordValidation';
import { PasswordStrengthIndicator } from '@/components/auth/PasswordStrengthIndicator';

interface SecurityTabProps {
  onClose?: () => void;
}

const SecurityTab: React.FC<SecurityTabProps> = ({ onClose }) => {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const passwordValidation = useMemo(
    () => validatePassword(newPassword),
    [newPassword]
  );
  const isSameAsCurrent = Boolean(
    currentPassword && newPassword && currentPassword === newPassword
  );

  const { data: sessionData, isLoading: isLoadingSessions } = useGetSessions();
  const revokeSessionMutation = useRevokeSession();

  const handleRevoke = async (id: string) => {
    try {
      await revokeSessionMutation.mutateAsync(id);
      notifications.show({
        title: 'Success',
        message: 'Device session revoked successfully.',
        color: 'green',
      });
    } catch (error: unknown) {
      const err = error as Error;
      notifications.show({
        title: 'Error',
        message: err.message || 'Failed to revoke device.',
        color: 'red',
      });
    }
  };

  const [isUpdatingPassword, setIsUpdatingPassword] = useState(false);

  const handleUpdatePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPassword) {
      notifications.show({
        title: 'Error',
        message: 'Please enter your current password.',
        color: 'red',
      });
      return;
    }

    if (!passwordValidation.isValid) {
      notifications.show({
        title: 'Weak Password',
        message:
          passwordValidation.errors[0] ||
          'Password must meet complexity requirements.',
        color: 'red',
      });
      return;
    }

    if (isSameAsCurrent) {
      notifications.show({
        title: 'Error',
        message: 'New password cannot be the same as your current password.',
        color: 'red',
      });
      return;
    }

    if (newPassword !== confirmPassword) {
      notifications.show({
        title: 'Error',
        message: 'New password and confirmation password do not match.',
        color: 'red',
      });
      return;
    }

    try {
      setIsUpdatingPassword(true);
      const result = await changePasswordAction({
        current_password: currentPassword,
        new_password: newPassword,
      });

      if (result.success) {
        notifications.show({
          title: 'Success',
          message: 'Password updated successfully!',
          color: 'green',
        });
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
      } else {
        notifications.show({
          title: 'Error',
          message: result.error || 'Failed to update password.',
          color: 'red',
        });
      }
    } catch (error) {
      console.error(error);
      notifications.show({
        title: 'Error',
        message: 'An unexpected error occurred.',
        color: 'red',
      });
    } finally {
      setIsUpdatingPassword(false);
    }
  };

  return (
    <div className="text-primary-text flex w-full flex-col">
      {/* Header */}
      <ProfileHeader name="Security" onClose={onClose} />
      <Box className="border-primary-text/6 border-t" />

      {/* Section 1: Change Password */}
      <div className="flex flex-col gap-4 p-4 sm:px-7! sm:py-6!">
        <h3 className="text-primary-text text-[15px] font-semibold">
          Change password
        </h3>

        <form onSubmit={handleUpdatePassword} className="flex flex-col gap-3">
          <PasswordInput
            placeholder="Current password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.currentTarget.value)}
            classNames={{
              root: 'w-full',
              wrapper: 'w-full',
              input:
                'bg-primary-text/2! border-primary-text/8! text-primary-text! placeholder:text-primary-text/30! rounded-full! h-10 px-4 text-sm focus:border-primary-text/20! w-full transition-all',
              innerInput:
                'text-primary-text! placeholder:text-primary-text/30!',
              visibilityToggle:
                'text-primary-text/40! hover:text-primary-text! mr-2 cursor-pointer',
            }}
          />

          <PasswordInput
            placeholder="New password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.currentTarget.value)}
            classNames={{
              root: 'w-full',
              wrapper: 'w-full',
              input:
                'bg-primary-text/2! border-primary-text/8! text-primary-text! placeholder:text-primary-text/30! rounded-full! h-10 px-4 text-sm focus:border-primary-text/20! w-full transition-all',
              innerInput:
                'text-primary-text! placeholder:text-primary-text/30!',
              visibilityToggle:
                'text-primary-text/40! hover:text-primary-text! mr-2 cursor-pointer',
            }}
          />

          <PasswordInput
            placeholder="Confirm new password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.currentTarget.value)}
            classNames={{
              root: 'w-full',
              wrapper: 'w-full',
              input:
                'bg-primary-text/2! border-primary-text/8! text-primary-text! placeholder:text-primary-text/30! rounded-full! h-10 px-4 text-sm focus:border-primary-text/20! w-full transition-all',
              innerInput:
                'text-primary-text! placeholder:text-primary-text/30!',
              visibilityToggle:
                'text-primary-text/40! hover:text-primary-text! mr-2 cursor-pointer',
            }}
          />

          <PasswordStrengthIndicator
            password={newPassword}
            confirmPassword={confirmPassword}
          />

          {isSameAsCurrent && (
            <p className="text-[11px] font-sans text-red-400">
              New password cannot be the same as your current password.
            </p>
          )}

          <PrimaryGlassBtn
            type="submit"
            disabled={
              isUpdatingPassword ||
              !currentPassword ||
              !passwordValidation.isValid ||
              newPassword !== confirmPassword ||
              isSameAsCurrent
            }
            className="bg-primary-text/10 hover:bg-primary-text/15 text-primary-text mt-1 flex w-full cursor-pointer items-center justify-center gap-2 rounded-full py-2.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isUpdatingPassword ? <Loader size={16} color="white" /> : null}
            Update password
          </PrimaryGlassBtn>
        </form>
      </div>

      {/* <Box className="border-primary-text/6 border-t p-0 sm:mx-7" /> */}

      {/* Section 2: Two-Factor Authentication */}
      {/* <div className="flex items-center justify-between p-4 sm:px-7! sm:py-6!">
        <div className="flex flex-col gap-1">
          <h3 className="text-primary-text text-[15px] font-semibold">
            Two-factor authentication
          </h3>
          <Text className="text-primary-text/45! text-[13px]!">
            Require an authenticator code in addition to your password.
          </Text>
        </div>

        <Switch
          checked={twoFactor}
          onChange={(e) => setTwoFactor(e.currentTarget.checked)}
          size="md"
          classNames={{
            track: `border rounded-full! w-[44px]! h-[24px]! cursor-pointer transition-all duration-200 ${
              twoFactor
                ? 'bg-primary-text/16! border-primary-text/22! shadow-[0px_1.5px_0px_0px_#FFFFFF59_inset,0px_2px_6px_0px_#00000033,0px_8px_32px_0px_#00000059]!'
                : 'bg-primary-text/6 border-primary-text/10 shadow-[0px_1px_0px_0px_#FFFFFF1F_inset,0px_4px_12px_0px_#00000040]'
            }`,
            thumb: `border w-[18px]! h-[18px]! rounded-full! transition-all duration-200 [&::before]:hidden! [&::after]:hidden! [&_*]:hidden! ${
              twoFactor
                ? 'bg-primary-text/92! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF99_inset,0px_2px_8px_0px_#00000059]'
                : 'bg-primary-text/35! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF4D_inset,0px_1px_4px_0px_#0000004D]'
            }`,
          }}
        />
      </div> */}

      <Box className="border-primary-text/6 border-t p-0 sm:mx-7" />

      {/* Section 3: Active Sessions */}
      <div className="flex flex-col gap-4 p-4 sm:px-7! sm:py-6!">
        <h3 className="text-primary-text text-[15px] font-semibold">
          Active sessions
        </h3>

        <div className="flex flex-col gap-3">
          {isLoadingSessions ? (
            <div className="flex justify-center py-4">
              <Loader size={24} color="gray" />
            </div>
          ) : (
            sessionData?.sessions?.map((session: SessionData) => (
              <div
                key={session.id}
                className="bg-primary-text/2 border-primary-text/8 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border p-4 transition-all"
              >
                <div className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-primary-text text-sm font-semibold">
                      {session.device_name ||
                        `${session.browser} on ${session.operating_system}`}
                    </span>
                    {session.current_device && (
                      <span className="rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400">
                        this device
                      </span>
                    )}
                  </div>
                  <span className="text-primary-text/40 text-xs break-all sm:break-normal">
                    {session.ip_address} · Last active:{' '}
                    {new Date(session.last_active_at).toLocaleString()}
                  </span>
                </div>

                {!session.current_device && (
                  <PrimaryGlassBtn
                    type="button"
                    onClick={() => handleRevoke(session.id)}
                    disabled={revokeSessionMutation.isPending}
                    className="bg-primary-text/6 border-primary-text/10 hover:bg-primary-text/12 text-primary-text cursor-pointer rounded-full border px-4 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 self-start sm:self-center shrink-0"
                  >
                    Revoke
                  </PrimaryGlassBtn>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default SecurityTab;
