import type { OrgStatus, StatusView } from "@vtrs/core";

export const ORG_STATUS: Record<OrgStatus, StatusView> = {
  PENDING_VERIFICATION: { label: "Awaiting code", tone: "ink", icon: "clock" },
  PENDING_APPROVAL: { label: "Needs approval", tone: "amber", icon: "flag" },
  ACTIVE: { label: "Active", tone: "teal", icon: "check-circle-2" },
  SUSPENDED: { label: "Suspended", tone: "red", icon: "ban" },
  REJECTED: { label: "Rejected", tone: "ink", icon: "x-circle" },
};

export const orgStatus = (value: string): StatusView =>
  ORG_STATUS[value as OrgStatus] ?? { label: value, tone: "ink", icon: "circle" };
