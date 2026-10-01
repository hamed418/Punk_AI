'use client';

import React, {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useRegister,
  useUpdateProfile,
  useUser,
  useLogout,
  useLogin,
  useGoogleLogin,
} from '../hooks/api/useAuthApi';

import type { User } from '@/types/user.dto';

import { identifyUser, resetUser, trackEvent } from '@/lib/analytics';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<void>;
  loginWithGoogle: (idToken: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    full_name?: string,
    business_name?: string,
    business_type?: string | null,
    why_choose_punk?: string
  ) => Promise<void>;
  updateProfile: (data?: {
    email?: string;
    password?: string;
    full_name?: string;
    select_meta_id?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const queryClient = useQueryClient();
  const { data: user, isLoading: loading } = useUser();

  const loginMutation = useLogin();
  const registerMutation = useRegister();
  const updateProfileMutation = useUpdateProfile();
  const logoutMutation = useLogout();
  const googleLoginMutation = useGoogleLogin();

  // Identify user on mount or user change
  React.useEffect(() => {
    if (user && user.email && !user.email.endsWith('@guest.local')) {
      identifyUser(user.id || user.email, {
        email: user.email,
        name: user.name || user.full_name,
        role: user.role,
        is_subscription_active: user.isSubscriptionActive,
      });
    }
  }, [user]);

  const login = useCallback(
    async (email: string, password: string, rememberMe: boolean = false) => {
      if (typeof document !== 'undefined') {
        document.cookie = 'is_impersonating=; path=/; max-age=0;';
      }
      await loginMutation.mutateAsync({ email, password, rememberMe });
      identifyUser(email, { email });
      trackEvent('user_logged_in', {
        email,
        login_method: 'credentials',
        auth_method: 'email',
      });
    },
    [loginMutation]
  );

  const loginWithGoogle = useCallback(
    async (idToken: string) => {
      if (typeof document !== 'undefined') {
        document.cookie = 'is_impersonating=; path=/; max-age=0;';
      }
      await googleLoginMutation.mutateAsync(idToken);
      trackEvent('user_logged_in', {
        login_method: 'google_oauth',
      });
    },
    [googleLoginMutation]
  );

  const register = useCallback(
    async (
      email: string,
      password: string,
      full_name?: string,
      business_name?: string,
      business_type?: string | null,
      why_choose_punk?: string
    ) => {
      await registerMutation.mutateAsync({
        email,
        password,
        name: full_name || '',
        full_name: full_name || '',
        business_name,
        business_type,
        why_choose_punk,
      });

      identifyUser(email, {
        email,
        full_name: full_name || '',
        business_name,
        business_type,
        why_choose_punk,
      });

      // Funnel Step 1: Signed Up
      trackEvent('Signed Up', {
        email,
        full_name: full_name || '',
        business_name,
        business_type,
        why_choose_punk,
        signup_method: 'standard_signup',
      });
      trackEvent('signed_up', {
        email,
        full_name: full_name || '',
        business_name,
        business_type,
        why_choose_punk,
        signup_method: 'standard_signup',
      });
    },
    [registerMutation]
  );

  const updateProfile = useCallback(
    async (data?: { email?: string; password?: string; full_name?: string; select_meta_id?: string }) => {
      await updateProfileMutation.mutateAsync({ name: data?.full_name, select_meta_id: data?.select_meta_id });
    },
    [updateProfileMutation]
  );

  const logout = useCallback(async () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    if (typeof document !== 'undefined') {
      document.cookie = 'is_impersonating=; path=/; max-age=0;';
    }
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.clear();
      } catch {}
    }
    queryClient.setQueryData(['user'], null);
    queryClient.clear();
    resetUser();
    try {
      await logoutMutation.mutateAsync();
    } catch (e) {
      console.error(e);
    }
  }, [logoutMutation, queryClient]);

  const value = useMemo(
    () => ({
      user: user || null,
      loading,
      login,
      loginWithGoogle,
      register,
      updateProfile,
      logout,
    }),
    [user, loading, login, loginWithGoogle, register, updateProfile, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
