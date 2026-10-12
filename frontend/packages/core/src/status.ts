/**
 * Status vocabularies (design system section 2.4). Every status has an icon and a word, never
 * colour alone. `tone` picks the signal family; `icon` is a Lucide icon name.
 */
export type Tone = "ink" | "blue" | "teal" | "amber" | "red";

export interface StatusView {
  label: string;
  tone: Tone;
  icon: string;
  /** Sentence for screen readers and tooltips. */
  hint?: string;
}

// ---- sync (the phone's own state for a result) -------------------------------------------

export type SyncStatus = "PENDING" | "SYNCING" | "SYNCED" | "FAILED" | "REQUIRES_REVIEW";

export const SYNC_STATUS: Record<SyncStatus, StatusView> = {
  PENDING: { label: "Waiting to send", tone: "ink", icon: "clock" },
  SYNCING: { label: "Sending", tone: "blue", icon: "refresh-cw" },
  SYNCED: { label: "Sent", tone: "teal", icon: "check-circle-2" },
  FAILED: { label: "Not sent", tone: "red", icon: "alert-circle" },
  REQUIRES_REVIEW: { label: "Needs review", tone: "amber", icon: "flag" },
};

// ---- review (the server's state for a result version) ------------------------------------

export const REVIEW_STATE: Record<string, StatusView> = {
  SUBMITTED: { label: "Submitted", tone: "ink", icon: "inbox" },
  REQUIRES_REVIEW: { label: "Needs review", tone: "amber", icon: "flag" },
  IN_REVIEW: { label: "In review", tone: "blue", icon: "eye" },
  APPROVED: { label: "Approved", tone: "teal", icon: "check-circle-2" },
  REJECTED: { label: "Rejected", tone: "red", icon: "x-circle" },
};

export const reviewState = (state: string): StatusView =>
  REVIEW_STATE[state] ?? { label: sentence(state), tone: "ink", icon: "circle" };

// ---- anomaly severity --------------------------------------------------------------------

export type Severity = "INFO" | "MEDIUM" | "HIGH" | "CRITICAL";

/** The design names Low, Medium and High; the platform adds Critical above High. */
export const SEVERITY: Record<Severity, StatusView & { rank: number; marker: string }> = {
  INFO: { label: "Low", tone: "blue", icon: "info", rank: 1, marker: "circle" },
  MEDIUM: { label: "Medium", tone: "amber", icon: "alert-triangle", rank: 2, marker: "diamond" },
  HIGH: { label: "High", tone: "red", icon: "alert-octagon", rank: 3, marker: "square" },
  CRITICAL: { label: "Critical", tone: "red", icon: "siren", rank: 4, marker: "triangle" },
};

export const severity = (value: string): (typeof SEVERITY)[Severity] =>
  SEVERITY[value as Severity] ?? SEVERITY.INFO;

export const SEVERITY_ORDER: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "INFO"];

// ---- flags -------------------------------------------------------------------------------

export const FLAG_STATUS: Record<string, StatusView> = {
  OPEN: { label: "Open", tone: "amber", icon: "circle-dot" },
  ACKNOWLEDGED: { label: "Acknowledged", tone: "blue", icon: "eye" },
  RESOLVED: { label: "Resolved", tone: "teal", icon: "check" },
  FALSE_POSITIVE: { label: "False positive", tone: "ink", icon: "ban" },
};

export const flagStatus = (value: string): StatusView =>
  FLAG_STATUS[value] ?? { label: sentence(value), tone: "ink", icon: "circle" };

