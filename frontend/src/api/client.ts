import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const client = createClient<paths>({ baseUrl: "" });

client.use({
  async onRequest({ request }) {
    const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1];
    if (token && request.method !== "GET") {
      request.headers.set("X-CSRFToken", token);
    }
    return request;
  },
});
