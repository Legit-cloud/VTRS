import type { ApiClient, Query, RequestOptions } from "./client";
import type {
  AlertPolicy,
  Analytics,
  Assignment,
  AuditEvent,
  Candidate,
  CandidateCreateRequest,
  ChallengeResponse,
  Contest,
  ContestCreateRequest,
  ContestResults,
  CoverageTimeline,
  DataQuality,
  Dashboard,
  DeviceRegistration,
  Election,
  ElectionCreateRequest,
  EvidenceState,
  EvidenceUploadEntry,
  ExportJob,
  ExportRequest,
  Flag,
  FlagDetail,
  FlagSummary,
  Health,
  Invitation,
  Level,
  Lga,
  LoginResponse,
  Me,
  Measure,
  Member,
  MyAssignment,
  Notification,
  Page,
  PollingUnit,
  PuHistory,
  Readiness,
  ReconcileOutcome,
  ReviewOutcome,
  ReviewQueueItem,
  ServerTime,
  SubmissionResult,
  SyncStatusResponse,
  TokenPair,
  TotpConfirm,
  TotpSetup,
  Ward,
} from "./types";

const V1 = "/api/v1";

type Paging = {
  cursor?: string | null;
  limit?: number;
};

/** Every endpoint the two clients use, grouped by what it is for. */
export function createEndpoints(api: ApiClient) {
  const get = <T>(path: string, query?: Query, opts?: RequestOptions) =>
    api.get<T>(`${V1}${path}`, { ...opts, query });
  const post = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    api.post<T>(`${V1}${path}`, body ?? {}, opts);

  return {
    time: () => get<ServerTime>("/time", undefined, { anonymous: true }),

    auth: {
      login: (body: {
        identifier: string;
        password: string;
        client?: "WEB" | "MOBILE";
        device_id?: string | null;
      }) => post<LoginResponse>("/auth/login", body, { anonymous: true }),
      loginMfa: (body: { mfa_token: string; code: string }) =>
        post<TokenPair>("/auth/login/mfa", body, { anonymous: true }),
      refresh: (body: { refresh_token: string; device_id?: string | null }) =>
        post<TokenPair>("/auth/refresh", body, { anonymous: true }),
      logout: () => post<void>("/auth/logout"),
      acceptInvitation: (token: string) =>
        post<ChallengeResponse>("/auth/invitations/accept", { token }, { anonymous: true }),
      completeInvitation: (body: {
        token: string;
        challenge_id: string;
        code: string;
        password: string;
        device?: DeviceRegistration | null;
      }) => post<TokenPair>("/auth/invitations/complete", body, { anonymous: true }),
      requestOtp: (body: { challenge_id: string; bot_token?: string }) =>
        post<ChallengeResponse>("/auth/otp/request", body, { anonymous: true }),
      verifyOtp: (body: { challenge_id: string; code: string }) =>
        post<{ purpose: string; organization_status?: string; reset_token?: string }>(
          "/auth/otp/verify",
          body,
          { anonymous: true },
        ),
      forgotPassword: (body: { identifier: string; bot_token?: string }) =>
        post<ChallengeResponse>("/auth/password/forgot", body, { anonymous: true }),
      resetPassword: (body: { reset_token: string; new_password: string }) =>
        post<void>("/auth/password/reset", body, { anonymous: true }),
      totpSetup: () => post<TotpSetup>("/auth/mfa/totp/setup"),
      totpConfirm: (code: string) => post<TotpConfirm>("/auth/mfa/totp/confirm", { code }),
      stepUp: (code: string) =>
        post<{ access_token: string; access_expires_at: string }>("/auth/mfa/step-up", { code }),
    },

    me: {
      get: () => get<Me>("/me"),
      assignments: () => get<MyAssignment[] | Page<MyAssignment>>("/me/assignments"),
      registerPushToken: (token: string) => api.put<void>(`${V1}/me/push-token`, { token }),
      notifications: (query: { unread?: boolean } & Paging = {}) =>
        get<Page<Notification>>("/me/notifications", query),
      unreadCount: () => get<{ unread: number }>("/me/notifications/unread-count"),
      markRead: (id: string) => post<Notification>(`/me/notifications/${id}/read`),
      markAllRead: () => post<{ marked: number }>("/me/notifications/read-all"),
    },

    sync: {
      submit: (items: unknown[], idempotencyKey?: string) =>
        post<SubmissionResult>("/sync/submissions", { items }, { idempotencyKey }),
      status: (ids: string[]) =>
        get<{ items: SyncStatusResponse[] } | SyncStatusResponse[]>("/sync/status", {
          ids: ids.join(","),
        }),
    },

    evidence: {
      requestUpload: (body: {
        evidence_id: string;
        version_id: string;
        kind: "EC8A" | "EC8B" | "EC8C";
        mime: string;
        size: number;
        sha256: string;
      }) => post<EvidenceUploadEntry>("/evidence/uploads", body),
      complete: (evidenceId: string) => post<EvidenceState>(`/evidence/${evidenceId}/complete`),
      downloadUrl: (evidenceId: string) =>
        post<{ url: string; expires_in: number }>(`/evidence/${evidenceId}/download-url`),
    },

    elections: {
      list: (query: { status?: string } & Paging = {}) => get<Page<Election>>("/elections", query),
      get: (id: string) => api.request<Election>("GET", `${V1}/elections/${id}`),
      create: (body: ElectionCreateRequest) => post<Election>("/elections", body),
      update: (id: string, body: Partial<ElectionCreateRequest>, etag: string) =>
        api.patch<Election>(`${V1}/elections/${id}`, body, { ifMatch: etag }),
      transition: (id: string, to: "DRAFT" | "CONFIGURED" | "LIVE" | "CLOSED") =>
        post<Election>(`/elections/${id}/transition`, { to }),
      lock: (id: string) => post<Election>(`/elections/${id}/lock`),
      analytics: (id: string) => get<Analytics>(`/elections/${id}/analytics`),
      readiness: (id: string) => get<Readiness>(`/elections/${id}/reconciliation`),
      reconcile: (id: string) => post<ReconcileOutcome>(`/elections/${id}/reconcile`),
      contests: (id: string) => get<Page<Contest> | Contest[]>(`/elections/${id}/contests`),
      createContest: (id: string, body: ContestCreateRequest) =>
        post<Contest>(`/elections/${id}/contests`, body),
    },

    contests: {
      get: (id: string) => api.request<Contest>("GET", `${V1}/contests/${id}`),
      update: (id: string, body: Partial<ContestCreateRequest>, etag: string) =>
        api.patch<Contest>(`${V1}/contests/${id}`, body, { ifMatch: etag }),
      remove: (id: string, etag: string) =>
        api.delete<void>(`${V1}/contests/${id}`, { ifMatch: etag }),
      candidates: (id: string) => get<Page<Candidate> | Candidate[]>(`/contests/${id}/candidates`),
      createCandidate: (id: string, body: CandidateCreateRequest) =>
        post<Candidate>(`/contests/${id}/candidates`, body),
      results: (
        id: string,
        query: { level?: Level; parent_id?: string | null; measure?: Measure } = {},
      ) => get<ContestResults>(`/contests/${id}/results`, query),
      coverage: (id: string, query: { interval?: string; parent_id?: string | null } = {}) =>
        get<CoverageTimeline>(`/contests/${id}/coverage-timeline`, query),
      history: (contestId: string, pollingUnitId: string) =>
        get<PuHistory>(`/contests/${contestId}/polling-units/${pollingUnitId}/history`),
    },

    candidates: {
      get: (id: string) => api.request<Candidate>("GET", `${V1}/candidates/${id}`),
      update: (id: string, body: Partial<CandidateCreateRequest>, etag: string) =>
        api.patch<Candidate>(`${V1}/candidates/${id}`, body, { ifMatch: etag }),
      remove: (id: string, etag: string) =>
        api.delete<void>(`${V1}/candidates/${id}`, { ifMatch: etag }),
    },

    dashboard: (electionId: string, measure?: Measure) =>
      get<Dashboard>(`/elections/${electionId}/dashboard`, { measure }),

    review: {
      queue: (
        electionId: string,
        query: {
          contest_id?: string;
          ward_id?: string;
          lga_id?: string;
          flagged?: boolean;
        } & Paging = {},
      ) => get<Page<ReviewQueueItem>>(`/elections/${electionId}/review-queue`, query),
      decide: (
        versionId: string,
        body: { decision: "APPROVED" | "REJECTED"; reason?: string; acknowledge_flags?: boolean },
      ) => post<ReviewOutcome>(`/results/${versionId}/review`, body),
    },

    flags: {
      list: (
        electionId: string,
        query: {
          status?: string;
          severity?: string;
          rule_code?: string;
          contest_id?: string;
          lga_id?: string;
          ward_id?: string;
          assigned_to_me?: boolean;
        } & Paging = {},
      ) => get<Page<Flag>>(`/elections/${electionId}/flags`, query),
      summary: (electionId: string) => get<FlagSummary>(`/elections/${electionId}/flags/summary`),
      get: (id: string) => get<FlagDetail>(`/flags/${id}`),
      acknowledge: (id: string) => post<FlagDetail>(`/flags/${id}/acknowledge`, {}),
      comment: (id: string, note: string) => post<FlagDetail>(`/flags/${id}/comments`, { note }),
      assign: (id: string, assigneeId: string | null) =>
        post<FlagDetail>(`/flags/${id}/assign`, { assignee_id: assigneeId }),
      resolve: (id: string, body: { outcome: "RESOLVED" | "FALSE_POSITIVE"; note: string }) =>
        post<FlagDetail>(`/flags/${id}/resolve`, body),
      reopen: (id: string, note: string) => post<FlagDetail>(`/flags/${id}/reopen`, { note }),
    },

    team: {
      users: (query: { role?: string } & Paging = {}) => get<Page<Member>>("/users", query),
      user: (id: string) => get<Member>(`/users/${id}`),
      deactivate: (id: string) => post<Member>(`/users/${id}/deactivate`),
      updateMembership: (
        id: string,
        body: { role: string; scope_ids?: string[]; granted_permissions?: string[] },
      ) => api.put<Member>(`${V1}/users/${id}/membership`, body),
      revokeDevice: (userId: string, deviceId: string) =>
        post<unknown>(`/users/${userId}/devices/${deviceId}/revoke`),
      invitations: (query: Paging = {}) => get<Page<Invitation>>("/invitations", query),
      invite: (body: {
        role: string;
        full_name: string;
        email: string;
        phone: string;
        scope_ids?: string[];
        granted_permissions?: string[];
      }) => post<Invitation>("/invitations", body),
      revokeInvitation: (id: string) => post<Invitation>(`/invitations/${id}/revoke`),
    },

    assignments: {
      list: (
        query: {
          election?: string;
          agent?: string;
          polling_unit?: string;
          status?: string;
        } & Paging = {},
      ) => get<Page<Assignment>>("/assignments", query),
      create: (body: { election_id: string; agent_id: string; polling_unit_id: string }) =>
        post<Assignment>("/assignments", body),
      revoke: (id: string) => post<Assignment>(`/assignments/${id}/revoke`),
    },

    geography: {
      lgas: (query: { state?: string } & Paging = {}) => get<Page<Lga>>("/geography/lgas", query),
      wards: (query: { lga?: string } & Paging = {}) => get<Page<Ward>>("/geography/wards", query),
      pollingUnits: (query: { ward?: string; lga?: string } & Paging = {}) =>
        get<Page<PollingUnit>>("/geography/polling-units", query),
    },

    exports: {
      list: (query: { status?: string } & Paging = {}) => get<Page<ExportJob>>("/exports", query),
      get: (id: string) => get<ExportJob>(`/exports/${id}`),
      request: (body: ExportRequest) => post<ExportJob>("/exports", body),
      downloadUrl: (id: string) =>
        post<{ url: string; expires_in: number; sha256?: string; size?: number | null }>(
          `/exports/${id}/download-url`,
        ),
    },

    audit: {
      events: (
        query: {
          since?: string;
          until?: string;
          action?: string;
          actor_id?: string;
          object_type?: string;
          object_id?: string;
        } & Paging = {},
      ) => get<Page<AuditEvent>>("/audit/events", query),
    },

    admin: {
      health: () => get<Health>("/admin/health"),
      dataQuality: () => get<DataQuality>("/admin/data-quality"),
      alertPolicy: () => get<AlertPolicy>("/admin/alert-policy"),
      updateAlertPolicy: (matrix: Record<string, Record<string, unknown>>) =>
        api.put<AlertPolicy>(`${V1}/admin/alert-policy`, { matrix }),
      resetAlertPolicy: () => api.delete<AlertPolicy>(`${V1}/admin/alert-policy`),
    },
  };
}

export type Endpoints = ReturnType<typeof createEndpoints>;