/** Plain titles for the rule codes the platform raises (see README, Anomalies). */
export const RULE_TITLES: Record<string, string> = {
  ARITHMETIC_VARIANCE: "Totals do not add up",
  OVER_VOTING: "More votes than accredited or registered voters",
  DUPLICATE_SOURCE: "Another source reported the same polling unit",
  VERSION_FORK: "Correction does not follow the previous version",
  UNASSIGNED_PU_ATTEMPT: "Submission from an agent not assigned to this unit",
  LATE_SUBMISSION: "Submitted after polls closed",
  CONFIG_VERSION_MISMATCH: "Captured against an outdated configuration",
  GPS_MISSING: "No GPS position with the submission",
  GPS_OUT_OF_GEOFENCE: "Submitted away from the polling unit",
  GPS_LOW_ACCURACY: "Imprecise GPS position",
  DEVICE_CLOCK_AHEAD: "Device clock is ahead of the server",
  CAPTURED_BEFORE_POLLS_OPEN: "Captured before polls opened",
  CAPTURED_BEFORE_POLLS_CLOSE: "Captured before polls closed",
  TURNOUT_OUTLIER: "Turnout is unusual for neighbouring units",
  VOTE_SHARE_OUTLIER: "Vote share is unusual for neighbouring units",
  HIGH_REJECTED_RATE: "Unusually many rejected ballots",
  UNANIMOUS_RESULT: "Every valid vote went to one candidate",
  DUPLICATE_EVIDENCE: "Result-sheet photo matches another polling unit's",
  EXIF_TIME_MISMATCH: "Photo time does not match the declared capture time",
  EXIF_GPS_MISMATCH: "Photo location is far from the polling unit",
  MISSING_EVIDENCE: "No result-sheet photo after the waiting period",
  EVIDENCE_QUARANTINED: "Result-sheet photo failed verification",
};

export const ruleTitle = (code: string): string => RULE_TITLES[code] ?? sentence(code);

// ---- elections, roles --------------------------------------------------------------------

export const ELECTION_STATUS: Record<string, StatusView> = {
  DRAFT: { label: "Draft", tone: "ink", icon: "file-pen-line" },
  CONFIGURED: { label: "Configured", tone: "blue", icon: "settings-2" },
  LOCKED: { label: "Locked", tone: "amber", icon: "lock" },
  LIVE: { label: "Live", tone: "teal", icon: "radio" },
  CLOSED: { label: "Closed", tone: "ink", icon: "square" },
  RECONCILED: { label: "Reconciled", tone: "teal", icon: "badge-check" },
};

export const electionStatus = (value: string): StatusView =>
  ELECTION_STATUS[value] ?? { label: sentence(value), tone: "ink", icon: "circle" };

export type RoleCode =
  "PARTY_ADMIN" | "LGA_OFFICER" | "WARD_OFFICER" | "PU_AGENT" | "PLATFORM_ADMIN";

export const ROLE_LABEL: Record<RoleCode, string> = {
  PARTY_ADMIN: "Party admin",
  LGA_OFFICER: "LGA officer",
  WARD_OFFICER: "Ward officer",
  PU_AGENT: "Polling unit agent",
  PLATFORM_ADMIN: "Platform admin",
};

export const OFFICE_LABEL: Record<string, string> = {
  PRESIDENTIAL: "Presidential",
  GOVERNORSHIP: "Governorship",
  SENATORIAL: "Senatorial",
  HOUSE_OF_REPRESENTATIVES: "House of Representatives",
  STATE_ASSEMBLY: "State Assembly",
  LGA_CHAIRMAN: "LGA chairman",
  COUNCILLOR: "Councillor",
  OTHER: "Other",
};

export const USER_STATUS: Record<string, StatusView> = {
  ACTIVE: { label: "Active", tone: "teal", icon: "check-circle-2" },
  PENDING_VERIFICATION: { label: "Invited", tone: "blue", icon: "mail" },
  INVITED: { label: "Invited", tone: "blue", icon: "mail" },
  DEACTIVATED: { label: "Deactivated", tone: "ink", icon: "user-x" },
  SUSPENDED: { label: "Suspended", tone: "red", icon: "ban" },
};

export const userStatus = (value: string): StatusView =>
  USER_STATUS[value] ?? { label: sentence(value), tone: "ink", icon: "circle" };

function sentence(code: string): string {
  const words = code.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
