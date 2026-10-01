"use server";

import { campaignsApi } from '../lib/api/campaigns';
import { extractErrorMessage } from '../lib/errorUtils';

export async function getCampaignsAction() {
  try {
    const data = await campaignsApi.getCampaigns();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get campaigns:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch campaigns.') };
  }
}

export async function getCampaignAction(id: string) {
  try {
    const data = await campaignsApi.getCampaign(id);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get campaign:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch campaign.') };
  }
}

export async function getCampaignReviewAction(id: string) {
  try {
    const data = await campaignsApi.getCampaignReview(id);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get campaign review:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch ad review.') };
  }
}

export async function syncMetaCampaignsAction() {
  try {
    const data = await campaignsApi.syncMetaCampaigns();
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to sync meta campaigns:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to sync meta campaigns.') };
  }
}
