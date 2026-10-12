import type { EvidenceManifest, Json, SyncStatus } from "@vtrs/core";
import type { Db } from "./db";

export interface OutboxEntry {
  versionId: string;
  electionId: string;
  contestId: string;
  contestTitle: string;
  pollingUnitId: string;
  puName: string;
  puCode: string;
  ward: string;
  lga: string;
  status: SyncStatus;
  attempts: number;
  lastError: string | null;
  serverState: string | null;
  versionNo: number | null;
  reviewReason: string | null;
  createdAt: number;
  sentAt: number | null;
  /** Result photo state: whether the picture has reached the server yet. */
  evidence: "NONE" | "PENDING" | "COMPLETE" | "FAILED";
}

interface SubmissionRow {
  version_id: string;
  election_id: string;
  contest_id: string;
  contest_title: string;
  polling_unit_id: string;
  pu_name: string;
  pu_code: string;
  ward: string;
  lga: string;
  item_json: string;
  status: SyncStatus;
  attempts: number;
  next_attempt_at: number;
  last_error: string | null;
  server_state: string | null;
  version_no: number | null;
  review_reason: string | null;
  created_at: number;
  sent_at: number | null;
}

export interface EvidenceRow {
  evidence_id: string;
  version_id: string;
  kind: string;
  local_uri: string;
  mime: string;
  size: number;
  sha256: string;
  status: "PENDING" | "COMPLETE" | "FAILED";
  upload_url: string | null;
  upload_headers: string | null;
  upload_expires: number | null;
  attempts: number;
  next_attempt_at: number;
  last_error: string | null;
}

export interface NewSubmission {
  versionId: string;
  electionId: string;
  contestId: string;
  contestTitle: string;
  pollingUnitId: string;
  puName: string;
  puCode: string;
  ward: string;
  lga: string;
  item: { [key: string]: Json };
  evidence: (EvidenceManifest & { localUri: string })[];
  now: number;
}

/** Save a finished result and its photo in one step, so a result is never queued without it. */
export async function enqueue(db: Db, s: NewSubmission): Promise<void> {
  await db.transaction(async () => {
    await db.run(
      `INSERT INTO submission (version_id, election_id, contest_id, contest_title, polling_unit_id,
         pu_name, pu_code, ward, lga, item_json, status, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)`,
      [
        s.versionId,
        s.electionId,
        s.contestId,
        s.contestTitle,
        s.pollingUnitId,
        s.puName,
        s.puCode,
        s.ward,
        s.lga,
        JSON.stringify(s.item),
        s.now,
      ],
    );
    for (const e of s.evidence) {
      await db.run(
        `INSERT INTO evidence (evidence_id, version_id, kind, local_uri, mime, size, sha256, status)
         VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')`,
        [e.evidence_id, s.versionId, e.kind, e.localUri, e.mime, e.size, e.sha256],
      );
    }
  });
}

const toEntry = (r: SubmissionRow, evidence: Map<string, EvidenceRow["status"][]>): OutboxEntry => {
  const states = evidence.get(r.version_id) ?? [];
  return {
    versionId: r.version_id,
    electionId: r.election_id,
    contestId: r.contest_id,
    contestTitle: r.contest_title,
    pollingUnitId: r.polling_unit_id,
    puName: r.pu_name,
    puCode: r.pu_code,
    ward: r.ward,
    lga: r.lga,
    status: r.status,
    attempts: r.attempts,
    lastError: r.last_error,
    serverState: r.server_state,
    versionNo: r.version_no,
    reviewReason: r.review_reason,
    createdAt: r.created_at,
    sentAt: r.sent_at,
    evidence:
      states.length === 0
        ? "NONE"
        : states.every((s) => s === "COMPLETE")
          ? "COMPLETE"
          : states.some((s) => s === "FAILED")
            ? "FAILED"
            : "PENDING",
  };
};

export async function listOutbox(db: Db): Promise<OutboxEntry[]> {
  const rows = await db.all<SubmissionRow>("SELECT * FROM submission ORDER BY created_at DESC");
  const ev = await db.all<{ version_id: string; status: EvidenceRow["status"] }>(
    "SELECT version_id, status FROM evidence",
  );
  const byVersion = new Map<string, EvidenceRow["status"][]>();
  for (const e of ev)
    byVersion.set(e.version_id, [...(byVersion.get(e.version_id) ?? []), e.status]);
  return rows.map((r) => toEntry(r, byVersion));
}

/** Results still on the phone that the server has not confirmed (the Outbox tab's badge). */
export async function pendingCount(db: Db): Promise<number> {
  const row = await db.first<{ n: number }>(
    `SELECT
       (SELECT COUNT(*) FROM submission WHERE status IN ('PENDING','SYNCING','FAILED')) +
       (SELECT COUNT(*) FROM evidence e JOIN submission s USING (version_id)
          WHERE e.status != 'COMPLETE' AND s.status IN ('SYNCED','REQUIRES_REVIEW')) AS n`,
  );
  return row?.n ?? 0;
}

/** The newest version that was not turned away: the parent for a correction. */
export async function latestVersionId(
  db: Db,
  contestId: string,
  pollingUnitId: string,
): Promise<string | null> {
  const row = await db.first<{ version_id: string }>(
    `SELECT version_id FROM submission
      WHERE contest_id = ? AND polling_unit_id = ? AND status != 'FAILED'
      ORDER BY created_at DESC LIMIT 1`,
    [contestId, pollingUnitId],
  );
  return row?.version_id ?? null;
}

/** Put a result the server turned away back in the queue (the agent fixed the cause). */
export async function retryNow(db: Db, versionId: string): Promise<void> {
  await db.run(
    `UPDATE submission SET status = 'PENDING', next_attempt_at = 0, last_error = NULL
      WHERE version_id = ? AND status IN ('FAILED','PENDING')`,
    [versionId],
  );
  await db.run(
    `UPDATE evidence SET status = 'PENDING', next_attempt_at = 0, last_error = NULL
      WHERE version_id = ? AND status = 'FAILED'`,
    [versionId],
  );
}

export async function retryAll(db: Db): Promise<void> {
  await db.run(
    "UPDATE submission SET status = 'PENDING', next_attempt_at = 0 WHERE status IN ('FAILED','PENDING')",
  );
  await db.run(
    "UPDATE evidence SET status = 'PENDING', next_attempt_at = 0 WHERE status = 'FAILED'",
  );
}
