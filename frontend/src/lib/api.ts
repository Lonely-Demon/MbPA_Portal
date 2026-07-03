/**
 * CSRF-aware fetch wrapper, plus small helpers shared across pages.
 *
 * Django's session auth requires the CSRF token on every mutating request.
 * React must read it from the csrftoken cookie (CSRF_COOKIE_HTTPONLY=False).
 *
 * L-1: most pages use the typed client in ../api/client.ts (generated from
 * the backend's OpenAPI schema) instead. This module stays around for two
 * things that client doesn't cover:
 *   - `api()` for GET /api/applications/status/, whose ?application_number
 *     query param isn't declared in the OpenAPI schema (the Django view
 *     reads it manually), so openapi-fetch has no typed way to pass it.
 *   - `uploadFile()`, a single shared multipart-upload helper — previously
 *     each upload call site (document upload, signed-certificate upload)
 *     duplicated its own CSRF-cookie-reading fetch() call.
 *   - `initCsrf()`, called once on app mount (see App.tsx).
 *
 * Usage:
 *   const data = await api("/api/identity/login/", { method: "POST", body: JSON.stringify({...}) });
 */

function getCsrfCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

// Generous but bounded — large multi-file uploads can legitimately take a
// while, but a request hanging forever is never an acceptable UI state.
export const API_TIMEOUT_MS = 65000;

export interface TimeoutError extends Error {
  isTimeout: true;
}

function isAbortError(err: unknown): err is DOMException {
  return err instanceof DOMException && err.name === "AbortError";
}

/**
 * Wraps a `Request` with a timeout, aborting and throwing a recognizable
 * `TimeoutError` (`isTimeout: true`) rather than hanging indefinitely.
 * Passed to openapi-fetch's `createClient({ fetch })` in api/client.ts so
 * every typed call gets this for free, plus used directly by api()/uploadFile()
 * below.
 */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = API_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (err) {
    if (isAbortError(err)) {
      const timeoutError = new Error(
        "Taking longer than usual to respond.",
      ) as TimeoutError;
      timeoutError.name = "TimeoutError";
      timeoutError.isTimeout = true;
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function isTimeoutError(err: unknown): err is TimeoutError {
  return err instanceof Error && (err as TimeoutError).isTimeout === true;
}

export async function api<T = unknown>(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const isMutating = !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method);

  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");
  if (isMutating) {
    headers.set("X-CSRFToken", getCsrfCookie());
  }

  const response = await fetchWithTimeout(input, { ...init, headers, credentials: "include" });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, body);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly body: string;

  constructor(status: number, statusText: string, body: string) {
    super(`HTTP ${status} ${statusText}`);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
    this.body = body;
  }
}

/** Seed the CSRF cookie by hitting the Django csrf endpoint once on app mount. */
export async function initCsrf(): Promise<void> {
  await api("/api/csrf/");
}

/**
 * POST a multipart FormData body (a file upload) with the CSRF header set.
 * Returns the raw Response — callers decide how to handle non-JSON or
 * non-2xx responses for their specific upload endpoint.
 */
export async function uploadFile(
  url: string,
  formData: FormData,
  timeoutMs: number = API_TIMEOUT_MS,
): Promise<Response> {
  return fetchWithTimeout(
    url,
    {
      method: "POST",
      body: formData,
      headers: { "X-CSRFToken": getCsrfCookie() },
      credentials: "include",
    },
    timeoutMs,
  );
}
