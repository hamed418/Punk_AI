import { APIError, NetworkError } from './errors';

/**
 * Parses and extracts a clean, human-readable error message from any error instance or API response.
 * Handles FastAPI validation arrays, NestJS error objects, status-based defaults, and network failures.
 */
export function extractErrorMessage(error: unknown, fallbackMessage = 'An unexpected error occurred. Please try again.'): string {
  if (!error) return fallbackMessage;

  if (typeof error === 'string') {
    return formatGenericMessage(error, fallbackMessage);
  }

  // Handle Network Errors / Abort Errors
  if (error instanceof NetworkError) {
    if (error.message && error.message !== 'Failed to fetch' && error.message !== 'NetworkError' && error.message !== 'Request failed after retries' && !error.message.includes('fetch')) {
      return formatGenericMessage(error.message, fallbackMessage);
    }
    return 'Unable to reach the server. Please check your network connection and try again.';
  }

  if (error instanceof Error && (error.name === 'AbortError' || error.message.includes('fetch'))) {
    return 'Unable to reach the server. Please check your network connection and try again.';
  }

  // If error is an APIError / ValidationError / UnauthorizedError
  if (error instanceof APIError) {
    // 1. First, check attached data object/detail if present from API response
    if (error.data) {
      const extracted = parseErrorPayload(error.data);
      if (extracted && !isGenericStatusText(extracted)) {
        return extracted;
      }
    }

    // 2. Next, check if error.message has a specific, informative message
    if (error.message && !isGenericStatusText(error.message)) {
      return formatGenericMessage(error.message, fallbackMessage);
    }

    // 3. Fallback based on HTTP status code if no specific detail was provided by backend
    if (error.status === 401) {
      return 'Invalid email or password. Please check your credentials and try again.';
    }
    if (error.status === 403) {
      return 'Access denied. You do not have permission to perform this action.';
    }
    if (error.status === 404) {
      return 'Account or requested resource was not found.';
    }
    if (error.status === 429) {
      return 'Too many attempts. Please wait a moment before trying again.';
    }
    if (error.status >= 500) {
      return 'Server error encountered. Please try again later.';
    }
  }

  // If error is standard JS Error
  if (error instanceof Error) {
    if (error.message && !isGenericStatusText(error.message)) {
      return formatGenericMessage(error.message, fallbackMessage);
    }
  }

  // Handle raw object payload `{ detail, message, error }` or `{ data: ... }`
  if (typeof error === 'object' && error !== null) {
    const obj = error as Record<string, unknown>;
    if (obj.data) {
      const extractedFromData = parseErrorPayload(obj.data);
      if (extractedFromData && !isGenericStatusText(extractedFromData)) {
        return extractedFromData;
      }
    }
    const extracted = parseErrorPayload(error);
    if (extracted && !isGenericStatusText(extracted)) {
      return extracted;
    }
  }

  return fallbackMessage;
}

/**
 * Checks if a string is a generic HTTP status label or placeholder rather than an informative message.
 */
function isGenericStatusText(text: string): boolean {
  if (!text) return true;
  const lower = text.trim().toLowerCase();
  return (
    lower === 'unauthorized' ||
    lower === 'unauthorizederror' ||
    lower === 'forbidden' ||
    lower === 'forbiddenerror' ||
    lower === 'not found' ||
    lower === 'internal server error' ||
    lower === 'bad request' ||
    lower === 'an error occurred' ||
    lower === '[object object]' ||
    lower === 'error' ||
    lower === 'network error' ||
    lower === 'failed to fetch' ||
    lower === 'null' ||
    lower === 'undefined'
  );
}

/**
 * Internal helper to parse structured API response bodies (FastAPI, NestJS, etc.)
 */
