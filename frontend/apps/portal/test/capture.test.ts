import { ApiError } from "@vtrs/core";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearDraft,
  hasDraft,
  loadDraft,
  newDraft,
  parseCount,
  saveDraft,
} from "@/lib/capture/draft";
import { backoffMs, isRetryable, withRetry } from "@/lib/capture/retry";

describe("backoff", () => {
  it("grows from 2 s, never passes 60 s, and is jittered below the ceiling", () => {
    expect(backoffMs(1, null, () => 1)).toBe(2_000);
    expect(backoffMs(2, null, () => 1)).toBe(4_000);
    expect(backoffMs(10, null, () => 1)).toBe(60_000);
    expect(backoffMs(4, null, () => 0.5)).toBe(8_000);
    // Never a hot loop, even when the jitter rolls zero.
    expect(backoffMs(1, null, () => 0)).toBe(1_000);
  });

  it("honours the server's Retry-After, capped at a minute", () => {
    expect(backoffMs(1, 7)).toBe(7_000);
    expect(backoffMs(1, 600)).toBe(60_000);
  });

  it("retries only what a retry can fix", () => {
    expect(isRetryable(new ApiError({ status: 0, code: "network", detail: "" }))).toBe(true);
    expect(isRetryable(new ApiError({ status: 503, code: "busy", detail: "" }))).toBe(true);
    expect(isRetryable(new ApiError({ status: 429, code: "throttled", detail: "" }))).toBe(true);
    expect(isRetryable(new ApiError({ status: 400, code: "malformed", detail: "" }))).toBe(false);
    expect(isRetryable(new ApiError({ status: 403, code: "forbidden", detail: "" }))).toBe(false);
  });
});

describe("withRetry", () => {
  afterEach(() => vi.useRealTimers());

  it("keeps the same call going through a dropped connection", async () => {
    vi.useFakeTimers();
    const task = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new ApiError({ status: 0, code: "network", detail: "offline" }))
      .mockRejectedValueOnce(new ApiError({ status: 503, code: "busy", detail: "", retryAfterSeconds: 3 }))
      .mockResolvedValue("ok");
    const retries: number[] = [];
    const done = withRetry(task, { onRetry: (_n, wait) => retries.push(wait) });
    await vi.runAllTimersAsync();
    await expect(done).resolves.toBe("ok");
    expect(task).toHaveBeenCalledTimes(3);
    expect(retries[1]).toBe(3_000);
  });

  it("gives up at once on a refusal", async () => {
    const refusal = new ApiError({ status: 400, code: "malformed", detail: "bad" });
    const task = vi.fn<() => Promise<string>>().mockRejectedValue(refusal);
    await expect(withRetry(task)).rejects.toBe(refusal);
    expect(task).toHaveBeenCalledTimes(1);
  });
});

describe("draft", () => {
  afterEach(() => window.localStorage.clear());

  it("survives a reload with the same version id, so a resend is a replay", () => {
    const draft = newDraft({ electionId: "e1", pollingUnitId: "p1", configVersion: 4 });
    saveDraft({ ...draft, votes: { c1: "120" } });
    const again = loadDraft("e1", "p1");
    expect(again?.versionId).toBe(draft.versionId);
    expect(again?.votes.c1).toBe("120");
    expect(hasDraft("e1", "p1")).toBe(true);
    clearDraft("e1", "p1");
    expect(loadDraft("e1", "p1")).toBeNull();
  });

  it("an untouched form is not a draft", () => {
    saveDraft(newDraft({ electionId: "e1", pollingUnitId: "p2", configVersion: 1 }));
    expect(hasDraft("e1", "p2")).toBe(false);
  });

  it("tells blank from zero from nonsense", () => {
    expect(parseCount("")).toBeNull();
    expect(parseCount(" 0 ")).toBe(0);
    expect(parseCount("125")).toBe(125);
    expect(parseCount("1.5")).toBe("invalid");
    expect(parseCount("-3")).toBe("invalid");
  });
});
