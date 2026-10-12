import { NextResponse } from "next/server";
import {
  callBackend,
  forbidden,
  isSameOrigin,
  publicTokens,
  relayProblem,
  withRefreshCookie,
  type TokenPair,
} from "@/lib/server/backend";

/** Finish an invitation on the web: the new session's refresh token goes into the cookie. */
export async function POST(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  const { token, challenge_id, code, password } = (await request.json()) as {
    token?: string;
    challenge_id?: string;
    code?: string;
    password?: string;
  };
  const upstream = await callBackend("/api/v1/auth/invitations/complete", {
    method: "POST",
    body: { token, challenge_id, code, password },
  });
  if (!upstream.ok) return relayProblem(upstream);
  const pair = (await upstream.json()) as TokenPair;
  return withRefreshCookie(NextResponse.json(publicTokens(pair)), pair);
}
