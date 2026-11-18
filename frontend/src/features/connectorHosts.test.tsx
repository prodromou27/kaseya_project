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
  return mockFetch(routesTable() as never);
}

function routesTable() {
  const admin = makeMe({ is_super_admin: true, global_capabilities: ["system.manage", "system.cross_customer", "system.audit.read"] });
  return {
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
  };
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

  it("enters the separate write token and validates the route on a test workstation in the portal", async () => {
    const { calls } = mockFetch({
      ...routesTable(),
      "POST /api/v1/integrations/i2/write-credential/": { body: { ...live, write_credential_configured: true, write_credential_source: "portal" } },
      "POST /api/v1/integrations/i2/validate-custom-field-route/": {
        body: { result: { route: "customfields", field: "PatchRing", field_id: "901", device: "d-1", value: "Ring test", observed: "Ring test" }, integration: live },
      },
    } as never);
    await openIntegrations();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const token = screen.getByRole("form", { name: "VSA X write token" });
    expect(token).toHaveTextContent("Status: not set");
    await userEvent.type(within(token).getByLabelText("Write token ID"), "w-id");
    await userEvent.type(within(token).getByLabelText("Write token secret"), "w-secret");
    await userEvent.click(within(token).getByRole("button", { name: "Save write token" }));
    const sent = calls.find((c) => c.url === "/api/v1/integrations/i2/write-credential/");
    expect(JSON.parse(String(sent?.init?.body))).toEqual({ token_id: "w-id", token_secret: "w-secret" });
    expect(within(token).getByLabelText("Write token secret")).toHaveValue("");

    const check = screen.getByRole("form", { name: "Validate on a test workstation" });
    await userEvent.type(within(check).getByLabelText("Test workstation"), "WS-TEST-01");
    await userEvent.type(within(check).getByLabelText("Custom field ID"), "901");
    await userEvent.type(within(check).getByLabelText("Test value"), "Ring test");
    const run = within(check).getByRole("button", { name: "Write test value and verify" });
    expect(run).toBeDisabled(); // needs the explicit test-workstation confirmation
    await userEvent.click(within(check).getByLabelText(/authorised test workstation/));
    await userEvent.click(run);
    expect(await within(check).findByText(/was written to d-1 and read back/)).toBeInTheDocument();
    const validation = calls.find((c) => c.url === "/api/v1/integrations/i2/validate-custom-field-route/");
    expect(JSON.parse(String(validation?.init?.body))).toEqual({ device: "WS-TEST-01", field_id: "901", value: "Ring test", confirm_test_device: true });
  });
});
