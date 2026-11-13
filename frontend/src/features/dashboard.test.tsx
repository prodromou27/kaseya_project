import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Customer, HealthSummary, TrendResponse } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const customerB: Customer = { ...customerA, id: "bbbbbbbb-0000-0000-0000-000000000002", code: "BETA", name: "Beta plc" };
const base = `/api/v1/customers/${customerA.id}`;

const health = {
  as_of: ["2026-11-13T10:00:00Z"], data_basis: ["live"], devices: 40, thresholds: {}, labels: {}, by_group: [], notes: [],
  dimensions: {
    connectivity: { seen_recently: 35, offline: 3, stale: 1, never_seen: 1 },
    disk: { ok: 30, warning: 6, critical: 2 },
    antivirus: { enabled_up_to_date: 37, disabled: 1, enabled_outdated: 2 },
    firewall: { enabled: 39, disabled: 1 },
  },
} as unknown as HealthSummary;

const trends: TrendResponse = {
  days: 7, method: "",
  points: [{
    day: "2026-11-13", as_of: "2026-11-13T10:00:00Z", source: "VSA", generation_id: "g1", data_basis: "live", devices: 40,
    software: { evaluation_id: "e", catalog_revision_ids: [], algorithm_version: "v", current: 90, outdated: 12, comparable: 102, eligible: 110, devices_with_outdated: 9 },
    os_updates: { devices_reporting: 38, devices_not_reporting: 2, devices_with_available: 20, devices_with_critical: 7 },
  }],
};

function routes(opts: { superAdmin?: boolean; customers?: Customer[]; integrations?: unknown[]; approved?: number } = {}) {
  const me = opts.superAdmin
    ? makeMe({ is_super_admin: true, memberships: [], global_capabilities: ["system.manage", "system.cross_customer"] })
    : makeMe();
  const customers = opts.customers ?? [customerA];
  return mockFetch({
    "GET /api/v1/auth/me/": { body: me },
    "GET /api/v1/customers/": { body: page(customers) },
    "GET /api/v1/integrations/": { body: page(opts.integrations ?? []) },
    "GET /api/v1/connector-hosts/": { body: { results: [], deployment: [] } },
    "GET /api/v1/mappings/": { body: { ...page([]), count: opts.approved ?? 0 } },
    [`GET ${base}/device-health/summary/`]: { body: health },
    [`GET ${base}/trends/`]: { body: trends },
  } as never);
}

describe("dashboard", () => {
  it("shows headline numbers that link to their pages, and the user's role instead of capability codes", async () => {
    routes();
    renderApp("/");
    const summary = await screen.findByRole("region", { name: "Summary" });
    const offline = within(summary).getByRole("link", { name: /Offline \/ stale/ });
    expect(offline).toHaveTextContent("5");
    expect(offline).toHaveAttribute("href", "/device-health");
    expect(within(summary).getByRole("link", { name: /Missing critical updates/ })).toHaveTextContent("7of 38 devices reporting");
    expect(within(summary).getByRole("link", { name: /Outdated software/ })).toHaveAttribute("href", "/software");
    expect(within(summary).getByRole("link", { name: /Antivirus issues/ })).toHaveTextContent("3");
    expect(screen.getByText("Engineer")).toBeInTheDocument();
    expect(screen.queryByText(/customer\.export/)).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Setup checklist" })).not.toBeInTheDocument();
  });

  it("lets a multi-customer user pick a customer in place", async () => {
    routes({ customers: [customerA, customerB] });
    renderApp("/assets");
    const list = await screen.findByRole("list", { name: "Customers" });
    await userEvent.click(within(list).getByRole("button", { name: /BETA/ }));
    expect(screen.getByLabelText("Customer")).toHaveValue(customerB.id);
  });

  it("guides a super admin through setup until data can flow", async () => {
    routes({ superAdmin: true, customers: [] });
    renderApp("/");
    const checklist = await screen.findByRole("region", { name: "Setup checklist" });
    expect(checklist).toHaveTextContent("0 of 7 steps done");
    expect(within(checklist).getByRole("link", { name: "Allow your VSA X hostname" })).toHaveAttribute("href", "/admin?tab=integrations");
    expect(within(checklist).getByRole("link", { name: "Create a customer" })).toHaveAttribute("href", "/customers");
  });

  it("hides the setup checklist once everything is done", async () => {
    routes({
      superAdmin: true,
      approved: 1,
      integrations: [{ id: "i", name: "VSA", provider: "vsa_x", is_fixture: false, credential_configured: true, last_test_outcome: "ok", enabled: true }],
    });
    renderApp("/");
    expect(await screen.findByRole("region", { name: "Summary" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Setup checklist" })).not.toBeInTheDocument();
  });

  it("groups the main navigation into sections", async () => {
    routes();
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const section of ["Overview", "Inventory", "Patching & software", "Onboarding & reports"]) {
      expect(within(nav).getByText(section)).toBeInTheDocument();
    }
    expect(within(nav).queryByText("Administration")).not.toBeInTheDocument(); // not a super admin
    expect(within(nav).queryByRole("link", { name: /IT Glue/ })).not.toBeInTheDocument();
  });
});
