import React, { KeyboardEvent, RefObject } from 'react';
import { Box, Text } from '@mantine/core';
import { Loader2, AlertCircle } from 'lucide-react';

export interface SignupOtpStepProps {
  email: string;
  otp: string[];
  setOtp: (val: string[]) => void;
  handleVerifyOtp: (e?: React.FormEvent) => void;
  handlePrevStep: () => void;
  handleResendOtp?: () => void;
  isSubmitting: boolean;
  otpRefs: RefObject<(HTMLInputElement | null)[]>;
  error?: string;
  countdown?: number;
  isResending?: boolean;
}



function formatTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

export const SignupOtpStep: React.FC<SignupOtpStepProps> = ({
  email,
  otp,
  setOtp,
  handleVerifyOtp,
  handlePrevStep,
  handleResendOtp,
  isSubmitting,
  otpRefs,
  error,
  countdown = 0,
  isResending = false,
}) => {
  const isComplete = otp.every((digit) => digit.trim().length === 1);

  const handleOtpChange = (
    index: number,
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const value = e.target.value;
    const cleanValue = value.replace(/\D/g, '');
    if (!cleanValue && value !== '') return;

    const newOtp = [...otp];
    newOtp[index] = cleanValue ? cleanValue.slice(-1) : '';
    setOtp(newOtp);

    if (cleanValue && index < 5) {
      otpRefs.current?.[index + 1]?.focus();
    }
  };

  const handleOtpKeyDown = (
    index: number,
    e: KeyboardEvent<HTMLInputElement>
  ) => {
    if (e.key === 'Backspace') {
      if (otp[index]) {
        const newOtp = [...otp];
        newOtp[index] = '';
        setOtp(newOtp);
      } else if (index > 0) {
        otpRefs.current?.[index - 1]?.focus();
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      otpRefs.current?.[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < 5) {
      otpRefs.current?.[index + 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData('text').replace(/\D/g, '');
    if (!pastedData) return;

    const digits = pastedData.slice(0, 6).split('');
    const newOtp = [...otp];
    digits.forEach((digit, i) => {
      if (i < 6) newOtp[i] = digit;
    });
    setOtp(newOtp);

    const nextIndex = Math.min(digits.length, 5);
    otpRefs.current?.[nextIndex]?.focus();
  };

  return (
    <form
      onSubmit={handleVerifyOtp}
      className="flex flex-col gap-4 px-8 py-10 animate-auth-in"
    >
      <Box className="text-center">
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Verify your email
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          Enter the 6-digit code sent to
        </Text>
        <Text className="mt-0.5 text-xs! font-medium text-[#faf9f5]">
          {email || 'your email'}
        </Text>
      </Box>

      <Box className="border-t border-white/10" />

      <Box className="flex flex-col gap-4">
        {/* OTP Inputs */}
        <Box className="flex justify-center gap-2.5">
          {otp.map((digit, index) => (
            <input
              key={index}
              ref={(el) => {
                if (otpRefs.current) otpRefs.current[index] = el;
              }}
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={1}
              value={digit}
              onChange={(e) => handleOtpChange(index, e)}
              onKeyDown={(e) => handleOtpKeyDown(index, e)}
              onPaste={handlePaste}
              className="h-13 w-11.5 rounded-2xl border border-white/10 bg-white/6 text-center text-xl font-semibold text-[#FAF9F5] transition-all focus:border-white/20 focus:bg-[#FFFFFF08] focus:outline-none"
            />
          ))}
        </Box>

        {/* Countdown */}
        <Text className="text-center text-xs text-[#faf9f5]/60">
          Resend in:{' '}
          <span
            className={
              countdown > 0
                ? 'font-medium text-[#ED4F30]'
                : 'font-medium text-white/60'
            }
          >
            {countdown > 0 ? formatTime(countdown) : '00:00'}
          </span>
        </Text>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
            <AlertCircle className="size-4 shrink-0 text-red-400" />
            <span className="leading-tight">{error}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !isComplete}
          className="flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            boxShadow:
              '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
          }}
        >
          {isSubmitting ? (
            <Loader2 className="h-4 w-4 animate-spin text-white" />
          ) : (
            'Verify'
          )}
        </button>

        <Box className="flex flex-col items-center gap-2">
          <button
            type="button"
            onClick={handleResendOtp}
            disabled={countdown > 0 || isResending || isSubmitting}
            className="cursor-pointer text-center text-xs text-[#FAF9F5] underline-offset-4 transition-colors hover:underline disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isResending ? 'Sending...' : "Didn't get the code? Resend code"}
          </button>

          <button
            type="button"
            onClick={handlePrevStep}
            className="cursor-pointer text-xs text-[#faf9f5]/70 underline-offset-4 transition-colors hover:text-white hover:underline"
          >
            Back to email
          </button>
        </Box>
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
