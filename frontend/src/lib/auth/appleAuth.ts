export interface AppleAuthResponse {
  id_token: string;
  code?: string;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  email?: string;
  user?: {
    name?: {
      firstName?: string;
      lastName?: string;
    };
    email?: string;
  };
}

declare global {
  interface Window {
    AppleID?: {
      auth: {
        init: (config: {
          clientId: string;
          scope: string;
          redirectURI: string;
          usePopup: boolean;
        }) => void;
        signIn: () => Promise<{
          authorization: {
            id_token: string;
            code?: string;
            state?: string;
          };
          user?: {
            name?: {
              firstName?: string;
              lastName?: string;
            };
            email?: string;
          };
        }>;
      };
    };
  }
}

let scriptPromise: Promise<void> | null = null;

export function loadAppleScript(): Promise<void> {
  if (typeof window === 'undefined') return Promise.resolve();
  if (window.AppleID) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[src*="appleid.auth.js"]');
    if (existing) {
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', (err) => reject(err));
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://appleid.cdn.apple.com/js/api/appleid/auth.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Apple Sign-In SDK'));
    document.head.appendChild(script);
  });

  return scriptPromise;
}

export async function signInWithApple(): Promise<AppleAuthResponse> {
  if (typeof window === 'undefined') {
    throw new Error('Apple Sign-In is only available in the browser.');
  }

  await loadAppleScript();

  if (!window.AppleID) {
    throw new Error('Apple Sign-In SDK could not be initialized.');
  }

  const clientId =
    process.env.NEXT_PUBLIC_APPLE_CLIENT_ID || 'ai.punk.web';
  const redirectURI = window.location.origin;

  try {
    window.AppleID.auth.init({
      clientId,
      scope: 'name email',
      redirectURI,
      usePopup: true,
    });
  } catch (initErr) {
    console.warn('AppleID init warning:', initErr);
  }

  const response = await window.AppleID.auth.signIn();

  if (!response?.authorization?.id_token) {
    throw new Error('No identity token returned by Apple.');
  }

  const firstName = response.user?.name?.firstName;
  const lastName = response.user?.name?.lastName;
  const fullName =
    firstName || lastName ? `${firstName || ''} ${lastName || ''}`.trim() : undefined;

  return {
    id_token: response.authorization.id_token,
    code: response.authorization.code,
    user: response.user,
    first_name: firstName,
    last_name: lastName,
    full_name: fullName,
    email: response.user?.email,
  };
}
