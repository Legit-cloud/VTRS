/**
 * Interface copy (design system section 5). One file, so a language can be added later without
 * touching components. Plain, short, sentence case; say what happened and what to do next.
 */
import { formatNumber } from "./format";

export const copy = {
  app: { name: "VTRS" },
  provisional: {
    label: "Provisional",
    caption: "Collected by our agents so far. Not the official INEC count.",
  },
  connection: {
    banner: "No connection. Your numbers are kept on this phone; we'll send them when you're back.",
    backOnline: "Back online. Sending…",
  },
  received: {
    headline: "Votes received",
    body: "Now add a photo or PDF of the result sheet. Your result isn't complete without it.",
    toast: "Votes received",
  },
  complete: { headline: "Result sheet uploaded", toast: "Sheet uploaded" },
  notSent: {
    headline: "Not sent yet",
    body: "Your numbers are kept on this phone. We're trying again; check your network.",
  },
  needsReview: { headline: "Received, needs review" },
  blankParty: (abbreviation: string) =>
    `Enter ${abbreviation}'s votes. Use 0 if they got none.`,
  missingParty:
    "Is a party or candidate missing? Tell an admin. Don't add it to another party's votes.",
  emptyAnomalies: "No anomalies in your area. New flags appear here as results come in.",
  live: { paused: "Live updates paused. Reconnecting…", live: "Live" },
  ownCollection: "Our agents' collection, not the official INEC count.",
} as const;

export function mismatchTotalCast(partyVotes: number, rejected: number, cast: number): string {
  return `Party votes plus rejected (${formatNumber(
    partyVotes + rejected,
  )}) are more than total votes cast (${formatNumber(cast)}). Check the result sheet.`;
}

export function shortfallTotalCast(partyVotes: number, rejected: number, cast: number): string {
  return `Party votes plus rejected (${formatNumber(
    partyVotes + rejected,
  )}) are less than total votes cast (${formatNumber(
    cast,
  )}). If the sheet says so, send it: a coordinator will check it.`;
}

export function mismatchAccredited(cast: number, accredited: number): string {
  return `Total votes cast (${formatNumber(cast)}) are more than accredited voters (${formatNumber(
    accredited,
  )}). Check the result sheet.`;
}

export function wrongLocation(distance: string, ward: string, unit: string): string {
  return `You're ${distance} from ${ward}, ${unit}.`;
}

export function completeFor(ward: string, unit: string): string {
  return `Your party can now see ${ward}, ${unit}, with its sheet.`;
}

export const toastVerb = {
  verify: "Result verified",
  reject: "Result rejected",
  invite: "Invitation sent",
  revoke: "Invitation revoked",
  deactivate: "Agent deactivated",
  assign: "Flag assigned",
  resolve: "Flag resolved",
  acknowledge: "Flag acknowledged",
  export: "Export requested",
  partySaved: "Party saved",
  issueResolved: "Issue resolved",
} as const;
