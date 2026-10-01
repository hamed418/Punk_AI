'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from 'react';
import { useSearchParams } from 'next/navigation';
import ProfilePage from '@/app/(main)/profile/components';

import { Modal } from '@mantine/core';
import BuyToken from '@/components/subscriptionModals/BuyToken';

export const VALID_PROFILE_TABS = [
  'general',
  'account',
  'security',
  'connections',
  'payment',
  'feedback',
] as const;

export type ProfileTab = (typeof VALID_PROFILE_TABS)[number];

const STORAGE_KEY = 'punk_last_profile_tab';

interface ProfileModalContextType {
  isProfileOpen: boolean;
  activeTab: ProfileTab;
  openProfile: (tab?: string) => void;
  closeProfile: () => void;
  setActiveTab: (tab: string) => void;
  isBuyTokensOpen: boolean;
  openBuyTokens: () => void;
  closeBuyTokens: () => void;
}

const ProfileModalContext = createContext<ProfileModalContextType>({
  isProfileOpen: false,
  activeTab: 'general',
  openProfile: () => {},
  closeProfile: () => {},
  setActiveTab: () => {},
  isBuyTokensOpen: false,
  openBuyTokens: () => {},
  closeBuyTokens: () => {},
});

export const ProfileModalProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const searchParams = useSearchParams();

  // Helper to read saved tab
  const getSavedTab = (): ProfileTab => {
    if (typeof window === 'undefined') return 'general';
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && VALID_PROFILE_TABS.includes(saved as ProfileTab)) {
        return saved as ProfileTab;
      }
    } catch {
      // ignore
    }
    return 'general';
  };

  // Helper to persist tab to localStorage
  const persistTab = (tab: ProfileTab) => {
    if (typeof window === 'undefined') return;
    try {
      localStorage.setItem(STORAGE_KEY, tab);
    } catch {
      // ignore
    }
  };

  const isProfileParam = searchParams.get('profile') === 'true';
  const tabParam = searchParams.get('tab');

  const [isProfileOpen, setIsProfileOpen] = useState(isProfileParam);
  const [activeTab, setActiveTabState] = useState<ProfileTab>(() => {
    if (tabParam && VALID_PROFILE_TABS.includes(tabParam as ProfileTab)) {
      return tabParam as ProfileTab;
    }
    return getSavedTab();
  });

  // Adjust state during render when searchParams change (official React pattern for syncing props/params to state)
  const [prevSearchParams, setPrevSearchParams] = useState(searchParams);
  if (prevSearchParams !== searchParams) {
    setPrevSearchParams(searchParams);
    setIsProfileOpen(isProfileParam);
    if (isProfileParam) {
      if (tabParam && VALID_PROFILE_TABS.includes(tabParam as ProfileTab)) {
        setActiveTabState(tabParam as ProfileTab);
      } else {
        setActiveTabState(getSavedTab());
      }
    }
  }

  // Set active tab and update storage & URL smoothly
  const setActiveTab = useCallback((tab: string) => {
    const validTab = VALID_PROFILE_TABS.includes(tab as ProfileTab)
      ? (tab as ProfileTab)
      : 'general';
    setActiveTabState(validTab);
    persistTab(validTab);

    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.get('profile') === 'true') {
        params.set('tab', validTab);
        const newUrl = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState(null, '', newUrl);
      }
    }
  }, []);

  const openProfile = useCallback((tab?: string) => {
    let targetTab: ProfileTab;
    if (tab && VALID_PROFILE_TABS.includes(tab as ProfileTab)) {
      targetTab = tab as ProfileTab;
    } else {
      targetTab = getSavedTab();
    }

    setActiveTabState(targetTab);
    setIsProfileOpen(true);

    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      params.set('profile', 'true');
      params.set('tab', targetTab);
      const newUrl = `${window.location.pathname}?${params.toString()}`;
      window.history.replaceState(null, '', newUrl);
    }
  }, []);

  const closeProfile = useCallback(() => {
    setIsProfileOpen(false);

    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.has('profile') || params.has('tab')) {
        params.delete('profile');
        params.delete('tab');
        const search = params.toString();
        const newUrl = search
          ? `${window.location.pathname}?${search}`
          : window.location.pathname;
        window.history.replaceState(null, '', newUrl);
      }
    }
  }, []);

  const [isBuyTokensOpen, setIsBuyTokensOpen] = useState(false);
  const openBuyTokens = useCallback(() => setIsBuyTokensOpen(true), []);
  const closeBuyTokens = useCallback(() => setIsBuyTokensOpen(false), []);

  // Persist active tab whenever it changes and profile is open
  useEffect(() => {
    if (isProfileOpen && activeTab) {
      persistTab(activeTab);
    }
  }, [isProfileOpen, activeTab]);

  return (
    <ProfileModalContext.Provider
      value={{
        isProfileOpen,
        activeTab,
        openProfile,
        closeProfile,
        setActiveTab,
        isBuyTokensOpen,
        openBuyTokens,
        closeBuyTokens,
      }}
    >
      {children}
      <ProfilePage
        isOpen={isProfileOpen}
        onClose={closeProfile}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
      <Modal
        opened={isBuyTokensOpen}
        onClose={closeBuyTokens}
        centered
        withCloseButton={false}
        padding={0}
        radius={28}
        zIndex={100002}
        overlayProps={{
          backgroundOpacity: 0.11,
          blur: 40,
        }}
        styles={{
          overlay: {
            background: 'rgba(9, 9, 9, 0.11)',
            backdropFilter: 'blur(40px)',
            WebkitBackdropFilter: 'blur(40px)',
          },
          content: { background: 'transparent', boxShadow: 'none' },
          body: { padding: 0 },
        }}
      >
        <BuyToken onClose={closeBuyTokens} />
      </Modal>
    </ProfileModalContext.Provider>
  );
};

export const useProfileModal = () => useContext(ProfileModalContext);
