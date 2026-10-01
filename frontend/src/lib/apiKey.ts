export function getApiKey(): string {
  const apiKey =
    process.env.NEXT_PUBLIC_API_KEY ||
    (typeof window === 'undefined' ? process.env.API_KEY : undefined);

  if (!apiKey) {
    const errorMsg =
      'NEXT_PUBLIC_API_KEY is not configured in the environment. Every request to the backend requires a valid X-API-Key header.';
    console.error(`[CONFIG ERROR] ${errorMsg}`);
    throw new Error(errorMsg);
  }

  return apiKey;
}
