"use server";

import { AuthService, LoginDto } from '../services/auth.service';
import { UserService } from '../services/user.service';
import { revalidateTag } from 'next/cache';
import { CreateUserDto, UpdateUserDto, SignupStartDto, SignupVerifyDto, SignupCompleteDto } from '../types/user.dto';
import { extractErrorMessage } from '../lib/errorUtils';
import { getApiKey } from '../lib/apiKey';

export async function loginAction(data: LoginDto) {
  try {
    await AuthService.login(data);
    return { success: true };
  } catch (error: unknown) {
    const err = error as { data?: { code?: string } };
    if (err?.data?.code === 'MAX_DEVICE_LIMIT_REACHED') {
      return { success: false, data: err.data };
    }
    return { success: false, error: extractErrorMessage(error, 'Login failed. Please check your credentials.') };
  }
}

export async function loginOtpSendAction(data: LoginOtpSendDto) {
  try {
    const res = await AuthService.loginOtpSend(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to send login code.') };
  }
}

export async function loginOtpVerifyAction(data: LoginOtpVerifyDto, rememberMe: boolean = false) {
  try {
    const res = await AuthService.loginOtpVerify(data, rememberMe);
    return { success: true, data: res.data };
  } catch (error: unknown) {
    const err = error as { data?: { code?: string } };
    if (err?.data?.code === 'MAX_DEVICE_LIMIT_REACHED') {
      return { success: false, data: err.data };
    }
    return { success: false, error: extractErrorMessage(error, 'Invalid or expired code.') };
  }
}

export async function checkEmailAction(email: string) {
  try {
    const res = await AuthService.checkEmail(email);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to check email.') };
  }
}

import { GoogleAuthDto, AppleAuthDto, SocialLoginResponse, LoginOtpSendDto, LoginOtpVerifyDto } from '../lib/api/auth';

export type SocialActionResult =
  | { success: true; data: SocialLoginResponse }
  | { success: false; data?: { code?: string; [key: string]: unknown }; error?: string };

export async function googleLoginAction(payload: string | GoogleAuthDto): Promise<SocialActionResult> {
  try {
    const res = await AuthService.googleLogin(payload);
    return { success: true, data: res.data };
  } catch (error: unknown) {
    const err = error as { data?: { code?: string; [key: string]: unknown } };
    if (err?.data?.code === 'MAX_DEVICE_LIMIT_REACHED' || err?.data?.code === 'AUTH_METHOD_MISMATCH') {
      return { success: false, data: err.data };
    }
    return { success: false, error: extractErrorMessage(error, 'Google authentication failed.') };
  }
}

export async function appleLoginAction(payload: AppleAuthDto): Promise<SocialActionResult> {
  try {
    const res = await AuthService.appleLogin(payload);
    return { success: true, data: res.data };
  } catch (error: unknown) {
    const err = error as { data?: { code?: string; [key: string]: unknown } };
    if (err?.data?.code === 'MAX_DEVICE_LIMIT_REACHED' || err?.data?.code === 'AUTH_METHOD_MISMATCH') {
      return { success: false, data: err.data };
    }
    return { success: false, error: extractErrorMessage(error, 'Apple authentication failed.') };
  }
}

export async function registerAction(data: CreateUserDto) {
  try {
    const result = await AuthService.register(data);
    return { success: true, data: result };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Registration failed. Please try again.') };
  }
}

export async function signupStartAction(data: SignupStartDto) {
  try {
    const result = await AuthService.signupStart(data);
    return { success: true, data: result };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to start signup.') };
  }
}

export async function signupVerifyAction(data: SignupVerifyDto) {
  try {
    const result = await AuthService.signupVerify(data);
    return { success: true, data: result };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Invalid verification code.') };
  }
}

export async function signupCompleteAction(data: SignupCompleteDto) {
  try {
    const result = await AuthService.signupComplete(data);
    return { success: true, data: result };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to complete signup.') };
  }
}

export async function verifyEarlyAccessAction(email: string) {
  try {
    const res = await AuthService.verifyEarlyAccess(email);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Payment verification failed.') };
  }
}

export async function verifyEmailAction(data: { email: string; code: string }) {
  try {
    const res = await AuthService.verifyEmail(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Verification failed. Please try again.') };
  }
}

export async function resendVerificationAction(data: { email: string }) {
  try {
    const res = await AuthService.resendVerification(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to resend code.') };
  }
}

export async function forgotPasswordAction(data: { email: string }) {
  try {
    const res = await AuthService.forgotPassword(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to process request.') };
  }
}

export async function resetPasswordAction(data: { email: string; code: string; new_password: string }) {
  try {
    const res = await AuthService.resetPassword(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to reset password.') };
  }
}

export async function changePasswordAction(data: { current_password: string; new_password: string }) {
  try {
    const { authApi } = await import('../lib/api/auth');
    const res = await authApi.changePassword(data);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to change password.') };
  }
}

export async function getMeAction() {
  try {
    const data = await UserService.getCurrentProfile();
    return { success: true, data };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to retrieve user profile.') };
  }
}

export async function updateProfileAction(data: UpdateUserDto) {
  try {
    const result = await UserService.updateUser('me', data); 
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user-profile');
    return { success: true, data: result };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to update profile.') };
  }
}

let refreshTokenPromise: Promise<{ success: boolean; accessToken?: string; error?: string }> | null = null;

export async function refreshAuthTokenAction() {
  if (refreshTokenPromise) {
    return refreshTokenPromise;
  }

  refreshTokenPromise = (async () => {
    try {
      const { getRefreshToken, setAuthToken, setRefreshToken } = await import('../lib/cookies');
      const refreshToken = await getRefreshToken();
      if (!refreshToken) {
        return { success: false, error: 'No refresh token available' };
      }
      const BASE_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const baseUrlClean = BASE_URL.replace(/\/$/, '');
      const refreshRes = await fetch(`${baseUrlClean}/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': getApiKey(),
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (refreshRes.ok) {
        const refreshData = await refreshRes.json();
        if (refreshData.access_token) {
          await setAuthToken(refreshData.access_token);
          if (refreshData.refresh_token) {
            await setRefreshToken(refreshData.refresh_token);
          }
          return { success: true, accessToken: refreshData.access_token };
        }
      }
      return { success: false, error: 'Token refresh failed' };
    } catch (error: unknown) {
      return { success: false, error: extractErrorMessage(error, 'Token refresh failed.') };
    } finally {
      refreshTokenPromise = null;
    }
  })();

  return refreshTokenPromise;
}

export async function logoutAction() {
  try {
    await AuthService.logout();
    return { success: true };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Logout failed.') };
  }
}

export async function completeLoginAction(pending_login_token: string) {
  try {
    await AuthService.completeLogin(pending_login_token);
    return { success: true };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Complete login failed.') };
  }
}

export async function getSessionsAction() {
  try {
    const res = await AuthService.getSessions();
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch sessions.') };
  }
}

export async function revokeSessionAction(sessionId: string) {
  try {
    const res = await AuthService.revokeSession(sessionId);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to revoke session.') };
  }
}

export async function revokePendingSessionAction(pendingToken: string, sessionId: string) {
  try {
    const res = await AuthService.revokePendingSession(pendingToken, sessionId);
    return { success: true, data: res };
  } catch (error: unknown) {
    return { success: false, error: extractErrorMessage(error, 'Failed to revoke session.') };
  }
}
