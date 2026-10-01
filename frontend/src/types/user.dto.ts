import { z } from 'zod';

export const UserOauthSchema = z.object({
  id: z.string(),
  platform: z.string(),
  is_valid: z.boolean(),
  meta_user_image: z.string().optional(),
  meta_user_name: z.string().optional(),
  accessible_accounts: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
    })
  ).optional(),
});

export type UserOauth = z.infer<typeof UserOauthSchema>;
export const UserSchema = z.object({
  id: z.string().uuid().or(z.string()),
  email: z.string().email(),
  name: z.string().min(2).optional(),
  full_name: z.string().optional(),
  business_name: z.string().optional().nullable(),
  role: z.enum(['USER', 'ADMIN', 'MANAGER']).or(z.string()),
  createdAt: z.string().optional(),
  updatedAt: z.string().optional(),
  profile_image: z.string().optional(),
  oauth_tokens: z.array(UserOauthSchema),
  subscriptions: z.array(z.object({
    id: z.string(),
    // The API returns null (not absent) for a subscription not yet bound to an
    // ad account — see types/subscription.ts.
    ad_account_id: z.string().nullable().optional(),
    status: z.string(),
    plan_id: z.string().optional(),
    stripe_subscription_id: z.string().optional(),
    current_period_end: z.string().nullable().optional(),
    cancel_at_period_end: z.boolean().optional(),
    created_at: z.string().optional(),
    total_tokens: z.number().optional(),
    used_tokens: z.number().optional(),
    remaining_tokens: z.number().optional(),
    plan: z.object({
      id: z.string(),
      description: z.string(),
      amount: z.number().or(z.string()),
      currency: z.string()
    }).optional()
  })).optional(),
  isSubscriptionActive: z.boolean().optional(),
  free_message_limit: z.number().optional(),
  free_token_usage: z.number().optional(),
  select_meta_id: z.string().optional(),
  phone: z.string().optional(),
});

export type User = z.infer<typeof UserSchema>;

export const CreateUserDtoSchema = z.object({
  email: z.string().email(),
  password: z.string().min(6),
  name: z.string().optional(),
  full_name: z.string().optional(),
  business_name: z.string().optional(),
  business_type: z.string().optional().nullable(),
  why_choose_punk: z.string().optional(),
});

export type CreateUserDto = z.infer<typeof CreateUserDtoSchema>;

export const UpdateUserDtoSchema = z.object({
  name: z.string().min(2).optional(),
  full_name: z.string().optional(),
  phone: z.string().optional(),
  select_meta_id: z.string().optional(),
  business_name: z.string().optional().nullable(),
  business_type: z.string().optional().nullable(),
  why_choose_punk: z.string().optional().nullable(),
});

export type UpdateUserDto = z.infer<typeof UpdateUserDtoSchema>;

export const SignupStartDtoSchema = z.object({
  email: z.string().email(),
});

export type SignupStartDto = z.infer<typeof SignupStartDtoSchema>;

export const SignupVerifyDtoSchema = z.object({
  signup_token: z.string(),
  code: z.string().length(6),
});

export type SignupVerifyDto = z.infer<typeof SignupVerifyDtoSchema>;

export const SignupCompleteDtoSchema = z.object({
  signup_token: z.string(),
  password: z.string().min(8),
  full_name: z.string().min(1),
  business_name: z.string().optional(),
  business_type: z.string().optional().nullable(),
  why_choose_punk: z.string().optional(),
});

export type SignupCompleteDto = z.infer<typeof SignupCompleteDtoSchema>;

