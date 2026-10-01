"use server";

import { mapApi } from '../lib/api/map';
import { extractErrorMessage } from '../lib/errorUtils';

export async function getMapSuggestionsAction(inputText: string, sessionId?: string) {
  try {
    const data = await mapApi.getSuggestions(inputText, sessionId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get map suggestions:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch map suggestions.') };
  }
}

export async function getNearbyPlacesAction(lat: number, lng: number, radius?: number, sessionId?: string) {
  try {
    const data = await mapApi.getNearbyPlaces(lat, lng, radius, sessionId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to get nearby places:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to fetch nearby places.') };
  }
}

export async function searchMapAction(query: string, sessionId?: string) {
  try {
    const data = await mapApi.searchMap(query, sessionId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Failed to search map:', error);
    return { success: false, error: extractErrorMessage(error, 'Failed to search map.') };
  }
}
