import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Integration, ProviderSpec } from "../lib/types";
import { makeMe, mockFetch, page, renderApp } from "../test/utils";

const live = {
  id: "i2", name: "VSA live", provider: "vsa_x", base_url: "https://vsa.example.com", region: "", credential_configured: false,
  credential_source: "none", credential_set_at: null, credential_set_by: null, enabled: false, installed_updates_budget: 0,
  applied_policies_budget: 0, notifications_budget: 0, custom_fields_budget: 0, verify_tls: true, max_rps: "0.5",
  status: "idle", is_fixture: false, last_test_at: null, last_test_outcome: "", last_test_result: {},
} as unknown as Integration;
const withToken = { ...live, credential_configured: true, credential_source: "portal", credential_set_at: "2026-11-13T10:00:00Z", credential_set_by: "super@example.test" };

const PROVIDERS: ProviderSpec[] = [
  {
    key: "vsa_x", label: "Kaseya VSA X", implemented: true, phase: "Phase 1 (available)", base_url_help: "https://<your VSA X server>", notes: "",
    fields: [
      { name: "token_id", label: "Token ID", secret: false, max_length: 200, help: "", pattern_message: "" },
      { name: "token_secret", label: "Token secret", secret: true, max_length: 500, help: "", pattern_message: "" },
    ],
  },
  {
    key: "itglue", label: "IT Glue", implemented: false, phase: "Planned (P3)", base_url_help: "", notes: "",
    fields: [{ name: "api_key", label: "API key", secret: true, max_length: 500, help: "", pattern_message: "" }],
  },
];

function routes(row: Integration, available = true) {
  const admin = makeMe({ is_super_admin: true, global_capabilities: ["system.manage", "system.cross_customer", "system.audit.read"] });
  return mockFetch({
    "GET /api/v1/auth/me/": { body: admin },
    "GET /api/v1/customers/": { body: page([]) },
    "GET /api/v1/mappings/": { body: page([]) },
    "GET /api/v1/integrations/": { body: page([row]) },
    "GET /api/v1/integrations/providers/": { body: PROVIDERS },
    "GET /api/v1/connector-hosts/": { body: { results: [], deployment: [] } },
    "GET /api/v1/integrations/credential-storage/": { body: { available } },
    "POST /api/v1/integrations/i2/credential/": { body: withToken },
    "DELETE /api/v1/integrations/i2/credential/": { body: live },
  } as never);
}

async function openIntegrations() {
  renderApp("/admin");
  await userEvent.click(await screen.findByRole("tab", { name: "Integrations" }));
}

describe("credentials entered in the portal", () => {
  it("renders the provider's fields, masks secrets and never displays them", async () => {
    const { calls } = routes(live);
    await openIntegrations();
    await userEvent.click(await screen.findByRole("button", { name: "Set credentials" }));
    const form = await screen.findByRole("form", { name: "Credentials: VSA live" });
    const secret = await within(form).findByLabelText("Token secret");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");
    await userEvent.type(within(form).getByLabelText("Token ID"), "fake-id");
    await userEvent.type(secret, "FAKE-SECRET");
    await userEvent.click(within(form).getByRole("button", { name: "Save credentials" }));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/credential/"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ fields: { token_id: "fake-id", token_secret: "FAKE-SECRET" } });
    expect(await screen.findByText(/Integration instances/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Credentials: VSA live" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("FAKE-SECRET");
  });

  it("lists every provider, available or planned, and only offers available ones", async () => {
    routes(live);
    await openIntegrations();
    const cards = await screen.findByRole("region", { name: "Available integrations" });
    expect(await within(cards).findByText("IT Glue")).toBeInTheDocument();
    expect(within(cards).getByText("Planned")).toBeInTheDocument();
    const select = screen.getByLabelText("Provider");
    expect(within(select).queryByRole("option", { name: "IT Glue" })).not.toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Kaseya VSA X" })).toBeInTheDocument();
  });

  it("shows who set the credentials and offers replace/remove", async () => {
    const { calls } = routes(withToken as Integration);
    await openIntegrations();
    expect(await screen.findByText("Set in portal (encrypted)")).toBeInTheDocument();
    expect(screen.getByText(/super@example\.test/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace credentials" })).toBeEnabled();
    const confirm = window.confirm;
    window.confirm = () => true;
    await userEvent.click(screen.getByRole("button", { name: "Remove credentials" }));
    window.confirm = confirm;
    expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/credential/"))).toBe(true);
  });

  it("explains when the server has no encryption key", async () => {
    routes(live, false);
    await openIntegrations();
    expect(await screen.findByText(/no credential encryption key/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set credentials" })).toBeDisabled();
  });
});
