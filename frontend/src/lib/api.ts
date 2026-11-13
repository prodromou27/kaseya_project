/**
 * Portal API client. Same-origin only; session cookie + CSRF header. The browser never calls vendor APIs.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

export const UNAUTHENTICATED_EVENT = "okp:unauthenticated";
const CSRF_COOKIE = "okp_csrftoken";

export function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) return decodeURIComponent(trimmed.slice(prefix.length));
  }
  return null;
}

type Query = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
    }
  }
  return url.pathname + url.search;
}

async function parseError(resp: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `Request failed (${resp.status}).`;
  let details: unknown;
  let requestId = resp.headers.get("X-Request-ID");
  try {
    const body = (await resp.json()) as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
      requestId = body.error.request_id ?? requestId;
    }
  } catch {
    /* non-JSON error body: keep generic message */
  }
  return new ApiError(resp.status, code, message, requestId, details);
}

export async function apiRequest<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  options: { query?: Query; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRFToken"] = csrf;
  }
  const resp = await fetch(buildUrl(path, options.query), {
    method,
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (resp.status === 401) {
    window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
  }
  if (!resp.ok) throw await parseError(resp);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

/** Multipart upload (one file). The browser sets the multipart boundary; CSRF is sent as for JSON writes. */
export async function apiUpload<T>(path: string, file: File, field = "file"): Promise<T> {
  const form = new FormData();
  form.append(field, file);
  const headers: Record<string, string> = { Accept: "application/json" };
  const csrf = readCookie(CSRF_COOKIE);
  if (csrf) headers["X-CSRFToken"] = csrf;
  const resp = await fetch(buildUrl(path), { method: "POST", headers, credentials: "same-origin", body: form });
  if (resp.status === 401) window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => apiRequest<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>("POST", path, { body }),
  patch: <T>(path: string, body: unknown) => apiRequest<T>("PATCH", path, { body }),
  del: <T>(path: string) => apiRequest<T>("DELETE", path),
};

/** Human-readable error text including the request ID for support correlation. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const ref = error.requestId ? ` (ref ${error.requestId})` : "";
    if (error.details && typeof error.details === "object") {
      const first = Object.entries(error.details as Record<string, unknown>)[0];
      if (first) {
        const [field, msg] = first;
        const text = Array.isArray(msg) ? msg.join(" ") : String(msg);
        return `${field === "non_field_errors" || field === "detail" ? "" : `${field}: `}${text}${ref}`;
      }
    }
    return `${error.message}${ref}`;
  }
  return "Unexpected error. Check your connection and try again.";
}
