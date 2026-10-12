import { NextResponse } from "next/server";
import { callBackend, clearRefreshCookie, forbidden, isSameOrigin } from "@/lib/server/backend";

export async function POST(request: Request) {
  if (!isSameOrigin(request)) return forbidden();
  const bearer = request.headers.get("authorization")?.replace(/^Bearer /i, "") ?? null;
  if (bearer) {
    // Best effort: the cookie is cleared even if the API is unreachable.
    await callBackend("/api/v1/auth/logout", { method: "POST", bearer }).catch(() => null);
  }
  return clearRefreshCookie(new NextResponse(null, { status: 204 }));
}
