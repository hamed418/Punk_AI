"use server";

import { subscriptionApi } from '../lib/api/subscription';
import type { CreateCheckoutSessionRequest } from "@/types/subscription";
import { extractErrorMessage } from '../lib/errorUtils';

export async function getPlansAction() {
  try {
    const data = await subscriptionApi.getPlans();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get plans:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to retrieve subscription plans.') };
  }
}

export async function createCheckoutSessionAction(requestData: CreateCheckoutSessionRequest) {
  try {
    const data = await subscriptionApi.createCheckoutSession(requestData);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to create checkout session:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to create checkout session.') };
  }
}

export async function createPortalSessionAction(return_url?: string) {
  try {
    const data = await subscriptionApi.createPortalSession(return_url);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to create portal session:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to open customer portal.') };
  }
}

export async function assignAdAccountAction(ads_account_id: string) {
  try {
    const data = await subscriptionApi.assignAdAccount(ads_account_id);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to assign ad account:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to assign ad account.') };
  }
}

export async function cancelSubscriptionAction(subscription_id: string) {
  try {
    const data = await subscriptionApi.cancelSubscription(subscription_id);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to cancel subscription:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to cancel subscription.') };
  }
}

export async function resumeSubscriptionAction(subscription_id: string) {
  try {
    const data = await subscriptionApi.resumeSubscription(subscription_id);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to resume subscription:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to resume subscription.') };
  }
}

// A server action, not a browser apiFetch: /subscription/success requires the
// caller's session (get_current_user, HTTPBearer), and lib/fetcher.ts only
// attaches the Authorization header when running on the server.
export async function syncCheckoutSessionAction(session_id: string) {
  try {
    const data = await subscriptionApi.syncCheckoutSession(session_id);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to sync checkout session:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to verify subscription payment.') };
  }
}

