"use client";

import { useQuery } from "@tanstack/react-query";
import { cursorFrom, type Lga, type Ward } from "@vtrs/core";
import { useMemo } from "react";
import { ep } from "./api";
import { useElection } from "./election";
import { stateName } from "./states";

export interface GeoNames {
  lgas: Map<string, Lga>;
  wards: Map<string, Ward>;
  /** Polling units are too many to preload; their codes come from the records that use them. */
  describe: (type: string, ids: string[]) => string;
}

async function allPages<T>(
  fetchPage: (cursor: string | null) => Promise<{ results: T[]; next: string | null }>,
): Promise<T[]> {
  const out: T[] = [];
  let cursor: string | null = null;
  do {
    const page: { results: T[]; next: string | null } = await fetchPage(cursor);
    out.push(...page.results);
    cursor = cursorFrom(page.next);
  } while (cursor);
  return out;
}

/** Every LGA and ward the caller may see, for turning scope ids into words. */
export function useGeoNames(enabled = true) {
  return useQuery({
    queryKey: ["geo", "names"],
    enabled,
    staleTime: 10 * 60_000,
    queryFn: async (): Promise<GeoNames> => {
      const [lgas, wards] = await Promise.all([
        allPages((cursor) => ep.geography.lgas({ limit: 200, cursor })),
        allPages((cursor) => ep.geography.wards({ limit: 200, cursor })),
      ]);
      const lgaMap = new Map(lgas.map((l) => [l.id, l]));
      const withSuffix = (name: string) => (/\bLGA$/i.test(name) ? name : `${name} LGA`);
      const wardMap = new Map(wards.map((w) => [w.id, w]));
      const describe = (type: string, ids: string[]) => {
        if (type === "ORG") return "Whole state";
        if (type === "LGA") {
          const names = ids.map((id) => lgaMap.get(id)?.name).filter(Boolean);
          return names.length ? names.map((n) => withSuffix(n!)).join(", ") : "LGA";
        }
        if (type === "WARD") {
          const named = ids.map((id) => wardMap.get(id)).filter((w): w is Ward => !!w);
          if (named.length === 0) return "Ward";
          const lga = lgaMap.get(named[0]!.lga_id)?.name;
          return `${lga ? `${withSuffix(lga)} · ` : ""}${named.map((w) => w.name).join(", ")}${
            named.length === 1 ? " only" : ""
          }`;
        }
        return `${ids.length} polling ${ids.length === 1 ? "unit" : "units"}`;
      };
      return { lgas: lgaMap, wards: wardMap, describe };
    },
  });
}

/**
 * LGAs for pickers, sorted by name. The master data holds every state that has been imported,
 * so when an election is selected only its own state's LGAs are offered.
 */
export function useElectionLgas(): {
  lgas: Lga[];
  loading: boolean;
  stateCode: string | undefined;
} {
  const names = useGeoNames();
  const { election } = useElection();
  return useMemo(() => {
    const all = [...(names.data?.lgas.values() ?? [])];
    const mine = election ? all.filter((l) => l.state_id === election.state_id) : all;
    return {
      lgas: mine.sort((a, b) => a.name.localeCompare(b.name)),
      loading: names.isLoading,
      stateCode: mine[0]?.state_code,
    };
  }, [names.data, names.isLoading, election]);
}

export interface StateOption {
  id: string;
  code: string;
  name: string;
  lgas: number;
}

/** The states that have master data loaded: the only ones an election can be held in. */
export function useStates(): { states: StateOption[]; loading: boolean } {
  const names = useGeoNames();
  return useMemo(() => {
    const byId = new Map<string, StateOption>();
    for (const lga of names.data?.lgas.values() ?? []) {
      const existing = byId.get(lga.state_id);
      if (existing) existing.lgas += 1;
      else
        byId.set(lga.state_id, {
          id: lga.state_id,
          code: lga.state_code,
          name: stateName(lga.state_code),
          lgas: 1,
        });
    }
    return {
      states: [...byId.values()].sort((a, b) => a.name.localeCompare(b.name)),
      loading: names.isLoading,
    };
  }, [names.data, names.isLoading]);
}
