import { authApi, GoogleAuthDto, AppleAuthDto, LoginOtpSendDto, LoginOtpVerifyDto } from '../lib/api/auth';
import { setAuthToken, removeAuthToken, setRefreshToken, removeRefreshToken } from '../lib/cookies';
import { CreateUserDto, CreateUserDtoSchema, SignupStartDto, SignupStartDtoSchema, SignupVerifyDto, SignupVerifyDtoSchema, SignupCompleteDto, SignupCompleteDtoSchema } from '../types/user.dto';

export interface LoginDto {
  email: string;
  password: string;
  rememberMe?: boolean;
}

export class AuthService {
  static async login(data: LoginDto) {
    try {
      const response = await authApi.login(data);
      const token = response.access_token;
      await setAuthToken(token, Boolean(data.rememberMe));
      
      if (response.refresh_token) {
        await setRefreshToken(response.refresh_token, Boolean(data.rememberMe));
      }
      
      return { success: true };
    } catch (error) {
      console.error('Login failed:', error);
      throw error; 
    }
  }

  static async loginOtpSend(data: LoginOtpSendDto) {
    try {
      return await authApi.loginOtpSend(data);
    } catch (error) {
      console.error('Failed to send login OTP:', error);
      throw error;
    }
  }

  static async loginOtpVerify(data: LoginOtpVerifyDto, rememberMe: boolean = false) {
    try {
      const response = await authApi.loginOtpVerify(data);
      const token = response.access_token;
      await setAuthToken(token, Boolean(rememberMe));
      if (response.refresh_token) {
        await setRefreshToken(response.refresh_token, Boolean(rememberMe));
      }
      return { success: true, data: response };
    } catch (error) {
      console.error('Failed to verify login OTP:', error);
      throw error;
    }
  }

  static async checkEmail(email: string) {
    try {
      return await authApi.checkEmail(email);
    } catch (error) {
      console.error('Failed to check email existence:', error);
      throw error;
    }
  }

  static async googleLogin(payload: string | GoogleAuthDto) {
    try {
      const response = await authApi.googleLogin(payload);
      if (response.access_token) {
        await setAuthToken(response.access_token);
      }
      if (response.refresh_token) {
        await setRefreshToken(response.refresh_token);
      }
      return { success: true, data: response };
    } catch (error) {
      console.error('Google login failed:', error);
      throw error;
    }
  }

  static async appleLogin(payload: AppleAuthDto) {
    try {
      const response = await authApi.appleLogin(payload);
      if (response.access_token) {
        await setAuthToken(response.access_token);
      }
      if (response.refresh_token) {
        await setRefreshToken(response.refresh_token);
      }
      return { success: true, data: response };
    } catch (error) {
      console.error('Apple login failed:', error);
      throw error;
    }
  }

  static async register(data: CreateUserDto) {
    try {
      const validatedData = CreateUserDtoSchema.parse(data);
      const response = await authApi.register(validatedData);
      return { success: true, user: response };
    } catch (error) {
      console.error('Registration failed:', error);
      throw error;
    }
  }

  static async signupStart(data: SignupStartDto) {
    try {
      const validatedData = SignupStartDtoSchema.parse(data);
      return await authApi.signupStart(validatedData);
    } catch (error) {
      console.error('Signup Start failed:', error);
      throw error;
    }
  }

  static async signupVerify(data: SignupVerifyDto) {
    try {
      const validatedData = SignupVerifyDtoSchema.parse(data);
      return await authApi.signupVerify(validatedData);
    } catch (error) {
      console.error('Signup Verify failed:', error);
      throw error;
    }
  }

  static async signupComplete(data: SignupCompleteDto) {
    try {
      const validatedData = SignupCompleteDtoSchema.parse(data);
      const response = await authApi.signupComplete(validatedData);
      
      if (response.access_token) {
        await setAuthToken(response.access_token);
      }
      if (response.refresh_token) {
        await setRefreshToken(response.refresh_token);
      }
      
      return response;
    } catch (error) {
      console.error('Signup Complete failed:', error);
      throw error;
    }
  }

  static async verifyEarlyAccess(email: string) {
    return await authApi.verifyEarlyAccess(email);
  }

  static async verifyEmail(data: { email: string; code: string }) {
    return await authApi.verifyEmail(data);
  }

  static async resendVerification(data: { email: string }) {
    return await authApi.resendVerification(data);
  }

  static async forgotPassword(data: { email: string }) {
    return await authApi.forgotPassword(data);
  }

  static async resetPassword(data: { email: string; code: string; new_password: string }) {
    return await authApi.resetPassword(data);
  }

  static async logout() {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout API failed, forcing local cleanup', error);
    } finally {
      await removeAuthToken();
      await removeRefreshToken();
    }
  }

  static async completeLogin(pending_login_token: string) {
    try {
      const response = await authApi.completeLogin(pending_login_token);
      const token = response.access_token;
      await setAuthToken(token);
      
      if (response.refresh_token) {
        await setRefreshToken(response.refresh_token);
      }
      return { success: true };
    } catch (error) {
      console.error('Complete login failed:', error);
      throw error;
    }
  }

  static async getSessions() {
    return await authApi.getSessions();
  }

  static async revokeSession(sessionId: string) {
    return await authApi.revokeSession(sessionId);
  }

  static async revokePendingSession(pendingToken: string, sessionId: string) {
    return await authApi.revokePendingSession({ pending_login_token: pendingToken, session_id: sessionId });
  }
}
