/**
 * Standardized PostHog Event Taxonomy for Punk AI Application (Frontend)
 * Following the Object + Action pattern in snake_case.
 */

export interface BaseEventProps {
  timestamp?: string;
  url?: string;
  pathname?: string;
  referrer?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_term?: string;
  utm_content?: string;
}

export interface PageViewedProps extends BaseEventProps {
  page_title?: string;
}

export interface OnboardingStartedProps extends BaseEventProps {
  email?: string;
  email_domain?: string;
  has_email_param: boolean;
}

export interface OnboardingEarlyAccessVerifiedProps extends BaseEventProps {
  email?: string;
  email_domain?: string;
  verification_status: 'valid' | 'already_registered' | 'not_paid' | 'error';
}

export interface OnboardingStepViewedProps extends BaseEventProps {
  step: number;
  step_name: 'tell_about_your_business' | 'create_account';
  email?: string;
}

export interface OnboardingStep1SubmittedProps extends BaseEventProps {
  business_name_provided: boolean;
  business_type: string | null;
  has_why_choose_punk: boolean;
  why_choose_punk_length?: number;
}

export interface OnboardingStep2SubmittedProps extends BaseEventProps {
  has_full_name: boolean;
  email_domain?: string;
}

export interface SignedUpProps extends BaseEventProps {
  email: string;
  email_domain?: string;
  full_name?: string;
  business_name?: string;
  business_type?: string | null;
  why_choose_punk?: string;
  signup_method?: string;
  auth_method?: 'email' | 'google' | 'apple';
  is_early_access?: boolean;
}

export interface SignupSocialInitiatedProps extends BaseEventProps {
  provider: 'google' | 'apple';
  flow?: string;
}

export interface AudienceGeneratedProps extends BaseEventProps {
  maid_count?: number | null;
  poi_count?: number;
  categories?: string[];
  search_radius?: number;
  center_lat?: number;
  center_lng?: number;
}

export interface CampaignCreatedProps extends BaseEventProps {
  campaign_id?: string;
  campaign_name?: string;
  objective?: string;
  ad_sets_count?: number;
  ads_count?: number;
  daily_budget?: number;
  publish_mode?: string;
}

export interface CampaignPublishedProps extends BaseEventProps {
  campaign_id?: string;
  campaign_name?: string;
  objective?: string;
  meta_campaign_id?: string;
  ad_account_id?: string;
  publish_mode?: string;
  status?: string;
}

export interface SubscriptionCancelledProps extends BaseEventProps {
  subscription_id?: string;
  plan_name?: string;
  cancel_reason?: string;
  cancel_at_period_end?: boolean;
}

export interface FeedbackSubmittedProps extends BaseEventProps {
  category?: string;
  feedback_type?: string;
  description?: string;
  email?: string;
  name?: string;
  rating?: number;
  has_attachment?: boolean;
}

export type UserRegisteredProps = SignedUpProps;

export interface UserRegistrationFailedProps extends BaseEventProps {
  error_message: string;
  step: number;
  email_domain?: string;
}

export interface UserLoggedInProps extends BaseEventProps {
  login_method: 'auto_post_registration' | 'credentials' | 'google_oauth' | 'apple_oauth' | string;
  auth_method?: 'email' | 'google' | 'apple' | 'otp';
  email?: string;
}

export interface OnboardingCompletedProps extends BaseEventProps {
  email: string;
  business_type?: string | null;
  auth_method?: 'email' | 'google' | 'apple' | 'otp';
  is_paid?: boolean;
  total_time_seconds?: number;
}

export interface MetaConnectPromptedProps extends BaseEventProps {
  source?: string;
  thread_id?: string;
}

export interface MetaConnectStartedProps extends BaseEventProps {
  source?: string;
  thread_id?: string;
}

export interface MetaConnectCancelledProps extends BaseEventProps {
  source?: string;
  thread_id?: string;
  duration_seconds?: number;
  reason?: string;
}

export interface MetaConnectedProps extends BaseEventProps {
  source?: string;
  thread_id?: string;
  accessible_accounts_count?: number;
}

export interface MetaConnectFailedProps extends BaseEventProps {
  source?: string;
  error_message?: string;
}

export interface ChatMessageSentProps extends BaseEventProps {
  thread_id?: string;
  message_length?: number;
  is_first_message?: boolean;
}

export interface ChatRunStoppedProps extends BaseEventProps {
  thread_id?: string;
  outcome?: string;
  step_label?: string | null;
  duration_seconds?: number;
}

export interface ModalClosedProps extends BaseEventProps {
  modal_name: string;
  source?: string;
  completed?: boolean;
}

export interface EventRegistry {
  // Funnel Events (Exact Display Names)
  'Signed Up': SignedUpProps;
  'Audience Generated': AudienceGeneratedProps;
  'Campaign Created': CampaignCreatedProps;
  'Campaign Published': CampaignPublishedProps;
  'Subscription Cancelled': SubscriptionCancelledProps;
  'Feedback Submitted': FeedbackSubmittedProps;

  // Meta Connection Flow & Drop-off Events
  'Meta Connect Prompted': MetaConnectPromptedProps;
  'Meta Connect Started': MetaConnectStartedProps;
  'Meta Connect Cancelled': MetaConnectCancelledProps;
  'Meta Connected': MetaConnectedProps;
  'Meta Connect Failed': MetaConnectFailedProps;

  // Chat Flow & Cancellation Events
  'Chat Message Sent': ChatMessageSentProps;
  'Chat Run Stopped': ChatRunStoppedProps;

  // Modal Drop-off Events
  'Pricing Modal Viewed': ModalClosedProps;
  'Pricing Modal Closed': ModalClosedProps;
  'Lead Form Cancelled': ModalClosedProps;

  // Snake_case aliases
  signed_up: SignedUpProps;
  audience_generated: AudienceGeneratedProps;
  campaign_created: CampaignCreatedProps;
  campaign_published: CampaignPublishedProps;
  subscription_cancelled: SubscriptionCancelledProps;
  feedback_submitted: FeedbackSubmittedProps;
  meta_connect_prompted: MetaConnectPromptedProps;
  meta_connect_started: MetaConnectStartedProps;
  meta_connect_cancelled: MetaConnectCancelledProps;
  meta_connected: MetaConnectedProps;
  meta_connect_failed: MetaConnectFailedProps;
  chat_message_sent: ChatMessageSentProps;
  chat_run_stopped: ChatRunStoppedProps;
  pricing_modal_viewed: ModalClosedProps;
  pricing_modal_closed: ModalClosedProps;
  lead_form_cancelled: ModalClosedProps;

  // Detailed lifecycle events
  page_viewed: PageViewedProps;
  onboarding_started: OnboardingStartedProps;
  onboarding_early_access_verified: OnboardingEarlyAccessVerifiedProps;
  onboarding_step_viewed: OnboardingStepViewedProps;
  onboarding_step1_submitted: OnboardingStep1SubmittedProps;
  onboarding_step2_submitted: OnboardingStep2SubmittedProps;
  user_registered: UserRegisteredProps;
  user_registration_failed: UserRegistrationFailedProps;
  user_logged_in: UserLoggedInProps;
  onboarding_completed: OnboardingCompletedProps;
  signup_social_initiated: SignupSocialInitiatedProps;
}

export type AnalyticsEventName = keyof EventRegistry;


