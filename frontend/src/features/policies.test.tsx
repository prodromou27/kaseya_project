import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PatchBaseline, PolicyDeviceRow, PolicySummary } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const admin = { ...customerA, my_capabilities: [...customerA.my_capabilities, "customer.manage_exceptions"] };
const base = `/api/v1/customers/${customerA.id}`;

const summary: PolicySummary = {
  as_of: ["2026-11-13T09:00:00Z"], data_basis: ["fixture"], devices: 4,
  patch_states: { assigned: 2, explicit_none: 1, not_reported: 1, unknown: 0 },
  collection_status: { collected: 4 },
  coverage: { assigned: 2, verified_denominator: 3, percent: 66.7, excluded_unknown: 1, definition: "assigned / verified" },
  by_policy: [{ policy_id: "301", policy_name: "WS weekly", devices: 1 }],
  drift: { no_baseline: 4, unknown: 0, matches: 0, different_policy: 0, missing_policy: 0, unexpected_policy: 0 },
  drift_labels: {
    no_baseline: "No approved expectation covers this device", unknown: "Assignment unknown", matches: "Matches the approved expectation",
    different_policy: "A different policy is assigned", missing_policy: "Expected a policy; No Policy is explicitly configured",
    unexpected_policy: "Expected no policy; a policy is assigned",
  },
  definitions: [{ policy_id: "301", status: "collected", name: "WS weekly", description: "Saturday", general_settings: { RebootOption: "DO_NOT_REBOOT" },
    os_rules: [{ Field: "SEVERITY", Operator: "CONTAINS", Severity: "CRITICAL", Action: "APPROVE_AND_INSTALL" }],
    software_rules: [{ ProductId: "7-zip-x64", ProductName: "7-Zip (64-bit)", Action: "INSTALL_AND_UPDATE" }], fetched_at: "2026-11-13T09:00:00Z", changed_since_previous: true }],
  scopes: { organizations: { "11": "Org A" }, sites: { "5": "HQ" }, groups: { "51": { name: "Workstations", site: "5" } } },
  carried_forward_note: "",
  note: "Policy assignment and policy configuration come from VSA X. They describe what is configured, not what was deployed.",
};
const device: PolicyDeviceRow = {
  asset_id: "a2", hostname: "PC2", site_external_id: "5", site_name: "HQ", group_external_id: "51", group_name: "Workstations",
  collection_status: "collected", collected_at: "2026-11-13T09:00:00Z", patch_state: "explicit_none", patch_policy_id: "",
  patch_policy_name: "No Policy (Explicitly configured)", expected: null, drift: "no_baseline",
};
const proposed: PatchBaseline = {
  id: "b1", scope_type: "group", scope_external_id: "51", expect_no_policy: false, expected_policy_id: "301", expected_policy_name: "WS weekly",
  reason: "WS standard", state: "proposed", proposed_by: "admin@example.test", reviewed_by: null, reviewed_at: null, created_at: "2026-11-13T09:00:00Z",
};

function routes(customer = admin) {
  window.sessionStorage.setItem("okp.selectedCustomer", customer.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customer]) },
    [`GET ${base}/patch-policies/summary/`]: { body: summary },
    [`GET ${base}/patch-policies/devices/`]: { body: page([device]) },
    [`GET ${base}/patch-policy-baselines/`]: { body: [proposed] },
    [`POST ${base}/patch-policy-baselines/`]: { status: 201, body: proposed },
    [`POST ${base}/patch-policy-baselines/b1/approve/`]: { status: 400, body: { error: { code: "validation_error", message: "The request was invalid.", details: { detail: "A different administrator must approve this expectation." } } } },
  } as never);
}

describe("patch policies", () => {
  it("keeps explicit No Policy, missing entry and unknown apart, with a stated denominator", async () => {
    routes(customerA);
    renderApp("/patch-policies");
    expect(await screen.findByText("No Policy (explicit)")).toBeInTheDocument();
    expect(screen.getByText("not the same as no policy")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 verified; 1 excluded")).toBeInTheDocument();
    expect(screen.getAllByText("configuration, not deployment status").length).toBeGreaterThan(0);
    expect(screen.getByText("changed since previous sync")).toBeInTheDocument();
    expect(screen.getByText(/not what was deployed/)).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Patch policy by device" })).toHaveTextContent("PC2");
    expect(screen.queryByRole("button", { name: "Propose expectation" })).not.toBeInTheDocument(); // read-only role
  });

  it("customer admin proposes an expectation and sees the separate-approver rule", async () => {
    const { calls } = routes();
    renderApp("/patch-policies");
    await screen.findByRole("table", { name: "Expected policies" });
    await userEvent.selectOptions(screen.getByLabelText("Scope"), "51");
    await userEvent.selectOptions(screen.getByLabelText("Expected policy"), "301");
    await userEvent.type(screen.getByLabelText("Reason"), "WS standard");
    await userEvent.click(screen.getByRole("button", { name: "Propose expectation" }));
    const post = calls.find((c) => c.method === "POST" && c.url === `${base}/patch-policy-baselines/`);
    expect(JSON.parse(String(post?.init?.body))).toEqual({ scope_type: "group", scope_external_id: "51", expect_no_policy: false, expected_policy_id: "301", reason: "WS standard" });
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A different administrator must approve");
  });
});