function parseErrorPayload(payload: unknown): string | null {
  if (!payload) return null;

  // Handle case where payload is a JSON stringified array or object
  if (typeof payload === 'string') {
    const trimmed = payload.trim();
    if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
      try {
        const parsed = JSON.parse(trimmed);
        return parseErrorPayload(parsed);
      } catch {
        // Not valid JSON string, fall through
      }
    }
  }

  // Handle direct array payload (e.g. Zod validation error array passed directly)
  if (Array.isArray(payload)) {
    const messages = payload
      .map(formatValidationErrorItem)
      .filter((msg): msg is string => Boolean(msg && typeof msg === 'string'));

    if (messages.length > 0) {
      return messages.join('. ');
    }
  }

  if (typeof payload !== 'object' || payload === null) return null;

  const obj = payload as Record<string, unknown>;
  const detail = obj.detail || obj.message || obj.error;

  // Case 1: string detail (could also be JSON stringified array/object)
  if (typeof detail === 'string' && detail.trim()) {
    const cleanDetail = detail.trim();
    if (cleanDetail === '[object Object]') return null;
    if (cleanDetail.startsWith('[') || cleanDetail.startsWith('{')) {
      try {
        const parsedDetail = JSON.parse(cleanDetail);
        const parsedResult = parseErrorPayload(parsedDetail);
        if (parsedResult) return parsedResult;
      } catch {
        // Not valid JSON string
      }
    }
    return formatGenericMessage(cleanDetail, '');
  }

  // Case 2: array detail (FastAPI/Zod validation errors)
  if (Array.isArray(detail)) {
    const messages = detail
      .map(formatValidationErrorItem)
      .filter((msg): msg is string => Boolean(msg && typeof msg === 'string'));

    if (messages.length > 0) {
      return messages.join('. ');
    }
  }

  // Case 3: nested object { msg: "..." }
  if (typeof detail === 'object' && detail !== null) {
    const detailObj = detail as Record<string, unknown>;
    if (typeof detailObj.msg === 'string') return formatGenericMessage(detailObj.msg, '');
    if (typeof detailObj.message === 'string') return formatGenericMessage(detailObj.message, '');
  }

  return null;
}

/**
 * Formats an individual validation error item from Zod or FastAPI into a user-friendly field message.
 */
function formatValidationErrorItem(item: unknown): string | null {
  if (typeof item === 'string') return formatGenericMessage(item, '');
  if (typeof item === 'object' && item !== null) {
    const itemObj = item as Record<string, unknown>;

    // Extract path/field name if available
    let fieldName = '';
    if (Array.isArray(itemObj.path) && itemObj.path.length > 0) {
      const rawField = String(itemObj.path[itemObj.path.length - 1]);
      fieldName = capitalizeField(rawField);
    } else if (Array.isArray(itemObj.loc) && itemObj.loc.length > 0) {
      const rawField = String(itemObj.loc[itemObj.loc.length - 1]);
      if (rawField !== 'body' && rawField !== 'query') {
        fieldName = capitalizeField(rawField);
      }
    }

    const rawMsg = (itemObj.message || itemObj.msg || itemObj.detail) as string | undefined;

    if (rawMsg) {
      let cleanMsg = rawMsg;
      // Convert technical Zod messages like "Too small: expected string to have >=2 characters"
      if (cleanMsg.includes('expected string to have >=')) {
        const match = cleanMsg.match(/>=\s*(\d+)/);
        const minLen = match ? match[1] : '';
        cleanMsg = `must be at least ${minLen} characters long`;
      }

      if (fieldName) {
        // Avoid duplicating field name if already in cleanMsg
        if (cleanMsg.toLowerCase().startsWith(fieldName.toLowerCase())) {
          return cleanMsg;
        }
        return `${fieldName} ${cleanMsg}`;
      }
      return cleanMsg;
    }
  }
  return null;
}

function capitalizeField(field: string): string {
  if (field === 'name' || field === 'full_name' || field === 'fullName') return 'Name';
  if (field === 'email') return 'Email address';
  if (field === 'password') return 'Password';
  return field.charAt(0).toUpperCase() + field.slice(1).replace(/_/g, ' ');
}

/**
 * Translates generic system messages like 'Unauthorized' or 'Failed to fetch' into friendly text.
 */
function formatGenericMessage(message: string, fallback: string): string {
  const cleanMsg = message.trim();

  // If the message is a raw JSON stringified array/object, try parsing it first
  if (cleanMsg.startsWith('[') || cleanMsg.startsWith('{')) {
    try {
      const parsed = JSON.parse(cleanMsg);
      const parsedRes = parseErrorPayload(parsed);
      if (parsedRes) return parsedRes;
    } catch {
      // ignore
    }
  }

  if (cleanMsg === 'Unauthorized' || cleanMsg === 'UnauthorizedError') {
    return 'Authentication required. Please sign in to continue.';
  }
  if (cleanMsg === 'Validation Error' || cleanMsg === 'ValidationError') {
    return 'Invalid data provided. Please check your entries and try again.';
  }
  if (cleanMsg === 'Failed to fetch' || cleanMsg === 'NetworkError' || cleanMsg === 'fetch failed') {
    return 'Unable to reach the server. Please verify your connection or try again shortly.';
  }
  if (cleanMsg === 'Request Timeout') {
    return 'The request timed out. Please try again.';
  }
  if (cleanMsg === '[object Object]') {
    return fallback || 'An unexpected issue occurred. Please try again.';
  }

  return cleanMsg;
}
