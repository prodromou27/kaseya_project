import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ConnectionTestResult, Integration } from "../lib/types";
import { makeMe, mockFetch, page, renderApp } from "../test/utils";

const integration: Integration = {
  id: "i1", name: "VSA demo", provider: "vsa_x", base_url: "https://vsa.invalid", region: "", credential_ref: "",
  credential_configured: false, enabled: true, installed_updates_budget: 0, applied_policies_budget: 0, verify_tls: true,
  max_rps: "20", status: "idle", is_fixture: true, last_test_at: null, last_test_outcome: "", last_test_result: {},
} as unknown as Integration;

const ok: ConnectionTestResult = {
  outcome: "ok", message: "Connected. The token can read the rate-limit endpoint.", data_basis: "fixture", latency_ms: 12,
  failed_request_limits: [{ limit: 100, remaining: 100, period_seconds: 60, reset_seconds: null, retry_seconds: null }],
  endpoint_limits: [{ endpoint: "Get Device Assets", rules: [{ limit: 3600, remaining: 0, period_seconds: 3600, reset_seconds: 3580, retry_seconds: 122 }] }],
};

function routes(result: ConnectionTestResult) {
  const admin = makeMe({ is_super_admin: true, global_capabilities: ["system.manage", "system.cross_customer", "system.audit.read"] });
  return mockFetch({
    "GET /api/v1/auth/me/": { body: admin },
    "GET /api/v1/customers/": { body: page([]) },
    "GET /api/v1/mappings/": { body: page([]) },
    "GET /api/v1/integrations/": { body: page([integration]) },
    "POST /api/v1/integrations/i1/test-connection/": { body: result },
  } as never);
}

describe("connection test", () => {
  it("shows outcome, latency and reported rate limits, labelling fixture data", async () => {
    routes(ok);
    renderApp("/admin");
    await userEvent.click(await screen.findByRole("tab", { name: "Integrations" }));
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByText(/Connected\. The token can read/)).toHaveTextContent("ok, 12 ms, fixture");
    expect(screen.getByText(/documented example, not a live server/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Endpoint rate limits" })).toHaveTextContent("Get Device Assets");
    expect(screen.getByText("122s")).toBeInTheDocument();
  });

  it("explains an authentication failure", async () => {
    routes({ outcome: "auth_failed", http_status: 401, message: "The VSA X server rejected the credentials (401/403). Check the token reference; not retried.", data_basis: "live", latency_ms: 30 });
    renderApp("/admin");
    await userEvent.click(await screen.findByRole("tab", { name: "Integrations" }));
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByText(/rejected the credentials/)).toHaveTextContent("auth_failed, HTTP 401");
  });
});
