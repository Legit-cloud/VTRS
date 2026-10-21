import type { ApiClient, Query, RequestOptions } from "./client";
import type {
  AlertPolicy,
  Analytics,
  Assignment,
  AuditEvent,
  ChallengeResponse,
  ConfigIssue,
  Constituency,
  Contestant,
  ContestantCreateRequest,
  CoverageTimeline,
  DataQuality,
  Dashboard,
  Election,
  ElectionCreateRequest,
  ElectionParty,
  ElectionResults,
  ElectionType,
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
  LogoUpload,
  Notification,
  Page,
  Party,
  PartyCreateRequest,
  PollingUnit,
  PuHistory,
  Readiness,
  ReconcileOutcome,
  ResultForm,
  ReviewOutcome,
  ReviewQueueItem,
  ServerTime,
  SubmissionOutcome,
  SubmissionStatus,
  CodeSent,
  TokenPair,
  Ward,
} from "./types";
import type {
  ImportReport,
  MessagingChannel,
  MasterDataState,
  PlatformAuditEvent,
  PlatformElection,
  PlatformOrg,
  PlatformOrgDetail,
  PlatformOverview,
  PlatformUnit,
} from "./platform";

const V1 = "/api/v1";

type Paging = {
  cursor?: string | null;
  limit?: number;
};

