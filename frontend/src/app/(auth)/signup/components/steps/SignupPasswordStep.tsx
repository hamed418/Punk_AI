import React, { useMemo } from 'react';
import { Box, Input, Text } from '@mantine/core';
import { ChevronLeft, Eye, EyeOff, Loader2, AlertCircle } from 'lucide-react';
import { PasswordStrengthIndicator } from '@/components/auth/PasswordStrengthIndicator';
import { validatePassword } from '@/lib/auth/passwordValidation';

export interface SignupPasswordStepProps {
  password: string;
  setPassword: (val: string) => void;
  confirmPassword: string;
  setConfirmPassword: (val: string) => void;
  showPassword: boolean;
  setShowPassword: (val: boolean) => void;
  showConfirmPassword: boolean;
  setShowConfirmPassword: (val: boolean) => void;
  handlePasswordSubmit: (e?: React.FormEvent) => void;
  handlePrevStep?: () => void;
  isSubmitting: boolean;
  error?: string;
}

export const SignupPasswordStep: React.FC<SignupPasswordStepProps> = ({
  password,
  setPassword,
  confirmPassword,
  setConfirmPassword,
  showPassword,
  setShowPassword,
  showConfirmPassword,
  setShowConfirmPassword,
  handlePasswordSubmit,
  handlePrevStep,
  isSubmitting,
  error,
}) => {
  const validation = useMemo(() => validatePassword(password), [password]);
  const hasConfirmTyped = confirmPassword.length > 0;
  const passwordsMatch = hasConfirmTyped && password === confirmPassword;
  const canSubmit = validation.isValid && passwordsMatch;

  return (
    <form
      onSubmit={handlePasswordSubmit}
      className="relative flex flex-col gap-4 px-8 py-10"
    >
      {handlePrevStep && (
        <button
          type="button"
          onClick={handlePrevStep}
          className="absolute top-7 left-7 cursor-pointer text-[#faf9f5]/60 transition-colors hover:text-[#faf9f5]"
          aria-label="Go back"
        >
          <ChevronLeft className="h-4.5 w-4.5" />
        </button>
      )}

      <Box className="text-center">
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Set up your password
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          Create a secure password to protect your account.
        </Text>
      </Box>

      <Box className="border-t border-white/10" />

      <Box className="flex flex-col gap-3.5">
        <Box>
          <Text className="mb-2 pb-1.25! text-[13px]! font-medium! text-white/90">
            New password
          </Text>
          <Box className="relative">
            <Input
              variant="unstyled"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              className="w-full"
              classNames={{
                input:
                  'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-5! pr-12! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
              }}
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowPassword(!showPassword)}
              className="absolute top-1/2 right-4 -translate-y-1/2 cursor-pointer text-[#FAF9F5]/70 transition-colors hover:text-[#FAF9F5]"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? (
                <EyeOff className="h-5 w-5" />
              ) : (
                <Eye className="h-5 w-5" />
              )}
            </button>
          </Box>
        </Box>

        <Box>
          <Text className="mb-2 pb-1.25! text-[13px]! font-medium! text-white/90">
            Confirm password
          </Text>
          <Box className="relative">
            <Input
              variant="unstyled"
              type={showConfirmPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter your password"
              className="w-full"
              classNames={{
                input:
                  'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-5! pr-12! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
              }}
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowConfirmPassword(!showConfirmPassword)}
              className="absolute top-1/2 right-4 -translate-y-1/2 cursor-pointer text-[#FAF9F5]/70 transition-colors hover:text-[#FAF9F5]"
              aria-label={
                showConfirmPassword ? 'Hide password' : 'Show password'
              }
            >
              {showConfirmPassword ? (
                <EyeOff className="h-5 w-5" />
              ) : (
                <Eye className="h-5 w-5" />
              )}
            </button>
          </Box>
        </Box>

        {/* Live Password Strength & Requirements Checklist */}
        <PasswordStrengthIndicator
          password={password}
          confirmPassword={confirmPassword}
        />
      </Box>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
          <AlertCircle className="size-4 shrink-0 text-red-400" />
          <span className="leading-tight">{error}</span>
        </div>
      )}

      <Box className="border-t border-white/10" />

      <button
        type="submit"
        disabled={isSubmitting || !canSubmit}
        className={`flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! ${
          canSubmit ? 'text-white hover:bg-white/15' : 'text-white/40'
        } transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50`}
        style={{
          boxShadow:
            '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
        }}
      >
        {isSubmitting ? (
          <Loader2 className="h-4 w-4 animate-spin text-white" />
        ) : (
          'Continue'
        )}
      </button>
    </form>
  );
};
