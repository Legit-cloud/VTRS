"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ApiError, type Me } from "@vtrs/core";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  ep,
  getAccessToken,
  refreshSession,
  setAccessToken,
  setSessionExpiredHandler,
} from "./api";

type Status = "loading" | "anonymous" | "authenticated";

export type LoginOutcome =
  { kind: "signed-in" } | { kind: "mfa"; mfaToken: string; destinationHint: string };

interface AuthState {
  status: Status;
  me: Me | null;
  can: (permission: string) => boolean;
  login: (identifier: string, password: string) => Promise<LoginOutcome>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  reloadMe: () => Promise<void>;
  /** Swap in the token a step-up returned. */
  adoptToken: (token: string, expiresAt: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export const PUBLIC_PATHS = ["/login", "/forgot-password", "/accept-invite"];

async function postSession<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError({ status: 0, code: "network_error", detail: "Could not reach the server." });
  }
  const text = await response.text();
  const json = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  if (!response.ok) {
    throw new ApiError({
      status: response.status,
      code: String(json.code ?? `http_${response.status}`),
      detail: String(json.detail ?? "Request failed."),
      errors: json.errors,
      requestId: (json.request_id as string | undefined) ?? null,
    });
  }
  return json as T;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const booted = useRef(false);

  const loadMe = useCallback(async () => {
    const profile = await ep.me.get();
    setMe(profile);
    setStatus("authenticated");
  }, []);

  const endSession = useCallback(() => {
    setAccessToken(null);
    setMe(null);
    setStatus("anonymous");
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      endSession();
      router.replace("/login?expired=1");
    });
    return () => setSessionExpiredHandler(null);
  }, [endSession, router]);

  // Pick up an existing session from the refresh cookie once per page load.
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    (async () => {
      const token = await refreshSession();
      if (!token) return setStatus("anonymous");
      try {
        await loadMe();
      } catch {
        setStatus("anonymous");
      }
    })();
  }, [loadMe]);

  // Anonymous visitors only see the public pages; signed-in users skip the login page.
  useEffect(() => {
    if (status === "loading") return;
    const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
    if (status === "anonymous" && !isPublic) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
    // Signed-in visitors to /login are moved on by the login page itself, which knows where
    // they were going.
  }, [status, pathname, router]);

  const value = useMemo<AuthState>(() => {
    const granted = new Set(me?.permissions ?? []);
    return {
      status,
      me,
      can: (permission) => granted.has(permission),
      async login(identifier, password) {
        const result = await postSession<{
          mfa_required: boolean;
          mfa_token?: string;
          destination_hint?: string;
          access_token?: string;
          access_expires_at?: string;
        }>("/session/login", { identifier, password });
        if (result.mfa_required && result.mfa_token) {
          return {
            kind: "mfa",
            mfaToken: result.mfa_token,
            destinationHint: result.destination_hint ?? "your email",
          };
        }
        setAccessToken(result.access_token ?? null, result.access_expires_at);
        await loadMe();
        return { kind: "signed-in" };
      },
      async verifyMfa(mfaToken, code) {
        const tokens = await postSession<{ access_token: string; access_expires_at: string }>(
          "/session/mfa",
          { mfa_token: mfaToken, code },
        );
        setAccessToken(tokens.access_token, tokens.access_expires_at);
        await loadMe();
      },
      async logout() {
        try {
          await fetch("/session/logout", {
            method: "POST",
            credentials: "same-origin",
            headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
          });
        } finally {
          endSession();
          router.replace("/login");
        }
      },
      reloadMe: loadMe,
      adoptToken(token, expiresAt) {
        setAccessToken(token, expiresAt);
      },
    };
  }, [status, me, loadMe, endSession, router]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

// Re-exported so pages do not need a second import for the typed client.
export { api, ep };
