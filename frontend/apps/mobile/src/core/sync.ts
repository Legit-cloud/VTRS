import { ApiError, sha256Hex, type Endpoints } from "@vtrs/core";
import type { Db } from "./db";
import type { EvidenceRow } from "./outbox";

export interface FileUploader {
  /** PUT the file at `uri` to a presigned URL. Resolves with the HTTP status; rejects on no network. */
  put(
    uri: string,
    url: string,
    headers: Record<string, string>,
    mime: string,
  ): Promise<{ status: number }>;
}

export interface SyncDeps {
  db: Db;
  ep: Pick<Endpoints, "sync" | "evidence">;
  files: FileUploader;
  now?: () => number;
  random?: () => number;
}

export interface SyncSummary {
  sent: number;
  rejected: number;
  deferred: number;
  photosSent: number;
  /** The session is no longer valid: the app should ask the agent to sign in again. */
  signedOut: boolean;
}

const BATCH = 10;
const STALE_SYNCING_MS = 2 * 60_000;
const BASE_BACKOFF_MS = 15_000;
const MAX_BACKOFF_MS = 15 * 60_000;
const SLOW_RETRY_MS = 5 * 60_000;

// Rejections that are about timing or load, not about the result: keep the result and retry.
const RETRYABLE_CODES = new Set(["capture_not_open", "throttled", "server_error"]);

interface Row {
  version_id: string;
  item_json: string;
  attempts: number;
}

interface Outcome {
  version_id: string | null;
  status: "SYNCED" | "REQUIRES_REVIEW" | "FAILED";
  http_status: number;
  code?: string;
  detail?: string;
  version_no?: number;
  state?: string;
  flags?: string[];
  evidence_uploads?: {
    evidence_id: string;
    status: string;
    upload?: {
      method: string;
      url: string;
      headers: Record<string, string>;
      expires_in: number;
    } | null;
  }[];
}

export function backoff(attempts: number, random: () => number = Math.random): number {
  const base = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** Math.min(attempts, 10));
  return Math.round(base * (0.75 + 0.5 * random()));
}

export class SyncEngine {
  private running: Promise<SyncSummary> | null = null;
  private listeners = new Set<() => void>();
  private readonly now: () => number;
  private readonly random: () => number;

