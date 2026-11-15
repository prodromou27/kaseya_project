import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const categories = [
  { key: "duplicate_serial", label: "Same serial number on several devices", count: 2 },
  { key: "not_seen", label: "Not seen recently", count: 1 },
  { key: "no_group", label: "Not in any group", count: 0 },
];
const finding = (category: string, hostname: string, detail: string) => ({
  category, asset_id: hostname, hostname, site: "HQ", group: "Workstations", group_external_id: "1", serial_number: "ABC",
  last_seen: "2026-05-01T08:00:00Z", days_since_seen: 198, detail,
});

describe("cleanup centre", () => {
  it("lists findings by category and filters with the category chips", async () => {
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA]) },
      [`GET ${base}/datasets/`]: { body: [] },
      [`GET ${base}/cleanup/`]: (_init: RequestInit | undefined, url: URL) => ({ body: {
        days: 90, categories, devices_with_findings: 3,
        results: url.searchParams.get("category") === "not_seen"
          ? [finding("not_seen", "OLD-PC", "Last seen 198 days before the snapshot")]
          : [finding("duplicate_serial", "PC-1", "Serial ABC also on PC-2"), finding("duplicate_serial", "PC-2", "Serial ABC also on PC-1"), finding("not_seen", "OLD-PC", "Last seen 198 days before the snapshot")],
        count: 3,
      } }),
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/cleanup");
    const table = await screen.findByRole("table", { name: "Cleanup findings" });
    expect(table).toHaveTextContent("Serial ABC also on PC-2");
    const chips = screen.getByRole("group", { name: "Cleanup categories" });
    expect(within(chips).getByRole("button", { name: /Not in any group/ })).toBeDisabled();
    await userEvent.click(within(chips).getByRole("button", { name: /Not seen recently/ }));
    expect(await screen.findByText("Last seen 198 days before the snapshot")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("category=not_seen"))).toBe(true);
    expect(screen.getByRole("button", { name: "Download to-do list (CSV)" })).toBeEnabled();
  });
});
