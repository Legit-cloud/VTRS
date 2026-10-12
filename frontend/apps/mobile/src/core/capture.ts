import {
  SHEET_FIELD_ORDER,
  buildSubmissionItem,
  checkTotals,
  formatNumber,
  type Check,
  type EvidenceManifest,
  type Json,
  type MyAssignment,
  type SheetField,
} from "@vtrs/core";

export type Contest = MyAssignment["contests"][number];

export interface PhotoDraft {
  uri: string;
  mime: "image/jpeg" | "image/png" | "image/webp";
  size: number;
  sha256: string;
  width: number;
  height: number;
}

export interface GpsFix {
  lat: number;
  lng: number;
  accuracyM: number | null;
}

/** What the agent has typed so far. Numbers stay strings until they are validated. */
export interface Draft {
  contestId: string;
  pollingUnitId: string;
  votes: Record<string, string>;
  totals: Partial<Record<SheetField, string>>;
  photo: PhotoDraft | null;
  gps: GpsFix | null;
  startedAt: number;
}

export const emptyDraft = (contestId: string, pollingUnitId: string, now: number): Draft => ({
  contestId,
  pollingUnitId,
  votes: {},
  totals: {},
  photo: null,
  gps: null,
  startedAt: now,
});

/** Digits only, no leading zeros, a sane ceiling. Returns null for "" or something else. */
export function parseCount(raw: string | undefined): number | null {
  if (raw === undefined || raw.trim() === "") return null;
  if (!/^\d{1,7}$/.test(raw.trim())) return null;
  const value = Number(raw.trim());
  return value <= 1_000_000 ? value : null;
}

export const sheetFieldsOf = (contest: Contest): SheetField[] => {
  const wanted = new Set(contest.sheet_fields as string[]);
  const ordered = SHEET_FIELD_ORDER.filter((f) => wanted.has(f));
  return ordered.includes("valid") ? ordered : ["valid", ...ordered];
};

export const FIELD_LABEL: Record<SheetField, string> = {
  accredited: "Accredited voters",
  valid: "Valid votes",
  rejected: "Rejected ballots",
  total_cast: "Total votes cast",
};

export interface Problem {
  step: "votes" | "totals" | "photo";
  field?: string;
  message: string;
}

export function candidateNumbers(contest: Contest, draft: Draft): number[] {
  return contest.candidates.map((c) => parseCount(draft.votes[c.id]) ?? 0);
}

export interface CheckProblem {
  key: "check.candidates" | "check.rejected" | "check.accredited";
  params: Record<string, string>;
}

/**
 * The server's arithmetic as keyed messages: the screen words them in the agent's language,
 * with numbers formatted the way the rest of the app shows them.
 */
export function describeChecks(checks: Check[], valid: number | null): CheckProblem[] {
  const out: CheckProblem[] = [];
  for (const c of checks) {
    if (c.ok) continue;
    if (c.id === "candidates_vs_valid") {
      out.push({
        key: "check.candidates",
        params: { sum: formatNumber(c.left), valid: formatNumber(c.right) },
      });
    } else if (c.id === "valid_plus_rejected_vs_cast") {
      const v = valid ?? 0;
      out.push({
        key: "check.rejected",
        params: {
          valid: formatNumber(v),
          rejected: formatNumber(c.left - v),
          sum: formatNumber(c.left),
          cast: formatNumber(c.right),
        },
      });
    } else if (c.id === "cast_vs_accredited") {
      out.push({
        key: "check.accredited",
        params: { cast: formatNumber(c.left), accredited: formatNumber(c.right) },
      });
    }
  }
  return out;
}

export function totalsAsNumbers(
  contest: Contest,
  draft: Draft,
): Partial<Record<SheetField, number>> {
  const out: Partial<Record<SheetField, number>> = {};
  for (const f of sheetFieldsOf(contest)) {
    const n = parseCount(draft.totals[f]);
    if (n !== null) out[f] = n;
  }
  return out;
}

export function liveChecks(contest: Contest, draft: Draft): Check[] {
  return checkTotals(candidateNumbers(contest, draft), totalsAsNumbers(contest, draft));
}

/** Everything that stops the result being sent. Arithmetic mismatches are warnings, not blocks. */
export function blockingProblems(contest: Contest, draft: Draft): Problem[] {
  const problems: Problem[] = [];
  for (const c of contest.candidates) {
    if (parseCount(draft.votes[c.id]) === null) {
      problems.push({
        step: "votes",
        field: c.id,
        message: `Enter the votes for ${c.name}. Write 0 if there are none.`,
      });
    }
  }
  for (const f of sheetFieldsOf(contest)) {
    if (parseCount(draft.totals[f]) === null) {
      problems.push({
        step: "totals",
        field: f,
        message: `Enter ${FIELD_LABEL[f].toLowerCase()}.`,
      });
    }
  }
  if (!draft.photo) {
    problems.push({
      step: "photo",
      message: "Take a photo of the result sheet so your party can check the numbers.",
    });
  }
  return problems;
}

export interface FinishInput {
  assignment: MyAssignment;
  contest: Contest;
  draft: Draft;
  deviceId: string;
  appVersion: string;
  versionId: string;
  evidenceId: string;
  parentVersionId: string | null;
  now: Date;
}

export interface Finished {
  item: { [key: string]: Json };
  evidence: (EvidenceManifest & { localUri: string })[];
}

/** Build the exact, hashed item that will be sent. Throws if something is missing. */
export function finish(input: FinishInput): Finished {
  const { contest, draft, assignment } = input;
  const problems = blockingProblems(contest, draft);
  if (problems.length > 0 || !draft.photo) throw new Error(problems[0]?.message ?? "Incomplete.");
  const manifest: EvidenceManifest = {
    evidence_id: input.evidenceId,
    kind: "EC8A",
    size: draft.photo.size,
    mime: draft.photo.mime,
    sha256: draft.photo.sha256,
  };
  const item = buildSubmissionItem(
    {
      versionId: input.versionId,
      contestId: contest.id,
      pollingUnitId: assignment.polling_unit.id,
      configVersion: assignment.election.config_version,
      parentVersionId: input.parentVersionId,
      totals: totalsAsNumbers(contest, draft),
      votes: contest.candidates.map((c) => ({
        candidateId: c.id,
        votes: parseCount(draft.votes[c.id]) ?? 0,
      })),
      // When the result was recorded on this phone, not when it later reaches the server.
      capturedAt: input.now,
      gps: draft.gps,
      deviceId: input.deviceId,
      appVersion: input.appVersion,
      evidence: [manifest],
    },
    sheetFieldsOf(contest),
  );
  return { item, evidence: [{ ...manifest, localUri: draft.photo.uri }] };
}
