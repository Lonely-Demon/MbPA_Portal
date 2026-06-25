/**
 * CSRF-aware fetch wrapper.
 *
 * Django's session auth requires the CSRF token on every mutating request.
 * React must read it from the csrftoken cookie (CSRF_COOKIE_HTTPONLY=False).
 *
 * Usage:
 *   const data = await api("/api/identity/login/", { method: "POST", body: JSON.stringify({...}) });
 */

function getCsrfCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
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

  const response = await fetch(input, { ...init, headers, credentials: "include" });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, body);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: string,
  ) {
    super(`HTTP ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

/** Seed the CSRF cookie by hitting the Django csrf endpoint once on app mount. */
export async function initCsrf(): Promise<void> {
  await api("/api/csrf/");
}
