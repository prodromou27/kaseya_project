import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Integration } from "../lib/types";
import { makeMe, mockFetch, page, renderApp } from "../test/utils";

const live = {
  id: "i2", name: "VSA live", provider: "vsa_x", base_url: "https://vsa.example.com", region: "", credential_configured: true,
  credential_source: "portal", credential_set_at: "2026-11-13T10:00:00Z", credential_set_by: "super@example.test", enabled: false,
  installed_updates_budget: 0, applied_policies_budget: 5, notifications_budget: 0, custom_fields_budget: 0, verify_tls: true,
  max_rps: "0.50", status: "idle", is_fixture: false, last_test_at: null, last_test_outcome: "", last_test_result: {},
} as unknown as Integration;

function routes() {
  const admin = makeMe({ is_super_admin: true, global_capabilities: ["system.manage", "system.cross_customer", "system.audit.read"] });
  return mockFetch({
    "GET /api/v1/auth/me/": { body: admin },
    "GET /api/v1/customers/": { body: page([]) },
    "GET /api/v1/mappings/": { body: page([]) },
    "GET /api/v1/integrations/": { body: page([live]) },
    "GET /api/v1/integrations/credential-storage/": { body: { available: true } },
    "GET /api/v1/connector-hosts/": {
      body: {
        results: [{ id: "h1", provider: "vsa_x", hostname: "vsa.example.com", reason: "pilot", added_by: "super@example.test", created_at: "2026-11-13T09:00:00Z" }],
        deployment: [{ provider: "itglue", hostname: "api.itglue.com" }],
      },
    },
    "POST /api/v1/connector-hosts/": { status: 201, body: {} },
    "PATCH /api/v1/integrations/i2/": { body: live },
  } as never);
}

async function openIntegrations() {
  renderApp("/admin");
  await userEvent.click(await screen.findByRole("tab", { name: "Integrations" }));
}

describe("API settings managed in the portal", () => {
  it("lists allowed VSA hosts (not other providers) and allows a new one", async () => {
    const { calls } = routes();
    await openIntegrations();
    const list = await screen.findByRole("list", { name: "Allowed hosts" });
    expect(list).toHaveTextContent("vsa.example.com");
    expect(list).not.toHaveTextContent("api.itglue.com");
    const form = screen.getByRole("form", { name: "Allow API host" });
    await userEvent.type(within(form).getByLabelText("VSA X hostname"), "tenant.vsax.net");
    await userEvent.click(within(form).getByRole("button", { name: "Allow host" }));
    const post = calls.find((c) => c.method === "POST" && c.url === "/api/v1/connector-hosts/");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ provider: "vsa_x", hostname: "tenant.vsax.net", reason: "" });
  });

  it("edits integration settings and warns that a new base URL removes the token", async () => {
    const { calls } = routes();
    await openIntegrations();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit integration: VSA live" });
    const url = within(form).getByLabelText("Base URL");
    await userEvent.clear(url);
    await userEvent.type(url, "https://vsa2.example.com");
    const budget = within(form).getByLabelText("Notifications budget / sync");
    await userEvent.clear(budget);
    await userEvent.type(budget, "25");
    let asked = "";
    const confirm = window.confirm;
    window.confirm = (msg?: string) => { asked = String(msg); return true; };
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    window.confirm = confirm;
    expect(asked).toMatch(/removes the stored API token/);
    const patch = calls.find((c) => c.method === "PATCH");
    expect(JSON.parse(String(patch?.init?.body))).toMatchObject({ base_url: "https://vsa2.example.com", notifications_budget: 25, applied_policies_budget: 5 });
  });
});
