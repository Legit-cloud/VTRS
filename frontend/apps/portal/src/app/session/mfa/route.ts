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

export async function POST(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  const { mfa_token, code } = (await request.json()) as { mfa_token?: string; code?: string };
  const upstream = await callBackend("/api/v1/auth/login/mfa", {
    method: "POST",
    body: { mfa_token, code },
  });
  if (!upstream.ok) return relayProblem(upstream);
  const pair = (await upstream.json()) as TokenPair;
  return withRefreshCookie(NextResponse.json(publicTokens(pair)), pair);
}
