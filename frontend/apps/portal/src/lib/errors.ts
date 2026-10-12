import { ApiError } from "@vtrs/core";

/** Flatten whatever the API put in `errors` into plain sentences. */
function messagesIn(node: unknown, out: string[] = []): string[] {
  if (typeof node === "string") out.push(node);
  else if (Array.isArray(node)) node.forEach((n) => messagesIn(n, out));
  else if (node && typeof node === "object") Object.values(node).forEach((n) => messagesIn(n, out));
  return out;
}

/**
 * What to show a person when a request failed, as separate lines. The API's headline for a bad
 * request is only "The request is invalid"; the reason is in the details, so lead with that.
 */
export function errorLines(error: unknown, fallback: string): string[] {
  if (!(error instanceof ApiError)) return [fallback];
  if (error.isNetwork) return ["Could not reach the server. Check your connection and try again."];
  if (error.code === "cancelled") return ["Cancelled."];
  if (error.status === 401) return ["Your session ended. Sign in again."];
  if (error.status === 412 || error.status === 428) {
    return ["Someone changed this while you were looking at it. Reload the page and try again."];
  }
  const details = messagesIn(error.errors).filter(Boolean);
  if (details.length > 0) {
    // De-duplicate and keep them short enough to read.
    return [...new Set(details)].slice(0, 6);
  }
  return [error.detail || fallback];
}

export const describeError = (error: unknown, fallback = "That did not go through."): string =>
  errorLines(error, fallback).join(" ");
