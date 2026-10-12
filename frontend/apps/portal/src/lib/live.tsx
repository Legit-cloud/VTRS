"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { getAccessToken, refreshSession } from "./api";

export type LiveState = "connecting" | "live" | "paused" | "off";

function socketUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) return `${configured.replace(/\/$/, "")}/ws/v1/dashboard`;
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}/ws/v1/dashboard`;
}

/**
 * Keeps one dashboard socket open for the election. The server sends ids only, so every
 * notice just invalidates the cached figures, coalesced to at most one refetch per 1.5 s.
 * The socket closes when its access token expires (4401): refresh and reconnect with backoff.
 */
export function useLiveUpdates(
  electionId: string | null,
  enabled = true,
): {
  state: LiveState;
  lastNoticeAt: number | null;
} {
  const queryClient = useQueryClient();
  const [state, setState] = useState<LiveState>("connecting");
  const [lastNoticeAt, setLastNoticeAt] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!electionId || !enabled) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;

    const invalidate = () => {
      if (timer.current) return;
      timer.current = setTimeout(() => {
        timer.current = null;
        void queryClient.invalidateQueries({ queryKey: ["dash"] });
        void queryClient.invalidateQueries({ queryKey: ["results"] });
        void queryClient.invalidateQueries({ queryKey: ["flags"] });
        void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
        setLastNoticeAt(Date.now());
      }, 1500);
    };

    const connect = async () => {
      if (closed) return;
      setState(attempt === 0 ? "connecting" : "paused");
      let token = getAccessToken();
      if (!token) token = await refreshSession();
      if (!token || closed) return setState("paused");
      try {
        socket = new WebSocket(socketUrl());
      } catch {
        return scheduleRetry();
      }
      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: "auth", token, election_id: electionId }));
      };
      socket.onmessage = (event) => {
        let message: { type?: string };
        try {
          message = JSON.parse(String(event.data)) as { type?: string };
        } catch {
          return;
        }
        if (message.type === "ready") {
          attempt = 0;
          setState("live");
          // Anything that changed while we were away.
          invalidate();
        } else if (message.type === "rollup.updated") {
          invalidate();
        }
      };
      socket.onclose = async (event) => {
        if (heartbeat) clearInterval(heartbeat);
        if (closed) return;
        setState("paused");
        // 4401: token expired or revoked. Refresh once; if that fails the session is over.
        if (event.code === 4401) await refreshSession();
        if (event.code === 4403 || event.code === 4404) return; // not retryable
        scheduleRetry();
      };
      heartbeat = setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
      }, 30_000);
    };

    const scheduleRetry = () => {
      attempt += 1;
      const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
      retry = setTimeout(connect, delay);
    };

    void connect();
    const onOnline = () => {
      if (!socket || socket.readyState > WebSocket.OPEN) void connect();
    };
    window.addEventListener("online", onOnline);

    return () => {
      closed = true;
      window.removeEventListener("online", onOnline);
      if (retry) clearTimeout(retry);
      if (heartbeat) clearInterval(heartbeat);
      if (timer.current) {
        clearTimeout(timer.current);
        timer.current = null;
      }
      socket?.close();
    };
  }, [electionId, enabled, queryClient]);

  return { state: !electionId || !enabled ? "off" : state, lastNoticeAt };
}
