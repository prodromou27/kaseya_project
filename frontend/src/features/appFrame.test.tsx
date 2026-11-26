import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";
import type { DatasetStatus } from "../lib/types";

const base = `/api/v1/customers/${customerA.id}`;
const dataset = (overrides: Partial<DatasetStatus> = {}): DatasetStatus => ({
  mapping_id: "m1",
  integration: { id: "i1", name: "Demo VSA X (fixture)", provider: "vsa_x", is_fixture: true, enabled: true },
  external_org_id: "1001", dataset: "vsa_assets", status: "stale", as_of: "2026-11-12T09:00:00Z", generation_id: "g1",
  row_count: 2, data_basis: "fixture",
  last_run: { id: "r1", state: "completed", error_code: "", created_at: "2026-11-12T08:59:00Z", ended_at: "2026-11-12T09:00:00Z", fetched: 2, quarantined: 0 },
  ...overrides,
});

function routes(datasets: DatasetStatus[]) {
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/datasets/`]: { body: datasets },
    [`GET ${base}/assets/facets/`]: { body: { group: [], os: [], device_type: [], site: [] } },
    [`GET ${base}/assets/`]: { body: { ...page([]), count: 0 } },
    [`GET ${base}/saved-views/`]: { body: page([]) },
  } as never);
}

describe("app frame (UX-11)", () => {
  it("shows the page section above the title and a one-line source status, stale data marked", async () => {
    routes([dataset()]);
    renderApp("/assets");
    const title = await screen.findByRole("heading", { level: 1, name: "Devices" });
    expect(title.previousElementSibling).toHaveTextContent("Daily work");
    const sources = await screen.findByRole("region", { name: "Data sources" });
    expect(sources).toHaveTextContent("stale");
    expect(sources).toHaveTextContent("Demo data, not a live VSA X tenant");
    expect(within(sources).queryByRole("heading", { name: "Data sources" })).toBeNull();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("keeps the detailed source card when a sync needs attention", async () => {
    routes([dataset({ last_run: { id: "r1", state: "failed", error_code: "auth_failed", created_at: "2026-11-12T08:59:00Z", ended_at: "2026-11-12T09:00:00Z", fetched: 0, quarantined: 0 } })]);
    renderApp("/assets");
    expect(await screen.findByRole("heading", { name: "Data sources" })).toBeInTheDocument();
    expect(screen.getByText(/VSA X rejected the API credentials/)).toBeInTheDocument();
  });
});
