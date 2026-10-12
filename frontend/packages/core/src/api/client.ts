import { uuid7 } from "../uuid";
import { ApiError, networkError, problemFromResponse } from "./errors";

export type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  /** A multipart upload. Sent as is; the runtime sets the boundary. */
  formData?: FormData;
  /** Reuse a key to make a retry safe; one is generated for every write otherwise. */
  idempotencyKey?: string;
  /** ETag from the last read, for configuration edits. */
  ifMatch?: string;
  signal?: AbortSignal;
  /** Skip the bearer token (login, OTP, invitation acceptance). */
  anonymous?: boolean;
  headers?: Record<string, string>;
}

export interface Reply<T> {
  data: T;
  etag: string | null;
  status: number;
}

export interface ApiClientOptions {
  /** Origin and prefix, e.g. `https://api.example.org`; empty for a same-origin proxy. */
  baseUrl: string;
  getAccessToken: () => string | null | Promise<string | null>;
  /** Get a fresh access token. Called at most once at a time; a null result ends the session. */
  refreshAccessToken?: () => Promise<string | null>;
  onSessionExpired?: () => void;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  defaultHeaders?: Record<string, string>;
}

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const parts: string[] = [];
  for (const [key, raw] of Object.entries(query)) {
    if (raw === undefined || raw === null || raw === "") continue;
    const value = Array.isArray(raw) ? raw.join(",") : String(raw);
    if (value === "") continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

/** Pull the cursor token out of a DRF `next` / `previous` URL. */
export function cursorFrom(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = /[?&]cursor=([^&]+)/.exec(url);
  return match ? decodeURIComponent(match[1]!) : null;
}

export class ApiClient {
  private refreshing: Promise<string | null> | null = null;

  constructor(private readonly options: ApiClientOptions) {}

  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<Reply<T>> {
    const first = await this.send(method, path, opts, false);
    if (first.status === 401 && !opts.anonymous && this.options.refreshAccessToken) {
      const token = await this.refresh();
      if (token) {
        const retry = await this.send(method, path, opts, true);
        return this.finish<T>(retry);
      }
      this.options.onSessionExpired?.();
    }
    return this.finish<T>(first);
  }

  get<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>("GET", path, opts).then((r) => r.data);
  }
  post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>("POST", path, { ...opts, body }).then((r) => r.data);
  }
  put<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>("PUT", path, { ...opts, body }).then((r) => r.data);
  }
  patch<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>("PATCH", path, { ...opts, body }).then((r) => r.data);
  }
  delete<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>("DELETE", path, opts).then((r) => r.data);
  }

  private refresh(): Promise<string | null> {
    if (!this.refreshing) {
      this.refreshing = this.options.refreshAccessToken!()
        .catch(() => null)
        .finally(() => {
          this.refreshing = null;
        });
    }
    return this.refreshing;
  }

  private async send(
    method: string,
    path: string,
    opts: RequestOptions,
    forceFreshToken: boolean,
  ): Promise<Response> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...this.options.defaultHeaders,
      ...opts.headers,
    };
    if (!opts.anonymous) {
      const token = await this.options.getAccessToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      else if (forceFreshToken) throw networkError(new Error("no token"));
    }
    const hasBody = opts.body !== undefined && method !== "GET";
    if (hasBody && !opts.formData) headers["Content-Type"] = "application/json";
    if (method !== "GET" && method !== "HEAD") {
      headers["Idempotency-Key"] = opts.idempotencyKey ?? uuid7();
    }
    if (opts.ifMatch) headers["If-Match"] = opts.ifMatch;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.options.timeoutMs ?? 30_000);
    const onAbort = () => controller.abort();
    opts.signal?.addEventListener("abort", onAbort);
    try {
      const doFetch = this.options.fetchImpl ?? fetch;
      return await doFetch(`${this.options.baseUrl}${path}${buildQuery(opts.query)}`, {
        method,
        headers,
        body: opts.formData ?? (hasBody ? JSON.stringify(opts.body) : undefined),
        signal: controller.signal,
        credentials: "same-origin",
      });
    } catch (cause) {
      throw networkError(cause);
    } finally {
      clearTimeout(timeout);
      opts.signal?.removeEventListener("abort", onAbort);
    }
  }

  private async finish<T>(response: Response): Promise<Reply<T>> {
    if (!response.ok) throw await problemFromResponse(response);
    const etag = response.headers.get("ETag");
    if (response.status === 204) return { data: undefined as T, etag, status: 204 };
    try {
      return { data: (await response.json()) as T, etag, status: response.status };
    } catch {
      throw new ApiError({
        status: response.status,
        code: "bad_response",
        detail: "The server sent a reply this app could not read.",
      });
    }
  }
}
