'use client';

import {
  Loader2,
  Eye,
  EyeOff,
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
} from 'lucide-react';
import type React from 'react';
import { useState, useRef, useEffect, useMemo } from 'react';
import { Box, Input, Text } from '@mantine/core';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useForgotPassword, useResetPassword } from '@/hooks/api/useAuthApi';
import { extractErrorMessage } from '@/lib/errorUtils';
import { PasswordStrengthIndicator } from '@/components/auth/PasswordStrengthIndicator';
import { validatePassword } from '@/lib/auth/passwordValidation';

const OTP_LENGTH = 5;
const RESEND_COOLDOWN_SECONDS = 60;

type Step = 'confirm' | 'otp' | 'new-password';

const ForgotPass: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Initial email resolution from URL query or fallback
  const initialEmail = searchParams.get('email') || '';

  const [step, setStep] = useState<Step>('confirm');
  const [email, setEmail] = useState(initialEmail);
  const [isEditingEmail, setIsEditingEmail] = useState(!initialEmail);

  // OTP State
  const [otp, setOtp] = useState<string[]>(Array(OTP_LENGTH).fill(''));
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const [resendCountdown, setResendCountdown] = useState(0);

  // Password State
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const newPasswordValidation = useMemo(
    () => validatePassword(newPassword),
    [newPassword]
  );

  // Status & Feedback
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // API mutations
  const forgotPasswordMutation = useForgotPassword();
  const resetPasswordMutation = useResetPassword();


  // Resend Countdown Timer
  useEffect(() => {
    if (resendCountdown <= 0) return;
    const interval = setInterval(() => {
      setResendCountdown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(interval);
  }, [resendCountdown]);

  // Auto-focus first OTP input when switching to 'otp' step
  useEffect(() => {
    if (step === 'otp') {
      setTimeout(() => {
        inputRefs.current[0]?.focus();
      }, 50);
    }
  }, [step]);

  // Handle Step 1: Send OTP / Confirmation
  const handleConfirmSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError('Please enter your email address.');
      return;
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError('Please enter a valid email address.');
      return;
    }

    setIsSubmitting(true);
    try {
      await forgotPasswordMutation.mutateAsync({ email: trimmedEmail });
      setResendCountdown(RESEND_COOLDOWN_SECONDS);
      setStep('otp');
    } catch (err: unknown) {
      setError(
        extractErrorMessage(err, 'Failed to send reset code. Please try again.')
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // OTP change handlers
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

  // Step 2: Handle OTP Submit
  const handleOtpSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    const code = otp.join('');
    if (code.length < OTP_LENGTH) {
      setError(`Please enter all ${OTP_LENGTH} digits.`);
      return;
    }

    // OTP is complete, proceed to Step 3: Set New Password
    setStep('new-password');
  };

  // Resend OTP
  const handleResend = async () => {
    if (resendCountdown > 0 || isSubmitting) return;

    setError(null);
    setSuccessMsg(null);
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError('Please enter your email address.');
      return;
    }

    setIsSubmitting(true);
    try {
      await forgotPasswordMutation.mutateAsync({ email: trimmedEmail });
      setResendCountdown(RESEND_COOLDOWN_SECONDS);
      setSuccessMsg('A new reset code has been sent to your email.');
    } catch (err: unknown) {
      setError(
        extractErrorMessage(err, 'Failed to resend code. Please try again.')
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Step 3: Handle New Password Submit
  const handleNewPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    const code = otp.join('');
    if (code.length < OTP_LENGTH) {
      setError(`Please enter all ${OTP_LENGTH} digits of your verification code.`);
      setStep('otp');
      return;
    }

    if (!newPasswordValidation.isValid) {
      setError(
        newPasswordValidation.errors[0] ||
          'Password does not meet security requirements.'
      );
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match. Please check and try again.');
      return;
    }

    setIsSubmitting(true);
    try {
      await resetPasswordMutation.mutateAsync({
        email: email.trim(),
        code,
        new_password: newPassword,
      });

      setSuccessMsg(
        'Password has been successfully reset! Redirecting to login...'
      );

      const targetEmail = email.trim();
      resetLoginSession(targetEmail);

      setTimeout(() => {
        const targetUrl = targetEmail
          ? `/?step=1&email=${encodeURIComponent(targetEmail)}`
          : '/?step=1';
        router.push(targetUrl);
      }, 1500);
    } catch (err: unknown) {
      const errMsg = extractErrorMessage(
        err,
        'Failed to reset password. Please check your verification code and try again.'
      );
      setError(errMsg);

      // If backend reports an invalid code, allow user to return to OTP step easily
      if (errMsg.toLowerCase().includes('code')) {
        setTimeout(() => {
          setStep('otp');
        }, 1200);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reset login state and return to login step 1
  const resetLoginSession = (targetEmail?: string) => {
    try {
      sessionStorage.setItem('signup_step', '1');
      sessionStorage.removeItem('auth_flow');
      sessionStorage.removeItem('login_method');
      sessionStorage.removeItem('login_token');
      sessionStorage.removeItem('signup_token');
      sessionStorage.removeItem('signup_password');
      sessionStorage.removeItem('signup_full_name');
      sessionStorage.removeItem('signup_business_type');
      sessionStorage.removeItem('signup_why_choose');
      sessionStorage.removeItem('signup_is_social');
      sessionStorage.removeItem('signup_social_method');
      sessionStorage.removeItem('signup_social_paid');
      if (targetEmail) {
        sessionStorage.setItem('signup_email', targetEmail);
      }
    } catch {
      // Ignore if sessionStorage access is restricted
    }
  };

  const handleBackToLogin = (e?: React.MouseEvent) => {
    if (e) e.preventDefault();
    const targetEmail = email.trim();
    resetLoginSession(targetEmail);
    const targetUrl = targetEmail
      ? `/?step=1&email=${encodeURIComponent(targetEmail)}`
      : '/?step=1';
    router.push(targetUrl);
  };

  // Handle top-left back chevron button
  const handleBack = () => {
    setError(null);
    setSuccessMsg(null);

    if (step === 'new-password') {
      setStep('otp');
    } else if (step === 'otp') {
      setStep('confirm');
    } else {
      handleBackToLogin();
    }
  };

  const isOtpComplete = otp.join('').length === OTP_LENGTH;

  return (
    <>
      {/* Top Left Back Navigation */}
      <button
        type="button"
        onClick={handleBack}
        className="absolute top-7 left-7 z-20 cursor-pointer text-[#faf9f5]/60 transition-colors hover:text-[#faf9f5]"
        aria-label="Go back"
      >
        <ChevronLeft className="h-5 w-5" />
      </button>

      {/* ================= STEP 1: CONFIRMATION ================= */}
      {step === 'confirm' && (
        <form
          onSubmit={handleConfirmSubmit}
          className="flex flex-col gap-5 px-4 py-5 animate-auth-in"
        >
          {/* Header */}
          <Box className="text-center">
            <Text className="text-2xl! font-semibold! text-[#faf9f5]">
              Reset password
            </Text>
            <Text className="mt-1! text-xs! text-[#faf9f5]/70">
              We&apos;ll help you get back in.
            </Text>
          </Box>

          {/* Body Content */}
          <Box className="my-2 text-center">
            {email && !isEditingEmail ? (
              <Box className="flex flex-col items-center gap-1.5">
                <Text className="mx-auto max-w-[320px] text-[13px]! leading-relaxed text-[#faf9f5]/70">
                  Click &ldquo;Continue&rdquo; to reset the password for{' '}
                  <span className="font-semibold text-[#faf9f5]">{email}</span>.
                  We&apos;ll send a verification code to confirm it&apos;s you.
                </Text>
              </Box>
            ) : (
              <Box className="flex flex-col gap-2 text-left">
                <Text className="text-[13px]! font-medium! text-white/90">
                  Email
                </Text>
                <Box className="relative">
                  <Box className="pointer-events-none absolute top-1/2 left-4.5 -translate-y-1/2 text-[#FAF9F573]">
                    <svg
                      width="20"
                      height="20"
                      viewBox="0 0 20 20"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                    >
                      <path
                        d="M15 4.16663H5C3.61929 4.16663 2.5 5.28591 2.5 6.66663V13.3333C2.5 14.714 3.61929 15.8333 5 15.8333H15C16.3807 15.8333 17.5 14.714 17.5 13.3333V6.66663C17.5 5.28591 16.3807 4.16663 15 4.16663Z"
                        stroke="#FAF9F573"
                        strokeWidth="1.33333"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      <path
                        d="M3.33398 5.83337L10.0007 10.8334L16.6673 5.83337"
                        stroke="#FAF9F573"
                        strokeWidth="1.33333"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </Box>
                  <Input
                    variant="unstyled"
                    type="email"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (error) setError(null);
                    }}
                    placeholder="Enter your email"
                    autoFocus
                    className="w-full"
                    classNames={{
                      input:
                        'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-[42px]! pr-4! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
                    }}
                  />
                </Box>
              </Box>
            )}
          </Box>

          {/* Feedback */}
          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
              <AlertCircle className="size-4 shrink-0 text-red-400" />
              <span className="leading-tight">{error}</span>
            </div>
          )}

          {/* Action Button */}
          <button
            type="submit"
            disabled={isSubmitting || !email.trim()}
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

          {/* Back to login */}
          <Box className="text-center mb-1">
            <Link
              href={email.trim() ? `/?step=1&email=${encodeURIComponent(email.trim())}` : '/?step=1'}
              onClick={handleBackToLogin}
              className="text-xs text-[#faf9f5]/70 underline-offset-4! transition-colors hover:text-white underline!"
            >
              Back to login
            </Link>
          </Box>
        </form>
      )}

      {/* ================= STEP 2: OTP VERIFICATION ================= */}
      {step === 'otp' && (
        <form
          onSubmit={handleOtpSubmit}
          className="flex flex-col gap-5 px-8 py-10 animate-auth-in"
        >
          {/* Header */}
          <Box className="text-center">
            <Text className="text-2xl! font-semibold! text-[#faf9f5]">
              Enter verification code
            </Text>
            <Text className="mt-1! text-xs! text-[#faf9f5]/70">
              Enter the 5-digit code sent to{' '}
              <span className="font-semibold text-[#faf9f5]">
                {email || 'your email'}
              </span>
            </Text>
          </Box>

          {/* OTP Input Boxes */}
          <Box className="my-2 flex justify-center gap-2.5">
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
                className="h-13 w-11.5 rounded-2xl border border-white/10 bg-white/6 text-center text-xl font-semibold text-[#FAF9F5] transition-all focus:outline-none"
              />
            ))}
          </Box>

          {/* Feedback */}
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

          {/* Continue Button */}
          <button
            type="submit"
            disabled={!isOtpComplete || isSubmitting}
            className="flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:opacity-50"
            style={{
              boxShadow:
                '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
            }}
          >
            Continue
          </button>

          {/* Resend & Back options */}
          <Box className="flex flex-col items-center gap-2">
            <Text className="text-center text-xs! text-[#faf9f5]/70">
              Didn&apos;t get the code?{' '}
              {resendCountdown > 0 ? (
                <span className="font-medium text-[#FAF9F5]/80">
                  Resend code in {resendCountdown}s
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={isSubmitting}
                  className="cursor-pointer font-medium text-[#FAF9F5] underline-offset-4 transition-colors hover:underline disabled:opacity-50"
                >
                  {isSubmitting ? 'Resending...' : 'Resend code'}
                </button>
              )}
            </Text>

            <Link
              href={email.trim() ? `/?step=1&email=${encodeURIComponent(email.trim())}` : '/?step=1'}
              onClick={handleBackToLogin}
              className="text-xs text-[#faf9f5]/70 underline-offset-4! transition-colors hover:text-white underline!"
            >
              Back to login
            </Link>
          </Box>
        </form>
      )}

      {/* ================= STEP 3: NEW PASSWORD & CONFIRM PASSWORD ================= */}
      {step === 'new-password' && (
        <form
          onSubmit={handleNewPasswordSubmit}
          className="flex flex-col gap-4 px-8 py-10 animate-auth-in"
        >
          {/* Header */}
          <Box className="text-center">
            <Text className="text-2xl! font-semibold! text-[#faf9f5]">
              Set new password
            </Text>
            <Text className="mt-1! text-xs! text-[#faf9f5]/70">
              Your new password must be at least 8 characters long.
            </Text>
          </Box>

          <Box className="border-t border-white/10" />

          {/* Form Fields */}
          <Box className="flex flex-col gap-3.5">
            {/* New Password */}
            <Box>
              <Text className="mb-1.5 pb-1! text-[13px]! font-medium! text-white/90">
                New Password
              </Text>
              <Box className="relative">
                <Box className="pointer-events-none absolute top-1/2 left-4.5 -translate-y-1/2 text-[#FAF9F573]">
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <rect
                      x="4.16699"
                      y="9.16663"
                      width="11.6667"
                      height="7.5"
                      rx="2"
                      stroke="#FAF9F573"
                      strokeWidth="1.33333"
                    />
                    <path
                      d="M6.66699 9.16663V5.83329C6.66699 4.00003 8.16699 2.5 10.0003 2.5C11.8337 2.5 13.3337 4.00003 13.3337 5.83329V9.16663"
                      stroke="#FAF9F573"
                      strokeWidth="1.33333"
                      strokeLinecap="round"
                    />
                  </svg>
                </Box>
                <Input
                  variant="unstyled"
                  type={showNewPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => {
                    setNewPassword(e.target.value);
                    if (error) setError(null);
                  }}
                  placeholder="Enter new password"
                  autoFocus
                  className="w-full"
                  classNames={{
                    input:
                      'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-[42px]! pr-12! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
                  }}
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  className="absolute top-1/2 right-4 -translate-y-1/2 cursor-pointer text-[#FAF9F5]/70 transition-colors hover:text-[#FAF9F5]"
                  aria-label={showNewPassword ? 'Hide password' : 'Show password'}
                >
                  {showNewPassword ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </Box>
            </Box>

            {/* Confirm Password */}
            <Box>
              <Text className="mb-1.5 pb-1! text-[13px]! font-medium! text-white/90">
                Confirm New Password
              </Text>
              <Box className="relative">
                <Box className="pointer-events-none absolute top-1/2 left-4.5 -translate-y-1/2 text-[#FAF9F573]">
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <rect
                      x="4.16699"
                      y="9.16663"
                      width="11.6667"
                      height="7.5"
                      rx="2"
                      stroke="#FAF9F573"
                      strokeWidth="1.33333"
                    />
                    <path
                      d="M6.66699 9.16663V5.83329C6.66699 4.00003 8.16699 2.5 10.0003 2.5C11.8337 2.5 13.3337 4.00003 13.3337 5.83329V9.16663"
                      stroke="#FAF9F573"
                      strokeWidth="1.33333"
                      strokeLinecap="round"
                    />
                  </svg>
                </Box>
                <Input
                  variant="unstyled"
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => {
                    setConfirmPassword(e.target.value);
                    if (error) setError(null);
                  }}
                  placeholder="Confirm new password"
                  className="w-full"
                  classNames={{
                    input:
                      'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-[42px]! pr-12! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
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
              password={newPassword}
              confirmPassword={confirmPassword}
            />

            {/* Feedback */}
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

            {/* Reset Button */}
            <button
              type="submit"
              disabled={
                isSubmitting ||
                !newPasswordValidation.isValid ||
                newPassword !== confirmPassword
              }
              className="mt-1 flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                boxShadow:
                  '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
              }}
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin text-white" />
              ) : (
                'Reset Password'
              )}
            </button>

            {/* Back to login */}
            <Box className="mt-1 text-center">
            <Link
              href={email.trim() ? `/?step=1&email=${encodeURIComponent(email.trim())}` : '/?step=1'}
              onClick={handleBackToLogin}
              className="text-xs text-[#faf9f5]/70 underline-offset-4! transition-colors hover:text-white underline!"
            >
              Back to login
            </Link>
            </Box>
          </Box>
        </form>
      )}
    </>
  );
};

export default ForgotPass;