/** Every endpoint the web app uses, grouped by what it is for. */
export function createEndpoints(api: ApiClient) {
  const get = <T>(path: string, query?: Query, opts?: RequestOptions) =>
    api.get<T>(`${V1}${path}`, { ...opts, query });
  const post = <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    api.post<T>(`${V1}${path}`, body ?? {}, opts);

  return {
    time: () => get<ServerTime>("/time", undefined, { anonymous: true }),

    auth: {
      login: (body: { identifier: string; password: string }) =>
        post<LoginResponse>("/auth/login", body, { anonymous: true }),
      loginMfa: (body: { mfa_token: string; code: string }) =>
        post<TokenPair>("/auth/login/mfa", body, { anonymous: true }),
      /** A fresh sign-in code by email; the server refuses within a minute of the last one. */
      loginMfaResend: (body: { mfa_token: string }) =>
        post<{ status: string }>("/auth/login/mfa/resend", body, { anonymous: true }),
      refresh: (body: { refresh_token: string }) =>
        post<TokenPair>("/auth/refresh", body, { anonymous: true }),
      logout: () => post<void>("/auth/logout"),
      acceptInvitation: (token: string) =>
        post<ChallengeResponse>("/auth/invitations/accept", { token }, { anonymous: true }),
      completeInvitation: (body: {
        token: string;
        challenge_id: string;
        code: string;
        password: string;
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
      /** Email a code for a sensitive action (asking again within a minute reuses it). */
      stepUpRequest: () => post<CodeSent>("/auth/mfa/step-up/request"),
      stepUp: (body: { challenge_id: string; code: string }) =>
        post<{ access_token: string; access_expires_at: string }>("/auth/mfa/step-up", body),
    },

    me: {
      get: () => get<Me>("/me"),
      assignments: () => get<MyAssignment[]>("/me/assignments"),
      notifications: (query: { unread?: boolean } & Paging = {}) =>
        get<Page<Notification>>("/me/notifications", query),
      unreadCount: () => get<{ unread: number }>("/me/notifications/unread-count"),
      markRead: (id: string) => post<Notification>(`/me/notifications/${id}/read`),
      markAllRead: () => post<{ marked: number }>("/me/notifications/read-all"),
    },

    agent: {
      form: (electionId: string, pollingUnitId: string) =>
        get<ResultForm>(`/elections/${electionId}/polling-units/${pollingUnitId}/form`),
      /**
       * One submission. The browser makes `version_id` when the form opens and keeps it, so a
       * retry or a double tap is a replay, never a second result. Refusals come back as an
       * outcome with `status: "FAILED"`, a `code` and a `detail`; they are not thrown.
       */
      submit: (item: unknown) =>
        api
          .request<SubmissionOutcome>("POST", `${V1}/submissions`, {
            body: item,
            idempotencyKey: (item as { version_id?: string }).version_id,
            acceptStatuses: [400, 403, 404, 409],
          })
          .then((r) => r.data),
      status: (versionId: string) => get<SubmissionStatus>(`/submissions/${versionId}`),
      reportIssue: (
        electionId: string,
        body: {
          polling_unit_id: string;
          kind: "PARTY_MISSING" | "CONTESTANT_MISSING";
          note: string;
        },
      ) => post<ConfigIssue>(`/elections/${electionId}/config-issues`, body),
    },

    evidence: {
      requestUpload: (body: {
        evidence_id: string;
        version_id: string;
        kind: "EC8A" | "EC8B" | "EC8C";
        mime: "image/jpeg" | "image/png" | "image/webp" | "application/pdf";
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
      remove: (id: string) => api.delete<void>(`${V1}/elections/${id}`),
      transition: (id: string, to: "DRAFT" | "CONFIGURED" | "LIVE" | "CLOSED") =>
        post<Election>(`/elections/${id}/transition`, { to }),
      lock: (id: string) => post<Election>(`/elections/${id}/lock`),
      analytics: (id: string) => get<Analytics>(`/elections/${id}/analytics`),
      readiness: (id: string) => get<Readiness>(`/elections/${id}/reconciliation`),
      reconcile: (id: string) => post<ReconcileOutcome>(`/elections/${id}/reconcile`),
      parties: (id: string) => get<ElectionParty[]>(`/elections/${id}/parties`),
      setParties: (id: string, partyIds: string[]) =>
        api.put<ElectionParty[]>(`${V1}/elections/${id}/parties`, { party_ids: partyIds }),
      contestants: (id: string, constituencyId?: string) =>
        get<Contestant[]>(`/elections/${id}/contestants`, { constituency_id: constituencyId }),
      createContestant: (id: string, body: ContestantCreateRequest) =>
        post<Contestant>(`/elections/${id}/contestants`, body),
      issues: (id: string, query: { status?: "OPEN" | "RESOLVED" } & Paging = {}) =>
        get<Page<ConfigIssue>>(`/elections/${id}/config-issues`, query),
      results: (
        id: string,
        query: { level?: Level; parent_id?: string | null; measure?: Measure } = {},
      ) => get<ElectionResults>(`/elections/${id}/results`, query),
      coverage: (id: string, query: { interval?: string; parent_id?: string | null } = {}) =>
        get<CoverageTimeline>(`/elections/${id}/coverage-timeline`, query),
      history: (electionId: string, pollingUnitId: string) =>
        get<PuHistory>(`/elections/${electionId}/polling-units/${pollingUnitId}/history`),
    },

    contestants: {
      get: (id: string) => api.request<Contestant>("GET", `${V1}/contestants/${id}`),
      rename: (id: string, name: string, etag: string) =>
        api.patch<Contestant>(`${V1}/contestants/${id}`, { name }, { ifMatch: etag }),
      remove: (id: string) => api.delete<void>(`${V1}/contestants/${id}`),
    },

    configIssues: {
      resolve: (id: string, note: string) =>
        post<ConfigIssue>(`/config-issues/${id}/resolve`, { note }),
    },

    parties: {
      list: () => get<Party[]>("/parties"),
      get: (id: string) => api.request<Party>("GET", `${V1}/parties/${id}`),
      create: (body: PartyCreateRequest) => post<Party>("/parties", body),
      update: (id: string, body: Partial<PartyCreateRequest>, etag: string) =>
        api.patch<Party>(`${V1}/parties/${id}`, body, { ifMatch: etag }),
      remove: (id: string) => api.delete<void>(`${V1}/parties/${id}`),
      requestLogo: (id: string, body: { mime: string; size: number; sha256: string }) =>
        post<LogoUpload>(`/parties/${id}/logo`, body),
      completeLogo: (id: string, body: { mime: string; sha256: string }) =>
        post<Party>(`/parties/${id}/logo/complete`, body),
      removeLogo: (id: string) => api.delete<Party>(`${V1}/parties/${id}/logo`),
    },

    dashboard: (electionId: string, measure?: Measure) =>
      get<Dashboard>(`/elections/${electionId}/dashboard`, { measure }),

    review: {
      queue: (
        electionId: string,
        query: {
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
      /** `ids` is a comma-separated list of polling unit ids (up to 100). */
      pollingUnits: (query: { ward?: string; lga?: string; ids?: string } & Paging = {}) =>
        get<Page<PollingUnit>>("/geography/polling-units", query),
      electionTypes: () => get<ElectionType[]>("/geography/election-types"),
      constituencies: (query: { kind?: string; state?: string; search?: string } & Paging = {}) =>
        get<Page<Constituency>>("/geography/constituencies", query),
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

    platform: {
      overview: () => get<PlatformOverview>("/platform/overview"),
      organizations: (query: { status?: string } & Paging = {}) =>
        get<Page<PlatformOrg>>("/platform/organizations", query),
      verificationQueue: (query: Paging = {}) =>
        get<Page<PlatformOrg>>("/platform/verification-queue", query),
      organization: (id: string) => get<PlatformOrgDetail>(`/platform/organizations/${id}`),
      approve: (id: string) => post<PlatformOrg>(`/platform/organizations/${id}/approve`),
      reject: (id: string, reason: string) =>
        post<PlatformOrg>(`/platform/organizations/${id}/reject`, { reason }),
      suspend: (id: string, reason: string) =>
        post<PlatformOrg>(`/platform/organizations/${id}/suspend`, { reason }),
      reinstate: (id: string) => post<PlatformOrg>(`/platform/organizations/${id}/reinstate`),
      elections: (query: { status?: string } & Paging = {}) =>
        get<Page<PlatformElection>>("/platform/elections", query),
      masterData: () => get<{ states: MasterDataState[] }>("/platform/master-data"),
      searchUnits: (q: string) =>
        get<{ results: PlatformUnit[] }>("/platform/master-data/search", { q }),
      previewImport: (file: Blob, name = "master-data.csv") => {
        const form = new FormData();
        form.append("file", file, name);
        return api
          .request<ImportReport>("POST", `${V1}/platform/master-data/preview`, {
            body: {},
            formData: form,
          })
          .then((r) => r.data);
      },
      importMasterData: (file: Blob, name = "master-data.csv") => {
        const form = new FormData();
        form.append("file", file, name);
        return api
          .request<ImportReport>("POST", `${V1}/platform/master-data/import`, {
            body: {},
            formData: form,
          })
          .then((r) => r.data);
      },
      messaging: (hours = 24) =>
        get<{ hours: number; channels: MessagingChannel[] }>("/platform/messaging", { hours }),
      testMessage: (channel: "SMS" | "EMAIL") =>
        post<{ sent_to: string; channel: string }>("/platform/messaging/test", { channel }),
      audit: (
        query: {
          organization_id?: string;
          action?: string;
          since?: string;
          until?: string;
        } & Paging = {},
      ) => get<Page<PlatformAuditEvent>>("/platform/audit", query),
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
