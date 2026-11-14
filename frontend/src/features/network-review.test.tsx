import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ExpectedSubnet, GroupNetwork } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const net: GroupNetwork = {
  instance_id: "source-1",
  group: { external_id: "51", name: "Workstations", is_active: true, site_external_id: "5", organization_external_id: "11" },
  group_listed: true, as_of: ["2026-11-13T09:00:00Z"], data_basis: ["fixture"],
  counts: { devices: 2, with_reported_addresses: 2, network_not_collected: 0, multi_adapter: 1 },
  subnets: [{ cidr: "10.0.1.0/24", devices: 2, addresses: 2 }], addresses_without_derived_subnet: {},
  duplicate_ips: [], mac_reuse: [], gateways: [], dns_servers: [], public_ips: [], devices: [],
  note: "Reported adapter data per device from VSA X. This is not discovered topology.", flags_note: "Review flags.",
  expected_subnets: [{ id: "s1", scope_type: "site", scope_external_id: "5", cidr: "10.0.1.0/24" }],
  outside_expected_subnet: [{ asset_id: "a5", hostname: "PC5", address: "172.20.1.1", adapter: "VPN", mac_locally_administered: true }],
  addresses_not_evaluated_against_expectation: 3,
  address_changes: { previous_generation: { id: "g0", published_at: "2026-11-12T09:00:00Z" }, compared_devices: 2,
    devices: [{ asset_id: "a2", hostname: "PC2", added: ["10.0.1.99"], removed: ["10.0.1.11"] }] },
  review_flags: [
    { flag: "duplicate_ip", count: 0 },
    { flag: "outside_expected_subnet", count: 1, evaluated: true },
    { flag: "address_changed_since_previous_snapshot", count: 1, evaluated: true },
  ],
};
const subnet: ExpectedSubnet = {
  id: "s1", scope_type: "site", scope_external_id: "5", cidr: "10.0.1.0/24", reason: "HQ LAN", state: "approved",
  proposed_by: "admin@example.test", reviewed_by: "super@example.test", reviewed_at: "2026-11-13T09:00:00Z", created_at: "2026-11-13T08:00:00Z",
};

function routes(caps: string[] = customerA.my_capabilities, n: GroupNetwork = net) {
  const customer = { ...customerA, my_capabilities: caps };
  window.sessionStorage.setItem("okp.selectedCustomer", customer.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customer]) },
    [`GET ${base}/groups/51/network/`]: { body: n },
    [`GET ${base}/groups/51/settings/`]: { body: { is_onboarding: false } },
    [`POST ${base}/groups/51/settings/`]: { body: { is_onboarding: true } },
    [`GET ${base}/expected-subnets/`]: { body: [subnet] },
    [`POST ${base}/expected-subnets/`]: { status: 201, body: { ...subnet, id: "s2", state: "proposed" } },
  } as never);
}

describe("network review", () => {
  it("an administrator marks a temporary onboarding group without vendor changes", async () => {
    const { calls } = routes([...customerA.my_capabilities, "customer.manage_exceptions"]);
    renderApp("/groups/51");
    await userEvent.click(await screen.findByLabelText("Use as an onboarding group"));
    const post = calls.find((c) => c.method === "POST" && c.url.includes("/settings/?instance=source-1"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ is_onboarding: true });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });
  it("shows review flags, outside addresses and address changes as observations", async () => {
    routes();
    renderApp("/groups/51");
    const flags = await screen.findByRole("list", { name: "Review flags" });
    expect(within(flags).getByText("Addresses outside the expected subnets")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Addresses outside expected subnets" })).toHaveTextContent("172.20.1.1");
    expect(screen.getByText("virtual / locally administered")).toBeInTheDocument();
    expect(screen.getByText(/3 address\(es\) had no expectation of the same IP version/)).toBeInTheDocument();
    expect(screen.getByText(/not proof of a wrong VLAN/)).toBeInTheDocument();
    expect(screen.getByText("10.0.1.99")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Expected subnets" })).toHaveTextContent("HQ LAN");
    expect(screen.queryByRole("button", { name: "Propose subnet" })).not.toBeInTheDocument();
  });

  it("marks flags that could not be evaluated", async () => {
    routes(customerA.my_capabilities, { ...net, outside_expected_subnet: [], review_flags: [{ flag: "outside_expected_subnet", count: 0, evaluated: false }],
      address_changes: { previous_generation: null, devices: [], not_evaluated_reason: "no previous complete snapshot" } });
    renderApp("/groups/51");
    const flags = await screen.findByRole("list", { name: "Review flags" });
    expect(within(flags).getByText("not evaluated")).toBeInTheDocument();
    expect(screen.getByText("Not evaluated (no previous complete snapshot).")).toBeInTheDocument();
  });

  it("customer admin proposes a group subnet", async () => {
    const { calls } = routes([...customerA.my_capabilities, "customer.manage_exceptions"]);
    renderApp("/groups/51");
    await userEvent.type(await screen.findByLabelText("Subnet (CIDR)"), "10.0.2.0/24");
    await userEvent.type(screen.getByLabelText("Reason"), "Second floor");
    await userEvent.click(screen.getByRole("button", { name: "Propose subnet" }));
    const post = calls.find((c) => c.method === "POST" && c.url === `${base}/expected-subnets/`);
    expect(JSON.parse(String(post?.init?.body))).toEqual({ scope_type: "group", scope_external_id: "51", cidr: "10.0.2.0/24", reason: "Second floor", integration_instance: "source-1" });
  });
});
