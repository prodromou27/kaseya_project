import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LifecycleSummary } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const entry = {
  id: "e1", label: "Windows 10 22H2", release_label: "22H2", version_prefix: "10.0.19045", edition_note: "", release_date: null,
  end_of_mainstream: null, end_of_support: "2025-10-14", extended_until: "2026-10-13", source_url: "https://lifecycle.example.test/w10",
  source_type: "vendor_lifecycle_page", source_checked_at: "2026-11-01", reviewed_by: "rev@example.test",
};
const summary: LifecycleSummary = {
  evaluated_on: "2026-11-13", algorithm_version: "lifecycle-1", ending_soon_days: 180, as_of: ["2026-11-13T10:00:00Z"], data_basis: ["live"],
  labels: { end_of_support: "End of support", ending_soon: "Ends within 180 days", supported: "Supported", unknown: "Unknown" },
  reasons: { no_entry: "No approved lifecycle entry matches.", matched: "Matched." },
  os: {
    devices: 5,
    totals: { end_of_support: 2, ending_soon: 0, supported: 0, unknown: 3 },
    groups: [
      { status: "end_of_support", reason: "matched", entry, reported: "", count: 2 },
      { status: "unknown", reason: "no_entry", entry: null, reported: "Windows 11 Enterprise", count: 3 },
    ],
  },
  software: { installations: 0, totals: { end_of_support: 0, ending_soon: 0, supported: 0, unknown: 0 }, devices_with_end_of_support: 0, groups: [] },
  notes: [],
};

function routes() {
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/lifecycle/`]: { body: summary },
    [`GET ${base}/lifecycle/devices/`]: {
      body: { count: 1, results: [{ asset_id: "a1", hostname: "PC-OLD", os_name: "Windows 10 Pro", os_version: "10.0.19045.1", status: "end_of_support", reason: "matched", entry }] },
    },
  } as never);
}

describe("lifecycle page", () => {
  it("shows cited end-of-support dates, keeps unknown separate and lists affected devices", async () => {
    const { calls } = routes();
    renderApp("/lifecycle");
    const table = await screen.findByRole("table", { name: "Operating system releases" });
    expect(table).toHaveTextContent("Windows 10 22H2");
    expect(table).toHaveTextContent("2025-10-14");
    expect(within(table).getByRole("link", { name: "vendor lifecycle page" })).toHaveAttribute("href", entry.source_url);
    expect(table).toHaveTextContent("No approved lifecycle entry matches.");
    expect(screen.getByText(/never counted as supported/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^End of support/ }));
    expect(await screen.findByRole("table", { name: "Devices: End of support" })).toHaveTextContent("PC-OLD");
    expect(calls.some((c) => c.url.includes("/lifecycle/devices/?kind=os&status=end_of_support"))).toBe(true);
  });
});

describe("lifecycle catalog admin", () => {
  it("proposes an OS entry with the cited source and no product", async () => {
    const admin = makeMe({ is_super_admin: true, memberships: [], global_capabilities: ["system.manage", "system.cross_customer"] });
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: admin },
      "GET /api/v1/customers/": { body: page([]) },
      "GET /api/v1/catalog/lifecycle/": { body: page([]) },
      "GET /api/v1/catalog/products/": { body: page([]) },
      "POST /api/v1/catalog/lifecycle/": { status: 201, body: {} },
    } as never);
    renderApp("/admin?tab=lifecycle");
    const form = await screen.findByRole("form", { name: "Propose lifecycle entry" });
    await userEvent.type(within(form).getByLabelText(/OS family/), "Windows 10");
    await userEvent.type(within(form).getByLabelText("Release"), "22H2");
    await userEvent.type(within(form).getByLabelText(/Version prefix/), "10.0.19045");
    await userEvent.type(within(form).getByLabelText("End of support"), "2025-10-14");
    await userEvent.type(within(form).getByLabelText("Source URL (https)"), "https://lifecycle.example.test/w10");
    await userEvent.click(within(form).getByRole("button", { name: "Propose" }));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({
      kind: "os", os_family: "Windows 10", product: null, release_label: "22H2", version_prefix: "10.0.19045",
      end_of_support: "2025-10-14", extended_until: null, confidence: "official", source_type: "vendor_lifecycle_page",
    });
  });
});
