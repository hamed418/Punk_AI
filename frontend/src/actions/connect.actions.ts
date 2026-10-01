"use server";

import { connectApi } from '../lib/api/connect';
import { revalidateTag } from 'next/cache';
import { extractErrorMessage } from '../lib/errorUtils';

/** Ad-platform connection status. Polled by the chat OAuth widget while the
 *  Meta popup is open — `connected` only flips once the callback has stored a
 *  token the backend would actually accept. */
export async function adsStatusAction() {
  try {
    const data = await connectApi.adsStatus();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to fetch ad platform status:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch ad platform status.') };
  }
}

/** What the connected advertiser still has to do in Meta, in order. */
export async function metaReadinessAction() {
  try {
    const data = await connectApi.readiness();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to fetch Meta readiness:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to check your Meta setup.') };
  }
}

/** Instant forms on the Pages the user shared. */
export async function metaLeadFormsAction() {
  try {
    const data = await connectApi.leadForms();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to fetch lead forms:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to load your lead forms.') };
  }
}

/** Leads submitted to one instant form. */
export async function metaFormLeadsAction(formId: string, pageId: string) {
  try {
    const data = await connectApi.formLeads(formId, pageId);
    return { success: true, data: data.results };
  } catch (error: unknown) {
    console.error('Failed to fetch form leads:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to load leads.') };
  }
}

/** Whether each Page's leads are reaching Punk. */
export async function leadDeliveryAction() {
  try {
    const data = await connectApi.leadDelivery();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to fetch lead delivery:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to check lead delivery.') };
  }
}

/** Subscribe Punk to a Page's leads and route them to the selected ad account. */
export async function connectLeadDeliveryAction(pageId: string) {
  try {
    const data = await connectApi.connectLeadDelivery(pageId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to connect lead delivery:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to connect lead delivery.') };
  }
}

export async function metaAdsRegisterAction() {
  try {
    const data = await connectApi.metaAdsRegister();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to register Meta Ads:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to register Meta Ads.') };
  }
}

export async function metaAdsDisconnectAction() {
  try {
    const data = await connectApi.metaAdsDisconnect();
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user-profile');
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user');

    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to disconnect Meta Ads:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to disconnect Meta Ads.') };
  }
}

export async function metaAdsDisconnectConnectionAction(tokenId: string) {
  try {
    const data = await connectApi.metaAdsDisconnectConnection(tokenId);
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user-profile');
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user');

    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to disconnect specific Meta connection:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to disconnect Meta connection.') };
  }
}

export async function removeMetaAdsAccountAction(adAccountId: string) {
  try {
    const data = await connectApi.removeMetaAdsAccount(adAccountId);
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user-profile');
    // @ts-expect-error: Next.js revalidateTag
    revalidateTag('user');

    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to remove Meta ad account:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to remove ad account.') };
  }
}
