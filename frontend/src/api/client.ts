import createClient from "openapi-fetch";
import { fetchWithTimeout } from "../lib/api";
import type { paths } from "./schema";

// Every call through this client is timeout-bounded — see fetchWithTimeout's
// docstring in lib/api.ts for why, and isTimeoutError() for how callers can
// tell a timeout apart from a real failure and re-check server state instead
// of reporting a hard error.
export const client = createClient<paths>({
  baseUrl: "",
  fetch: (request: Request) => fetchWithTimeout(request),
});

client.use({
  async onRequest({ request }) {
    const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1];
    if (token && request.method !== "GET") {
      request.headers.set("X-CSRFToken", token);
    }
    return request;
  },
});
