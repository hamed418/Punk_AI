import React, { useMemo } from 'react';
import { Check, X } from 'lucide-react';
import { validatePassword } from '@/lib/passwordValidation';

interface PasswordStrengthIndicatorProps {
  password: string;
  confirmPassword?: string;
  className?: string;
}

export const PasswordStrengthIndicator: React.FC<PasswordStrengthIndicatorProps> = ({
  password,
  confirmPassword,
  className = '',
}) => {
  const result = useMemo(() => validatePassword(password), [password]);
  const hasTyped = password.length > 0;
  const hasConfirmTyped = typeof confirmPassword === 'string' && confirmPassword.length > 0;
  const passwordsMatch = hasConfirmTyped && password === confirmPassword;

  const checklistItems = [
    { label: 'At least 8 characters', met: result.criteria.minLength },
    { label: 'Uppercase & lowercase letters', met: result.criteria.hasUppercase && result.criteria.hasLowercase },
    { label: 'At least one number (0-9)', met: result.criteria.hasNumber },
    { label: 'At least one special character (!@#$...)', met: result.criteria.hasSpecialChar },
  ];

  if (!hasTyped && !hasConfirmTyped) {
    return null;
  }

  return (
    <div
      className={`space-y-2.5 rounded-8 border border-border-default bg-surface-primary/60 p-3 font-sans text-xs ${className}`}
    >
      {/* Strength Bar */}
      {hasTyped && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] font-sans leading-tight">
            <span className="font-medium text-text-muted">Password strength</span>
            <span
              className="font-semibold transition-colors"
              style={{ color: result.strengthColor }}
            >
              {result.strengthLabel}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-1.5 h-1">
            {[1, 2, 3, 4].map((step) => {
              const active = result.score >= step;
              return (
                <div
                  key={step}
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    backgroundColor: active
                      ? result.strengthColor
                      : 'var(--border-primary, #EBEBEB)',
                  }}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Criteria Checklist */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 font-sans">
        {checklistItems.map((item, idx) => (
          <div
            key={idx}
            className={`flex items-center gap-1.5 text-[11px] leading-tight font-sans transition-colors ${
              item.met
                ? 'font-medium text-state-success'
                : 'text-text-muted'
            }`}
          >
            {item.met ? (
              <Check className="h-3.5 w-3.5 shrink-0 text-state-success stroke-[2.5]" />
            ) : (
              <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-text-muted/40 ml-1 mr-1" />
            )}
            <span>{item.label}</span>
          </div>
        ))}

        {/* Confirmation match check */}
        {hasConfirmTyped && (
          <div
            className={`flex items-center gap-1.5 text-[11px] leading-tight font-sans transition-colors ${
              passwordsMatch
                ? 'font-medium text-state-success'
                : 'font-medium text-state-danger'
            }`}
          >
            {passwordsMatch ? (
              <Check className="h-3.5 w-3.5 shrink-0 text-state-success stroke-[2.5]" />
            ) : (
              <X className="h-3.5 w-3.5 shrink-0 text-state-danger stroke-[2.5]" />
            )}
            <span>{passwordsMatch ? 'Passwords match' : 'Passwords do not match'}</span>
          </div>
        )}
      </div>
    </div>
  );
};
