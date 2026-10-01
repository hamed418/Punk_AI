'use client';

import { useRouter, usePathname } from 'next/navigation';
import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Box, Skeleton } from '@mantine/core';
import GlobeLoop from '@/components/GlobeLoop';

interface AuthLayoutProps {
  children: React.ReactNode;
}

const AuthPageSkeleton: React.FC<{ pathname: string }> = ({ pathname }) => {
  const isForgot = pathname.includes('forgot-password');
  const isVerify = pathname.includes('verify-email');
  const isSignup = pathname.includes('signup');
  const isLogin = !isForgot && !isVerify && !isSignup;

  return (
    <div
      className={`flex flex-col ${
        isSignup ? 'gap-5 px-8 py-12' : 'gap-4 px-6 py-8 sm:px-8 sm:py-10'
      }`}
    >
      {/* Header */}
      <Box className="flex flex-col items-center gap-2 text-center">
        <Skeleton
          h={28}
          w={isForgot ? '60%' : isVerify ? '55%' : isSignup ? '65%' : '55%'}
          radius="md"
          className="bg-white/8!"
        />
        <Skeleton
          h={14}
          w={isForgot ? '85%' : isVerify ? '75%' : isSignup ? '80%' : '75%'}
          radius="sm"
          className="bg-white/8!"
        />
      </Box>

      {/* Login specific */}
      {isLogin && (
        <>
          <Box className="flex flex-col gap-2.5">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex flex-col gap-3">
            <Box className="flex flex-col gap-1.5">
              <Skeleton h={12} w="20%" radius="sm" className="bg-white/8!" />
              <Skeleton h={44} radius="xl" className="bg-white/8!" />
            </Box>
            <Box className="flex flex-col gap-1.5">
              <Skeleton h={12} w="25%" radius="sm" className="bg-white/8!" />
              <Skeleton h={44} radius="xl" className="bg-white/8!" />
            </Box>
            <Box className="flex items-center justify-between py-0.5">
              <Skeleton h={14} w="35%" radius="sm" className="bg-white/8!" />
              <Skeleton h={14} w="30%" radius="sm" className="bg-white/8!" />
            </Box>
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="mt-1 flex justify-center">
            <Skeleton h={14} w="60%" radius="sm" className="bg-white/8!" />
          </Box>
        </>
      )}

      {/* Signup specific */}
      {isSignup && (
        <>
          <Box className="flex flex-col gap-2.5">
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
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

      {/* Forgot Password specific */}
      {isForgot && (
        <>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex flex-col gap-3">
            <Box className="flex flex-col gap-1.5">
              <Skeleton h={12} w="20%" radius="sm" className="bg-white/8!" />
              <Skeleton h={44} radius="xl" className="bg-white/8!" />
            </Box>
            <Skeleton h={44} radius="xl" className="bg-white/8!" />
          </Box>
          <Box className="mt-1 flex justify-center">
            <Skeleton h={14} w="50%" radius="sm" className="bg-white/8!" />
          </Box>
        </>
      )}

      {/* Verify Email specific */}
      {isVerify && (
        <>
          <Box className="my-1 border-t border-white/10" />
          <Box className="flex justify-center gap-2.5 py-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton
                key={i}
                h={52}
                w={46}
                radius="lg"
                className="bg-white/8!"
              />
            ))}
          </Box>
          <Box className="flex justify-center">
            <Skeleton h={14} w="30%" radius="sm" className="bg-white/8!" />
          </Box>
          <Skeleton h={44} radius="xl" className="bg-white/8!" />
          <Box className="mt-1 flex flex-col items-center gap-2">
            <Skeleton h={14} w="45%" radius="sm" className="bg-white/8!" />
            <Skeleton h={14} w="30%" radius="sm" className="bg-white/8!" />
          </Box>
        </>
      )}
    </div>
  );
};

const emptySubscribe = () => () => {};

