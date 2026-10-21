/** RFC 9457 problem+json from the server, plus the failures that never reach it. */
export interface ProblemBody {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  request_id?: string;
  errors?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly errors: unknown;
  readonly requestId: string | null;
  readonly retryAfterSeconds: number | null;

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    errors?: unknown;
    requestId?: string | null;
    retryAfterSeconds?: number | null;
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.detail = init.detail;
    this.errors = init.errors ?? null;
    this.requestId = init.requestId ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
  }

  /** The request never got an answer: offline, DNS, timeout, aborted connection. */
  get isNetwork(): boolean {
    return this.status === 0;
  }
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
  get isForbidden(): boolean {
    return this.status === 403;
  }
  get needsStepUp(): boolean {
    return this.code === "mfa_step_up_required";
  }
  /** The session never had its emailed sign-in code: sign in again. */
  get needsSignInCode(): boolean {
    return this.code === "mfa_required";
  }
  /** A stale edit: reload, then try again. */
  get isStale(): boolean {
    return this.status === 412 || this.status === 428;
  }
  get isRetryable(): boolean {
    return this.isNetwork || this.status === 429 || this.status >= 500;
  }

  /** `{ field: ["message"] }` for validation errors, flattened to the first message. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const walk = (node: unknown, path: string) => {
      if (node == null) return;
      if (typeof node === "string") {
        out[path || "_"] ??= node;
      } else if (Array.isArray(node)) {
        node.forEach((entry, index) => {
          if (typeof entry === "string") out[path || "_"] ??= entry;
          else walk(entry, path ? `${path}.${index}` : String(index));
        });
      } else if (typeof node === "object") {
        for (const [key, value] of Object.entries(node)) walk(value, path ? `${path}.${key}` : key);
      }
    };
    walk(this.errors, "");
    return out;
  }
}

export function networkError(cause: unknown): ApiError {
  const aborted = cause instanceof Error && cause.name === "AbortError";
  return new ApiError({
    status: 0,
    code: aborted ? "aborted" : "network_error",
    detail: aborted ? "The request was cancelled." : "Could not reach the server.",
  });
}

export async function problemFromResponse(response: Response): Promise<ApiError> {
  let body: ProblemBody = {};
  try {
    body = (await response.json()) as ProblemBody;
  } catch {
    // Not JSON (a proxy error page, for instance): fall back to the status line.
  }
  const retryAfter = Number(response.headers.get("Retry-After"));
  return new ApiError({
    status: response.status,
    code: body.code ?? `http_${response.status}`,
    detail: body.detail ?? (response.statusText || "Request failed."),
    errors: body.errors,
    requestId: body.request_id ?? response.headers.get("X-Request-ID"),
    retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  });
}
