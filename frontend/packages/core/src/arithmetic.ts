import type { SheetField } from "./submission";

export type TotalsInput = Partial<Record<SheetField, number | null>>;

export interface Check {
  id: "candidates_vs_valid" | "valid_plus_rejected_vs_cast" | "cast_vs_accredited";
  ok: boolean;
  /** Numbers involved, for the sentence shown to the agent. */
  left: number;
  right: number;
}

/**
 * The same arithmetic the server applies (`apps/anomalies/domain/inline.py`), so an agent
 * hears about a mismatch before sending, while the sheet is still in their hands.
 */
export function checkTotals(candidateVotes: readonly number[], totals: TotalsInput): Check[] {
  const checks: Check[] = [];
  const sum = candidateVotes.reduce((a, b) => a + b, 0);
  const valid = totals.valid;
  if (valid != null) {
    checks.push({ id: "candidates_vs_valid", ok: sum === valid, left: sum, right: valid });
  }
  if (valid != null && totals.rejected != null && totals.total_cast != null) {
    const left = valid + totals.rejected;
    checks.push({
      id: "valid_plus_rejected_vs_cast",
      ok: left === totals.total_cast,
      left,
      right: totals.total_cast,
    });
  }
  if (totals.accredited != null) {
    const cast = totals.total_cast ?? valid;
    if (cast != null) {
      checks.push({
        id: "cast_vs_accredited",
        ok: cast <= totals.accredited,
        left: cast,
        right: totals.accredited,
      });
    }
  }
  return checks;
}
