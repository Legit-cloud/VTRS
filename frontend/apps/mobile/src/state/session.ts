import { ApiClient, ApiError, createEndpoints } from "@vtrs/core";
import { API_URL } from "../platform/config";
import { secure } from "../platform/secure";

/**
 * The session is app-wide and read from non-React code (the API client's token hooks), so it
 * lives here as plain data rather than in component state. The access token is memory only;
 * the refresh token and the device id are kept in the keychain.
 */
export const session = {
  access: null as string | null,
  refresh: null as string | null,
  device: null as string | null,
  online: true,
  /** Set by the provider: the server refused our refresh token, so the session is over. */
  onSignedOut: (() => undefined) as () => void,
};

/** Calls that need no token: sign-in, invitations, refresh. */
export const anonymous = createEndpoints(
  new ApiClient({ baseUrl: API_URL, getAccessToken: () => null, timeoutMs: 20_000 }),
);

const client = new ApiClient({
  baseUrl: API_URL,
  getAccessToken: () => session.access,
  timeoutMs: 20_000,
  refreshAccessToken: async () => {
    if (!session.refresh) return null;
    try {
      const pair = await anonymous.auth.refresh({
        refresh_token: session.refresh,
        device_id: session.device,
      });
      session.access = pair.access_token;
      session.refresh = pair.refresh_token;
      await secure.set("refresh", pair.refresh_token);
      return pair.access_token;
    } catch (error) {
      // A refused refresh token means the session is over; a dead network does not.
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        session.onSignedOut();
      }
      return null;
    }
  },
});

export const ep = createEndpoints(client);
