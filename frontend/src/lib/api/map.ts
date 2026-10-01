import { apiFetch } from '../fetcher';

// sessionId attributes the Google request to the chat session it came from
// (see backend app/modules/map/service.py::_count_api_call). Optional — omit
// it and the call is simply uncounted, same as before.
const sessionQS = (sessionId?: string) => (sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : '');

export const mapApi = {
  getSuggestions: (inputText: string, sessionId?: string) => {
    return apiFetch<unknown[]>(`/map/suggestions?input_text=${encodeURIComponent(inputText)}${sessionQS(sessionId)}`, {
      method: 'GET',
    });
  },

  getNearbyPlaces: (lat: number, lng: number, radius: number = 2000, sessionId?: string) => {
    return apiFetch<unknown>(`/map/nearby?lat=${lat}&lng=${lng}&radius=${radius}${sessionQS(sessionId)}`, {
      method: 'GET',
    });
  },

  searchMap: (query: string, sessionId?: string) => {
    return apiFetch<unknown>(`/map/search?q=${encodeURIComponent(query)}${sessionQS(sessionId)}`, {
      method: 'GET',
    });
  },
};
