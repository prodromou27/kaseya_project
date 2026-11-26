import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const device = { id: "a1", hostname: "WS-1", site_name: "HQ", group_name: "WS", os_name: "Windows 11", software_status: "collected", software_count: 3 };

function routes() {
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/datasets/`]: { body: [] },
    [`GET ${base}/assets/facets/`]: { body: {
      group: [], os: [], device_type: [], site: [], manufacturer: ["Dell Inc."], model: [], os_version: ["10.0.22631"],
      agent_version: ["5.1.2"], domain: ["corp.example"], tag: ["finance"], patch_policy: ["Workstations - weekly"],
    } },
    [`GET ${base}/assets/`]: { body: { ...page([device]), count: 1 } },
    [`GET ${base}/saved-views/`]: { body: page([]) },
    [`GET ${base}/custom-field-allowlist/`]: { body: [{ id: "w1", name: "Department", state: "approved" }, { id: "w2", name: "Owner", state: "approved" }] },
  } as never);
}

const lastList = (calls: { method: string; url: string }[]) =>
  new URL(calls.filter((c) => c.method === "GET" && c.url.startsWith(`${base}/assets/?`)).at(-1)?.url ?? "", "http://x").searchParams;

describe("device filters (FLT-01)", () => {
  it("filters by hardware, software and patching, with removable chips", async () => {
    const { calls } = routes();
    renderApp("/assets");
    await screen.findByRole("table", { name: "ACME assets" });
    await userEvent.click(screen.getByText("More filters"));
    await userEvent.selectOptions(screen.getByLabelText("Role"), "server");
    await userEvent.selectOptions(await screen.findByLabelText("Manufacturer"), "Dell Inc.");
    await userEvent.selectOptions(screen.getByLabelText("Missing OS updates"), "critical");
    await userEvent.selectOptions(screen.getByLabelText("Patch policy"), "__none__");
    await userEvent.type(screen.getByLabelText("Program name contains"), "Chrome");
    await userEvent.selectOptions(screen.getByLabelText("Program is"), "not_installed");
    await waitFor(() => expect(lastList(calls).get("software")).toBe("Chrome"));
    const q = lastList(calls);
    expect(Object.fromEntries(["role", "manufacturer", "missing_updates", "patch_policy", "software_presence"].map((k) => [k, q.get(k)]))).toEqual({
      role: "server", manufacturer: "Dell Inc.", missing_updates: "critical", patch_policy: "__none__", software_presence: "not_installed",
    });
    const chips = screen.getByLabelText("Active device filters");
    expect(chips).toHaveTextContent("Program: Chrome not installed");
    expect(chips).toHaveTextContent("Patch policy: none / not reported");
    await userEvent.click(within(chips).getByRole("button", { name: "Remove Program filter" }));
    await waitFor(() => expect(lastList(calls).get("software")).toBeNull());
    expect(lastList(calls).get("software_presence")).toBeNull();
  });

  it("combines several custom field rules; incomplete rules are not sent", async () => {
    const { calls } = routes();
    renderApp("/assets");
    await screen.findByRole("table", { name: "ACME assets" });
    await userEvent.click(screen.getByText("More filters"));
    const first = screen.getByRole("group", { name: "Custom field rule 1" });
    const by = within(first).getByLabelText("Filter by custom field");
    await within(by).findByRole("option", { name: "Department" });
    await userEvent.selectOptions(by, "Department");
    await userEvent.selectOptions(within(first).getByLabelText("Condition"), "equals");
    expect(lastList(calls).get("custom_field")).toBeNull(); // no value yet: not sent
    await userEvent.type(within(first).getByLabelText("Compare with"), "TBD");
    await userEvent.click(screen.getByRole("button", { name: "Add another custom field rule" }));
    const second = screen.getByRole("group", { name: "Custom field rule 2" });
    await userEvent.selectOptions(within(second).getByLabelText("Filter by custom field"), "Owner");
    await waitFor(() => expect(lastList(calls).get("custom_field_2")).toBe("Owner"));
    const q = lastList(calls);
    expect([q.get("custom_field"), q.get("custom_field_state"), q.get("custom_field_value")]).toEqual(["Department", "equals", "TBD"]);
    expect(q.get("custom_field_state_2")).toBe("missing");
    expect(screen.getByLabelText("Active device filters")).toHaveTextContent("Custom field 2: Owner is empty");
  });
});
