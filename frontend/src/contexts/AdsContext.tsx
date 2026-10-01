'use client';

import React, { createContext, type ReactNode, useContext } from 'react';
import {
  useMetaAdsDisconnect,
  useMetaAdsRegister,
} from '../hooks/api/useAdsConnectApi';
import { trackEvent } from '@/lib/analytics';

// Connection actions only. This context used to also expose `platforms` /
// `loading` / `refreshStatus`, but `refreshStatus` returned hard-coded mock data
// (act_123456789, "Shawarma Palace Ads") and nothing consumed it — the real
// account list is user.oauth_tokens[].accessible_accounts.
interface AdsContextType {
  connectPlatform: (platform: 'google' | 'meta') => Promise<void>;
  disconnectPlatform: (platform: 'google' | 'meta') => Promise<void>;
}

const AdsContext = createContext<AdsContextType | undefined>(undefined);

export const AdsProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const connectMetaAds = useMetaAdsRegister();
  const disconnectMetaAds = useMetaAdsDisconnect();

  const connectPlatform = async (platform: 'google' | 'meta') => {
    if (platform === 'meta') {
      trackEvent('Meta Connect Started', {
        source: 'settings_connections_tab',
      });
      trackEvent('meta_connect_started', {
        source: 'settings_connections_tab',
      });
      const response = await connectMetaAds.mutateAsync();
      if (response?.authorization_url) {
        window.location.href = response.authorization_url;
      }
    }
  };

  const disconnectPlatform = async (platform: 'google' | 'meta') => {
    if (platform === 'meta') {
      await disconnectMetaAds.mutateAsync();
    }
  };

  return (
    <AdsContext.Provider
      value={{
        connectPlatform,
        disconnectPlatform,
      }}
    >
      {children}
    </AdsContext.Provider>
  );
};

export const useAds = () => {
  const context = useContext(AdsContext);
  if (context === undefined) {
    throw new Error('useAds must be used within an AdsProvider');
  }
  return context;
};
