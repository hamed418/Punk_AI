import React, { useMemo } from 'react';
import { Check, X } from 'lucide-react';
import { validatePassword } from '@/lib/auth/passwordValidation';

export interface PasswordStrengthIndicatorProps {
  password: string;
  confirmPassword?: string;
  showRules?: boolean;
}

export const PasswordStrengthIndicator: React.FC<PasswordStrengthIndicatorProps> = ({
  password,
  confirmPassword,
  showRules = true,
}) => {
  const result = useMemo(() => validatePassword(password), [password]);

  const hasTyped = password.length > 0;
  const hasConfirmTyped = typeof confirmPassword === 'string' && confirmPassword.length > 0;
  const passwordsMatch = hasConfirmTyped && confirmPassword === password;

  return (
    <div className="flex flex-col gap-2.5 pt-1 font-sans">
      {/* Strength Bar & Label */}
      {hasTyped && (
        <div className="flex flex-col gap-1.5 animate-auth-in font-sans">
          <div className="flex items-center justify-between text-[11px] font-sans leading-tight">
            <span className="font-medium text-[#FAF9F5]/70">Password strength</span>
            <span
              className="font-semibold transition-colors"
              style={{ color: result.strengthColor }}
            >
              {result.strengthLabel}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-1.5">
            {[1, 2, 3, 4].map((step) => {
              const isActive = result.score >= step;
              return (
                <div
                  key={step}
                  className="h-1 rounded-full transition-all duration-300"
                  style={{
                    backgroundColor: isActive
                      ? result.strengthColor
                      : 'rgba(255, 255, 255, 0.1)',
                  }}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Checklist Rules */}
      {showRules && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1 font-sans">
          {result.rules.map((rule) => {
            const isMet = hasTyped && rule.passed;
            return (
              <div
                key={rule.id}
                className="flex items-center gap-2 text-[11px] font-sans leading-tight transition-colors duration-200"
              >
                <span
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full transition-all duration-200 ${
                    isMet
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      : 'bg-white/5 text-[#FAF9F5]/30 border border-white/10'
                  }`}
                >
                  {isMet ? (
                    <Check className="h-2.5 w-2.5 stroke-[3]" />
                  ) : (
                    <span className="h-1 w-1 rounded-full bg-[#FAF9F5]/30" />
                  )}
                </span>
                <span
                  className={
                    isMet
                      ? 'text-[#FAF9F5]/90 font-medium transition-colors'
                      : 'text-[#FAF9F5]/50 transition-colors'
                  }
                >
                  {rule.label}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Confirmation Match Status */}
      {hasConfirmTyped && (
        <div className="flex items-center gap-2 pt-0.5 text-[11px] font-sans leading-tight animate-auth-in">
          <span
            className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full transition-all duration-200 ${
              passwordsMatch
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-red-500/20 text-red-400 border border-red-500/30'
            }`}
          >
            {passwordsMatch ? (
              <Check className="h-2.5 w-2.5 stroke-[3]" />
            ) : (
              <X className="h-2.5 w-2.5 stroke-[3]" />
            )}
          </span>
          <span
            className={`font-medium ${
              passwordsMatch ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {passwordsMatch ? 'Passwords match' : 'Passwords do not match'}
          </span>
        </div>
      )}
    </div>
  );
};
