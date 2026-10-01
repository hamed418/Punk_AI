import React, { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Box, Input, Text } from '@mantine/core';
import { Loader2, AlertCircle } from 'lucide-react';
import { useGoogleLogin as useGoogleOAuth } from '@react-oauth/google';
import { useGoogleLogin as useBackendGoogleLogin } from '@/hooks/api/useAuthApi';
import { trackEvent, identifyUser } from '@/lib/analytics';
import { showSuccessNotification, showErrorNotification } from '@/lib/toast';
import { extractErrorMessage } from '@/lib/errorUtils';

export interface SignupEmailStepProps {
  email: string;
  setEmail: (val: string) => void;
  handleStartSignup: (
    e?: React.FormEvent,
    socialTriggers?: {
      triggerGoogle: (hintEmail?: string) => void;
    }
  ) => void;
  isSubmitting: boolean;
  error?: string;
  onSocialSuccess?: (data: {
    email: string;
    fullName?: string;
    isNewUser: boolean;
    isPaid: boolean;
    authMethod: 'google';
    businessName?: string | null;
  }) => void;
  onAuthMethodMismatch?: (data: {
    email: string;
    loginToken: string;
    message: string;
  }) => void;
}

export const SignupEmailStep: React.FC<SignupEmailStepProps> = ({
  email,
  setEmail,
  handleStartSignup,
  isSubmitting,
  error,
  onSocialSuccess,
  onAuthMethodMismatch,
}) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const flowParam = searchParams.get('flow') || '';
  const isPaidParam = searchParams.get('paid') === 'true';

  const [socialLoading, setSocialLoading] = useState<'google' | null>(null);

  const backendGoogleMutation = useBackendGoogleLogin();

  const googleOAuthLogin = useGoogleOAuth({
    onSuccess: async (tokenResponse) => {
      try {
        setSocialLoading('google');
        const res = await backendGoogleMutation.mutateAsync({
          access_token: tokenResponse.access_token,
          flow: flowParam || undefined,
          paid: isPaidParam,
        });

        const userEmail = res?.email || '';
        const userFullName = res?.full_name || '';
        const isPaid = res?.is_paid ?? false;
        const isNew = res?.is_new_user ?? false;
        const businessName = res?.business_name;

        identifyUser(userEmail, {
          email: userEmail,
          full_name: userFullName,
          auth_method: 'google',
          is_subscription_active: isPaid,
        });

        if (onSocialSuccess) {
          onSocialSuccess({
            email: userEmail,
            fullName: userFullName,
            isNewUser: isNew,
            isPaid,
            authMethod: 'google',
            businessName,
          });
          return;
        }

        if (isNew) {
          trackEvent('user_registered', {
            email: userEmail,
            full_name: userFullName,
            signup_method: 'google_oauth',
            auth_method: 'google',
            is_early_access: isPaid,
          });
        } else {
          trackEvent('user_logged_in', {
            email: userEmail,
            login_method: 'google_oauth',
            auth_method: 'google',
          });
        }

        showSuccessNotification(
          'Welcome to Punk',
          isPaid
            ? 'Your early access Pro spot is active! Premium access granted.'
            : 'Welcome to Punk Beta! Free early access tokens granted.'
        );
        router.push('/chat');
      } catch (err: unknown) {
        const errorObj = err as {
          data?: { code?: string; email?: string; login_token?: string; message?: string };
        };
        if (errorObj?.data?.code === 'AUTH_METHOD_MISMATCH' && errorObj.data.email) {
          if (onAuthMethodMismatch) {
            onAuthMethodMismatch({
              email: errorObj.data.email,
              loginToken: errorObj.data.login_token || '',
              message:
                errorObj.data.message ||
                'This account uses email authentication. A verification code has been sent to your email.',
            });
            return;
          }
        }
        const msg = extractErrorMessage(err, 'Google authentication failed.');
        showErrorNotification('Authentication Error', msg);
      } finally {
        setSocialLoading(null);
      }
    },
    onError: (err) => {
      console.error('Google OAuth error:', err);
      showErrorNotification('Google Login Failed', 'Could not authenticate with Google.');
    },
  });

  const handleGoogleClick = (hintEmail?: string | React.MouseEvent) => {
    trackEvent('signup_social_initiated', {
      provider: 'google',
      flow: flowParam || (isPaidParam ? 'paid' : 'beta'),
    });
    const effectiveHint =
      typeof hintEmail === 'string' && hintEmail.includes('@')
        ? hintEmail.trim()
        : email.trim();
    if (effectiveHint && effectiveHint.includes('@')) {
      googleOAuthLogin({ hint: effectiveHint });
    } else {
      googleOAuthLogin();
    }
  };

  const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleStartSignup(e, {
      triggerGoogle: (hintEmail) => handleGoogleClick(hintEmail),
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4 px-8 py-12"
    >
      <Box className="text-center">
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Welcome to Punk
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          Enter your email to continue
        </Text>
      </Box>

      {/* Social Logins */}
      <Box className="flex flex-col gap-2.5">
        <button
          type="button"
          onClick={handleGoogleClick}
          disabled={Boolean(socialLoading) || isSubmitting}
          className="flex h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-white/10 bg-white/5 text-sm text-white/90 transition-colors duration-150 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            boxShadow: '0px 1px 0px 0px #FFFFFF0F inset',
          }}
        >
          {socialLoading === 'google' ? (
            <Loader2 className="h-4 w-4 animate-spin text-white" />
          ) : (
            <svg viewBox="0 0 24 24" width="16" height="16">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.16v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.16C1.43 8.55 1 10.22 1 12s.43 3.45 1.16 4.93l2.85-2.22.83-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.16 7.07l3.68 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
          )}
          Continue with Google
        </button>
      </Box>

      <Box className="relative flex items-center justify-center gap-2 py-1">
        <Box className="grow border-t border-white/10" />
        <Text className="mx-4 text-[11px]! tracking-widest text-[#FAF9F566]! uppercase">
          or
        </Text>
        <Box className="grow border-t border-white/10" />
      </Box>

      <Box className="flex flex-col gap-2.5">
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
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Enter your email"
            className="w-full"
            classNames={{
              input:
                'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-[42px]! pr-4! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
            }}
          />
        </Box>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
            <AlertCircle className="size-4 shrink-0 text-red-400" />
            <span className="leading-tight">{error}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !isValidEmail}
          className={`flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! ${
            isValidEmail ? 'text-white' : 'text-white/40'
          } transition-all hover:bg-white/15 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50`}
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
