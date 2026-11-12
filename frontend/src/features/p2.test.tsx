import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TrendChart } from "../components/TrendChart";
import type { OsUpdateSummary, ReportTemplate, TrendResponse } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const exporter = { ...customerA, my_capabilities: ["customer.read", "customer.export", "customer.sync"] };
const base = `/api/v1/customers/${customerA.id}`;

const osSummary: OsUpdateSummary = {
  as_of: ["2026-11-12T09:00:00Z"], generation_ids: ["g1"], data_basis: ["fixture"], devices_total: 10,
  available_section: { collected: 6, not_collected: 2, not_supported: 2, not_requested: 0, failed: 0, carried_forward: 0 },
  devices_reporting_updates: 6, devices_with_available_updates: 4, devices_with_zero_available: 2,
  devices_by_severity: { Critical: 3, Important: 1 }, devices_with_other_severity: 0,
  installed_section: { collected: 3, not_collected: 0, not_supported: 2, not_requested: 5, failed: 0, carried_forward: 0 },
  top_available_updates: [{ os_update_id: "u1", kb_article: "5099001", title: "DEMO update", severity: "Critical", devices: 3 }],
  freshness_note: "The VSA X API does not document a per-device update-scan timestamp.",
  scope_note: "Operating-system updates reported by VSA X only. Not third-party application patches.",
};

const templates: ReportTemplate[] = [
  { key: "asset_inventory", title: "Asset inventory (RPT-01)", description: "Devices.", formats: ["csv", "xlsx", "pdf"],
    required_capabilities: ["customer.export", "customer.read"], columns: [], limitations: "",
    filters: { os: { type: "CharField", required: false } } },
  { key: "customer_audit_log", title: "Customer audit log", description: "", formats: ["csv"],
    required_capabilities: ["customer.export", "customer.audit.read"], columns: [], limitations: "", filters: {} },
];

function routes(extra: Record<string, unknown> = {}) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([exporter]) },
    [`GET ${base}/datasets/`]: { body: [] },
    [`GET ${base}/os-updates/summary/`]: { body: osSummary },
    [`GET ${base}/os-updates/`]: { body: page([]) },
    [`GET ${base}/reports/`]: { body: page([]) },
    [`GET ${base}/trends/`]: { body: { days: 90, points: [], method: "m" } satisfies TrendResponse },
    "GET /api/v1/report-templates/": { body: templates },
    ...extra,
  } as never);
}

describe("windows updates", () => {
  it("never presents devices without update data as zero", async () => {
    routes();
    renderApp("/windows-updates");
    expect(await screen.findByText("Devices with available updates")).toBeInTheDocument();
    expect(screen.getByText("of 6 devices that reported the AvailableUpdates section")).toBeInTheDocument();
    expect(screen.getByText("only devices that returned an empty list")).toBeInTheDocument();
    expect(screen.getByText(/2 not collected · 2 non-Windows — never counted as zero/)).toBeInTheDocument();
    expect(screen.getByText(/Not third-party application patches/)).toBeInTheDocument();
    expect(screen.getByText(/does not document a per-device update-scan timestamp/)).toBeInTheDocument();
  });

  it("filters update records by KB from the top-updates table", async () => {
    const { calls } = routes();
    renderApp("/windows-updates");
    await userEvent.click(await screen.findByRole("button", { name: "KB5099001" }));
    expect(calls.some((c) => c.url.includes("/os-updates/?") && c.url.includes("kb=5099001"))).toBe(true);
  });
});

describe("reports", () => {
  it("offers only templates the user may run, with their formats", async () => {
    const { calls } = routes({ [`POST ${base}/reports/`]: { status: 202, body: { id: "r1" } } });
    renderApp("/reports");
    const report = await screen.findByLabelText("Report");
    expect(within(report).getAllByRole("option").map((o) => o.textContent)).toEqual(["Asset inventory (RPT-01)"]);
    const format = screen.getByLabelText("Format");
    expect(within(format).getAllByRole("option").map((o) => o.textContent)).toEqual(["CSV", "XLSX", "PDF"]);
    await userEvent.selectOptions(format, "pdf");
    await userEvent.type(screen.getByLabelText("os"), "Windows 11");
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ report_type: "asset_inventory", format: "pdf", filters: { os: "Windows 11" } });
  });
});

describe("trend chart", () => {
  const props = {
    title: "Devices over time",
    unit: "devices",
    xLabels: ["2026-11-10", "2026-11-11", "2026-11-12"],
    series: [
      { key: "a", label: "In inventory", values: [10, 12, 12] },
      { key: "b", label: "With outdated", values: [4, null, 3] },
    ],
  };

  it("has a legend, direct end labels and an accessible table view", async () => {
    render(<TrendChart {...props} />);
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("In inventoryWith outdated");
    expect(screen.getByText("In inventory: 12")).toBeInTheDocument();
    expect(screen.getByText("With outdated: 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show table" }));
    const table = screen.getByRole("table", { name: "Devices over time" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByText("n/a")).toBeInTheDocument(); // gaps are shown, never interpolated
  });
});
