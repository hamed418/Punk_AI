'use client';

import { AdsProvider } from '../contexts/AdsContext';
import { AuthProvider } from '../contexts/AuthContext';
import { ChatProvider } from '../contexts/ChatContext';
import { QueryProvider } from './QueryProvider';
import MantineUIProvider from './MantineUIProvider';
import { GoogleOAuthProvider } from '@react-oauth/google';
import PostHogProvider from './PostHogProvider';

const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '';

const Providers = ({ children }: { children: React.ReactNode }) => {
  return (
    <PostHogProvider>
      <GoogleOAuthProvider clientId={clientId}>
        <MantineUIProvider>
          <QueryProvider>
            <AuthProvider>
              <AdsProvider>
                <ChatProvider>{children}</ChatProvider>
              </AdsProvider>
            </AuthProvider>
          </QueryProvider>
        </MantineUIProvider>
      </GoogleOAuthProvider>
    </PostHogProvider>
  );
};

export default Providers;
