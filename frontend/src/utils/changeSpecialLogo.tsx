'use client';

import { useEffect, useSyncExternalStore } from 'react';
import { useComputedColorScheme } from '@mantine/core';

const STORAGE_KEY = 'punk_special_logo_active';
const EVENT_NAME = 'punkSpecialLogoChange';
const REVERT_DELAY_MS = 5000; // 5 seconds visibility duration

let revertTimer: ReturnType<typeof setTimeout> | null = null;

/** Read whether special logo is active from localStorage */
export function getSpecialLogoActive(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

const subscribeSpecialLogo = (callback: () => void) => {
  if (typeof window === 'undefined') return () => { };
  window.addEventListener(EVENT_NAME, callback);
  return () => window.removeEventListener(EVENT_NAME, callback);
};

const getSpecialLogoServerSnapshot = () => false;

/** Set special logo active state with 5-second automatic revert timer */
export function setSpecialLogoActive(active: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(active));
  } catch {
    // ignore write errors
  }

  if (revertTimer) {
    clearTimeout(revertTimer);
    revertTimer = null;
  }

  if (active) {
    // Automatically revert back to the previous colored logo after 5 seconds
    revertTimer = setTimeout(() => {
      setSpecialLogoActive(false);
    }, REVERT_DELAY_MS);
  }

  if (typeof window !== 'undefined') {
    const event = new CustomEvent(EVENT_NAME, { detail: { active } });
    window.dispatchEvent(event);
  }
}

/** Toggle special logo active state */
export function toggleSpecialLogo(): boolean {
  const current = getSpecialLogoActive();
  const next = !current;
  setSpecialLogoActive(next);
  return next;
}

export function changeSpecialLogo(
  _onTrigger?: (isSpecial: boolean) => void,
): void {
  // Special logo trigger functionality removed
}

export function useSpecialLogo() {
  const isSpecial = useSyncExternalStore(
    subscribeSpecialLogo,
    getSpecialLogoActive,
    getSpecialLogoServerSnapshot
  );

  const computedColorScheme = useComputedColorScheme('dark', {
    getInitialValueInEffect: true,
  });

  useEffect(() => {
    // If initial state on mount or toggle is active, ensure the 5-second revert timer is running
    if (isSpecial && !revertTimer) {
      revertTimer = setTimeout(() => {
        setSpecialLogoActive(false);
      }, REVERT_DELAY_MS);
    }
  }, [isSpecial]);

  const logoSrc =
    computedColorScheme === 'dark'
      ? '/logo/White Diamond Icon.svg'
      : '/logo/Black Diamond Icon (1).svg';

  return {
    isSpecial,
    logoSrc,
    toggleSpecialLogo,
    handleSpecialLogoClick: () => changeSpecialLogo(),
    changeSpecialLogo,
  };
}

export default changeSpecialLogo;
