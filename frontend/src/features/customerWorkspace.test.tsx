import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;

describe("customer workspace", () => {
  it("summarises health, compliance, patching and network once each, with links into each investigation", async () => {
    const customer = { ...customerA, my_capabilities: ["customer.read", "customer.export"] };
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customer]) },
      [`GET ${base}/`]: { body: customer },
      [`GET ${base}/device-health/summary/`]: { body: { devices: 40, dimensions: { connectivity: { offline: 3, stale: 1 }, disk: { critical: 2 }, antivirus: { disabled: 1 } } } },
      [`GET ${base}/os-updates/summary/`]: { body: { devices_reporting_updates: 38, devices_by_severity: { Critical: 7 } } },
      [`GET ${base}/compliance-baselines/overview/`]: { body: { baselines: [{ id: "b1", name: "Workstation standard", score_pct: 80, devices_in_scope: 40, totals: { pass: 32, fail: 8, unknown: 0 } }] } },
      [`GET ${base}/software/third-party/`]: { body: { totals: { outdated: 12, outdated_not_covered: 9, outdated_no_policy: 1, outdated_covered: 2 } } },
      [`GET ${base}/subnets/`]: { body: { subnets: 5, by_status: { unassigned: 2 }, mixed_groups: 1, devices_outside_expected: 3 } },
      [`GET ${base}/datasets/`]: { body: [] },
      [`GET ${base}/reports/`]: { body: page([]) },
    } as never);
    renderApp(`/customers/${customerA.id}`);
    const summary = await screen.findByRole("region", { name: "Summary" });
    const offline = await within(summary).findByRole("link", { name: /Offline \/ stale/ });
    expect(offline).toHaveAttribute("href", "/device-health?connectivity=offline,stale,never_seen");
    expect(offline).toHaveTextContent("4");
    const compliance = screen.getByRole("region", { name: "Compliance" });
    expect(await within(compliance).findByRole("link", { name: "Workstation standard" })).toHaveAttribute("href", "/compliance/b1");
    expect(compliance).toHaveTextContent("80%");
    const patching = screen.getByRole("region", { name: "Patching" });
    expect(await within(patching).findByRole("link", { name: "10" })).toBeInTheDocument(); // 9 no rule + 1 no policy
    expect(await within(screen.getByRole("region", { name: "Network" })).findByRole("link", { name: "3" })).toHaveAttribute("href", "/groups?view=subnets");
    expect(screen.getByRole("button", { name: "Monthly scorecard (PDF)" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Device health" })).not.toBeInTheDocument(); // the figures above cover it
  });
});
