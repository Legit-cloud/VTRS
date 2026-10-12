import { uuid7, type MyAssignment } from "@vtrs/core";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  emptyDraft,
  finish,
  type Contest,
  type Draft,
  type GpsFix,
  type PhotoDraft,
} from "../core/capture";
import { enqueue, latestVersionId } from "../core/outbox";
import { APP_VERSION } from "../platform/config";
import { currentFix } from "../platform/location";
import { useApp } from "./app";

interface CaptureValue {
  assignment: MyAssignment;
  contest: Contest;
  draft: Draft;
  loaded: boolean;
  setVote: (candidateId: string, value: string) => void;
  setTotal: (field: string, value: string) => void;
  setPhoto: (photo: PhotoDraft | null) => void;
  /** Queue the result. Resolves with the id used to follow it. */
  send: () => Promise<string>;
}

const CaptureContext = createContext<CaptureValue | null>(null);

export function useCapture(): CaptureValue {
  const value = useContext(CaptureContext);
  if (!value) throw new Error("useCapture outside CaptureProvider");
  return value;
}

/** Holds what the agent is typing, and saves it after every change so nothing is lost. */
export function CaptureProvider({
  assignment,
  contest,
  children,
}: {
  assignment: MyAssignment;
  contest: Contest;
  children: ReactNode;
}) {
  const { db, deviceId, afterEnqueue } = useApp();
  const pollingUnitId = assignment.polling_unit.id;
  const [draft, setDraft] = useState<Draft>(() =>
    emptyDraft(contest.id, pollingUnitId, Date.now()),
  );
  const [loaded, setLoaded] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!db) return;
    let alive = true;
    db.first<{ json: string }>(
      "SELECT json FROM draft WHERE contest_id = ? AND polling_unit_id = ?",
      [contest.id, pollingUnitId],
    )
      .then((row) => {
        if (alive && row) setDraft(JSON.parse(row.json) as Draft);
      })
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [db, contest.id, pollingUnitId]);

  const persist = useCallback(
    (next: Draft) => {
      if (!db) return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        void db.run(
          `INSERT INTO draft (contest_id, polling_unit_id, json, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(contest_id, polling_unit_id)
           DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at`,
          [next.contestId, next.pollingUnitId, JSON.stringify(next), Date.now()],
        );
      }, 300);
    },
    [db],
  );

  const update = useCallback(
    (change: (current: Draft) => Draft) => {
      setDraft((current) => {
        const next = change(current);
        persist(next);
        return next;
      });
    },
    [persist],
  );

  const send = useCallback(async () => {
    if (!db || !deviceId) throw new Error("This phone is not set up yet. Sign in again.");
    const fix: GpsFix | null = await currentFix();
    const versionId = uuid7();
    const parent = await latestVersionId(db, contest.id, pollingUnitId);
    const done = finish({
      assignment,
      contest,
      draft: { ...draft, gps: fix ?? draft.gps },
      deviceId,
      appVersion: APP_VERSION,
      versionId,
      evidenceId: uuid7(),
      parentVersionId: parent,
      now: new Date(),
    });
    await enqueue(db, {
      versionId,
      electionId: assignment.election.id,
      contestId: contest.id,
      contestTitle: contest.title,
      pollingUnitId,
      puName: assignment.polling_unit.name,
      puCode: assignment.polling_unit.inec_code,
      ward: assignment.polling_unit.ward,
      lga: assignment.polling_unit.lga,
      item: done.item,
      evidence: done.evidence,
      now: Date.now(),
    });
    await db.run("DELETE FROM draft WHERE contest_id = ? AND polling_unit_id = ?", [
      contest.id,
      pollingUnitId,
    ]);
    afterEnqueue();
    return versionId;
  }, [db, deviceId, assignment, contest, draft, pollingUnitId, afterEnqueue]);

  const value = useMemo<CaptureValue>(
    () => ({
      assignment,
      contest,
      draft,
      loaded,
      setVote: (id, v) =>
        update((d) => ({ ...d, votes: { ...d.votes, [id]: v.replace(/\D/g, "") } })),
      setTotal: (f, v) =>
        update((d) => ({ ...d, totals: { ...d.totals, [f]: v.replace(/\D/g, "") } })),
      setPhoto: (photo) => update((d) => ({ ...d, photo })),
      send,
    }),
    [assignment, contest, draft, loaded, update, send],
  );
  return <CaptureContext.Provider value={value}>{children}</CaptureContext.Provider>;
}
