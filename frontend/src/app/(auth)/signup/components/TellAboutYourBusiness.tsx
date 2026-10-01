'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { Box, Skeleton } from '@mantine/core';

import { extractErrorMessage } from '@/lib/errorUtils';
import { showSuccessNotification, showErrorNotification } from '@/lib/toast';
import { trackEvent, identifyUser } from '@/lib/analytics';
import { updateProfileAction } from '@/actions/auth.actions';
import {
  useSignupStart,
  useSignupVerify,
  useSignupComplete,
  useCheckEmail,
  useLogin,
} from '@/hooks/api/useAuthApi';
import { DeviceLimitModal } from '@/app/(auth)/login/components/DeviceLimitModal';
import type { SessionListResponse } from '@/lib/api/auth';

import { SignupEmailStep } from './steps/SignupEmailStep';
import { SignupOtpStep } from './steps/SignupOtpStep';
import { SignupPasswordStep } from './steps/SignupPasswordStep';
import { SignupProfileStep } from './steps/SignupProfileStep';
import { LoginPasswordStep } from './steps/LoginPasswordStep';
import { validatePassword } from '@/lib/auth/passwordValidation';

const SignupStepSkeleton: React.FC<{ targetStep: number }> = ({ targetStep }) => {
  return (
    <div className="flex flex-col gap-4 px-8 py-12">
      {/* Header */}
      <Box className="flex flex-col items-center gap-2 text-center">
        <Skeleton h={28} w="65%" radius="md" className="bg-white/8!" />
        <Skeleton h={14} w="80%" radius="sm" className="bg-white/8!" />
        {targetStep === 1 && (
          <Skeleton h={14} w="55%" radius="sm" className="bg-white/8!" />
        )}
      </Box>

      {targetStep === 1 && (
        <>
          <Box className="flex flex-col gap-2.5">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex flex-col gap-3">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="mt-1 flex justify-center">
            <Skeleton h={12} w="70%" radius="sm" className="bg-white/8!" />
          </Box>
        </>
      )}

      {targetStep === 2 && (
        <>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex justify-center gap-2.5 py-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton
                key={i}
                h={52}
                w={44}
                radius="lg"
                className="bg-white/8!"
              />
            ))}
          </Box>
          <Box className="flex justify-center py-1">
            <Skeleton h={14} w="40%" radius="sm" className="bg-white/8!" />
          </Box>
          <Box className="mt-2 flex flex-col gap-2.5">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={40} radius="xl" className="bg-white/8!" />
          </Box>
        </>
      )}

      {targetStep === 3 && (
        <>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex flex-col gap-3">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="flex flex-col gap-2 py-2">
            {[0, 1, 2].map((i) => (
              <Box key={i} className="flex items-center gap-2">
                <Skeleton circle h={14} w={14} className="bg-white/8!" />
                <Skeleton
                  h={12}
                  w={i === 0 ? '55%' : i === 1 ? '45%' : '60%'}
                  radius="sm"
                  className="bg-white/8!"
                />
              </Box>
            ))}
          </Box>
          <Box className="flex flex-col gap-2.5">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={40} radius="xl" className="bg-white/8!" />
          </Box>
        </>
      )}

      {targetStep === 4 && (
        <>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex flex-col gap-3">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="mt-2 flex flex-col gap-2.5">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={40} radius="xl" className="bg-white/8!" />
          </Box>
        </>
      )}
    </div>
  );
};

