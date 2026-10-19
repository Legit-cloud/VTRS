import { payloadHash, type Json } from "./canonical";

/** The totals every result records, as the result sheet shows them. Valid votes are not
 * entered: the server takes them as the sum of the party votes. */
export type SheetField = "accredited" | "rejected" | "total_cast";
export const SHEET_FIELD_ORDER: readonly SheetField[] = ["accredited", "total_cast", "rejected"];

export type EvidenceKind = "EC8A" | "EC8B" | "EC8C";
export type EvidenceMime = "image/jpeg" | "image/png" | "image/webp" | "application/pdf";

export interface EvidenceManifest {
  evidence_id: string;
  kind: EvidenceKind;
  size: number;
  mime: EvidenceMime;
  sha256: string;
}

export interface SubmissionDraft {
  /** Made when the form opens and kept with the draft: a retry or double tap reuses it. */
  versionId: string;
  electionId: string;
  pollingUnitId: string;
  configVersion: number;
  parentVersionId: string | null;
  totals: Partial<Record<SheetField, number | null>>;
  /** One line per party on the form; null means the agent left it blank. */
  votes: Array<{ candidateId: string; votes: number | null }>;
  capturedAt: Date;
  gps: { lat: number; lng: number; accuracyM?: number | null } | null;
}

/** Fixed-point string with six decimals, the precision the server stores. */
export const coordinate = (value: number): string => value.toFixed(6);

const isCount = (value: number | null | undefined): value is number =>
  value !== null && value !== undefined && Number.isSafeInteger(value) && value >= 0;

/**
 * Build the exact object that is sent and hashed. Everything that could print differently on
 * the two sides (timestamps, coordinates) is already a string here. Throws if any party or
 * total is blank: zero is a number, blank is not.
 */
export function buildSubmission(draft: SubmissionDraft): { [key: string]: Json } {
  const totals: { [key: string]: Json } = {};
  for (const field of SHEET_FIELD_ORDER) {
    const value = draft.totals[field];
    if (!isCount(value)) throw new Error(`Result field ${field} is missing.`);
    totals[field] = value;
  }
  const votes = draft.votes.map((v) => {
    if (!isCount(v.votes)) throw new Error("Every party needs a number, 0 included.");
    return { candidate_id: v.candidateId, votes: v.votes };
  });
  const item: { [key: string]: Json } = {
    version_id: draft.versionId,
    election_id: draft.electionId,
    polling_unit_id: draft.pollingUnitId,
    config_version: draft.configVersion,
    parent_version_id: draft.parentVersionId,
    totals,
    votes,
    device_captured_at: draft.capturedAt.toISOString(),
    gps: draft.gps
      ? {
          lat: coordinate(draft.gps.lat),
          lng: coordinate(draft.gps.lng),
          ...(draft.gps.accuracyM != null ? { accuracy_m: draft.gps.accuracyM.toFixed(2) } : {}),
        }
      : null,
  };
  return { ...item, payload_hash: payloadHash(item) };
}
