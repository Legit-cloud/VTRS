"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import type { Candidate, Contest } from "@vtrs/core";
import { useMemo } from "react";
import { ep } from "@/lib/api";

export interface ContestSetup {
  contest: Contest;
  candidates: Candidate[];
  /** Why this contest is not ready, in words. Empty when it is. */
  problems: string[];
  hasOwnCandidate: boolean;
}

export interface Configuration {
  loading: boolean;
  contests: ContestSetup[];
  /** Mirrors the server's rules for marking an election ready or locking it. */
  blockers: string[];
  /** Worth fixing, but they do not stop anything. */
  advice: string[];
  ready: boolean;
  candidateCount: number;
}

/**
 * Contests and their candidates for one election, with the same completeness rules the server
 * applies when moving to Ready and Locked, so the screen can say what is missing before the
 * button is pressed rather than after it fails.
 */
export function useConfiguration(electionId: string): Configuration {
  const contests = useQuery({
    queryKey: ["contests", electionId],
    queryFn: async (): Promise<Contest[]> => {
      const data = await ep.elections.contests(electionId);
      return Array.isArray(data) ? data : data.results;
    },
  });
  const candidates = useQueries({
    queries: (contests.data ?? []).map((c) => ({
      queryKey: ["candidates", c.id],
      queryFn: async (): Promise<Candidate[]> => {
        const data = await ep.contests.candidates(c.id);
        return Array.isArray(data) ? data : data.results;
      },
    })),
  });

  return useMemo(() => {
    const list = contests.data ?? [];
    const loading = contests.isLoading || candidates.some((q) => q.isLoading);
    const setups: ContestSetup[] = list.map((contest, i) => {
      const people = candidates[i]?.data ?? [];
      const problems: string[] = [];
      if (people.length < 2) {
        problems.push(
          people.length === 0
            ? `${contest.title} has no candidates yet. Add at least two.`
            : `${contest.title} has one candidate. Add at least one more.`,
        );
      }
      if (people.filter((p) => p.is_own_party).length > 1) {
        problems.push(`${contest.title} marks more than one candidate as yours. Keep one.`);
      }
      return {
        contest,
        candidates: people,
        problems,
        hasOwnCandidate: people.some((p) => p.is_own_party),
      };
    });
    const blockers = list.length === 0 ? ["Add the contest you are tracking."] : [];
    blockers.push(...setups.flatMap((s) => s.problems));
    const advice = setups
      .filter((s) => s.candidates.length >= 2 && !s.hasOwnCandidate)
      .map(
        (s) =>
          `Mark which ${s.contest.title} candidate is yours, so the dashboard can show how you are doing.`,
      );
    return {
      loading,
      contests: setups,
      blockers,
      advice,
      ready: !loading && blockers.length === 0,
      candidateCount: setups.reduce((n, s) => n + s.candidates.length, 0),
    };
  }, [contests.data, contests.isLoading, candidates]);
}
