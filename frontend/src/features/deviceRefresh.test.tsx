import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const detail = {
  id: "a1", external_id: "ext-1", active: true, in_current_dataset: true,
  customer: { id: customerA.id, code: "ACME", name: "Acme Ltd" },
  asset: {
    id: "a1", external_id: "ext-1", hostname: "DEMOA-WS001", description: "", device_type: "windows",
    group_name: "Workstations", site_external_id: "2001", site_name: "HQ", group_external_id: "20011",
    organization_external_id: "1001", client_version: "5.1.2", last_seen_online: "2026-11-12T08:00:00Z",
    last_seen_stale: false, os_name: "Windows 11", os_version: "10.0", manufacturer: "", model: "", serial_number: "SN1",
    domain: "", tags: [], software_status: "collected", software_count: 0, active: true, source: "VSA X",
    data_basis: "live", generation_id: "g1", as_of: "2026-11-12T09:00:00Z",
  },
  details: null, third_party_patch_status: null, os_updates: null, policies: null, software: [], history: [],
};

function setup(capabilities: string[]) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  const customer = { ...customerA, my_capabilities: capabilities };
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe({ memberships: [{ customer: { id: customerA.id, code: "ACME", name: "Acme Ltd" }, role: "engineer", capabilities }] }) },
    "GET /api/v1/customers/": { body: page([customer]) },
    "GET /api/v1/assets/a1/": { body: detail },
    "POST /api/v1/assets/a1/refresh-details/": { status: 202, body: { sync_run_id: "r1", state: "queued", detail: "ok" } },
  });
}

describe("refresh one device's details (PERF-01)", () => {
  it("asks the next sync to fetch this device's details", async () => {
    const { calls } = setup(["customer.read", "customer.sync"]);
    renderApp("/assets/a1");
    await userEvent.click(await screen.findByRole("button", { name: "Refresh details now" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/Refresh requested/);
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/v1/assets/a1/refresh-details/"]);
  });

  it("is not offered without the customer's sync permission", async () => {
    setup(["customer.read"]);
    renderApp("/assets/a1");
    expect(await screen.findByRole("heading", { name: "DEMOA-WS001" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refresh details now" })).not.toBeInTheDocument();
  });
});