  constructor(private readonly deps: SyncDeps) {
    this.now = deps.now ?? Date.now;
    this.random = deps.random ?? Math.random;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit() {
    this.listeners.forEach((l) => l());
  }

  /** Run one pass. Calls made while a pass is running share its result. */
  run(): Promise<SyncSummary> {
    if (!this.running) {
      this.running = this.pass().finally(() => {
        this.running = null;
        this.emit();
      });
    }
    return this.running;
  }

  private async pass(): Promise<SyncSummary> {
    const { db } = this.deps;
    const summary: SyncSummary = {
      sent: 0,
      rejected: 0,
      deferred: 0,
      photosSent: 0,
      signedOut: false,
    };

    // A crash mid-request leaves rows marked as sending; the key makes a resend harmless.
    await db.run(
      "UPDATE submission SET status = 'PENDING' WHERE status = 'SYNCING' AND next_attempt_at < ?",
      [this.now() - STALE_SYNCING_MS],
    );

    for (;;) {
      const rows = await db.all<Row>(
        `SELECT version_id, item_json, attempts FROM submission
          WHERE status = 'PENDING' AND next_attempt_at <= ?
          ORDER BY created_at LIMIT ?`,
        [this.now(), BATCH],
      );
      if (rows.length === 0) break;
      const stop = await this.sendBatch(rows, summary);
      this.emit();
      if (stop) return summary;
    }

    await this.pushEvidence(summary);
    return summary;
  }

  private async sendBatch(rows: Row[], summary: SyncSummary): Promise<boolean> {
    const { db, ep } = this.deps;
    const ids = rows.map((r) => r.version_id).sort();
    await db.run(
      `UPDATE submission SET status = 'SYNCING', next_attempt_at = ? WHERE version_id IN (${ids
        .map(() => "?")
        .join(",")})`,
      [this.now(), ...ids],
    );
    // Same ids, same key: a retry of this exact batch is answered from the server's record.
    const key = `sync-${sha256Hex(ids.join(",")).slice(0, 40)}`;
    let outcomes: Outcome[];
    try {
      const result = await ep.sync.submit(
        rows.map((r) => JSON.parse(r.item_json) as unknown),
        key,
      );
      outcomes = result.items as unknown as Outcome[];
    } catch (error) {
      return this.batchFailed(rows, error, summary);
    }

    const byId = new Map(outcomes.map((o) => [o.version_id, o]));
    for (const row of rows) {
      const o = byId.get(row.version_id);
      if (!o) {
        await this.defer(row, "The server did not answer for this result.");
        summary.deferred += 1;
        continue;
      }
      if (o.status === "SYNCED" || o.status === "REQUIRES_REVIEW") {
        await db.run(
          `UPDATE submission SET status = ?, server_state = ?, version_no = ?, flags = ?,
                  sent_at = ?, last_error = NULL WHERE version_id = ?`,
          [
            o.status,
            o.state ?? null,
            o.version_no ?? null,
            JSON.stringify(o.flags ?? []),
            this.now(),
            row.version_id,
          ],
        );
        for (const entry of o.evidence_uploads ?? []) {
          if (entry.upload) {
            await db.run(
              `UPDATE evidence SET upload_url = ?, upload_headers = ?, upload_expires = ?
                WHERE evidence_id = ?`,
              [
                entry.upload.url,
                JSON.stringify(entry.upload.headers ?? {}),
                this.now() + Math.max(0, entry.upload.expires_in - 30) * 1000,
                entry.evidence_id,
              ],
            );
          }
        }
        summary.sent += 1;
      } else if (this.isRetryable(o)) {
        await this.defer(row, o.detail ?? "Waiting to send.", o.code === "capture_not_open");
        summary.deferred += 1;
      } else {
        await db.run(
          "UPDATE submission SET status = 'FAILED', last_error = ? WHERE version_id = ?",
          [o.detail ?? "The server turned this result away.", row.version_id],
        );
        summary.rejected += 1;
      }
    }
    return false;
  }

  private isRetryable(o: Outcome): boolean {
    return (
      o.http_status >= 500 ||
      o.http_status === 408 ||
      o.http_status === 429 ||
      (o.code !== undefined && RETRYABLE_CODES.has(o.code))
    );
  }

  /** The whole request failed. Returns true when later batches should not be tried now. */
  private async batchFailed(rows: Row[], error: unknown, summary: SyncSummary): Promise<boolean> {
    const { db } = this.deps;
    const api = error instanceof ApiError ? error : null;
    if (api?.isUnauthorized) {
      for (const row of rows) {
        await db.run("UPDATE submission SET status = 'PENDING' WHERE version_id = ?", [
          row.version_id,
        ]);
      }
      summary.signedOut = true;
      return true;
    }
    const retryable = !api || api.isRetryable;
    for (const row of rows) {
      if (retryable) {
        await this.defer(row, api?.detail ?? "Could not reach the server.");
        summary.deferred += 1;
      } else {
        await db.run(
          "UPDATE submission SET status = 'FAILED', last_error = ? WHERE version_id = ?",
          [api!.detail, row.version_id],
        );
        summary.rejected += 1;
      }
    }
    return true;
  }

  private async defer(row: Row, reason: string, slow = false): Promise<void> {
    const delay = slow ? SLOW_RETRY_MS : backoff(row.attempts + 1, this.random);
    await this.deps.db.run(
      `UPDATE submission SET status = 'PENDING', attempts = attempts + 1, next_attempt_at = ?,
              last_error = ? WHERE version_id = ?`,
      [this.now() + delay, reason, row.version_id],
    );
  }

  // ---- photos ----------------------------------------------------------------------------

  private async pushEvidence(summary: SyncSummary): Promise<void> {
    const { db } = this.deps;
    // Only photos whose result the server has already accepted: it will not take a file for a
    // version it has never seen.
    const rows = await db.all<EvidenceRow>(
      `SELECT e.* FROM evidence e JOIN submission s ON s.version_id = e.version_id
        WHERE e.status = 'PENDING' AND e.next_attempt_at <= ?
          AND s.status IN ('SYNCED','REQUIRES_REVIEW')
        ORDER BY s.created_at`,
      [this.now()],
    );
    for (const row of rows) {
      const outcome = await this.pushOne(row);
      if (outcome === "done") summary.photosSent += 1;
      if (outcome === "signed-out") {
        summary.signedOut = true;
        return;
      }
      this.emit();
    }
  }

  private async pushOne(row: EvidenceRow): Promise<"done" | "later" | "failed" | "signed-out"> {
    const { db, ep, files } = this.deps;
    try {
      let url = row.upload_url;
      let headers: Record<string, string> = row.upload_headers
        ? JSON.parse(row.upload_headers)
        : {};
      if (!url || (row.upload_expires ?? 0) <= this.now()) {
        const entry = await ep.evidence.requestUpload({
          evidence_id: row.evidence_id,
          version_id: row.version_id,
          kind: row.kind as "EC8A" | "EC8B" | "EC8C",
          mime: row.mime,
          size: row.size,
          sha256: row.sha256,
        });
        if (!entry.upload) {
          // The server already holds this file.
          await db.run("UPDATE evidence SET status = 'COMPLETE' WHERE evidence_id = ?", [
            row.evidence_id,
          ]);
          return "done";
        }
        url = entry.upload.url;
        headers = entry.upload.headers ?? {};
      }
      const put = await files.put(row.local_uri, url, headers, row.mime);
      if (put.status < 200 || put.status >= 300) {
        throw new ApiError({
          status: put.status,
          code: "upload_refused",
          detail: `The photo upload was refused (${put.status}).`,
        });
      }
      await ep.evidence.complete(row.evidence_id);
      await db.run(
        "UPDATE evidence SET status = 'COMPLETE', upload_url = NULL, last_error = NULL WHERE evidence_id = ?",
        [row.evidence_id],
      );
      return "done";
    } catch (error) {
      const api = error instanceof ApiError ? error : null;
      if (api?.isUnauthorized) return "signed-out";
      const permanent = api && !api.isRetryable && api.status !== 403 && api.status !== 0;
      if (permanent && api.status !== 401) {
        // An upload URL that expired answers 403 from the object store: ask for a new one.
        await db.run(
          "UPDATE evidence SET status = 'FAILED', last_error = ? WHERE evidence_id = ?",
          [api.detail, row.evidence_id],
        );
        return "failed";
      }
      await db.run(
        `UPDATE evidence SET attempts = attempts + 1, next_attempt_at = ?, last_error = ?,
                upload_url = NULL WHERE evidence_id = ?`,
        [
          this.now() + backoff(row.attempts + 1, this.random),
          api?.detail ?? (error instanceof Error ? error.message : "Upload failed."),
          row.evidence_id,
        ],
      );
      return "later";
    }
  }

  // ---- review decisions ----------------------------------------------------------------------

  /** Ask the server what happened to results that were accepted: approved, or turned back. */
  async refreshReviews(): Promise<void> {
    const { db, ep } = this.deps;
    const rows = await db.all<{ version_id: string }>(
      `SELECT version_id FROM submission
        WHERE status IN ('SYNCED','REQUIRES_REVIEW') AND created_at > ?
        ORDER BY created_at DESC LIMIT 50`,
      [this.now() - 7 * 24 * 3600_000],
    );
    if (rows.length === 0) return;
    let payload;
    try {
      payload = await ep.sync.status(rows.map((r) => r.version_id));
    } catch {
      return; // not worth reporting: the next pass tries again
    }
    const items = (Array.isArray(payload) ? payload : payload.items) as {
      version_id: string;
      state?: string;
      version_no?: number;
      review?: { decision?: string; reason?: string } | null;
    }[];
    for (const item of items) {
      await db.run(
        `UPDATE submission SET server_state = COALESCE(?, server_state),
                version_no = COALESCE(?, version_no), review_reason = ? WHERE version_id = ?`,
        [item.state ?? null, item.version_no ?? null, item.review?.reason ?? null, item.version_id],
      );
    }
    this.emit();
  }
}
