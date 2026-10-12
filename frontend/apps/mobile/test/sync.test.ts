import { ApiError, setRandomSource, uuid7, type Endpoints } from "@vtrs/core";
import { randomBytes } from "node:crypto";
import { beforeEach, describe, expect, it } from "vitest";
import {
  blockingProblems,
  emptyDraft,
  finish,
  liveChecks,
  parseCount,
  sheetFieldsOf,
  type Contest,
} from "../src/core/capture";
import { migrate } from "../src/core/db";
import { enqueue, latestVersionId, listOutbox, pendingCount, retryNow } from "../src/core/outbox";
import { SyncEngine, backoff, type FileUploader } from "../src/core/sync";
import { nodeDb } from "./node-db";

setRandomSource((n) => new Uint8Array(randomBytes(n)));

const contest: Contest = {
  id: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c02",
  office: "GOVERNORSHIP",
  title: "Governor",
  sheet_fields: ["accredited", "valid", "rejected", "total_cast"],
  candidates: [
    { id: "c1", name: "Ada Obi", party_acronym: "APC", ballot_order: 1 },
    { id: "c2", name: "Bola Ade", party_acronym: "PDP", ballot_order: 2 },
  ],
};
const assignment = {
  assignment_id: "a1",
  election: {
    id: "e1",
    name: "Election",
    election_date: "2026-10-12",
    status: "LIVE",
    capture_open: true,
    config_version: 3,
    polls_open_at: null,
    polls_close_at: null,
  },
  polling_unit: {
    id: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c03",
    inec_code: "SYN-01-01-001",
    name: "Primary School",
    ward: "Ward 1",
    lga: "LGA 1",
    latitude: "7.3776",
    longitude: "3.9470",
    registered_voters: 600,
  },
  contests: [contest],
};

function filled() {
  const draft = emptyDraft(contest.id, assignment.polling_unit.id, 1_000);
  draft.votes = { c1: "301", c2: "197" };
  draft.totals = { accredited: "520", valid: "498", rejected: "12", total_cast: "510" };
  draft.photo = {
    uri: "file:///cache/sheet.jpg",
    mime: "image/jpeg",
    size: 1234,
    sha256: "a".repeat(64),
    width: 2000,
    height: 1500,
  };
  draft.gps = { lat: 7.3776, lng: 3.947, accuracyM: 8 };
  return draft;
}

function makeItem(now = 1_000) {
  return finish({
    assignment: assignment as never,
    contest,
    draft: filled(),
    deviceId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c06",
    appVersion: "1.0.0",
    versionId: uuid7(),
    evidenceId: uuid7(),
    parentVersionId: null,
    now: new Date(now),
  });
}

async function queued(db: ReturnType<typeof nodeDb>, now = 1_000) {
  const done = makeItem(now);
  await enqueue(db, {
    versionId: done.item.version_id as string,
    electionId: "e1",
    contestId: contest.id,
    contestTitle: contest.title,
    pollingUnitId: assignment.polling_unit.id,
    puName: "Primary School",
    puCode: "SYN-01-01-001",
    ward: "Ward 1",
    lga: "LGA 1",
    item: done.item,
    evidence: done.evidence,
    now,
  });
  return done;
}

interface Calls {
  submits: { items: unknown[]; key?: string }[];
  uploads: string[];
  completed: string[];
}

function fakeEndpoints(opts: {
  submit?: (items: Record<string, unknown>[]) => unknown;
  submitError?: () => Error | null;
  putStatus?: number;
}) {
  const calls: Calls = { submits: [], uploads: [], completed: [] };
  const ep = {
    sync: {
      submit: async (items: unknown[], key?: string) => {
        calls.submits.push({ items, key });
        const failure = opts.submitError?.();
        if (failure) throw failure;
        const typed = items as Record<string, unknown>[];
        if (opts.submit) return opts.submit(typed);
        return {
          items: typed.map((i) => ({
            version_id: i.version_id,
            status: "SYNCED",
            http_status: 201,
            replayed: false,
            version_no: 1,
            state: "SUBMITTED",
            flags: [],
            evidence_uploads: (i.evidence as { evidence_id: string }[]).map((e) => ({
              evidence_id: e.evidence_id,
              status: "PENDING",
              upload: {
                method: "PUT",
                url: `https://store.example/${e.evidence_id}`,
                headers: { "Content-Type": "image/jpeg" },
                expires_in: 600,
              },
            })),
          })),
        };
      },
      status: async () => ({ items: [] }),
    },
    evidence: {
      requestUpload: async () => ({
        evidence_id: "x",
        status: "PENDING",
        upload: { method: "PUT", url: "https://store.example/new", headers: {}, expires_in: 600 },
      }),
      complete: async (id: string) => {
        calls.completed.push(id);
        return { evidence_id: id, status: "STORED" };
      },
    },
  } as unknown as Pick<Endpoints, "sync" | "evidence">;
  const files: FileUploader = {
    put: async (_uri, url) => {
      calls.uploads.push(url);
      return { status: opts.putStatus ?? 200 };
    },
  };
  return { ep, files, calls };
}

