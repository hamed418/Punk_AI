// Using a dynamic require to prevent Webpack from bundling next/headers in the client
const getNextHeaders = async () => {
  if (typeof window === 'undefined') {
    const m = 'next/headers';
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { headers } = require(m);
    return await headers();
  }
  return null;
};

export async function getClientIp(): Promise<string | null> {
  const headersList = await getNextHeaders();
  if (!headersList) return null;
  const forwardedFor = headersList.get('x-forwarded-for');
  if (forwardedFor) {
    return forwardedFor.split(',')[0];
  }
  return headersList.get('x-real-ip');
}

export async function getForwardableHeaders(): Promise<Record<string, string>> {
  const headersList = await getNextHeaders();
  const forwardable: Record<string, string> = {};
  if (!headersList) return forwardable;
  
  const ip = await getClientIp();
  if (ip) {
    forwardable['x-forwarded-for'] = ip;
  }

  const userAgent = headersList.get('user-agent');
  if (userAgent) {
    forwardable['user-agent'] = userAgent;
  }

  return forwardable;
}
