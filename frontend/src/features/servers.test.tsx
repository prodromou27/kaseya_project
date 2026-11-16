import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";
import { ownerEmail, type OwnerGroup, type ServerRow } from "./servers/ServersPage";

const admin = { ...customerA, my_capabilities: ["customer.read", "customer.export", "customer.manage_exceptions"] };
const group: OwnerGroup = { id: "g1", name: "Finance servers", owner_name: "Maria", owner_email: "maria@example.test", notes: "", servers: 1 };
const base: ServerRow = {
  asset_id: "a1", hostname: "FIN-SRV01", os_name: "Windows Server 2016 Standard", os_version: "10.0.14393", site: "HQ", vsa_group: "Servers",
  last_seen_online: "2026-11-16T08:00:00Z", server_source: "detected", is_server: true, note: "",
  owner_group_id: "g1", owner_group: "Finance servers", owner_name: "Maria", owner_email: "maria@example.test",
  os_updates_status: "collected", updates_available: 5, critical_available: 2, important_available: 1,
  patch_policy_state: "assigned", patch_policy: "Servers monthly", outdated_programs: 0,
  os_lifecycle: "end_of_support", os_end_of_support: "2027-01-12", needs_attention: true,
  reasons: ["2 Critical OS updates available", "Operating system out of support since 2027-01-12 - upgrade needed"],
};
const unowned: ServerRow = { ...base, asset_id: "a2", hostname: "APP-SRV02", owner_group_id: null, owner_group: "", owner_name: "", owner_email: "",
  updates_available: 0, critical_available: 0, important_available: 0, os_lifecycle: "supported", os_end_of_support: null, needs_attention: false, reasons: [] };
const list = { rows: [base, unowned], count: 2, detection_note: "Detected from the OS name.",
  totals: { servers: 2, needs_attention: 1, unassigned: 1, critical: 1, out_of_support: 1 } };

describe("servers & owners", () => {
  it("lists servers with what each needs and assigns an owner to selected servers", async () => {
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/server-owner-groups/`]: { body: [group] },
      [`GET /api/v1/customers/${customerA.id}/servers/`]: { body: list },
      [`POST /api/v1/customers/${customerA.id}/servers/designate/`]: { body: { updated: 1 } },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/servers");
    const table = await screen.findByRole("table", { name: "Servers" });
    expect(table).toHaveTextContent("2 Critical OS updates available");
    expect(table).toHaveTextContent("Out of support");
    expect(within(table).getByText("No owner")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("checkbox", { name: "Select row 2" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Owner group" }), "g1");
    await userEvent.click(screen.getByRole("button", { name: "Assign owner" }));
    const post = calls.find((c) => c.url.includes("/servers/designate/"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ assets: ["a2"], owner_group: "g1" });
  });

  it("builds an owner email listing only that owner's servers needing attention", () => {
    const link = decodeURIComponent(ownerEmail(group, admin, [base, unowned]));
    expect(link.startsWith("mailto:maria@example.test?subject=Server patching: Finance servers")).toBe(true);
    expect(link).toContain("- FIN-SRV01: 2 Critical OS updates available");
    expect(link).not.toContain("APP-SRV02");
  });

  it("schedules a monthly report for an owner group and shows existing schedules", async () => {
    const other: OwnerGroup = { ...group, id: "g2", name: "HR servers", owner_email: "" };
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/server-owner-groups/`]: { body: [group, other] },
      [`GET /api/v1/customers/${customerA.id}/servers/`]: { body: list },
      [`GET /api/v1/customers/${customerA.id}/report-definitions/`]: { body: page([
        { id: "d1", name: "Server patching - Finance servers", report_type: "server_owner_patching", format: "pdf", filters: { owner_group: "g1" }, owner: "eng@example.test" },
      ]) },
      [`GET /api/v1/customers/${customerA.id}/report-schedules/`]: { body: page([
        { id: "s1", definition: "d1", frequency: "monthly", time_of_day: "07:00:00", weekday: null, day_of_month: 1, timezone: "UTC", recipient_emails: [], enabled: true, next_run_at: null, last_run_at: null },
      ]) },
      [`POST /api/v1/customers/${customerA.id}/report-definitions/`]: { status: 201, body: { id: "d2", name: "Server patching - HR servers", report_type: "server_owner_patching", format: "pdf", filters: { owner_group: "g2" }, owner: "eng@example.test" } },
      [`POST /api/v1/customers/${customerA.id}/report-schedules/`]: { status: 201, body: { id: "s2" } },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/servers?tab=owners");
    const table = await screen.findByRole("table", { name: "Owner groups" });
    const finance = within(table).getByRole("row", { name: /Finance servers/ });
    expect(await within(finance).findByText("Monthly on day 1")).toBeInTheDocument();
    const hr = within(table).getByRole("row", { name: /HR servers/ });
    await userEvent.click(within(hr).getByRole("button", { name: "Schedule monthly" }));
    expect(await screen.findByText(/Scheduled monthly/)).toBeInTheDocument();
    const def = calls.find((c) => c.method === "POST" && c.url.includes("/report-definitions/"));
    expect(JSON.parse(String(def?.init?.body))).toMatchObject({ report_type: "server_owner_patching", filters: { owner_group: "g2" } });
    const sched = calls.find((c) => c.method === "POST" && c.url.includes("/report-schedules/"));
    expect(JSON.parse(String(sched?.init?.body))).toMatchObject({ definition: "d2", frequency: "monthly", day_of_month: 1 });
  });
});