describe("capture", () => {
  it("parses counts strictly", () => {
    expect(parseCount("0")).toBe(0);
    expect(parseCount(" 412 ")).toBe(412);
    expect(parseCount("")).toBeNull();
    expect(parseCount("12a")).toBeNull();
    expect(parseCount("-3")).toBeNull();
    expect(parseCount("99999999")).toBeNull();
  });

  it("asks only for the fields the contest records, valid always first", () => {
    expect(sheetFieldsOf({ ...contest, sheet_fields: ["rejected"] })).toEqual([
      "valid",
      "rejected",
    ]);
  });

  it("blocks on blanks and a missing photo, but only warns on arithmetic", () => {
    const empty = emptyDraft(contest.id, "pu", 0);
    const problems = blockingProblems(contest, empty);
    expect(problems.map((p) => p.step)).toContain("photo");
    expect(problems.filter((p) => p.step === "votes")).toHaveLength(2);

    const mismatch = filled();
    mismatch.totals.valid = "412";
    expect(blockingProblems(contest, mismatch)).toEqual([]);
    expect(liveChecks(contest, mismatch).some((c) => !c.ok)).toBe(true);
  });

  it("builds a hashed item whose manifest matches the photo", () => {
    const done = makeItem();
    expect(done.item.payload_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(done.evidence[0]).toMatchObject({ kind: "EC8A", size: 1234, mime: "image/jpeg" });
    expect((done.item.totals as Record<string, number>).total_cast).toBe(510);
  });
});

describe("sync engine", () => {
  let db: ReturnType<typeof nodeDb>;
  beforeEach(async () => {
    db = nodeDb();
    await migrate(db);
  });

  it("sends a result, uploads its photo and finishes", async () => {
    await queued(db);
    const { ep, files, calls } = fakeEndpoints({});
    const engine = new SyncEngine({ db, ep, files, now: () => 5_000 });
    expect(await pendingCount(db)).toBe(1); // the photo travels with its result

    const summary = await engine.run();
    expect(summary).toMatchObject({ sent: 1, photosSent: 1, signedOut: false });
    expect(calls.uploads).toHaveLength(1);
    expect(calls.completed).toHaveLength(1);

    const [entry] = await listOutbox(db);
    expect(entry).toMatchObject({ status: "SYNCED", evidence: "COMPLETE", versionNo: 1 });
    expect(await pendingCount(db)).toBe(0);
  });

  it("keeps the result and backs off when there is no network", async () => {
    await queued(db);
    const down = fakeEndpoints({
      submitError: () =>
        new ApiError({ status: 0, code: "network_error", detail: "Could not reach the server." }),
    });
    const engine = new SyncEngine({
      db,
      ep: down.ep,
      files: down.files,
      now: () => 5_000,
      random: () => 0.5,
    });
    const summary = await engine.run();
    expect(summary.deferred).toBe(1);
    const [entry] = await listOutbox(db);
    expect(entry).toMatchObject({ status: "PENDING", attempts: 1 });
    expect(entry!.lastError).toMatch(/reach the server/);

    // Not retried before its time; retried after.
    const early = fakeEndpoints({});
    await new SyncEngine({ db, ep: early.ep, files: early.files, now: () => 6_000 }).run();
    expect(early.calls.submits).toHaveLength(0);
    const later = fakeEndpoints({});
    await new SyncEngine({ db, ep: later.ep, files: later.files, now: () => 5_000 + 60_000 }).run();
    expect(later.calls.submits).toHaveLength(1);
  });

  it("resends the same batch under the same key", async () => {
    await queued(db);
    const first = fakeEndpoints({
      submitError: () => new ApiError({ status: 503, code: "x", detail: "down" }),
    });
    await new SyncEngine({ db, ep: first.ep, files: first.files, now: () => 5_000 }).run();
    const second = fakeEndpoints({});
    await new SyncEngine({
      db,
      ep: second.ep,
      files: second.files,
      now: () => 5_000 + 20 * 60_000,
    }).run();
    expect(first.calls.submits[0]!.key).toBeDefined();
    expect(second.calls.submits[0]!.key).toBe(first.calls.submits[0]!.key);
  });

  it("marks a result the server refuses as failed, and lets the agent retry it", async () => {
    const done = await queued(db);
    const refuse = fakeEndpoints({
      submit: (items) => ({
        items: items.map((i) => ({
          version_id: i.version_id,
          status: "FAILED",
          http_status: 400,
          code: "candidate_mismatch",
          detail: "Give exactly one line for every candidate in the contest.",
          replayed: false,
        })),
      }),
    });
    const summary = await new SyncEngine({
      db,
      ep: refuse.ep,
      files: refuse.files,
      now: () => 5_000,
    }).run();
    expect(summary.rejected).toBe(1);
    const [entry] = await listOutbox(db);
    expect(entry!.status).toBe("FAILED");
    expect(entry!.lastError).toMatch(/every candidate/);

    // A failed version is not a parent for the next one.
    expect(await latestVersionId(db, contest.id, assignment.polling_unit.id)).toBeNull();

    await retryNow(db, done.item.version_id as string);
    expect((await listOutbox(db))[0]!.status).toBe("PENDING");
  });

  it("holds a result when capture has not opened, instead of failing it", async () => {
    await queued(db);
    const closed = fakeEndpoints({
      submit: (items) => ({
        items: items.map((i) => ({
          version_id: i.version_id,
          status: "FAILED",
          http_status: 409,
          code: "capture_not_open",
          detail: "Result capture has not opened for this election.",
          replayed: false,
        })),
      }),
    });
    await new SyncEngine({ db, ep: closed.ep, files: closed.files, now: () => 5_000 }).run();
    expect((await listOutbox(db))[0]).toMatchObject({ status: "PENDING", attempts: 1 });
  });

  it("stops and reports when the session is gone, without losing anything", async () => {
    await queued(db);
    const out = fakeEndpoints({
      submitError: () =>
        new ApiError({ status: 401, code: "token_expired", detail: "Sign in again." }),
    });
    const summary = await new SyncEngine({
      db,
      ep: out.ep,
      files: out.files,
      now: () => 5_000,
    }).run();
    expect(summary.signedOut).toBe(true);
    expect((await listOutbox(db))[0]!.status).toBe("PENDING");
  });

  it("retries a photo whose upload fails, without resending the result", async () => {
    await queued(db);
    const flaky = fakeEndpoints({ putStatus: 500 });
    const engine = new SyncEngine({
      db,
      ep: flaky.ep,
      files: flaky.files,
      now: () => 5_000,
      random: () => 0.5,
    });
    await engine.run();
    let [entry] = await listOutbox(db);
    expect(entry).toMatchObject({ status: "SYNCED", evidence: "PENDING" });

    const good = fakeEndpoints({});
    await new SyncEngine({ db, ep: good.ep, files: good.files, now: () => 5_000 + 60_000 }).run();
    [entry] = await listOutbox(db);
    expect(entry!.evidence).toBe("COMPLETE");
    expect(good.calls.submits).toHaveLength(0);
  });

  it("shares one pass between simultaneous triggers", async () => {
    await queued(db);
    const { ep, files, calls } = fakeEndpoints({});
    const engine = new SyncEngine({ db, ep, files, now: () => 5_000 });
    await Promise.all([engine.run(), engine.run(), engine.run()]);
    expect(calls.submits).toHaveLength(1);
  });

  it("sends in batches of ten", async () => {
    for (let i = 0; i < 23; i++) await queued(db, 1_000 + i);
    const { ep, files, calls } = fakeEndpoints({});
    await new SyncEngine({ db, ep, files, now: () => 5_000 }).run();
    expect(calls.submits.map((s) => s.items.length)).toEqual([10, 10, 3]);
  });

  it("backs off with jitter up to a ceiling", () => {
    expect(backoff(1, () => 0.5)).toBe(30_000);
    expect(backoff(20, () => 0.5)).toBe(15 * 60_000);
    expect(backoff(3, () => 0)).toBeLessThan(backoff(3, () => 1));
  });
});
