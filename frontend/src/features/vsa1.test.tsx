import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { GroupNetwork, HierarchyResponse, NodeCounts } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const counts = (o: Partial<NodeCounts> = {}): NodeCounts => ({
  devices: 3, stale: 0, never_seen: 0, agent_not_installed: 0, no_network_data: 0, no_update_data: 0, ...o,
});

const tree: HierarchyResponse = {
  as_of: ["2026-11-13T09:00:00Z"], data_basis: ["fixture"], hierarchy_status: ["collected"], devices_without_asset: 1,
  stale_days: 7, unassigned: counts({ devices: 2 }), note: "Names are labels; VSA IDs are the keys.",
  organizations: [{
    external_id: "1001", name: "Demo Org A", counts: counts({ devices: 5, stale: 1 }),
    sites: [{ external_id: "2001", name: "HQ", counts: counts({ devices: 5, stale: 1 }),
      groups: [{ external_id: "20011", name: "Workstations", is_active: true, counts: counts({ stale: 1, no_network_data: 1 }) },
               { external_id: "20012", name: "Servers", is_active: false, counts: counts({ devices: 2 }) }] }],
  }],
};

const net: GroupNetwork = {
  group: { external_id: "20011", name: "Workstations", is_active: true, site_external_id: "2001", organization_external_id: "1001" },
  group_listed: true, as_of: ["2026-11-13T09:00:00Z"], data_basis: ["fixture"],
  counts: { devices: 3, with_reported_addresses: 2, network_not_collected: 1, multi_adapter: 1 },
  subnets: [{ cidr: "10.1.10.0/24", devices: 2, addresses: 2 }],
  addresses_without_derived_subnet: { ipv6_prefix_not_reported: 2 },
  duplicate_ips: [{ address: "10.1.10.86", devices: [{ asset_id: "a1", hostname: "WS076", group_external_id: "20011" },
                                                      { asset_id: "a2", hostname: "SRV077", group_external_id: "20012" }] }],
  mac_reuse: [], gateways: [{ value: "10.1.10.1", adapters: 2 }], dns_servers: [], public_ips: [],
  devices: [
    { asset_id: "a1", hostname: "WS076", last_seen_online: null, network_status: "collected", public_ip: "",
      adapters: [{ name: "Ethernet", mac: "005001004C00", mac_locally_administered: false, dhcp_enabled: true, subnet_mask: "255.255.255.0",
                   gateways: ["10.1.10.1"], dns_servers: [], sources: ["LocalIpAddresses"],
                   addresses: [{ raw: "10.1.10.86", address: "10.1.10.86", version: 4, kind: "private", network_cidr: "10.1.10.0/24", cidr_status: "derived" },
                               { raw: "fe80::4c:1%17", address: "fe80::4c:1", version: 6, kind: "link_local", network_cidr: "", cidr_status: "prefix_not_reported" }] }] },
    { asset_id: "a3", hostname: "WS023", last_seen_online: null, network_status: "not_collected", public_ip: "", adapters: [] },
  ],
  note: "Reported adapter data per device from VSA X. This is not discovered topology, VLAN or authoritative subnet data.",
  flags_note: "Duplicate addresses and MAC reuse are review flags, not proof of misconfiguration.",
};

function routes(extra: Record<string, unknown> = {}) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/datasets/`]: { body: [] },
    [`GET ${base}/hierarchy/`]: { body: tree },
    [`GET ${base}/groups/20011/network/`]: { body: net },
    [`GET ${base}/assets/`]: { body: page([]) },
    [`GET ${base}/assets/facets/`]: { body: { group: [], os: [] } },
    [`GET ${base}/saved-views/`]: { body: page([]) },
    ...extra,
  } as never);
}

describe("groups & network", () => {
  it("renders the org > site > group tree with honest counts", async () => {
    routes();
    renderApp("/groups");
    const orgs = await screen.findByRole("list", { name: "Organisations" });
    expect(within(orgs).getByText("Demo Org A")).toBeInTheDocument();
    expect(within(orgs).getByRole("link", { name: "Workstations" })).toHaveAttribute("href", "/groups/20011");
    expect(within(orgs).getByText("inactive")).toBeInTheDocument();
    expect(within(orgs).getAllByText("1 no network data").length).toBeGreaterThan(0);
    expect(screen.getByText(/2 device\(s\) are not in any listed active group/)).toBeInTheDocument();
    expect(screen.getByText(/1 device-list entries had no inventory record/)).toBeInTheDocument();
  });

  it("shows derived subnets, review flags and not-collected devices for a group", async () => {
    routes();
    renderApp("/groups/20011");
    expect(await screen.findByRole("table", { name: "Derived subnets" })).toHaveTextContent("10.1.10.0/24");
    expect(screen.getByText(/not discovered topology/)).toBeInTheDocument();
    expect(screen.getByText("duplicate IP")).toBeInTheDocument();
    expect(screen.getByText(/\(group 20012\)/)).toBeInTheDocument();
    expect(screen.getByText("network not collected")).toBeInTheDocument();
    expect(screen.getByText("(prefix not reported)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Assets" })).toHaveAttribute("href", "/assets?group_id=20011");
  });

  it("filters assets by the VSA group from the URL", async () => {
    const { calls } = routes();
    renderApp("/assets?group_id=20011");
    expect(await screen.findByText("VSA group 20011")).toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith(`${base}/assets/?`) && c.url.includes("group_id=20011"))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(screen.queryByText("VSA group 20011")).not.toBeInTheDocument();
  });
});
