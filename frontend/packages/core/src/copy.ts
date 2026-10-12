/**
 * Interface copy (design system section 5). One file, so a language can be added later without
 * touching components. Plain, short, sentence case; say what happened and what to do next.
 */
import { formatNumber } from "./format";

export const copy = {
  app: { name: "VTRS" },
  provisional: {
    label: "Provisional",
    caption: "Based on results reported so far. Not the official declaration.",
  },
  offline: {
    banner: "You're offline. Results are saved on this phone.",
    backOnline: (count: number) =>
      count > 0
        ? `Back online. Sending ${count} ${count === 1 ? "result" : "results"}…`
        : "Back online.",
  },
  sent: { headline: "Result sent", toast: "Result sent" },
  savedOffline: {
    headline: "Saved on this phone",
    body: "We'll send it as soon as you have a network. You can close the app.",
    line: "Result saved on this phone. It will send when you're back online.",
  },
  failedSend: {
    headline: "Not sent yet",
    body: "Your result is safe on this phone. Check your network and try again.",
    line: "Result not sent. Check your network, then tap Try again. Your result is safe on this phone.",
  },
  needsReview: { headline: "Sent, needs review" },
  emptyAnomalies: "No anomalies in your area. New flags appear here as results come in.",
  live: { paused: "Live updates paused. Reconnecting…", live: "Live" },
} as const;

export function mismatchCandidates(sum: number, valid: number): string {
  return `Candidate votes add up to ${formatNumber(sum)}, but valid votes is ${formatNumber(
    valid,
  )}. Check the result sheet.`;
}

export function mismatchRejected(valid: number, rejected: number, cast: number): string {
  return `Valid votes (${formatNumber(valid)}) plus rejected (${formatNumber(
    rejected,
  )}) is ${formatNumber(valid + rejected)}, but total cast is ${formatNumber(cast)}. Check the result sheet.`;
}

export function mismatchAccredited(cast: number, accredited: number): string {
  return `${formatNumber(cast)} votes were cast, but only ${formatNumber(
    accredited,
  )} voters were accredited. Check the result sheet.`;
}

export function wrongLocation(distance: string, ward: string, unit: string): string {
  return `You're ${distance} from ${ward}, ${unit}. Move to your polling unit to submit.`;
}

export function sentTo(ward: string, unit: string): string {
  return `Your party can now see ${ward}, ${unit}.`;
}

export const toastVerb = {
  approve: "Result approved",
  reject: "Result rejected",
  invite: "Invitation sent",
  revoke: "Invitation revoked",
  deactivate: "Agent deactivated",
  assign: "Flag assigned",
  resolve: "Flag resolved",
  acknowledge: "Flag acknowledged",
  export: "Export requested",
} as const;
