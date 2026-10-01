export interface PasswordCriteria {
  minLength: boolean;
  maxLength: boolean;
  hasUppercase: boolean;
  hasLowercase: boolean;
  hasNumber: boolean;
  hasSpecialChar: boolean;
}

export interface PasswordValidationResult {
  isValid: boolean;
  criteria: PasswordCriteria;
  score: number; // 0 to 4
  strengthLabel: 'Weak' | 'Fair' | 'Good' | 'Strong';
  strengthColor: string;
  errors: string[];
}

export function validatePassword(password: string): PasswordValidationResult {
  const criteria: PasswordCriteria = {
    minLength: password.length >= 8,
    maxLength: password.length <= 72,
    hasUppercase: /[A-Z]/.test(password),
    hasLowercase: /[a-z]/.test(password),
    hasNumber: /[0-9]/.test(password),
    hasSpecialChar: /[^A-Za-z0-9]/.test(password),
  };

  const errors: string[] = [];
  if (!criteria.minLength) {
    errors.push('Password must be at least 8 characters long.');
  }
  if (!criteria.maxLength) {
    errors.push('Password cannot exceed 72 characters.');
  }
  if (!criteria.hasUppercase) {
    errors.push('Password must include at least one uppercase letter (A-Z).');
  }
  if (!criteria.hasLowercase) {
    errors.push('Password must include at least one lowercase letter (a-z).');
  }
  if (!criteria.hasNumber) {
    errors.push('Password must include at least one number (0-9).');
  }
  if (!criteria.hasSpecialChar) {
    errors.push('Password must include at least one special character (e.g. !@#$%^&*).');
  }

  // Calculate strength score
  let satisfiedCount = 0;
  if (criteria.minLength) satisfiedCount += 1;
  if (criteria.hasUppercase && criteria.hasLowercase) satisfiedCount += 1;
  if (criteria.hasNumber) satisfiedCount += 1;
  if (criteria.hasSpecialChar) satisfiedCount += 1;

  let score = 0;
  let strengthLabel: 'Weak' | 'Fair' | 'Good' | 'Strong' = 'Weak';
  let strengthColor = '#ef4444'; // red-500

  if (password.length === 0) {
    score = 0;
    strengthLabel = 'Weak';
    strengthColor = '#6b7280'; // gray-500
  } else if (satisfiedCount <= 1 || password.length < 8) {
    score = 1;
    strengthLabel = 'Weak';
    strengthColor = '#ef4444';
  } else if (satisfiedCount === 2) {
    score = 2;
    strengthLabel = 'Fair';
    strengthColor = '#f59e0b'; // amber-500
  } else if (satisfiedCount === 3) {
    score = 3;
    strengthLabel = 'Good';
    strengthColor = '#3b82f6'; // blue-500
  } else {
    score = 4;
    strengthLabel = 'Strong';
    strengthColor = '#10b981'; // emerald-500
  }

  const isValid =
    criteria.minLength &&
    criteria.maxLength &&
    criteria.hasUppercase &&
    criteria.hasLowercase &&
    criteria.hasNumber &&
    criteria.hasSpecialChar;

  return {
    isValid,
    criteria,
    score,
    strengthLabel,
    strengthColor,
    errors,
  };
}
