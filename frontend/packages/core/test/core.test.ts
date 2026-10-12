import { describe, expect, it } from "vitest";
import fixtures from "./server-fixtures.json";
import {
  ApiClient,
  ApiError,
  buildQuery,
  buildSubmissionItem,
  canonicalJson,
  checkTotals,
  cursorFrom,
  distanceMetres,
  formatDateTime,
  formatLocalPhone,
  formatNumber,
  formatPercent,
  isUuid,
  normalizePhone,
  payloadHash,
  uuid7,
  type Json,
} from "../src";

describe("canonical JSON matches the server byte for byte", () => {
  for (const [name, fx] of Object.entries(fixtures)) {
    it(name, () => {
      expect(canonicalJson(fx.input as Json)).toBe(fx.canonical);
      expect(payloadHash(fx.input as { [k: string]: Json })).toBe(fx.hash);
    });
  }

  it("refuses floats instead of printing them differently", () => {
    expect(() => canonicalJson({ a: 1.5 })).toThrow(/integers only/);
  });
});

describe("submission item", () => {
  const draft = {
    versionId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c01",
    contestId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c02",
    pollingUnitId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c03",
    configVersion: 3,
    parentVersionId: null,
    totals: { accredited: 520, valid: 498, rejected: 12, total_cast: 510 },
    votes: [
      { candidateId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c04", votes: 301 },
      { candidateId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c05", votes: 197 },
    ],
    capturedAt: new Date("2026-10-12T14:05:09.123Z"),
    gps: { lat: 7.3776, lng: 3.947, accuracyM: 12.5 },
    deviceId: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c06",
    appVersion: "1.0.0",
    evidence: [
      {
        evidence_id: "0198a2b4-7c3e-7a10-8c11-4d2f6a9b1c07",
        kind: "EC8A" as const,
        size: 348120,
        mime: "image/jpeg" as const,
        sha256: "a".repeat(64),
      },
    ],
  };

  it("reproduces the server's hash for the same content", () => {
    const item = buildSubmissionItem(draft, ["accredited", "valid", "rejected", "total_cast"]);
    expect(item.payload_hash).toBe(fixtures.submission.hash);
  });

  it("only sends the fields the contest asks for", () => {
    const item = buildSubmissionItem(draft, ["valid"]);
    expect(item.totals).toEqual({ valid: 498 });
  });

  it("refuses a missing required field", () => {
    expect(() => buildSubmissionItem({ ...draft, totals: {} }, ["valid"])).toThrow();
  });
});

describe("arithmetic", () => {
  it("passes a sheet that adds up", () => {
    const checks = checkTotals([301, 197], {
      valid: 498,
      rejected: 12,
      total_cast: 510,
      accredited: 520,
    });
    expect(checks.every((c) => c.ok)).toBe(true);
  });

  it("reports both numbers when candidates and valid disagree", () => {
    const [first] = checkTotals([300, 115], { valid: 412 });
    expect(first).toMatchObject({ id: "candidates_vs_valid", ok: false, left: 415, right: 412 });
  });

  it("flags more cast than accredited", () => {
    const checks = checkTotals([10], { valid: 10, accredited: 8 });
    expect(checks.find((c) => c.id === "cast_vs_accredited")?.ok).toBe(false);
  });
});

describe("formatting", () => {
  it("groups thousands and keeps one decimal", () => {
    expect(formatNumber(6390)).toBe("6,390");
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatPercent(94.349)).toBe("94.3%");
    expect(formatPercent(100)).toBe("100%");
    expect(formatPercent(99.99)).toBe("99.9%");
  });

  it("shows Africa/Lagos time in 24 hours", () => {
    expect(formatDateTime("2026-10-12T13:05:00Z")).toBe("12 Oct 2026, 14:05");
    expect(formatDateTime("2026-12-31T23:30:00Z")).toBe("1 Jan 2027, 00:30");
  });
});

describe("phone numbers", () => {
  it("normalises like the server", () => {
    expect(normalizePhone("0803 123 4567")).toBe("+2348031234567");
    expect(normalizePhone("+234 803 123 4567")).toBe("+2348031234567");
    expect(normalizePhone("0803123")).toBeNull();
    expect(normalizePhone("abc")).toBeNull();
  });

  it("formats as the agent types", () => {
    expect(formatLocalPhone("08031234567")).toBe("0803 123 4567");
    expect(formatLocalPhone("0803")).toBe("0803");
  });
});

describe("ids and geography", () => {
  it("makes sortable UUIDv7 values", () => {
    const a = uuid7(1_700_000_000_000);
    const b = uuid7(1_700_000_001_000);
    expect(isUuid(a)).toBe(true);
    expect(a < b).toBe(true);
    expect(a[14]).toBe("7");
  });

  it("measures distance", () => {
    const d = distanceMetres({ lat: 7.3776, lng: 3.947 }, { lat: 7.3776, lng: 3.9605 });
    expect(d).toBeGreaterThan(1400);
    expect(d).toBeLessThan(1600);
  });
});

describe("api client", () => {
  const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    });

  it("builds queries without empty values", () => {
    expect(buildQuery({ a: "1", b: undefined, c: "", d: true, e: ["x", "y"] })).toBe(
      "?a=1&d=true&e=x%2Cy",
    );
    expect(cursorFrom("http://x/api?cursor=cD00ODY%3D&limit=5")).toBe("cD00ODY=");
  });

  it("refreshes once on 401 and replays the request", async () => {
    let token = "old";
    const seen: string[] = [];
    let refreshCalls = 0;
    const client = new ApiClient({
      baseUrl: "",
      getAccessToken: () => token,
      refreshAccessToken: async () => {
        refreshCalls += 1;
        await new Promise((r) => setTimeout(r, 5));
        token = "new";
        return token;
      },
      fetchImpl: async (_url, init) => {
        const auth = (init?.headers as Record<string, string>).Authorization!;
        seen.push(auth);
        return auth === "Bearer new"
          ? json(200, { ok: true })
          : json(401, { code: "token_expired" });
      },
    });
    const [a, b] = await Promise.all([
      client.get<{ ok: boolean }>("/x"),
      client.get<{ ok: boolean }>("/y"),
    ]);
    expect(a.ok && b.ok).toBe(true);
    expect(refreshCalls).toBe(1);
    expect(seen.filter((s) => s === "Bearer new")).toHaveLength(2);
  });

  it("sends an idempotency key on writes and parses problem+json", async () => {
    let key = "";
    const client = new ApiClient({
      baseUrl: "",
      getAccessToken: () => "t",
      fetchImpl: async (_url, init) => {
        key = (init?.headers as Record<string, string>)["Idempotency-Key"]!;
        return json(400, {
          code: "validation_error",
          detail: "The request is invalid.",
          errors: { email: ["Enter a valid email address."] },
        });
      },
    });
    const error = await client.post("/x", { a: 1 }).catch((e: unknown) => e);
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).fieldErrors()).toEqual({ email: "Enter a valid email address." });
  });

  it("maps a dead network to a status-0 error", async () => {
    const client = new ApiClient({
      baseUrl: "",
      getAccessToken: () => null,
      fetchImpl: async () => {
        throw new TypeError("Network request failed");
      },
    });
    const error = (await client.get("/x").catch((e: unknown) => e)) as ApiError;
    expect(error.isNetwork).toBe(true);
    expect(error.isRetryable).toBe(true);
  });
});
