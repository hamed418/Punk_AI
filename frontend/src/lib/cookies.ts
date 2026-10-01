// Using a dynamic require to prevent Webpack from bundling next/headers in the client
const getNextCookies = async () => {
  if (typeof window === 'undefined') {
    const m = 'next/headers';
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { cookies } = require(m);
    return await cookies();
  }
  return null;
};

const TOKEN_KEY = 'auth_token';
const REFRESH_TOKEN_KEY = 'refresh_token';


export async function getAuthToken(): Promise<string | undefined> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return undefined;
  const token = cookieStore.get(TOKEN_KEY)?.value;
  return token;
}



export async function setAuthToken(token: string, rememberMe: boolean = false): Promise<void> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return;
  const rootDomain = process.env.NEXT_PUBLIC_ROOT_DOMAIN;
  cookieStore.set({
    name: TOKEN_KEY,
    value: token,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    ...(rememberMe ? { maxAge: 30 * 24 * 60 * 60 } : {}),
    ...(rootDomain ? { domain: rootDomain } : {}),
  });
}


export async function removeAuthToken(): Promise<void> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return;
  const rootDomain = process.env.NEXT_PUBLIC_ROOT_DOMAIN;
  cookieStore.delete({
    name: TOKEN_KEY,
    path: '/',
    ...(rootDomain ? { domain: rootDomain } : {}),
  });
}


export async function getRefreshToken(): Promise<string | undefined> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return undefined;
  const token = cookieStore.get(REFRESH_TOKEN_KEY)?.value;
  return token;
}


export async function setRefreshToken(token: string, rememberMe: boolean = false): Promise<void> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return;
  const rootDomain = process.env.NEXT_PUBLIC_ROOT_DOMAIN;
  cookieStore.set({
    name: REFRESH_TOKEN_KEY,
    value: token,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    ...(rememberMe ? { maxAge: 30 * 24 * 60 * 60 } : {}),
    ...(rootDomain ? { domain: rootDomain } : {}),
  });
}


export async function removeRefreshToken(): Promise<void> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return;
  const rootDomain = process.env.NEXT_PUBLIC_ROOT_DOMAIN;
  cookieStore.delete({
    name: REFRESH_TOKEN_KEY,
    path: '/',
    ...(rootDomain ? { domain: rootDomain } : {}),
  });
}

const IMPERSONATING_KEY = 'is_impersonating';
const ADMIN_URL_KEY = 'impersonator_admin_url';

export async function getIsImpersonating(): Promise<boolean> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return false;
  return cookieStore.get(IMPERSONATING_KEY)?.value === 'true';
}

export async function setIsImpersonating(adminUrl?: string): Promise<void> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return;
  cookieStore.set({
    name: IMPERSONATING_KEY,
    value: 'true',
    httpOnly: false,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
  });
  if (adminUrl) {
    cookieStore.set({
      name: ADMIN_URL_KEY,
      value: adminUrl,
      httpOnly: false,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
    });
  }
}

export async function clearImpersonation(): Promise<void> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return;
  cookieStore.delete(IMPERSONATING_KEY);
  cookieStore.delete(ADMIN_URL_KEY);
}

export async function getAdminPanelUrl(): Promise<string | undefined> {
  const cookieStore = await getNextCookies();
  if (!cookieStore) return undefined;
  return cookieStore.get(ADMIN_URL_KEY)?.value;
}

