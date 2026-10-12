import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  REFRESH_COOKIE,
  callBackend,
  clearRefreshCookie,
  forbidden,
  isSameOrigin,
  publicTokens,
  withRefreshCookie,
  type TokenPair,
} from "@/lib/server/backend";

/** Trade the httpOnly refresh cookie for a fresh access token. Rotates the cookie. */
export async function POST(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    return NextResponse.json({ code: "no_session", detail: "Not signed in." }, { status: 401 });
  }
  const upstream = await callBackend("/api/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refresh },
  });
  if (!upstream.ok) {
    const body = await upstream.text();
    const response = new NextResponse(body, {
      status: upstream.status === 429 ? 429 : 401,
      headers: { "Content-Type": "application/json" },
    });
    // A refused token (expired, reused, revoked) is useless; a throttled one is not.
    return upstream.status === 429 ? response : clearRefreshCookie(response);
  }
  const pair = (await upstream.json()) as TokenPair;
  return withRefreshCookie(NextResponse.json(publicTokens(pair)), pair);
}
