import React, { useState } from 'react';
import Link from 'next/link';
import { Box, Input, Text } from '@mantine/core';
import { Loader2, AlertCircle, Eye, EyeOff } from 'lucide-react';

export interface LoginPasswordStepProps {
  email: string;
  password: string;
  setPassword: (val: string) => void;
  handlePasswordLogin: (e?: React.FormEvent) => void;
  handlePrevStep?: () => void;
  isSubmitting: boolean;
  error?: string;
}

export const LoginPasswordStep: React.FC<LoginPasswordStepProps> = ({
  email,
  password,
  setPassword,
  handlePasswordLogin,
  handlePrevStep,
  isSubmitting,
  error,
}) => {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <form
      onSubmit={handlePasswordLogin}
      className="flex flex-col gap-4 px-8 py-10 animate-auth-in"
    >
      <Box className="text-center">
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Enter your password
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          {email}
        </Text>
      </Box>

      <Box className="border-t border-white/10" />

      <Box className="flex flex-col gap-3">
        {/* Password Input */}
        <Box className="relative">
          <Input
            variant="unstyled"
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter your password"
            autoFocus
            className="w-full"
            classNames={{
              input:
                'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-4.5! pr-11! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
            }}
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute top-1/2 right-4 -translate-y-1/2 cursor-pointer text-[#FAF9F573] transition-colors hover:text-white"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? (
              <EyeOff className="size-4" />
            ) : (
              <Eye className="size-4" />
            )}
          </button>
        </Box>

        <Box className="flex items-center justify-end px-1 text-xs">
          <Link
            href={
              email
                ? `/forgot-password?email=${encodeURIComponent(email)}`
                : '/forgot-password'
            }
            className="font-medium text-[#FAF9F5] underline-offset-4 transition-colors hover:underline"
          >
            Forgot password?
          </Link>
        </Box>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
            <AlertCircle className="size-4 shrink-0 text-red-400" />
            <span className="leading-tight">{error}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !password.trim()}
          className="flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:opacity-50"
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

        {handlePrevStep && (
          <Box className="flex justify-center pt-1">
            <button
              type="button"
              onClick={handlePrevStep}
              className="cursor-pointer text-xs! text-[#faf9f5]/70 underline-offset-4 transition-colors hover:text-white underline"
            >
              Back to login
            </button>
          </Box>
        )}
      </Box>

      <div className="mt-2 flex items-center justify-center gap-3 text-xs text-white/60">
        <a
          href="https://usepunk.ai/terms"
          target="_blank"
          rel="noopener noreferrer"
          className="underline-offset-4 hover:text-white hover:underline"
        >
          Terms of Use
        </a>
        <span>|</span>
        <a
          href="https://usepunk.ai/privacy"
          target="_blank"
          rel="noopener noreferrer"
          className="underline-offset-4 hover:text-white hover:underline"
        >
          Privacy Policy
        </a>
      </div>
    </form>
  );
};
