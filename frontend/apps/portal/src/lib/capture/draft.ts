import { uuid7, type SheetField } from "@vtrs/core";

/**
 * The unsent form, kept in this browser so a reload or a dropped connection does not lose the
 * typed numbers (FR-6.6.2). A convenience, not a record: the server's copy is the only one that
 * counts. The version id is made when the form first opens and kept with the draft, so every
 * retry or double tap of the same numbers is a replay, never a second result.
 */
export interface Draft {
  versionId: string;
  electionId: string;
  pollingUnitId: string;
  configVersion: number;
  parentVersionId: string | null;
  /** Typed text per contestant id; "" means blank. */
  votes: Record<string, string>;
  totals: Record<SheetField, string>;
  startedAt: string;
}

const PREFIX = "vtrs.draft.";
const key = (electionId: string, pollingUnitId: string) =>
  `${PREFIX}${electionId}.${pollingUnitId}`;

export function newDraft(init: {
  electionId: string;
  pollingUnitId: string;
  configVersion: number;
  parentVersionId?: string | null;
  votes?: Record<string, string>;
  totals?: Partial<Record<SheetField, string>>;
}): Draft {
  return {
    versionId: uuid7(),
    electionId: init.electionId,
    pollingUnitId: init.pollingUnitId,
    configVersion: init.configVersion,
    parentVersionId: init.parentVersionId ?? null,
    votes: init.votes ?? {},
    totals: { accredited: "", total_cast: "", rejected: "", ...init.totals },
    startedAt: new Date().toISOString(),
  };
}

export function loadDraft(electionId: string, pollingUnitId: string): Draft | null {
  try {
    const raw = window.localStorage.getItem(key(electionId, pollingUnitId));
    if (!raw) return null;
    const draft = JSON.parse(raw) as Draft;
    return draft.versionId && draft.electionId === electionId ? draft : null;
  } catch {
    return null;
  }
}

export function saveDraft(draft: Draft): void {
  try {
    window.localStorage.setItem(key(draft.electionId, draft.pollingUnitId), JSON.stringify(draft));
  } catch {
    // Private mode or a full store: the form still works, it just will not survive a reload.
  }
}

export function clearDraft(electionId: string, pollingUnitId: string): void {
  try {
    window.localStorage.removeItem(key(electionId, pollingUnitId));
  } catch {
    // nothing to clear
  }
}

export function hasDraft(electionId: string, pollingUnitId: string): boolean {
  const draft = typeof window === "undefined" ? null : loadDraft(electionId, pollingUnitId);
  return !!draft && (Object.values(draft.votes).some(Boolean) || Object.values(draft.totals).some(Boolean));
}

/** "" stays blank (null); anything else must be a whole, non-negative number. */
export function parseCount(text: string): number | null | "invalid" {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (!/^\d{1,7}$/.test(trimmed)) return "invalid";
  return Number(trimmed);
}
