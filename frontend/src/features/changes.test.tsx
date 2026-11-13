import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ChangeDevice, ChangeSummary } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const summary: ChangeSummary = {
  from: { id: "g1", published_at: "2026-11-12T09:00:00Z", data_basis: "fixture", devices: 4 },
  to: { id: "g2", published_at: "2026-11-13T09:00:00Z", data_basis: "fixture", devices: 4 },
  counts: { device_added: 1, device_removed: 1, hostname: 1, group: 1, site: 0, os: 0, agent_version: 1, agent_installed: 0, ip_addresses: 1, software: 1 },
  devices_compared: 3, not_compared: { ip_addresses: 1, software: 0 },
  note: "Changes are differences observed between two complete VSA X snapshots. No person is attributed.",
};
const device: ChangeDevice = {
  asset_id: "a1", external_id: "11-dev-001", hostname: "PC1-RENAMED", group_external_id: "51",
  changes: [{ kind: "hostname", from: "PC1", to: "PC1-RENAMED" }, { kind: "software", added: ["7-Zip 24.08"], removed: ["7-Zip 23.01"] }],
};

function routes() {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/changes/snapshots/`]: { body: [] },
    [`GET ${base}/changes/`]: { body: summary },
    [`GET ${base}/changes/devices/`]: { body: page([device]) },
  } as never);
}

describe("inventory changes", () => {
  it("shows the snapshot window, uncompared sections and observed differences", async () => {
    const { calls } = routes();
    renderApp("/changes");
    expect(await screen.findByText(/No person is attributed/)).toBeInTheDocument();
    expect(screen.getByText(/Not compared \(section missing in either snapshot\): IP addresses 1/)).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Changed devices" });
    expect(table).toHaveTextContent("PC1 → PC1-RENAMED");
    expect(table).toHaveTextContent("+ 7-Zip 24.08");
    expect(screen.getByRole("button", { name: /Site changed/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Software changed/ }));
    expect(calls.some((c) => c.url.includes("/changes/devices/") && c.url.includes("kind=software"))).toBe(true);
  });
});
