import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getMeAction,
  loginAction,
  googleLoginAction,
  appleLoginAction,
  registerAction,
  verifyEmailAction,
  resendVerificationAction,
  forgotPasswordAction,
  resetPasswordAction,
  updateProfileAction,
  logoutAction,
  getSessionsAction,
  completeLoginAction,
  revokeSessionAction,
  revokePendingSessionAction,
  signupStartAction,
  signupVerifyAction,
  signupCompleteAction,
  loginOtpSendAction,
  loginOtpVerifyAction,
  checkEmailAction,
} from '../../actions/auth.actions';
import type { LoginDto } from '../../services/auth.service';
import { CreateUserDto, UpdateUserDto, SignupStartDto, SignupVerifyDto, SignupCompleteDto } from '../../types/user.dto';
import type { LoginOtpSendDto, LoginOtpVerifyDto } from '../../lib/api/auth';

interface LoginErrorType extends Error {
  data?: unknown;
}

export const useUser = () => {
  const query = useQuery({
    queryKey: ['user'],
    queryFn: async () => {
      const result = await getMeAction();
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    retry: false,
  });

  return {
    ...query,
    isLoading: query.isLoading,
  };
};

export const useLogin = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: LoginDto) => {
      const result = await loginAction(data);
      if (!result.success) {
        const error = new Error(result.error || 'Login failed') as LoginErrorType;
        if (result.data) error.data = result.data;
        throw error;
      }
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
};

export const useLoginOtpSend = () => {
  return useMutation({
    mutationFn: async (data: LoginOtpSendDto) => {
      const result = await loginOtpSendAction(data);
      if (!result.success) {
        throw new Error(result.error || 'Failed to send login code');
      }
      return result.data!;
    },
  });
};

export const useLoginOtpVerify = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { verifyData: LoginOtpVerifyDto; rememberMe?: boolean }) => {
      const result = await loginOtpVerifyAction(data.verifyData, data.rememberMe);
      if (!result.success) {
        const error = new Error(result.error || 'Invalid or expired code') as LoginErrorType;
        if (result.data) error.data = result.data;
        throw error;
      }
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
};

export const useCheckEmail = () => {
  return useMutation({
    mutationFn: async (email: string) => {
      const result = await checkEmailAction(email);
      if (!result.success) {
        throw new Error(result.error || 'Failed to check email');
      }
      return result.data!;
    },
  });
};

export const useGoogleLogin = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: string | { access_token?: string; id_token?: string; flow?: string; paid?: boolean }) => {
      const result = await googleLoginAction(payload);
      if (!result.success) {
        const error = new Error(result.error || 'Google login failed') as LoginErrorType;
        if (result.data) error.data = result.data;
        throw error;
      }
      return result.data as import('../../lib/api/auth').SocialLoginResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
};

export const useAppleLogin = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      id_token: string;
      code?: string;
      first_name?: string;
      last_name?: string;
      full_name?: string;
      email?: string;
      user?: { name?: { firstName?: string; lastName?: string }; email?: string };
      flow?: string;
      paid?: boolean;
    }) => {
      const result = await appleLoginAction(payload);
      if (!result.success) {
        const error = new Error(result.error || 'Apple login failed') as LoginErrorType;
        if (result.data) error.data = result.data;
        throw error;
      }
      return result.data as import('../../lib/api/auth').SocialLoginResponse;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
};

export const useRegister = () => {
  return useMutation({
    mutationFn: async (data: CreateUserDto) => {
      const result = await registerAction(data);
      if (!result.success) throw new Error(result.error);
      return result;
    },
  });
};

export const useSignupStart = () => {
  return useMutation({
    mutationFn: async (data: SignupStartDto) => {
      const result = await signupStartAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useSignupVerify = () => {
  return useMutation({
    mutationFn: async (data: SignupVerifyDto) => {
      const result = await signupVerifyAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useSignupComplete = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: SignupCompleteDto) => {
      const result = await signupCompleteAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
};

export const useVerifyEmail = () => {
  return useMutation({
    mutationFn: async (data: { email: string; code: string }) => {
      const result = await verifyEmailAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useResendVerification = () => {
  return useMutation({
    mutationFn: async (data: { email: string }) => {
      const result = await resendVerificationAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useForgotPassword = () => {
  return useMutation({
    mutationFn: async (data: { email: string }) => {
      const result = await forgotPasswordAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useResetPassword = () => {
  return useMutation({
    mutationFn: async (data: { email: string; code: string; new_password: string }) => {
      const result = await resetPasswordAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });
};

export const useUpdateProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: UpdateUserDto) => {
      const result = await updateProfileAction(data);
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['user'], data);
      // select_meta_id can change here (ad-account switch) — the campaigns
      // tab's cached list is scoped to whichever account was selected before.
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
    },
  });
};

export const useLogout = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await logoutAction();
      if (!result.success) throw new Error(result.error);
      return result;
    },
    onSuccess: () => {
      queryClient.setQueryData(['user'], null);
      queryClient.clear();
    },
  });
};

export const useGetSessions = () => {
  const query = useQuery({
    queryKey: ['sessions'],
    queryFn: async () => {
      const result = await getSessionsAction();
      if (!result.success) throw new Error(result.error);
      return result.data!;
    },
  });

  return {
    ...query,
    isLoading: query.isLoading,
  };
};

export const useRevokeSession = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const result = await revokeSessionAction(sessionId);
      if (!result.success) throw new Error(result.error);
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
  });
};

export const useCompleteLogin = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (pendingToken: string) => {
      const result = await completeLoginAction(pendingToken);
      if (!result.success) throw new Error(result.error);
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user'] });
    },
  });
};

export const useRevokePendingSession = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { pendingToken: string; sessionId: string }) => {
      const result = await revokePendingSessionAction(data.pendingToken, data.sessionId);
      if (!result.success) throw new Error(result.error);
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
  });
};
