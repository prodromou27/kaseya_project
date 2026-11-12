import { describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/utils";
import { ApiError, UNAUTHENTICATED_EVENT, api, describeError } from "./api";

describe("api client", () => {
  it("sends CSRF token and JSON body on mutations, same-origin credentials", async () => {
    document.cookie = "okp_csrftoken=tok123";
    const { calls } = mockFetch({ "POST /api/v1/customers/": { status: 201, body: { id: "1" } } });
    await api.post("/customers/", { code: "X" });
    const init = calls[0]!.init!;
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok123");
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe(JSON.stringify({ code: "X" }));
  });

  it("does not send CSRF header on GET and drops empty query params", async () => {
    const { calls } = mockFetch({ "GET /api/v1/customers/": { body: { results: [] } } });
    await api.get("/customers/", { search: "", page: 2, x: undefined });
    expect(calls[0]!.url).toBe("/api/v1/customers/?page=2");
    expect((calls[0]!.init!.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
  });

  it("parses the standard error envelope", async () => {
    mockFetch({
      "GET /api/v1/x/": { status: 403, body: { error: { code: "permission_denied", message: "Nope.", request_id: "r-1" } } },
    });
    const error = await api.get("/x/").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, code: "permission_denied", requestId: "r-1" });
    expect(describeError(error)).toBe("Nope. (ref r-1)");
  });

  it("emits an unauthenticated event on 401", async () => {
    mockFetch({ "GET /api/v1/auth/me/": { status: 401, body: { error: { code: "not_authenticated", message: "x" } } } });
    const listener = vi.fn();
    window.addEventListener(UNAUTHENTICATED_EVENT, listener);
    await api.get("/auth/me/").catch(() => undefined);
    window.removeEventListener(UNAUTHENTICATED_EVENT, listener);
    expect(listener).toHaveBeenCalledOnce();
  });

  it("describes field validation errors", () => {
    const err = new ApiError(400, "validation_error", "The request was invalid.", "r-2", { email: ["No active user with this email."] });
    expect(describeError(err)).toBe("email: No active user with this email. (ref r-2)");
  });

  it("handles non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    const error = (await api.get("/x/").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(error.message).toBe("Request failed (502).");
  });
});
