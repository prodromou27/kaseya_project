import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}/compliance-baselines/`;
const totals = { pass: 3, fail: 6, unknown: 1 };
const rules = [
  { id: "r1", kind: "required_software", label: "“Chrome” is installed (version 131 or later)", severity: "high", counts: { pass: 4, fail: 5, unknown: 1 } },
  { id: "r2", kind: "antivirus_healthy", label: "Antivirus enabled and up to date", severity: "medium", counts: { pass: 8, fail: 1, unknown: 1 } },
];
const groups = [{ site: "HQ", group_external_id: "1", group_name: "Servers", score_pct: 0, pass: 0, fail: 2, unknown: 0 }];
const overview = {
  baselines: [{ id: "b1", name: "Workstation standard", devices_in_scope: 10, totals, score_pct: 33.3, rules, groups }],
  rule_kinds: [{ kind: "required_software", label: "Required software is installed" }, { kind: "antivirus_healthy", label: "Antivirus enabled and up to date" }],
};
const baseline = { id: "b1", name: "Workstation standard", description: "", enabled: true, scope_device_type: "", scope_site_external_id: "",
  scope_group_external_id: "", rules: [], created_by: "a@x", created_at: "2026-11-15T10:00:00Z", updated_at: "2026-11-15T10:00:00Z" };
const results = {
  baseline_id: "b1", devices_in_scope: 10, totals, score_pct: 33.3, rules, groups,
  count: 1, page: 1, page_size: 50,
  results: [{ asset_id: "a1", hostname: "PC-7", site_name: "HQ", site_external_id: "1", group_name: "Servers", group_external_id: "1",
    device_type: "windows", status: "fail", failed: 1, failed_high: 1,
    results: [{ rule_id: "r1", state: "fail", reason: "Google Chrome 130.0 is older than 131", severity: "high" },
      { rule_id: "r2", state: "unknown", reason: "Antivirus state not reported", severity: "medium" }] }],
};

function routes(capabilities: string[] = ["customer.read"]) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([{ ...customerA, my_capabilities: capabilities }]) },
    [`GET ${base}overview/`]: { body: overview },
    [`GET ${base}`]: { body: page([baseline]) },
    [`GET ${base}b1/`]: { body: baseline },
    [`GET ${base}b1/results/`]: { body: results },
  } as never);
}

describe("compliance", () => {
  it("shows each baseline's score and opens its failing devices with reasons", async () => {
    routes();
    renderApp("/compliance");
    const card = await screen.findByRole("link", { name: /Workstation standard/ });
    expect(card).toHaveTextContent("33.3%");
    expect(card).toHaveTextContent("6 not compliant");
    expect(screen.queryByRole("button", { name: "New baseline" })).not.toBeInTheDocument(); // read-only member
    await userEvent.click(card);
    const table = await screen.findByRole("table", { name: "Compliance by device" });
    expect(within(table).getByText("PC-7")).toBeInTheDocument();
    expect(table).toHaveTextContent("Google Chrome 130.0 is older than 131");
    expect(table).toHaveTextContent("Antivirus state not reported");
    expect(screen.getByRole("button", { name: /“Chrome” is installed/ })).toHaveTextContent("5 failing");
  });

  it("lets a customer admin start a baseline with rule-specific fields", async () => {
    routes(["customer.read", "customer.manage_exceptions"]);
    renderApp("/compliance");
    await userEvent.click(await screen.findByRole("button", { name: "New baseline" }));
    const form = screen.getByRole("form", { name: "New baseline" });
    const kind = within(form).getByLabelText("Rule");
    await userEvent.selectOptions(kind, "required_software");
    expect(within(form).getByLabelText("Program name contains")).toBeRequired();
    expect(within(form).getByLabelText("Minimum version (optional)")).not.toBeRequired();
  });
});
