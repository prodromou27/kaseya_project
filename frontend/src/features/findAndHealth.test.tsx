import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const customerB = { ...customerA, id: "22222222-2222-4222-8222-222222222222", code: "BETA", name: "Beta Ltd" };
const hit = (id: string, hostname: string, c: typeof customerA) => ({
  asset_id: id, hostname, customer_id: c.id, customer_code: c.code, customer_name: c.name,
  site: "HQ", group: "Workstations", os: "Windows 11", last_seen_online: null,
});

describe("find a device from the header", () => {
  it("searches every customer as you type and opens the chosen device in its customer", async () => {
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA, customerB]) },
      "GET /api/v1/customers/overview/": { body: { results: [], count: 0, truncated: false } },
      "GET /api/v1/assets/lookup/": { body: { results: [hit("a1", "FIN-PC01", customerA), hit("b7", "FIN-LAPTOP", customerB)] } },
    });
    renderApp("/");
    await userEvent.type(await screen.findByRole("combobox", { name: /Find a device/ }), "fin");
    const list = await screen.findByRole("listbox", { name: "Matching devices" });
    expect((await within(list).findAllByRole("option")).map((o) => o.textContent)).toEqual([
      expect.stringContaining("FIN-PC01ACME"), expect.stringContaining("FIN-LAPTOPBETA"),
    ]);
    expect(calls.some((c) => c.url === "/api/v1/assets/lookup/?q=fin")).toBe(true);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    // The device's customer becomes the selected customer and the device page opens.
    await waitFor(() => expect(window.sessionStorage.getItem("okp.selectedCustomer")).toBe(customerB.id));
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/api/v1/assets/b7/"))).toBe(true));
  });

  it("says when nothing matches and does not search for a single character", async () => {
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA]) },
      "GET /api/v1/assets/lookup/": { body: { results: [] } },
    });
    renderApp("/");
    const box = await screen.findByRole("combobox", { name: /Find a device/ });
    await userEvent.type(box, "z");
    await new Promise((r) => setTimeout(r, 400));
    expect(calls.some((c) => c.url.startsWith("/api/v1/assets/lookup/"))).toBe(false);
    await userEvent.type(box, "zz");
    expect(await screen.findByText(/No device matches/)).toBeInTheDocument();
  });
});

describe("customer health on the dashboard", () => {
  it("shows every customer's health when none is selected and opens one in place", async () => {
    window.sessionStorage.removeItem("okp.selectedCustomer");
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA, customerB]) },
      "GET /api/v1/customers/overview/": { body: { results: [
        { id: customerA.id, code: "ACME", name: "Acme Ltd", status: "active", devices: 40, offline: 3, disk_critical: 1, antivirus_issues: 0,
          critical_updates: 2, outdated_software_devices: 5, compliance_pct: 92, baselines: 1, as_of: "2026-11-20T08:00:00Z", stale: false },
        { id: customerB.id, code: "BETA", name: "Beta Ltd", status: "active", devices: 10, offline: 0, disk_critical: 0, antivirus_issues: 0,
          critical_updates: 0, outdated_software_devices: 0, compliance_pct: 100, baselines: 1, as_of: "2026-11-20T08:00:00Z", stale: false },
      ], count: 2, truncated: false } },
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Your customers" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("link", { name: "BETA" }));
    await waitFor(() => expect(window.sessionStorage.getItem("okp.selectedCustomer")).toBe(customerB.id));
    expect(await screen.findByRole("heading", { name: "Compliance" })).toBeInTheDocument(); // the customer summary, on the dashboard
    expect(screen.getByRole("heading", { name: "Patching" })).toBeInTheDocument();
  });
});
