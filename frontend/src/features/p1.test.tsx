import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";
import type { AssetRow, DatasetStatus, SoftwareSummary } from "../lib/types";

const engineerCustomer = { ...customerA, my_capabilities: ["customer.read", "customer.export", "customer.sync"] };
const base = `/api/v1/customers/${customerA.id}`;

const dataset = (overrides: Partial<DatasetStatus> = {}): DatasetStatus => ({
  mapping_id: "m1",
  integration: { id: "i1", name: "Demo VSA X (fixture)", provider: "vsa_x", is_fixture: true, enabled: true },
  external_org_id: "1001",
  dataset: "vsa_assets",
  status: "fresh",
  as_of: "2026-11-12T09:00:00Z",
  generation_id: "g1",
  row_count: 2,
  data_basis: "fixture",
  last_run: { id: "r1", state: "completed", error_code: "", created_at: "2026-11-12T08:59:00Z", ended_at: "2026-11-12T09:00:00Z", fetched: 2, quarantined: 1 },
  ...overrides,
});

const asset = (overrides: Partial<AssetRow> = {}): AssetRow => ({
  id: "a1", external_id: "ext-1", hostname: "DEMOA-WS001", description: "", device_type: "windows",
  group_name: "DEMOA Org - HQ - Workstations", site_external_id: "2001", organization_external_id: "1001",
  client_version: "5.1.2", last_seen_online: "2026-11-12T08:00:00Z", last_seen_stale: false, os_name: "Windows 11 Enterprise",
  os_version: "10.0", manufacturer: "", model: "", serial_number: "SN1", domain: "", tags: [], software_status: "collected",
  software_count: 5, active: true, source: "Demo VSA X (fixture)", data_basis: "fixture", generation_id: "g1",
  as_of: "2026-11-12T09:00:00Z", ...overrides,
});

const summary: SoftwareSummary = {
  as_of: ["2026-11-12T09:00:00Z"], generation_ids: ["g1"], evaluation_ids: ["e1"], catalog_revision_ids: ["r1"],
  algorithm_version: "1.0.0", data_basis: ["fixture"],
  totals: { current: 3, outdated: 1, newer: 0, unknown: 2, unsupported: 4, excluded: 0 },
  eligible_installations: 10, comparable_installations: 4, comparable_coverage_pct: 40, version_compliance_pct: 75,
  unique_assets_with_outdated: 1, unique_assets_evaluated: 2,
  products: [{ product_id: "p1", label: "Google Chrome", channel: "stable",
               states: { current: 3, outdated: 1, newer: 0, unknown: 0, unsupported: 0, excluded: 0 },
               installations: 4, unique_assets: 2, versions: [{ version: "130.0", state: "outdated", installations: 1, unique_assets: 1 }] }],
  top_unsupported: [],
  disclaimer: "Version comparison against a reviewed reference catalog only. Not evidence of missing third-party patches or vulnerabilities.",
};

function routes(extra: Record<string, unknown> = {}) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([engineerCustomer]) },
    [`GET ${base}/datasets/`]: { body: [dataset()] },
    [`GET ${base}/assets/facets/`]: { body: { group: ["DEMOA Org - HQ - Workstations"], os: ["Windows 11 Enterprise"] } },
    [`GET ${base}/assets/`]: { body: page([asset(), asset({ id: "a2", hostname: "DEMOA-WS041", software_status: "not_collected", software_count: null, last_seen_stale: true })]) },
    [`GET ${base}/software/summary/`]: { body: summary },
    [`GET ${base}/software/`]: { body: page([]) },
    [`GET ${base}/software-exceptions/`]: { body: page([]) },
    ...extra,
  } as never);
}

describe("assets", () => {
  it("lists scoped inventory with provenance, fixture labelling and not-collected state", async () => {
    routes();
    renderApp("/assets");
    const table = await screen.findByRole("table", { name: "ACME assets" });
    expect(within(table).getByRole("link", { name: "DEMOA-WS001" })).toHaveAttribute("href", "/assets/a1");
    expect(within(table).getByText("not collected")).toBeInTheDocument();
    expect(within(table).getByText("offline")).toBeInTheDocument();
    expect(screen.getByText(/not a live VSA X tenant/)).toBeInTheDocument();
    expect(screen.getByText(/1 quarantined/)).toBeInTheDocument();
  });

  it("shows stale and never-synced sources explicitly", async () => {
    routes({ [`GET ${base}/datasets/`]: { body: [dataset({ status: "stale" }), dataset({ mapping_id: "m2", status: "never_synced", as_of: null, row_count: null, data_basis: null, last_run: null })] } });
    renderApp("/assets");
    expect(await screen.findByText("stale")).toBeInTheDocument();
    expect(screen.getByText("never synced")).toBeInTheDocument();
    expect(screen.getByText("no published dataset")).toBeInTheDocument();
  });

  it("explains when no source mapping is approved", async () => {
    routes({ [`GET ${base}/datasets/`]: { body: [] } });
    renderApp("/assets");
    expect(await screen.findByText(/No approved source mapping/)).toBeInTheDocument();
  });

  it("requests a read-only sync for users with the sync capability", async () => {
    const { calls } = routes({ [`POST ${base}/sync-runs/`]: { status: 202, body: { runs: [], refused: [] } } });
    renderApp("/assets");
    await userEvent.click(await screen.findByRole("button", { name: "Sync now (read-only)" }));
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/sync-runs/"))).toBe(true);
  });
});

describe("software versions", () => {
  it("shows denominators, separate populations and the non-patch disclaimer", async () => {
    routes();
    renderApp("/software");
    expect(await screen.findByText("75%")).toBeInTheDocument();
    expect(screen.getByText("current / (current + outdated) = 3 / 4")).toBeInTheDocument();
    expect(screen.getByText("4 of 10 installations comparable")).toBeInTheDocument();
    expect(screen.getByText(/Not evidence of missing third-party patches/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Not catalogued 4/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Unknown 2/ })).toBeInTheDocument();
  });

  it("hides exception management without the capability", async () => {
    routes();
    renderApp("/software");
    await screen.findByText("75%");
    expect(screen.queryByRole("form", { name: "Add exception" })).not.toBeInTheDocument();
  });

  it("drills down by product and state", async () => {
    const { calls } = routes();
    renderApp("/software");
    await userEvent.click(await screen.findByRole("button", { name: "1" }));
    expect(calls.some((c) => c.url.includes("/software/?") && c.url.includes("product=p1") && c.url.includes("state=outdated"))).toBe(true);
  });
});
