/**
 * Runs the real sync engine, with the app's own SQL, against a running API: sign in as an agent
 * on their registered device, read the assignment, record a result, send it, and read it back.
 *
 *   VTRS_LIVE_API=http://127.0.0.1:8000 \
 *   VTRS_LIVE_AGENT='{"email":"…","password":"…","device_id":"…","parent_version_id":"…"}' \
 *   npx vitest run test/live.test.ts
 *
 * Skipped unless both are set, so the normal test run never needs a server.
 */
import { ApiClient, createEndpoints, setRandomSource, uuid7, type MyAssignment } from "@vtrs/core";
import { randomBytes } from "node:crypto";
import { describe, expect, it } from "vitest";
import { emptyDraft, finish } from "../src/core/capture";
import { migrate } from "../src/core/db";
import { enqueue, listOutbox } from "../src/core/outbox";
import { SyncEngine, type FileUploader } from "../src/core/sync";
import { nodeDb } from "./node-db";

setRandomSource((n) => new Uint8Array(randomBytes(n)));

const API = process.env.VTRS_LIVE_API;
const AGENT = process.env.VTRS_LIVE_AGENT
  ? (JSON.parse(process.env.VTRS_LIVE_AGENT) as {
      email: string;
      password: string;
      device_id: string;
      parent_version_id: string | null;
    })
  : null;

describe.skipIf(!API || !AGENT)("agent app against the live API", () => {
  it("signs in, records, sends and reads back a result with its photo", async () => {
    const anonymous = createEndpoints(new ApiClient({ baseUrl: API!, getAccessToken: () => null }));
    const login = (await anonymous.auth.login({
      identifier: AGENT!.email,
      password: AGENT!.password,
      client: "MOBILE",
      device_id: AGENT!.device_id,
    })) as { access_token: string; device_id: string };
    expect(login.device_id).toBe(AGENT!.device_id);

    const client = new ApiClient({ baseUrl: API!, getAccessToken: () => login.access_token });
    const ep = createEndpoints(client);

    const list = await ep.me.assignments();
    const assignments = (Array.isArray(list) ? list : list.results) as MyAssignment[];
    const assignment = assignments[0]!;
    const contest = assignment.contests[0]!;
    expect(contest.candidates.length).toBeGreaterThan(0);

    // A tiny stand-in for the photo; the server stores whatever bytes were hashed.
    const photo = new Uint8Array(randomBytes(2048));
    const { sha256Hex } = await import("@vtrs/core");
    const draft = emptyDraft(contest.id, assignment.polling_unit.id, Date.now());
    contest.candidates.forEach((c, i) => (draft.votes[c.id] = String(100 + i * 7)));
    const valid = contest.candidates.reduce((sum, _c, i) => sum + 100 + i * 7, 0);
    draft.totals = {
      accredited: String(valid + 20),
      valid: String(valid),
      rejected: "5",
      total_cast: String(valid + 5),
    };
    draft.photo = {
      uri: "memory://sheet",
      mime: "image/jpeg",
      size: photo.byteLength,
      sha256: sha256Hex(photo),
      width: 100,
      height: 100,
    };
    draft.gps = {
      lat: Number(assignment.polling_unit.latitude),
      lng: Number(assignment.polling_unit.longitude),
      accuracyM: 8,
    };

    const versionId = uuid7();
    const done = finish({
      assignment,
      contest,
      draft,
      deviceId: AGENT!.device_id,
      appVersion: "1.0.0",
      versionId,
      evidenceId: uuid7(),
      parentVersionId: AGENT!.parent_version_id,
      now: new Date(),
    });

    const db = nodeDb();
    await migrate(db);
    await enqueue(db, {
      versionId,
      electionId: assignment.election.id,
      contestId: contest.id,
      contestTitle: contest.title,
      pollingUnitId: assignment.polling_unit.id,
      puName: assignment.polling_unit.name,
      puCode: assignment.polling_unit.inec_code,
      ward: assignment.polling_unit.ward,
      lga: assignment.polling_unit.lga,
      item: done.item,
      evidence: done.evidence,
      now: Date.now(),
    });

    const uploaded: string[] = [];
    const files: FileUploader = {
      async put(_uri, url, headers) {
        const response = await fetch(url, { method: "PUT", headers, body: photo });
        uploaded.push(`${response.status}`);
        return { status: response.status };
      },
    };
    const engine = new SyncEngine({ db, ep, files });
    const summary = await engine.run();
    expect(summary.rejected).toBe(0);
    expect(summary.sent).toBe(1);

    const [entry] = await listOutbox(db);
    expect(["SYNCED", "REQUIRES_REVIEW"]).toContain(entry!.status);
    expect(entry!.versionNo).toBeGreaterThan(0);

    // The server agrees it holds this version.
    const status = await ep.sync.status([versionId]);
    const items = (Array.isArray(status) ? status : status.items) as {
      version_id: string;
      status: string;
    }[];
    expect(items.find((i) => i.version_id === versionId)?.status).toMatch(/SYNCED|REQUIRES_REVIEW/);

    // Replaying the same item changes nothing: idempotent end to end.
    const again = await ep.sync.submit([done.item]);
    expect(again.items[0]).toMatchObject({ replayed: true });
    console.log("photo upload statuses:", uploaded.join(","), "evidence:", entry!.evidence);
  }, 60_000);
});
