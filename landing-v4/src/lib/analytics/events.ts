/**
 * Standardized PostHog Event Taxonomy for Punk AI Landing Page
 * Following the Object + Action (noun + verb) pattern in snake_case.
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
  section?: string;
}

export interface SectionViewedProps extends BaseEventProps {
  section_name: 'hero' | 'how-it-works' | 'pricing' | 'faq' | 'compliance' | 'technology';
  view_duration_seconds?: number;
}

export interface ScrollDepthReachedProps extends BaseEventProps {
  depth_percentage: 25 | 50 | 75 | 100;
  max_scroll_px?: number;
}

export interface CtaClickedProps extends BaseEventProps {
  cta_name: string;
  cta_location: 'navbar' | 'hero' | 'pricing_pro' | 'pricing_agency' | 'early_access_modal' | 'waitlist_upsell' | 'footer';
  button_text: string;
  target_modal?: 'secure_spot' | 'join_early_access' | 'apply_waitlist';
  plan_id?: string;
  destination_url?: string;
}

export interface EarlyAccessModalOpenedProps extends BaseEventProps {
  source: 'hero_form' | 'pricing_pro' | 'pricing_agency' | 'navbar' | 'url' | 'waitlist_upsell';
  modal_type: 'secure_spot' | 'join_early_access' | 'apply_waitlist';
  plan_id?: string;
  has_prefilled_email?: boolean;
}

export interface EarlyAccessModalClosedProps extends BaseEventProps {
  modal_type: 'secure_spot' | 'join_early_access' | 'apply_waitlist';
  time_spent_seconds?: number;
}

export interface EarlyAccessFormSubmittedProps extends BaseEventProps {
  form_type: 'secure_spot' | 'apply_waitlist';
  plan_id?: string;
  email_domain?: string;
  has_email: boolean;
}

export interface CheckoutInitiatedProps extends BaseEventProps {
  plan_id?: string;
  plan_name?: string;
  amount?: number | string;
  currency?: string;
  email_domain?: string;
}

export interface WaitlistJoinedProps extends BaseEventProps {
  applicant_number?: number;
  source?: string;
  email_domain?: string;
}

export interface PaymentSucceededProps extends BaseEventProps {
  session_id?: string;
  member_number?: number;
  total_members?: number;
  source?: string;
  plan_name?: string;
}

export interface AppAccessClickedProps extends BaseEventProps {
  destination_url: string;
  has_email?: boolean;
  member_number?: number;
}

export interface FaqToggledProps extends BaseEventProps {
  faq_id: number | string;
  faq_question: string;
  action: 'expand' | 'collapse';
}

export interface NavLinkClickedProps extends BaseEventProps {
  link_label: string;
  destination_href: string;
  nav_type: 'header_desktop' | 'header_mobile' | 'footer';
}

export interface SocialLinkClickedProps extends BaseEventProps {
  platform: string;
  destination_url: string;
}

/**
 * Type-safe map linking each PostHog event name to its property interface.
 */
export interface EventRegistry {
  // Title Case Display Names
  'Early Access Modal Opened': EarlyAccessModalOpenedProps;
  'Early Access Modal Closed': EarlyAccessModalClosedProps;
  'Early Access Form Submitted': EarlyAccessFormSubmittedProps;
  'Checkout Initiated': CheckoutInitiatedProps;
  'Payment Succeeded': PaymentSucceededProps;
  'App Access Clicked': AppAccessClickedProps;

  // Snake_case Names
  page_viewed: PageViewedProps;
  section_viewed: SectionViewedProps;
  scroll_depth_reached: ScrollDepthReachedProps;
  cta_clicked: CtaClickedProps;
  early_access_modal_opened: EarlyAccessModalOpenedProps;
  early_access_modal_closed: EarlyAccessModalClosedProps;
  early_access_form_submitted: EarlyAccessFormSubmittedProps;
  checkout_initiated: CheckoutInitiatedProps;
  waitlist_joined: WaitlistJoinedProps;
  payment_succeeded: PaymentSucceededProps;
  app_access_clicked: AppAccessClickedProps;
  faq_toggled: FaqToggledProps;
  nav_link_clicked: NavLinkClickedProps;
  social_link_clicked: SocialLinkClickedProps;
}

export type AnalyticsEventName = keyof EventRegistry;
