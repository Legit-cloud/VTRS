import { ApiError } from "@vtrs/core";

const BASE_MS = 2_000;
const CAP_MS = 60_000;

/**
 * Exponential backoff with full jitter, 2 s up to 60 s (spec section 10.4), or the server's
 * Retry-After when it sent one.
 */
export function backoffMs(
  attempt: number,
  retryAfterSeconds: number | null = null,
  random: () => number = Math.random,
): number {
  if (retryAfterSeconds != null && retryAfterSeconds > 0) {
    return Math.min(CAP_MS, retryAfterSeconds * 1000);
  }
  const ceiling = Math.min(CAP_MS, BASE_MS * 2 ** Math.max(0, attempt - 1));
  return Math.max(BASE_MS / 2, Math.round(random() * ceiling));
}

/** Network failures, timeouts, 429 and 5xx are worth another go; anything else is an answer. */
export const isRetryable = (error: unknown): boolean =>
  error instanceof ApiError ? error.isRetryable : error instanceof TypeError;

export interface RetryHooks {
  /** Called before each wait: which attempt failed, and how long until the next. */
  onRetry?: (attempt: number, waitMs: number, error: unknown) => void;
  signal?: AbortSignal;
}

/** Run `task` until it succeeds or fails for a reason a retry cannot fix. */
export async function withRetry<T>(task: () => Promise<T>, hooks: RetryHooks = {}): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await task();
    } catch (error) {
      if (!isRetryable(error) || hooks.signal?.aborted) throw error;
      const wait = backoffMs(
        attempt,
        error instanceof ApiError ? error.retryAfterSeconds : null,
      );
      hooks.onRetry?.(attempt, wait, error);
      await sleep(wait, hooks.signal);
    }
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new ApiError({ status: 0, code: "cancelled", detail: "Cancelled." }));
      },
      { once: true },
    );
  });
}