const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  React.useEffect(() => {
    if (!loading && user) {
      // Only hold a logged-in user on step 4 when they are in the middle of
      // a social-signup onboarding flow (sessionStorage flag is still set)
      // AND their profile is genuinely incomplete.
      const isSocialSignup =
        typeof window !== 'undefined' &&
        sessionStorage.getItem('signup_is_social') === 'true';
      const isStep4 =
        typeof window !== 'undefined' &&
        (new URLSearchParams(window.location.search).get('step') === '4' ||
          sessionStorage.getItem('signup_step') === '4');
      const hasMissingProfile = !user?.business_name || !user.business_name.trim();

      if (isSocialSignup && hasMissingProfile) {
        // Stay on / or /signup at step 4 so they can complete their profile
        if ((pathname === '/' || pathname.includes('/signup')) && isStep4) {
          return;
        }
        router.replace('/?step=4');
        return;
      }

      // Fully authenticated user — always go to chat
      router.replace('/chat');
    }
  }, [loading, user, router, pathname]);

  const contentRef = React.useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = React.useState<number | null>(null);
  const isMounted = React.useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );

  // Transition state for page changes
  const [isPageTransitioning, setIsPageTransitioning] = React.useState(false);
  const [transitionPathname, setTransitionPathname] = React.useState(pathname);
  const prevPathnameRef = React.useRef(pathname);
  const transitionTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (prevPathnameRef.current !== pathname) {
      prevPathnameRef.current = pathname;
      setTransitionPathname(pathname);
      setIsPageTransitioning(true);

      if (transitionTimerRef.current) {
        clearTimeout(transitionTimerRef.current);
      }
      transitionTimerRef.current = setTimeout(() => {
        setIsPageTransitioning(false);
      }, 280);
    }
    return () => {
      if (transitionTimerRef.current) {
        clearTimeout(transitionTimerRef.current);
      }
    };
  }, [pathname]);

  React.useEffect(() => {
    if (!contentRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const h =
          entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height;
        if (h > 0) {
          setContentHeight(Math.round(h));
        }
      }
    });
    observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, []);

  const isSocialOnboarding =
    (pathname === '/' || pathname.includes('/signup') || pathname.includes('/login')) &&
    typeof window !== 'undefined' &&
    sessionStorage.getItem('signup_is_social') === 'true' &&
    (!user?.business_name || !user.business_name.trim());

  if (!loading && user && !isSocialOnboarding) {
    return null;
  }

  return (
    <Box
      className="relative flex min-h-screen w-full items-center justify-center overflow-hidden"
      style={{
        background:
          'linear-gradient(0deg, rgba(255, 255, 255, 1e-05), rgba(255, 255, 255, 1e-05)),linear-gradient(0deg, rgba(0, 0, 0, 0.5), rgba(0, 0, 0, 0.5))',
      }}
    >
      {/* Rotating Globe Background (fixed size to encompass auth UI) */}
      <GlobeLoop fixedSize={680} />

      {/* Centered Auth Content */}
      <main className="relative z-10 flex flex-1 items-center justify-center p-4 py-8">
        <div className="mx-auto! my-auto! w-full max-w-110">
          <div
            className={`relative overflow-hidden rounded-[30px] bg-[#00000080] backdrop-blur-[18px] ${
              isMounted ? 'transition-[height] duration-300 ease-in-out' : ''
            }`}
            style={{
              height: contentHeight ? `${contentHeight}px` : 'auto',
              backdropFilter: 'blur(18px)',
              WebkitBackdropFilter: 'blur(18px)',
              boxShadow:
                '0px 8px 24px 0px rgba(0, 0, 0, 0.5) inset, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
            }}
          >
            <div ref={contentRef} className="w-full">
              {isPageTransitioning ? (
                <AuthPageSkeleton pathname={transitionPathname} />
              ) : (
                <div key={pathname} className="w-full animate-auth-in">
                  {children}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </Box>
  );
};

export default AuthLayout;
