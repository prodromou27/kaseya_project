import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Integration } from "../lib/types";
import { makeMe, mockFetch, page, renderApp } from "../test/utils";

const live = {
  id: "i2", name: "VSA live", provider: "vsa_x", base_url: "https://vsa.example.com", region: "", credential_configured: false,
  credential_source: "none", credential_set_at: null, credential_set_by: null, enabled: false, installed_updates_budget: 0,
  applied_policies_budget: 0, notifications_budget: 0, custom_fields_budget: 0, verify_tls: true, max_rps: "0.5",
  status: "idle", is_fixture: false, last_test_at: null, last_test_outcome: "", last_test_result: {},
} as unknown as Integration;
const withToken = { ...live, credential_configured: true, credential_source: "portal", credential_set_at: "2026-11-13T10:00:00Z", credential_set_by: "super@example.test" };

function routes(row: Integration, available = true) {
  const admin = makeMe({ is_super_admin: true, global_capabilities: ["system.manage", "system.cross_customer", "system.audit.read"] });
  return mockFetch({
    "GET /api/v1/auth/me/": { body: admin },
    "GET /api/v1/customers/": { body: page([]) },
    "GET /api/v1/mappings/": { body: page([]) },
    "GET /api/v1/integrations/": { body: page([row]) },
    "GET /api/v1/integrations/credential-storage/": { body: { available } },
    "POST /api/v1/integrations/i2/credential/": { body: withToken },
    "DELETE /api/v1/integrations/i2/credential/": { body: live },
  } as never);
}

async function openIntegrations() {
  renderApp("/admin");
  await userEvent.click(await screen.findByRole("tab", { name: "Integrations" }));
}

describe("portal-entered API token", () => {
  it("sends the token pair once with a password-type secret field and never displays it", async () => {
    const { calls } = routes(live);
    await openIntegrations();
    await userEvent.click(await screen.findByRole("button", { name: "Set API token" }));
    const form = screen.getByRole("form", { name: "API token: VSA live" });
    const secret = within(form).getByLabelText("Token secret");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");
    await userEvent.type(within(form).getByLabelText("Token ID"), "fake-id");
    await userEvent.type(secret, "FAKE-SECRET");
    await userEvent.click(within(form).getByRole("button", { name: "Save token" }));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/credential/"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ token_id: "fake-id", token_secret: "FAKE-SECRET" });
    expect(await screen.findByText(/Integration instances/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "API token: VSA live" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("FAKE-SECRET");
  });

  it("shows who set the token and offers replace/remove", async () => {
    const { calls } = routes(withToken as Integration);
    await openIntegrations();
    expect(await screen.findByText("Token set in portal")).toBeInTheDocument();
    expect(screen.getByText(/super@example\.test/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace API token" })).toBeEnabled();
    const confirm = window.confirm;
    window.confirm = () => true;
    await userEvent.click(screen.getByRole("button", { name: "Remove token" }));
    window.confirm = confirm;
    expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/credential/"))).toBe(true);
  });

  it("explains when the server has no encryption key", async () => {
    routes(live, false);
    await openIntegrations();
    expect(await screen.findByText(/no credential encryption key/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set API token" })).toBeDisabled();
  });
});
