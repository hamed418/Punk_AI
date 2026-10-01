import { apiFetch } from '../fetcher';
import { SuccessResponse } from '../../types/api.types';
import { CreateUserDto, SignupStartDto, SignupVerifyDto, SignupCompleteDto } from '../../types/user.dto';

interface LoginDto {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
}

export interface SocialLoginResponse extends LoginResponse {
  user_id?: string;
  email?: string;
  full_name?: string | null;
  business_name?: string | null;
  why_choose_punk?: string | null;
  auth_method?: string;
  is_new_user?: boolean;
  is_paid?: boolean;
}

export interface GoogleAuthDto {
  access_token?: string;
  id_token?: string;
  flow?: string;
  paid?: boolean;
}

export interface AppleAuthDto {
  id_token: string;
  code?: string;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  email?: string;
  user?: {
    name?: {
      firstName?: string;
      lastName?: string;
    };
    email?: string;
  };
  flow?: string;
  paid?: boolean;
}

export interface SessionData {
  id: string;
  device_name: string | null;
  device_type: string | null;
  browser: string | null;
  operating_system: string | null;
  ip_address: string | null;
  last_active_at: string;
  current_device: boolean;
}

export interface SessionListResponse {
  max_devices: number;
  active_devices: number;
  sessions: SessionData[];
}

export interface LoginOtpSendDto {
  email: string;
}

export interface LoginOtpSendResponse {
  status: string;
  login_token: string;
  message: string;
}

export interface LoginOtpVerifyDto {
  login_token: string;
  code: string;
}

export interface CheckEmailResponse {
  exists: boolean;
  email: string;
  message: string;
  auth_method?: 'email' | 'google' | 'apple' | null;
}

export const authApi = {
  login: (data: LoginDto) => {
    return apiFetch<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  loginOtpSend: (data: LoginOtpSendDto) => {
    return apiFetch<LoginOtpSendResponse>('/auth/login/otp/send', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  loginOtpVerify: (data: LoginOtpVerifyDto) => {
    return apiFetch<LoginResponse>('/auth/login/otp/verify', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  googleLogin: (payload: string | GoogleAuthDto) => {
    const body = typeof payload === 'string' ? { access_token: payload } : payload;
    return apiFetch<SocialLoginResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify(body),
      cache: 'no-store',
    });
  },

  appleLogin: (payload: AppleAuthDto) => {
    return apiFetch<SocialLoginResponse>('/auth/apple', {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
    });
  },

  register: (data: CreateUserDto) => {
    return apiFetch<Record<string, unknown>>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  signupStart: (data: SignupStartDto) => {
    return apiFetch<{ signup_token: string; message: string }>('/auth/signup/start', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  signupVerify: (data: SignupVerifyDto) => {
    return apiFetch<{ message: string; is_verified: boolean }>('/auth/signup/verify', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  signupComplete: (data: SignupCompleteDto) => {
    return apiFetch<{
      status: string;
      message: string;
      user_id: string;
      email: string;
      access_token?: string;
      refresh_token?: string;
      is_paid?: boolean;
    }>('/auth/signup/complete', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  checkEmail: (email: string) => {
    return apiFetch<CheckEmailResponse>(
      `/auth/check-email?email=${encodeURIComponent(email)}`,
      {
        method: 'GET',
        cache: 'no-store',
      }
    );
  },

  verifyEarlyAccess: (email: string) => {
    return apiFetch<{ is_paid: boolean; is_registered: boolean; email?: string; message?: string }>(
      `/auth/verify-early-access?email=${encodeURIComponent(email)}`,
      {
        method: 'GET',
        cache: 'no-store',
      }
    );
  },

  verifyEmail: (data: { email: string; code: string }) => {
    return apiFetch<{ message: string; is_verified: boolean }>('/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  resendVerification: (data: { email: string }) => {
    return apiFetch<{ message: string }>('/auth/resend-verification', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  forgotPassword: (data: { email: string }) => {
    return apiFetch<{ message: string }>('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  changePassword: (data: { current_password: string; new_password: string }) => {
    return apiFetch<{ message: string }>('/user/change-password', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  resetPassword: (data: { email: string; code: string; new_password: string }) => {
    return apiFetch<{ message: string }>('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  logout: () => {
    return apiFetch<SuccessResponse<null>>('/auth/logout', {
      method: 'POST',
      cache: 'no-store',
    });
  },

  getSessions: () => {
    return apiFetch<SessionListResponse>('/auth/sessions', {
      method: 'GET',
      cache: 'no-store',
    });
  },

  revokeSession: (sessionId: string) => {
    return apiFetch<{ message: string }>(`/auth/sessions/${sessionId}`, {
      method: 'DELETE',
      cache: 'no-store',
    });
  },

  revokePendingSession: (data: { pending_login_token: string; session_id: string }) => {
    return apiFetch<{ message: string }>('/auth/revoke-pending-session', {
      method: 'POST',
      body: JSON.stringify(data),
      cache: 'no-store',
    });
  },

  completeLogin: (pending_login_token: string) => {
    return apiFetch<LoginResponse>('/auth/complete-login', {
      method: 'POST',
      body: JSON.stringify({ pending_login_token }),
      cache: 'no-store',
    });
  },
};