const TellAboutYourBusiness: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const emailParam = searchParams.get('email') || '';

  // 1: Email, 2: OTP, 3: Password, 4: Profile
  const [step, setStep] = useState<number>(1);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [transitionTargetStep, setTransitionTargetStep] = useState<number | null>(null);
  const transitionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onboardingStartTime = useRef<number | null>(null);



  // Field states
  const [email, setEmail] = useState(emailParam);
  const [otp, setOtp] = useState<string[]>(Array(6).fill(''));
  const otpRefs = useRef<(HTMLInputElement | null)[]>([]);

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [fullName, setFullName] = useState('');
  const [businessType, setBusinessType] = useState<string | null>(null);
  const [whyChoosePunk, setWhyChoosePunk] = useState('');

  // Flow & API states
  const [authFlow, setAuthFlow] = useState<'signup' | 'login'>('signup');
  const [loginMethod, setLoginMethod] = useState<'otp' | 'password'>('otp');
  const [loginPassword, setLoginPassword] = useState('');
  const [signupToken, setSignupToken] = useState<string>('');
  const [loginToken, setLoginToken] = useState<string>('');
  const [resendCountdown, setResendCountdown] = useState<number>(0);
  const [isResending, setIsResending] = useState<boolean>(false);
  const [deviceLimitData, setDeviceLimitData] = useState<
    (SessionListResponse & { pending_login_token: string }) | null
  >(null);
  const [error, setError] = useState('');

  // Social auth state
  const [isSocialUser, setIsSocialUser] = useState(false);
  const [socialAuthMethod, setSocialAuthMethod] = useState<'google' | 'apple'>('google');
  const [isSocialPaid, setIsSocialPaid] = useState(false);
  const [isSocialUpdating, setIsSocialUpdating] = useState(false);

  const isRestored = useRef(false);

  const checkEmailMutation = useCheckEmail();
  const loginMutation = useLogin();
  const signupStartMutation = useSignupStart();
  const signupVerifyMutation = useSignupVerify();
  const signupCompleteMutation = useSignupComplete();

  // Handle resend countdown timer
  useEffect(() => {
    if (resendCountdown <= 0) return;
    const interval = setInterval(() => {
      setResendCountdown((prev) => Math.max(prev - 1, 0));
    }, 1000);
    return () => clearInterval(interval);
  }, [resendCountdown]);

  const isSubmitting =
    checkEmailMutation.isPending ||
    signupStartMutation.isPending ||
    signupVerifyMutation.isPending ||
    signupCompleteMutation.isPending ||
    loginMutation.isPending ||
    isSocialUpdating;

  // Step Guard: Validates that prerequisites exist for a requested step
  const getEffectiveStep = React.useCallback(
    (
      targetStep: number,
      curEmail = email,
      curToken = signupToken,
      curPassword = password,
      social = isSocialUser,
      curLoginToken = loginToken,
      curFlow = authFlow
    ): number => {
      const clamped = Math.min(Math.max(targetStep, 1), 4);
      // Social user can jump directly to step 4 (Profile)
      if (social && clamped === 4) return 4;
      // Login flow: step 2 is password input, requires only email
      if (curFlow === 'login') {
        if (clamped >= 2 && !curEmail.trim()) return 1;
        return clamped;
      }
      // Signup flow:
      // Step 2 (OTP) strictly requires an email AND an issued signupToken
      if (clamped >= 2 && (!curEmail.trim() || !curToken)) return 1;
      // Step 3 (Password) strictly requires signupToken (after verified OTP)
      if (clamped >= 3 && !curToken) return 1;
      // Step 4 (Profile) strictly requires password and signupToken unless social
      if (clamped >= 4 && (!curPassword || !curToken) && !social) return 1;
      return clamped;
    },
    [email, signupToken, password, isSocialUser, loginToken, authFlow]
  );

  // Sync step state to URL query parameter without triggering Next.js RSC re-renders
  const syncStepToUrl = React.useCallback((targetStep: number) => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (targetStep === 1) {
      url.searchParams.delete('step');
    } else {
      url.searchParams.set('step', targetStep.toString());
    }
    window.history.replaceState(window.history.state, '', url.toString());
  }, []);

  const updateStep = (
    nextStep: number,
    curEmail = email,
    curToken = signupToken,
    curPassword = password,
    social = isSocialUser,
    curLoginToken = loginToken,
    curFlow = authFlow
  ) => {
    const effective = getEffectiveStep(
      nextStep,
      curEmail,
      curToken,
      curPassword,
      social,
      curLoginToken,
      curFlow
    );
    if (effective === step) return;

    if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current);
    setTransitionTargetStep(effective);
    setIsTransitioning(true);

    transitionTimerRef.current = setTimeout(() => {
      setStep(effective);
      syncStepToUrl(effective);
      setIsTransitioning(false);
      setTransitionTargetStep(null);
    }, 280);
  };

  useEffect(() => {
    if (!onboardingStartTime.current) {
      onboardingStartTime.current = Date.now();
    }

    // Restore state from sessionStorage on mount asynchronously to avoid cascading render warnings
    const timer = setTimeout(() => {
      try {
        const storedEmail = sessionStorage.getItem('signup_email') || '';

        // If email query parameter is provided and differs from stored session, clear stale data
        if (emailParam && emailParam !== storedEmail) {
          sessionStorage.removeItem('signup_step');
          sessionStorage.removeItem('signup_email');
          sessionStorage.removeItem('signup_token');
          sessionStorage.removeItem('signup_password');
          sessionStorage.removeItem('signup_full_name');
          sessionStorage.removeItem('signup_business_type');
          sessionStorage.removeItem('signup_why_choose');
        }

        const effectiveEmail = emailParam || sessionStorage.getItem('signup_email') || '';
        const savedToken = sessionStorage.getItem('signup_token') || '';
        const savedPassword = sessionStorage.getItem('signup_password') || '';
        const savedFullName = sessionStorage.getItem('signup_full_name') || '';
        const savedBusinessType = sessionStorage.getItem(
          'signup_business_type'
        );
        const savedWhyChoose =
          sessionStorage.getItem('signup_why_choose') || '';

        const stepQuery = searchParams.get('step');
        const savedStep = sessionStorage.getItem('signup_step');
        const rawRequested = stepQuery
          ? parseInt(stepQuery, 10)
          : savedStep
            ? parseInt(savedStep, 10)
            : 1;

        const savedIsSocial = sessionStorage.getItem('signup_is_social') === 'true';
        const savedSocialMethod = (sessionStorage.getItem('signup_social_method') as 'google' | 'apple') || 'google';
        const savedSocialPaid = sessionStorage.getItem('signup_social_paid') === 'true';
        const savedAuthFlow = (sessionStorage.getItem('auth_flow') as 'login' | 'signup') || 'signup';
        const savedLoginMethod = (sessionStorage.getItem('login_method') as 'otp' | 'password') || 'otp';
        const savedLoginToken = sessionStorage.getItem('login_token') || '';

        if (savedIsSocial) {
          setIsSocialUser(true);
          setSocialAuthMethod(savedSocialMethod);
          setIsSocialPaid(savedSocialPaid);
        }
        if (savedAuthFlow) setAuthFlow(savedAuthFlow);
        if (savedLoginMethod) setLoginMethod(savedLoginMethod);
        if (savedLoginToken) setLoginToken(savedLoginToken);

        const effective = getEffectiveStep(
          isNaN(rawRequested) ? 1 : rawRequested,
          effectiveEmail,
          savedToken,
          savedPassword,
          savedIsSocial,
          savedLoginToken,
          savedAuthFlow
        );

        if (effectiveEmail && effectiveEmail !== email) setEmail(effectiveEmail);
        if (savedToken) setSignupToken(savedToken);
        if (savedPassword) setPassword(savedPassword);
        if (savedFullName) setFullName(savedFullName);
        if (savedBusinessType) setBusinessType(savedBusinessType);
        if (savedWhyChoose) setWhyChoosePunk(savedWhyChoose);

        if (effective !== step) {
          setStep(effective);
        }

        // Keep URL param in sync on initial mount
        syncStepToUrl(effective);
      } catch {
        // Ignore if sessionStorage access is restricted
      } finally {
        isRestored.current = true;
      }
    }, 0);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Listen to browser Back/Forward navigation and enforce step guards
  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      const stepQuery = params.get('step');
      if (stepQuery) {
        const parsed = parseInt(stepQuery, 10);
        if (!isNaN(parsed)) {
          const effective = getEffectiveStep(parsed);
          setStep((cur) => (cur !== effective ? effective : cur));
        }
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [getEffectiveStep]);

  // Save state to sessionStorage on change
  useEffect(() => {
    if (!isRestored.current) return;
    sessionStorage.setItem('signup_step', step.toString());
    sessionStorage.setItem('signup_email', email);
    sessionStorage.setItem('signup_token', signupToken);
    sessionStorage.setItem('signup_password', password);
    sessionStorage.setItem('signup_full_name', fullName);
    sessionStorage.setItem('auth_flow', authFlow);
    sessionStorage.setItem('login_method', loginMethod);
    if (loginToken) {
      sessionStorage.setItem('login_token', loginToken);
    } else {
      sessionStorage.removeItem('login_token');
    }
    if (businessType) {
      sessionStorage.setItem('signup_business_type', businessType);
    } else {
      sessionStorage.removeItem('signup_business_type');
    }
    sessionStorage.setItem('signup_why_choose', whyChoosePunk);
    if (isSocialUser) {
      sessionStorage.setItem('signup_is_social', 'true');
      sessionStorage.setItem('signup_social_method', socialAuthMethod);
      sessionStorage.setItem('signup_social_paid', isSocialPaid ? 'true' : 'false');
    } else {
      sessionStorage.removeItem('signup_is_social');
      sessionStorage.removeItem('signup_social_method');
      sessionStorage.removeItem('signup_social_paid');
    }
  }, [
    step,
    email,
    signupToken,
    loginToken,
    authFlow,
    loginMethod,
    password,
    fullName,
    businessType,
    whyChoosePunk,
    isSocialUser,
    socialAuthMethod,
    isSocialPaid,
  ]);

  const handleNextStep = (
    nextEmail?: string,
    nextToken?: string,
    nextPassword?: string
  ) => {
    setError('');
    const e = nextEmail ?? email;
    const t = nextToken ?? signupToken;
    const p = nextPassword ?? password;
    updateStep(step + 1, e, t, p);
  };

  const handlePrevStep = () => {
    setError('');
    updateStep(step - 1);
  };

  // Step 1: Start Auth (Email - automatically checks if existing or new user, or Google user)
  const handleStartAuth = async (
    e?: React.FormEvent,
    socialTriggers?: {
      triggerGoogle: (hintEmail?: string) => void;
    }
  ) => {
    if (e) e.preventDefault();
    setError('');
    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      setError('Please enter your email address.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError('Please enter a valid email address.');
      return;
    }

    try {
      const checkRes = await checkEmailMutation.mutateAsync(trimmedEmail);

      if (checkRes.exists) {
        // If account is tied to Google, automatically start that provider's login flow!
        if (checkRes.auth_method === 'google') {
          showSuccessNotification('Google Account Found', 'Starting Google Sign-In...');
          if (socialTriggers?.triggerGoogle) {
            socialTriggers.triggerGoogle(trimmedEmail);
          }
          return;
        }

        // User exists -> Proceed with password login (no OTP)
        setAuthFlow('login');
        setLoginMethod('password');
        setLoginPassword('');
        try {
          sessionStorage.setItem('auth_flow', 'login');
          sessionStorage.setItem('login_method', 'password');
          sessionStorage.setItem('signup_email', trimmedEmail);
        } catch {}
        updateStep(2, trimmedEmail, undefined, undefined, false, '', 'login');
      } else {
        // New user -> Proceed with signup verification OTP
        setAuthFlow('signup');
        try {
          sessionStorage.setItem('auth_flow', 'signup');
          sessionStorage.setItem('signup_email', trimmedEmail);
        } catch {}
        const signupRes = await signupStartMutation.mutateAsync({ email: trimmedEmail });
        setSignupToken(signupRes.signup_token);
        try {
          sessionStorage.setItem('signup_token', signupRes.signup_token);
        } catch {}
        setResendCountdown(90);
        setOtp(Array(6).fill(''));
        showSuccessNotification('Check your email', `We sent you a verification code.`);
        updateStep(2, trimmedEmail, signupRes.signup_token, undefined, false, '', 'signup');
      }
    } catch (err: unknown) {
      const msg = extractErrorMessage(err, 'Failed to proceed. Please try again.');
      setError(msg);
      showErrorNotification('Error', msg);
    }
  };

  const handleAuthMethodMismatch = ({
    email: targetEmail,
  }: {
    email: string;
    loginToken?: string;
    message?: string;
  }) => {
    setError('');
    setEmail(targetEmail);
    setAuthFlow('login');
    setLoginMethod('password');
    setLoginPassword('');

    try {
      sessionStorage.setItem('auth_flow', 'login');
      sessionStorage.setItem('login_method', 'password');
      sessionStorage.setItem('signup_email', targetEmail);
    } catch {}

    updateStep(2, targetEmail, undefined, undefined, false, '', 'login');
  };

  // Resend OTP (for signup email verification)
  const handleResendOtp = async () => {
    if (resendCountdown > 0 || isResending) return;
    setError('');
    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      setError('Please enter your email address.');
      return;
    }

    setIsResending(true);
    try {
      const res = await signupStartMutation.mutateAsync({ email: trimmedEmail });
      setSignupToken(res.signup_token);
      try {
        sessionStorage.setItem('signup_token', res.signup_token);
      } catch {}
      setResendCountdown(90);
      showSuccessNotification('Code resent', `We sent a new verification code to your email.`);
    } catch (err: unknown) {
      const msg = extractErrorMessage(err, 'Failed to resend verification code.');
      setError(msg);
      showErrorNotification('Error', msg);
    } finally {
      setIsResending(false);
    }
  };

  // Step 2: Verify OTP (Signup email verification)
  const handleVerifyOtp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setError('');
    const code = otp.join('').trim();
    if (code.length !== 6) {
      setError('Please enter the 6-digit code.');
      return;
    }

    const token = signupToken || sessionStorage.getItem('signup_token') || '';
    if (!token) {
      setError('Signup session expired. Please enter your email again.');
      updateStep(1);
      return;
    }

    try {
      await signupVerifyMutation.mutateAsync({
        signup_token: token,
        code,
      });
      showSuccessNotification('Email verified', 'Please set your password.');
      updateStep(3);
    } catch (err: unknown) {
      const msg = extractErrorMessage(err, 'Invalid verification code.');
      setError(msg);
      showErrorNotification('Error', msg);
    }
  };

  // Step 2 Alternative (Login): Password Login
  const handlePasswordLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setError('');
    const trimmedEmail = email.trim().toLowerCase();
    if (!loginPassword.trim()) {
      setError('Please enter your password.');
      return;
    }

    try {
      const res = await loginMutation.mutateAsync({
        email: trimmedEmail,
        password: loginPassword,
        rememberMe: true,
      });

      identifyUser(trimmedEmail, { email: trimmedEmail });
      trackEvent('user_logged_in', {
        email: trimmedEmail,
        login_method: 'password',
        auth_method: 'email',
      });

      // Clean up login session items
      try {
        sessionStorage.clear();
      } catch {}

      showSuccessNotification('Logged in', 'Welcome back!');
      router.push('/chat');
    } catch (err: unknown) {
      const errorObj = err as { data?: { code?: string } };
      if (errorObj?.data?.code === 'MAX_DEVICE_LIMIT_REACHED') {
        setDeviceLimitData(
          errorObj.data as SessionListResponse & { pending_login_token: string }
        );
      } else {
        const msg = extractErrorMessage(err, 'Invalid email or password.');
        setError(msg);
        showErrorNotification('Login Failed', msg);
      }
    }
  };

  // Step 3: Password
  const handlePasswordSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setError('');

    const validation = validatePassword(password);
    if (!validation.isValid) {
      const msg = validation.errors[0] || 'Password does not meet requirements.';
      setError(msg);
      showErrorNotification('Weak Password', msg);
      return;
    }

    if (password !== confirmPassword) {
      const msg = 'Passwords do not match.';
      setError(msg);
      showErrorNotification('Password Mismatch', msg);
      return;
    }

    showSuccessNotification('Password set', 'Just one more step.');
    handleNextStep(undefined, undefined, password);
  };

  const handleSocialSuccess = ({
    email: userEmail,
    fullName: userFullName,
    isNewUser,
    isPaid,
    authMethod,
    businessName,
  }: {
    email: string;
    fullName?: string;
    isNewUser: boolean;
    isPaid: boolean;
    authMethod: 'google';
    businessName?: string | null;
  }) => {
    if (isNewUser || !businessName) {
      setIsSocialUser(true);
      setSocialAuthMethod(authMethod);
      setIsSocialPaid(isPaid);
      setEmail(userEmail);
      if (userFullName) setFullName(userFullName);

      try {
        sessionStorage.setItem('signup_is_social', 'true');
        sessionStorage.setItem('signup_social_method', authMethod);
        sessionStorage.setItem('signup_social_paid', isPaid ? 'true' : 'false');
        sessionStorage.setItem('signup_email', userEmail);
        if (userFullName) sessionStorage.setItem('signup_full_name', userFullName);
        sessionStorage.setItem('signup_step', '4');
      } catch {}

      updateStep(4, userEmail, undefined, undefined, true);
    } else {
      trackEvent('user_logged_in', {
        email: userEmail,
        login_method: `${authMethod}_oauth`,
        auth_method: authMethod,
      });
      showSuccessNotification('Logged in', 'Welcome back!');
      router.push('/chat');
    }
  };

  // Step 4: Complete Profile
  const handleCompleteSignup = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setError('');
    const trimmedName = fullName.trim();
    if (!trimmedName) {
      setError('Please enter your full name.');
      return;
    }
    if (!businessType) {
      setError('Please select your business type.');
      return;
    }

    if (isSocialUser) {
      try {
        setIsSocialUpdating(true);
        const updateRes = await updateProfileAction({
          full_name: trimmedName,
          business_name: businessType,
          business_type: businessType,
          why_choose_punk: whyChoosePunk,
        });

        if (!updateRes.success) {
          throw new Error(updateRes.error || 'Failed to update profile.');
        }

        identifyUser(email, {
          email,
          full_name: trimmedName,
          business_type: businessType,
          role: 'user',
          is_subscription_active: isSocialPaid,
        });

        trackEvent('user_registered', {
          email,
          full_name: trimmedName,
          business_type: businessType,
          why_choose_punk: whyChoosePunk,
          signup_method: 'google_oauth',
          auth_method: socialAuthMethod,
          is_early_access: isSocialPaid,
        });

        trackEvent('onboarding_completed', {
          email,
          auth_method: socialAuthMethod,
          is_paid: isSocialPaid,
        });

        // Clear sessionStorage on successful signup
        sessionStorage.removeItem('signup_step');
        sessionStorage.removeItem('signup_email');
        sessionStorage.removeItem('signup_token');
        sessionStorage.removeItem('signup_password');
        sessionStorage.removeItem('signup_full_name');
        sessionStorage.removeItem('signup_business_type');
        sessionStorage.removeItem('signup_why_choose');
        sessionStorage.removeItem('signup_is_social');
        sessionStorage.removeItem('signup_social_method');
        sessionStorage.removeItem('signup_social_paid');

        showSuccessNotification(
          'Welcome to Punk',
          isSocialPaid
            ? 'Your early access Pro spot is active! Premium access granted.'
            : 'Welcome to Punk Beta! Free early access tokens granted.'
        );
        router.push('/chat');
      } catch (err) {
        const msg = extractErrorMessage(err, 'Failed to complete profile.');
        setError(msg);
        showErrorNotification('Error', msg);
      } finally {
        setIsSocialUpdating(false);
      }
      return;
    }

    try {
      const completeRes = await signupCompleteMutation.mutateAsync({
        signup_token: signupToken,
        password,
        full_name: trimmedName,
        business_type: businessType,
        why_choose_punk: whyChoosePunk,
      });

      const isPaid = completeRes?.is_paid ?? false;

      identifyUser(email, {
        email,
        full_name: trimmedName,
        business_type: businessType,
        role: 'user',
        is_subscription_active: isPaid,
      });

      trackEvent('user_registered', {
        email,
        full_name: trimmedName,
        business_type: businessType,
        why_choose_punk: whyChoosePunk,
        signup_method: 'early_access_flow',
        is_early_access: true,
      });

      // Clear sessionStorage on successful signup
      sessionStorage.removeItem('signup_step');
      sessionStorage.removeItem('signup_email');
      sessionStorage.removeItem('signup_token');
      sessionStorage.removeItem('signup_password');
      sessionStorage.removeItem('signup_full_name');
      sessionStorage.removeItem('signup_business_type');
      sessionStorage.removeItem('signup_why_choose');

      showSuccessNotification(
        'Welcome to Punk',
        isPaid
          ? 'Your early access Pro spot is active! Premium access granted.'
          : 'Welcome to Punk Beta! Free early access tokens granted.'
      );
      router.push('/chat');
    } catch (err) {
      const msg = extractErrorMessage(err, 'Failed to complete signup.');
      setError(msg);
      showErrorNotification('Error', msg);
    }
  };

  // Render Content
  return (
    <div className="w-full">
      {deviceLimitData ? (
        <div key="device-limit" className="w-full animate-auth-in">
          <DeviceLimitModal
            data={deviceLimitData}
            onClose={() => setDeviceLimitData(null)}
            onSuccess={() => {
              setDeviceLimitData(null);
              router.push('/chat');
            }}
          />
        </div>
      ) : isTransitioning ? (
        <SignupStepSkeleton targetStep={transitionTargetStep ?? step} />
      ) : (
        <div key={`step-${step}`} className="w-full animate-auth-in">
          {step === 1 && (
            <SignupEmailStep
              email={email}
              setEmail={(val) => {
                setEmail(val);
                if (signupToken) {
                  setSignupToken('');
                  try {
                    sessionStorage.removeItem('signup_token');
                  } catch {}
                }
                if (loginToken) {
                  setLoginToken('');
                  try {
                    sessionStorage.removeItem('login_token');
                  } catch {}
                }
                if (error) setError('');
              }}
              handleStartSignup={handleStartAuth}
              isSubmitting={isSubmitting}
              error={error}
              onSocialSuccess={handleSocialSuccess}
              onAuthMethodMismatch={handleAuthMethodMismatch}
            />
          )}

          {step === 2 &&
            (authFlow === 'login' ? (
              <LoginPasswordStep
                email={email}
                password={loginPassword}
                setPassword={(val) => {
                  setLoginPassword(val);
                  if (error) setError('');
                }}
                handlePasswordLogin={handlePasswordLogin}
                handlePrevStep={handlePrevStep}
                isSubmitting={isSubmitting}
                error={error}
              />
            ) : (
              <SignupOtpStep
                email={email}
                otp={otp}
                setOtp={(val) => {
                  setOtp(val);
                  if (error) setError('');
                }}
                handleVerifyOtp={handleVerifyOtp}
                handlePrevStep={handlePrevStep}
                handleResendOtp={handleResendOtp}
                isSubmitting={isSubmitting}
                otpRefs={otpRefs}
                error={error}
                countdown={resendCountdown}
                isResending={isResending}
              />
            ))}

          {step === 3 && (
            <SignupPasswordStep
              password={password}
              setPassword={(val) => {
                setPassword(val);
                if (error) setError('');
              }}
              confirmPassword={confirmPassword}
              setConfirmPassword={(val) => {
                setConfirmPassword(val);
                if (error) setError('');
              }}
              showPassword={showPassword}
              setShowPassword={setShowPassword}
              showConfirmPassword={showConfirmPassword}
              setShowConfirmPassword={setShowConfirmPassword}
              handlePasswordSubmit={handlePasswordSubmit}
              handlePrevStep={handlePrevStep}
              isSubmitting={isSubmitting}
              error={error}
            />
          )}

          {step === 4 && (
            <SignupProfileStep
              fullName={fullName}
              setFullName={(val) => {
                setFullName(val);
                if (error) setError('');
              }}
              businessType={businessType}
              setBusinessType={(val) => {
                setBusinessType(val);
                if (error) setError('');
              }}
              whyChoosePunk={whyChoosePunk}
              setWhyChoosePunk={(val) => {
                setWhyChoosePunk(val);
                if (error) setError('');
              }}
              handleCompleteSignup={handleCompleteSignup}
              handlePrevStep={isSocialUser || authFlow === 'login' ? undefined : handlePrevStep}
              isSubmitting={isSubmitting || isSocialUpdating}
              error={error}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default TellAboutYourBusiness;
