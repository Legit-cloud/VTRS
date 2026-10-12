import { ApiClient, createEndpoints } from "@vtrs/core";

/**
 * The access token lives in this module's memory only. It is never written to storage; the
 * refresh token is an httpOnly cookie that page scripts cannot read.
 */
let accessToken: string | null = null;
let accessExpiresAt = 0;
let onExpired: (() => void) | null = null;
const listeners = new Set<() => void>();

export function setAccessToken(token: string | null, expiresAt?: string): void {
  accessToken = token;
  accessExpiresAt = expiresAt ? new Date(expiresAt).getTime() : 0;
  listeners.forEach((l) => l());
}
export const getAccessToken = (): string | null => accessToken;
export const getAccessExpiry = (): number => accessExpiresAt;
export const subscribeToken = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onExpired = handler;
}

interface SessionTokens {
  access_token: string;
  access_expires_at: string;
}

/** Ask the server to trade the refresh cookie for a new access token. */
export async function refreshSession(): Promise<string | null> {
  try {
    const response = await fetch("/session/refresh", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!response.ok) return null;
    const tokens = (await response.json()) as SessionTokens;
    setAccessToken(tokens.access_token, tokens.access_expires_at);
    return tokens.access_token;
  } catch {
    return null;
  }
}

export const api = new ApiClient({
  baseUrl: "",
  getAccessToken: () => accessToken,
  refreshAccessToken: refreshSession,
  onSessionExpired: () => {
    setAccessToken(null);
    onExpired?.();
  },
});

export const ep = createEndpoints(api);
