/** Shapes the platform endpoints return. The OpenAPI contract leaves these as free objects. */

export type OrgStatus =
  "PENDING_VERIFICATION" | "PENDING_APPROVAL" | "ACTIVE" | "SUSPENDED" | "REJECTED";

export interface PlatformOrg {
  id: string;
  name: string;
  legal_name: string;
  status: OrgStatus;
  status_reason: string;
  created_at: string;
  verified_at: string | null;
  approved_at: string | null;
  people: number;
  agents: number;
  election_count: number;
}

export interface PlatformOrgDetail {
  organization: PlatformOrg;
  admins: Array<{
    user_id: string;
    full_name: string;
    status: string;
    email: string;
    phone: string;
  }>;
  elections: Array<{
    id: string;
    name: string;
    status: string;
    election_date: string;
    locked_at: string | null;
    opened_at: string | null;
    closed_at: string | null;
  }>;
  activity: Array<{
    id: string;
    at: string;
    action: string;
    actor_role: string;
    object_type: string;
    object_id: string;
  }>;
}

export interface PlatformOverview {
  organizations: {
    active: number;
    pending_verification: number;
    pending_approval: number;
    suspended: number;
    rejected: number;
  };
  elections: { live: number; total: number; by_status: Record<string, number> };
  agents: number;
  submissions: { last_hour: number; target_per_hour: number };
  open_flags: number;
  messaging_failed_last_hour: number;
  needs_attention: Array<{ kind: string; count: number; text: string }>;
  as_of: string;
}

export interface PlatformElection {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  status: string;
  election_date: string;
  locked_at: string | null;
  opened_at: string | null;
  closed_at: string | null;
  config_version: number;
}

export interface MasterDataState {
  state_id: string;
  code: string;
  name: string;
  lgas: number;
  wards: number;
  polling_units: number;
  located: number;
  with_registered_voters: number;
  located_pct: number | null;
  voters_pct: number | null;
}

export interface ImportReport {
  ok: boolean;
  applied: boolean;
  changes: Record<string, { created: number; updated: number }>;
  counts?: Record<string, number>;
  errors?: Array<string | { line?: number; message?: string }>;
  warnings?: string[];
}

export interface MessagingChannel {
  channel: string;
  provider: string;
  attempted: number;
  sent: number;
  delivered: number;
  failed: number;
  pending: number;
  skipped: number;
  success_pct: number | null;
}

export interface PlatformAuditEvent {
  id: string;
  at: string;
  organization_id: string | null;
  action: string;
  object_type: string;
  object_id: string;
  actor_id: string | null;
  actor_role: string;
  diff: Record<string, unknown>;
}

export interface PlatformUnit {
  id: string;
  code: string;
  name: string;
  ward: string;
  lga: string;
  state: string;
  latitude: string | null;
  longitude: string | null;
  registered_voters: number | null;
}
