import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { HealthRow, HealthSummary } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const summary: HealthSummary = {
  as_of: ["2026-11-13T09:00:00Z"], data_basis: ["fixture"], devices: 5,
  thresholds: { offline_hours: 24, stale_days: 7, disk_warning_free_pct: 15, disk_critical_free_pct: 5, minimum_agent_version: "", source: "default", approved_id: "" },
  dimensions: {
    connectivity: { seen_recently: 2, offline: 1, stale: 1, never_seen: 1 },
    agent_installed: { installed: 5, not_installed: 0, unknown: 0 },
    agent_version: { current: 0, old: 0, unparseable: 0, missing: 0, not_evaluated: 5 },
    disk: { ok: 0, warning: 3, critical: 1, free_pct_not_reported: 0, no_disks_reported: 0, not_collected: 1 },
    antivirus: { enabled_up_to_date: 0, enabled_outdated: 0, enabled_update_unknown: 3, disabled: 1, state_unknown: 0, not_reported: 0, not_collected: 1 },
    firewall: { enabled: 4, disabled: 0, state_unknown: 0, not_reported: 0, not_collected: 1 },
  },
  labels: {
    connectivity: { seen_recently: "Seen within the offline threshold", offline: "Offline", stale: "Stale", never_seen: "No last-seen time reported" },
    agent_installed: { installed: "Agent installed", not_installed: "Agent not installed", unknown: "Unknown" },
    agent_version: { current: "At or above", old: "Below", unparseable: "Not comparable", missing: "Missing", not_evaluated: "No approved minimum version" },
    disk: { ok: "OK", warning: "Below warning threshold", critical: "Below critical threshold", free_pct_not_reported: "No %", no_disks_reported: "No disks", not_collected: "Disk section not collected" },
    antivirus: { enabled_up_to_date: "Up to date", enabled_outdated: "Outdated", enabled_update_unknown: "Enabled, update state unknown", disabled: "Disabled", state_unknown: "Unknown", not_reported: "Not reported", not_collected: "Security section not collected" },
    firewall: { enabled: "Enabled", disabled: "Disabled", state_unknown: "Unknown", not_reported: "Not reported", not_collected: "Security section not collected" },
  },
  by_group: [{ group_external_id: "51", group_name: "Workstations", site: "HQ", devices: 5, disk_attention: 4 }],
  notes: ["Health is derived from the VSA X inventory snapshot at its publish time. It is not live monitoring telemetry."],
};
const row: HealthRow = {
  asset_id: "a5", hostname: "PC5", site_external_id: "5", site_name: "HQ", group_external_id: "51", group_name: "Workstations", device_type: "windows",
  last_seen_online: "2026-11-13T07:00:00Z", days_since_seen: 0.1, snapshot_at: "2026-11-13T09:00:00Z", client_version: "5.1.2",
  connectivity: "seen_recently", agent_installed: "installed", agent_version: "not_evaluated", disk: "critical", worst_disk_free_pct: 3,
  antivirus: "disabled", firewall: "enabled", patch_policy: "unknown", reported_aggregates: {}, hardware: { cpu: "", cores: "", logical_processors: "", memory_total_raw: "1234" },
};

function routes(customer = customerA) {
  window.sessionStorage.setItem("okp.selectedCustomer", customer.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customer]) },
    [`GET ${base}/device-health/summary/`]: { body: summary },
    [`GET ${base}/device-health/devices/`]: { body: page([row]) },
    [`GET ${base}/health-thresholds/`]: { body: [] },
    [`POST ${base}/health-thresholds/`]: { status: 201, body: {} },
  } as never);
}

describe("device health", () => {
  it("shows complete partitions, default thresholds and the not-live note", async () => {
    routes();
    renderApp("/device-health");
    const disk = await screen.findByRole("region", { name: "System disk free space" });
    expect(within(disk).getByText("of 5 devices")).toBeInTheDocument();
    expect(within(disk).getByRole("button", { name: "Disk section not collected" })).toBeEnabled();
    expect(within(disk).getByRole("button", { name: "No disks" })).toBeDisabled();
    expect(screen.getByText("documented defaults")).toBeInTheDocument();
    expect(screen.getByText(/agent age not evaluated/)).toBeInTheDocument();
    expect(screen.getByText(/not live monitoring telemetry/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Attention by group" })).toHaveTextContent("n/e");
    expect(screen.queryByRole("button", { name: "Propose thresholds" })).not.toBeInTheDocument();
  });

  it("clicking a cohort filters the device list", async () => {
    const { calls } = routes();
    renderApp("/device-health");
    const disk = await screen.findByRole("region", { name: "System disk free space" });
    await userEvent.click(within(disk).getByRole("button", { name: "Below critical threshold" }));
    expect(await screen.findByText(/Filtered by/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/device-health/devices/") && c.url.includes("disk=critical"))).toBe(true);
  });

  it("customer admin can propose thresholds", async () => {
    const { calls } = routes({ ...customerA, my_capabilities: [...customerA.my_capabilities, "customer.manage_exceptions"] });
    renderApp("/device-health");
    await userEvent.type(await screen.findByLabelText("Minimum agent version"), "5.1");
    await userEvent.type(screen.getByLabelText("Reason"), "Agent baseline");
    await userEvent.click(screen.getByRole("button", { name: "Propose thresholds" }));
    const post = calls.find((c) => c.method === "POST" && c.url === `${base}/health-thresholds/`);
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ minimum_agent_version: "5.1", offline_hours: 24, disk_critical_free_pct: 5 });
  });
});
