import { payloadHash, type Json } from "./canonical";

export type SheetField = "accredited" | "valid" | "rejected" | "total_cast";
export const SHEET_FIELD_ORDER: readonly SheetField[] = [
  "accredited",
  "valid",
  "rejected",
  "total_cast",
];

export type EvidenceKind = "EC8A" | "EC8B" | "EC8C";
export type EvidenceMime = "image/jpeg" | "image/png" | "image/webp";

export interface EvidenceManifest {
  evidence_id: string;
  kind: EvidenceKind;
  size: number;
  mime: EvidenceMime;
  sha256: string;
}

export interface SubmissionDraft {
  versionId: string;
  contestId: string;
  pollingUnitId: string;
  configVersion: number;
  parentVersionId: string | null;
  totals: Partial<Record<SheetField, number>>;
  votes: Array<{ candidateId: string; votes: number }>;
  capturedAt: Date;
  gps: { lat: number; lng: number; accuracyM?: number | null } | null;
  deviceId: string;
  appVersion: string;
  evidence: EvidenceManifest[];
}

/** Fixed-point string with six decimals, the precision the server stores. */
export const coordinate = (value: number): string => value.toFixed(6);

/**
 * Build the exact object that is sent and signed. Everything that could print differently on
 * the two sides (timestamps, coordinates) is already a string here.
 */
export function buildSubmissionItem(
  draft: SubmissionDraft,
  sheetFields: readonly SheetField[],
): { [key: string]: Json } {
  const totals: { [key: string]: Json } = {};
  for (const field of sheetFields) {
    const value = draft.totals[field];
    if (value === undefined || !Number.isSafeInteger(value) || value < 0) {
      throw new Error(`Result field ${field} is missing.`);
    }
    totals[field] = value;
  }
  const item: { [key: string]: Json } = {
    version_id: draft.versionId,
    contest_id: draft.contestId,
    polling_unit_id: draft.pollingUnitId,
    config_version: draft.configVersion,
    parent_version_id: draft.parentVersionId,
    totals,
    votes: draft.votes.map((v) => ({ candidate_id: v.candidateId, votes: v.votes })),
    device_captured_at: draft.capturedAt.toISOString(),
    gps: draft.gps
      ? {
          lat: coordinate(draft.gps.lat),
          lng: coordinate(draft.gps.lng),
          ...(draft.gps.accuracyM != null ? { accuracy_m: draft.gps.accuracyM.toFixed(2) } : {}),
        }
      : null,
    device_id: draft.deviceId,
    app_version: draft.appVersion,
    evidence: draft.evidence.map((e) => ({ ...e })),
  };
  return { ...item, payload_hash: payloadHash(item) };
}
