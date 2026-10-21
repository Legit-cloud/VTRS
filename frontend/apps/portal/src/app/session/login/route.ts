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

interface LoginResult extends Partial<TokenPair> {
  mfa_required: boolean;
  mfa_token?: string;
  challenge_id?: string;
  destination_hint?: string;
}

export async function POST(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  const { identifier, password } = (await request.json()) as {
    identifier?: string;
    password?: string;
  };
  const upstream = await callBackend("/api/v1/auth/login", {
    method: "POST",
    body: { identifier, password },
  });
  if (!upstream.ok) return relayProblem(upstream);
  const result = (await upstream.json()) as LoginResult;
  if (result.mfa_required || !result.access_token) {
    return NextResponse.json({
      mfa_required: true,
      mfa_token: result.mfa_token,
      challenge_id: result.challenge_id,
      destination_hint: result.destination_hint,
    });
  }
  const pair = result as TokenPair;
  return withRefreshCookie(NextResponse.json({ mfa_required: false, ...publicTokens(pair) }), pair);
}
