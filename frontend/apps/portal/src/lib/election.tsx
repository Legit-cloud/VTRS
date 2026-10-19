"use client";

import { useQuery } from "@tanstack/react-query";
import type { Election } from "@vtrs/core";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { ep } from "./api";
import { useAuth } from "./auth";

const STORAGE_KEY = "vtrs.election";

interface ElectionState {
  elections: Election[];
  election: Election | null;
  select: (id: string) => void;
  loading: boolean;
  error: unknown;
  refetch: () => void;
}

const ElectionContext = createContext<ElectionState | null>(null);

// Prefer a running election, then the next to run, then whatever exists.
const ORDER = ["LIVE", "LOCKED", "CONFIGURED", "DRAFT", "CLOSED", "RECONCILED"];
const rank = (e: Election) => {
  const i = ORDER.indexOf(e.status ?? "DRAFT");
  return i === -1 ? ORDER.length : i;
};

function remembered(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function ElectionProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [selected, setSelected] = useState<string | null>(remembered);

  const query = useQuery({
    queryKey: ["elections"],
    queryFn: async () => (await ep.elections.list({ limit: 100 })).results,
    enabled: status === "authenticated",
  });

  const elections = useMemo(
    () =>
      [...(query.data ?? [])].sort(
        (a, b) => rank(a) - rank(b) || b.election_date.localeCompare(a.election_date),
      ),
    [query.data],
  );

  const election = useMemo(
    () => elections.find((e) => e.id === selected) ?? elections[0] ?? null,
    [elections, selected],
  );

  const select = useCallback((id: string) => {
    setSelected(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // Private mode: the choice just will not outlive the tab.
    }
  }, []);

  const value = useMemo<ElectionState>(
    () => ({
      elections,
      election,
      select,
      loading: query.isLoading,
      error: query.error,
      refetch: () => void query.refetch(),
    }),
    [elections, election, select, query],
  );

  return <ElectionContext.Provider value={value}>{children}</ElectionContext.Provider>;
}

export function useElection(): ElectionState {
  const value = useContext(ElectionContext);
  if (!value) throw new Error("useElection must be used inside ElectionProvider");
  return value;
}
