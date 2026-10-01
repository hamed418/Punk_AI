export interface PasswordValidationRule {
  id: string;
  label: string;
  passed: boolean;
}

export interface PasswordValidationResult {
  isValid: boolean;
  score: number; // 0 to 4
  strengthLabel: 'Very Weak' | 'Weak' | 'Fair' | 'Good' | 'Strong';
  strengthColor: string;
  rules: PasswordValidationRule[];
  errors: string[];
}

export function validatePassword(password: string): PasswordValidationResult {
  const trimmed = password ?? '';
  const minLength = trimmed.length >= 8;
  const maxLength = trimmed.length <= 72;
  const hasUppercase = /[A-Z]/.test(trimmed);
  const hasLowercase = /[a-z]/.test(trimmed);
  const hasNumber = /[0-9]/.test(trimmed);
  const hasSpecial = /[^A-Za-z0-9]/.test(trimmed);

  const rules: PasswordValidationRule[] = [
    { id: 'min_length', label: 'At least 8 characters', passed: minLength },
    { id: 'letter_case', label: 'Uppercase & lowercase letters', passed: hasUppercase && hasLowercase },
    { id: 'number', label: 'At least one number', passed: hasNumber },
    { id: 'special', label: 'At least one special character', passed: hasSpecial },
  ];

  const passedCount = rules.filter((r) => r.passed).length;

  let score = 0;
  let strengthLabel: PasswordValidationResult['strengthLabel'] = 'Very Weak';
  let strengthColor = '#6b7280'; // gray-500

  if (trimmed.length === 0) {
    score = 0;
    strengthLabel = 'Very Weak';
    strengthColor = '#6b7280';
  } else if (passedCount <= 1) {
    score = 1;
    strengthLabel = 'Weak';
    strengthColor = '#f87171'; // red-400
  } else if (passedCount === 2) {
    score = 2;
    strengthLabel = 'Fair';
    strengthColor = '#fbbf24'; // amber-400
  } else if (passedCount === 3) {
    score = 3;
    strengthLabel = 'Good';
    strengthColor = '#38bdf8'; // sky-400
  } else if (passedCount === 4) {
    score = 4;
    strengthLabel = 'Strong';
    strengthColor = '#34d399'; // emerald-400
  }

  const errors: string[] = [];
  if (!minLength) errors.push('Password must be at least 8 characters long.');
  if (!maxLength) errors.push('Password cannot exceed 72 characters.');
  if (!hasUppercase) errors.push('Password must contain at least one uppercase letter.');
  if (!hasLowercase) errors.push('Password must contain at least one lowercase letter.');
  if (!hasNumber) errors.push('Password must contain at least one number.');
  if (!hasSpecial) errors.push('Password must contain at least one special character.');

  const isValid = minLength && maxLength && hasUppercase && hasLowercase && hasNumber && hasSpecial;

  return {
    isValid,
    score,
    strengthLabel,
    strengthColor,
    rules,
    errors,
  };
}
