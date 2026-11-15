import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const row = (code: string, devices: number, offline: number, compliance: number | null, stale = false) => ({
  id: `${code}-id`, code, name: `${code} Ltd`, status: "active", devices, offline, disk_critical: 0, antivirus_issues: 1,
  critical_updates: null, outdated_software_devices: 2, compliance_pct: compliance, baselines: compliance === null ? 0 : 1,
  as_of: stale ? null : "2026-11-15T10:00:00Z", stale,
});

describe("all customers overview", () => {
  it("lists customers side by side, sorts and marks attention and stale data", async () => {
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA]) },
      "GET /api/v1/customers/overview/": { body: { count: 2, truncated: false, results: [row("ACME", 40, 3, 92.5), row("BETA", 12, 0, null, true)] } },
    } as never);
    renderApp("/all-customers");
    const table = await screen.findByRole("table", { name: "All customers" });
    const [acme, beta] = within(table).getAllByRole("row").slice(1) as [HTMLElement, HTMLElement];
    expect(acme).toHaveTextContent("ACME");
    expect(acme).toHaveTextContent("92.5%");
    expect(beta).toHaveTextContent("never synced");
    expect(within(beta).getAllByText("—").length).toBeGreaterThan(0);
    await userEvent.click(within(table).getByRole("button", { name: /Devices/ }));
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("ACME"); // descending: 40 before 12
    expect(within(acme).getByRole("link", { name: "ACME" })).toHaveAttribute("href", "/customers/ACME-id");
  });
});
