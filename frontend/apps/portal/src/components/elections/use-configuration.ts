"use client";

import { useQuery } from "@tanstack/react-query";
import type { Contestant, ElectionParty } from "@vtrs/core";
import { useMemo } from "react";
import { ep } from "@/lib/api";

export interface ConstituencySetup {
  constituencyId: string;
  constituencyName: string;
  /** In the election's party order. */
  contestants: Contestant[];
  /** Why this constituency is not ready, in words. Empty when it is. */
  problems: string[];
  hasOwnContestant: boolean;
}

export interface Configuration {
  loading: boolean;
  error: unknown;
  /** Contesting parties in their fixed display order. */
  parties: ElectionParty[];
  constituencies: ConstituencySetup[];
  /** Mirrors the server's rules for marking an election ready or locking it. */
  blockers: string[];
  /** Worth fixing, but they do not stop anything. */
  advice: string[];
  ready: boolean;
  contestantCount: number;
}

/**
 * The contesting parties and contestants of one election, with the same completeness rules the
 * server applies when moving to Ready and Locked (`configuration_problems`), so the screen can
 * say what is missing before the button is pressed rather than after it fails.
 */
export function useConfiguration(electionId: string): Configuration {
  const parties = useQuery({
    queryKey: ["election-parties", electionId],
    queryFn: () => ep.elections.parties(electionId),
  });
  const contestants = useQuery({
    queryKey: ["contestants", electionId],
    queryFn: () => ep.elections.contestants(electionId),
  });

  return useMemo(() => {
    const ordered = [...(parties.data ?? [])].sort((a, b) => a.ballot_order - b.ballot_order);
    const contesting = new Set(ordered.map((p) => p.party_id));
    const own = ordered.find((p) => p.is_own);
    const order = Object.fromEntries(ordered.map((p) => [p.party_id, p.ballot_order]));

    const groups = new Map<string, ConstituencySetup>();
    for (const c of contestants.data ?? []) {
      let group = groups.get(c.constituency_id);
      if (!group) {
        group = {
          constituencyId: c.constituency_id,
          constituencyName: c.constituency_name,
          contestants: [],
          problems: [],
          hasOwnContestant: false,
        };
        groups.set(c.constituency_id, group);
      }
      group.contestants.push(c);
    }
    const constituencies = [...groups.values()].sort((a, b) =>
      a.constituencyName.localeCompare(b.constituencyName),
    );
    for (const group of constituencies) {
      group.contestants.sort((a, b) => (order[a.party_id] ?? 999) - (order[b.party_id] ?? 999));
      const n = group.contestants.length;
      if (n < 2) {
        group.problems.push(
          `${group.constituencyName} has one contestant. Add another party's contestant.`,
        );
      }
      const stray = group.contestants.filter((c) => !contesting.has(c.party_id));
      if (stray.length > 0) {
        group.problems.push(
          `${group.constituencyName}: ${stray.map((c) => c.name).join(", ")} ${
            stray.length === 1 ? "stands" : "stand"
          } for a party that is not contesting. Add the party or remove the contestant.`,
        );
      }
      group.hasOwnContestant = !!own && group.contestants.some((c) => c.party_id === own.party_id);
    }

    const blockers: string[] = [];
    if (ordered.length < 2) blockers.push("Choose at least two contesting parties.");
    if (constituencies.length === 0) blockers.push("Add the contestants for a constituency.");
    blockers.push(...constituencies.flatMap((g) => g.problems));

    const advice: string[] = [];
    if (ordered.length > 0 && !own) {
      advice.push(
        "Your own party is not among the contesting parties, so the War Room cannot show your margin.",
      );
    } else if (own) {
      for (const g of constituencies) {
        if (g.contestants.length >= 2 && !g.hasOwnContestant) {
          advice.push(`${g.constituencyName} has no ${own.abbreviation} contestant.`);
        }
      }
    }

    const loading = parties.isLoading || contestants.isLoading;
    return {
      loading,
      error: parties.error ?? contestants.error,
      parties: ordered,
      constituencies,
      blockers,
      advice,
      ready: !loading && blockers.length === 0,
      contestantCount: (contestants.data ?? []).length,
    };
  }, [parties.data, parties.isLoading, parties.error, contestants.data, contestants.isLoading, contestants.error]);
}
