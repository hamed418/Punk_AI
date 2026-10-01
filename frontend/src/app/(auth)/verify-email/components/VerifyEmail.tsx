'use client';

import { Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import { Box, Text } from '@mantine/core';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import { useVerifyEmail, useResendVerification } from '@/hooks/api/useAuthApi';
import { extractErrorMessage } from '@/lib/errorUtils';

const OTP_LENGTH = 5;
const RESEND_COUNTDOWN = 90; // seconds



const VerifyEmail: React.FC = () => {
  const searchParams = useSearchParams();
  const router = useRouter();
  const emailParam = searchParams.get('email') || '';

  const [otp, setOtp] = useState<string[]>(Array(OTP_LENGTH).fill(''));
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [countdown, setCountdown] = useState(RESEND_COUNTDOWN);

  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  const verifyEmailMutation = useVerifyEmail();
  const resendVerificationMutation = useResendVerification();

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  };

  const handleOtpChange = (index: number, value: string) => {
    const digit = value.replace(/\D/g, '').slice(-1);
    const next = [...otp];
    next[index] = digit;
    setOtp(next);
    setError(null);

    if (digit && index < OTP_LENGTH - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (
    index: number,
    e: React.KeyboardEvent<HTMLInputElement>
  ) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
    if (e.key === 'ArrowLeft' && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
    if (e.key === 'ArrowRight' && index < OTP_LENGTH - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData
      .getData('text')
      .replace(/\D/g, '')
      .slice(0, OTP_LENGTH);
    const next = Array(OTP_LENGTH).fill('');
    pasted.split('').forEach((ch, i) => {
      next[i] = ch;
    });
    setOtp(next);
    const focusIndex = Math.min(pasted.length, OTP_LENGTH - 1);
    inputRefs.current[focusIndex]?.focus();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    if (!emailParam) {
      setError('Missing email parameter. Please register or specify email.');
      return;
    }

    const code = otp.join('');
    if (code.length < OTP_LENGTH) {
      setError(`Please enter all ${OTP_LENGTH} digits.`);
      return;
    }

    setIsSubmitting(true);
    try {
      await verifyEmailMutation.mutateAsync({ email: emailParam, code });
      setSuccessMsg('Email verified successfully! Redirecting...');
      setTimeout(() => {
        router.push('/');
      }, 1500);
    } catch (err: unknown) {
      setError(
        extractErrorMessage(
          err,
          'Verification failed. Please check the code and try again.'
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResend = async () => {
    if (countdown > 0) return;
    setError(null);
    setSuccessMsg(null);

    if (!emailParam) {
      setError('Missing email parameter.');
      return;
    }

    try {
      await resendVerificationMutation.mutateAsync({ email: emailParam });
      setSuccessMsg('A new verification code has been sent to your email.');
      setCountdown(RESEND_COUNTDOWN);
    } catch (err: unknown) {
      setError(
        extractErrorMessage(err, 'Failed to resend code. Please try again.')
      );
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-8 py-10">
      <Box className="text-center">
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Verify your email
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          Enter the 5-digit code sent to
        </Text>
        <Text className="mt-0.5 text-xs! font-medium text-[#faf9f5]">
          {emailParam || 'your email'}
        </Text>
      </Box>

      <Box className="border-t border-white/10" />

      <Box className="flex flex-col gap-4">
        {/* OTP Inputs */}
        <Box className="flex justify-center gap-2.5">
          {otp.map((digit, i) => (
            <input
              key={i}
              ref={(el) => {
                inputRefs.current[i] = el;
              }}
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={1}
              value={digit}
              onChange={(e) => handleOtpChange(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
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

        {successMsg && (
          <div className="flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3.5 py-2.5 text-xs text-emerald-400">
            <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
            <span className="leading-tight">{successMsg}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            boxShadow:
              '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
          }}
        >
          {isSubmitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            'Verify'
          )}
        </button>

        <Box className="flex flex-col items-center gap-2">
          <button
            type="button"
            onClick={handleResend}
            disabled={countdown > 0 || isSubmitting}
            className="cursor-pointer text-center text-xs text-[#FAF9F5] underline-offset-4 transition-colors hover:underline disabled:cursor-not-allowed disabled:opacity-40"
          >
            Didn&apos;t get the code? Resend code
          </button>

          <Link
            href="/"
            className="text-xs text-[#faf9f5]/70 underline-offset-4 transition-colors hover:text-white hover:underline"
          >
            Back to Punk
          </Link>
        </Box>
      </Box>
    </form>
  );
};

export default VerifyEmail;
