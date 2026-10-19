import type { SheetField } from "./submission";

export type TotalsInput = Partial<Record<SheetField, number | null>>;

export interface Check {
  id: "votes_plus_rejected_vs_cast" | "cast_vs_accredited" | "cast_not_reconciled";
  /** A blocking check stops the send; the server refuses the same numbers. */
  blocking: boolean;
  ok: boolean;
  /** Numbers involved, for the sentence shown to the agent. */
  left: number;
  right: number;
}

/**
 * The same rules the server applies (`apps/results/domain/sheet.py` and the inline anomaly
 * rule), so an agent hears about a problem before sending, while the sheet is in their hands.
 *
 * - party votes + rejected must not exceed total cast (refused by the server)
 * - total cast must not exceed accredited (refused by the server)
 * - party votes + rejected below total cast is accepted but flagged for a coordinator
 */
export function checkTotals(partyVotes: readonly number[], totals: TotalsInput): Check[] {
  const checks: Check[] = [];
  const sum = partyVotes.reduce((a, b) => a + b, 0);
  const { rejected, total_cast: cast, accredited } = totals;
  if (rejected != null && cast != null) {
    const left = sum + rejected;
    checks.push({
      id: "votes_plus_rejected_vs_cast",
      blocking: true,
      ok: left <= cast,
      left,
      right: cast,
    });
    if (left <= cast) {
      checks.push({
        id: "cast_not_reconciled",
        blocking: false,
        ok: left === cast,
        left,
        right: cast,
      });
    }
  }
  if (cast != null && accredited != null) {
    checks.push({
      id: "cast_vs_accredited",
      blocking: true,
      ok: cast <= accredited,
      left: cast,
      right: accredited,
    });
  }
  return checks;
}

/** The first problem that stops a send, or null when the numbers can go. */
export const blockingProblem = (checks: readonly Check[]): Check | null =>
  checks.find((c) => c.blocking && !c.ok) ?? null;
