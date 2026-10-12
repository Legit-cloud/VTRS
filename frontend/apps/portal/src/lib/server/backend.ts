import { NextResponse } from "next/server";

/** Server-side only. The browser reaches the API through this origin's /api/v1 proxy. */
export const API_ORIGIN = process.env.VTRS_API_URL ?? "http://localhost:8000";

export const REFRESH_COOKIE = "vtrs_rt";

export interface TokenPair {
  token_type: string;
  access_token: string;
  access_expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
  session_id: string;
}

export async function callBackend(
  path: string,
  init: { method?: string; body?: unknown; bearer?: string | null; requestId?: string | null } = {},
): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (init.bearer) headers.Authorization = `Bearer ${init.bearer}`;
  if (init.requestId) headers["X-Request-ID"] = init.requestId;
  // Writes need a key; one per call is right here because the browser does not retry these.
  if ((init.method ?? "GET") !== "GET") headers["Idempotency-Key"] = crypto.randomUUID();
  return fetch(`${API_ORIGIN}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
}

/** Cross-site form posts cannot set JSON bodies, but be explicit: refuse foreign origins. */
export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true; // same-origin fetches from some clients omit it
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function forbidden(): NextResponse {
  return NextResponse.json(
    { code: "forbidden", detail: "Cross-origin request refused.", status: 403 },
    { status: 403 },
  );
}

export function withRefreshCookie(response: NextResponse, pair: TokenPair): NextResponse {
  response.cookies.set({
    name: REFRESH_COOKIE,
    value: pair.refresh_token,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/session",
    expires: new Date(pair.refresh_expires_at),
  });
  return response;
}

export function clearRefreshCookie(response: NextResponse): NextResponse {
  response.cookies.set({
    name: REFRESH_COOKIE,
    value: "",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/session",
    maxAge: 0,
  });
  return response;
}

/** What the browser is allowed to see of a token pair: never the refresh token. */
export function publicTokens(pair: TokenPair) {
  return {
    access_token: pair.access_token,
    access_expires_at: pair.access_expires_at,
    session_id: pair.session_id,
  };
}

/** Pass a backend problem+json through unchanged. */
export async function relayProblem(upstream: Response): Promise<NextResponse> {
  const text = await upstream.text();
  return new NextResponse(text || null, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/problem+json",
      ...(upstream.headers.get("retry-after")
        ? { "Retry-After": upstream.headers.get("retry-after")! }
        : {}),
    },
  });
}
