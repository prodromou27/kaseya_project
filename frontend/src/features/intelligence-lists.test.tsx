import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const summary = { as_of: [], generation_ids: [], data_basis: ["fixture"], devices_total: 205,
  available_section: { collected: 200, not_collected: 5, not_supported: 0, failed: 0, carried_forward: 0, not_requested: 0 },
  installed_section: { collected: 0, not_collected: 0, not_supported: 0, failed: 0, carried_forward: 0, not_requested: 205 },
  devices_reporting_updates: 200, devices_with_available_updates: 190, devices_with_zero_available: 10,
  devices_by_severity: {}, top_available_updates: [], freshness_note: "No source scan timestamp.", scope_note: "OS updates only." };
function setup(fail = false) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({ "GET /api/v1/auth/me/": { body: makeMe() }, "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/datasets/`]: { body: [] }, [`GET ${base}/os-updates/summary/`]: { body: summary },
    [`GET ${base}/os-updates/devices/`]: (_init, url) => fail ? { status: 503 } : { body: { ...page([{
      asset_id: "a1", device_type: "mac", hostname: url.searchParams.get("page") === "2" ? "WS-201" : "WS-001", os_name: "Windows",
      available_status: "not_collected", available_count: null, installed_status: "not_requested", last_seen_online: null,
    }]), count: 205 } }, [`POST ${base}/reports/`]: { status: 202, body: { id: "run1", state: "queued" } },
  });
}

it("paginates collection evidence beyond the previous cap and preserves unknown counts", async () => {
  const { calls } = setup();
  renderApp("/windows-updates?view=coverage&status=not_collected");
  expect(await screen.findByRole("table", { name: "Devices: Not collected" })).toHaveTextContent("Unknown");
  expect(screen.getByRole("table", { name: "Devices: Not collected" })).toHaveTextContent("mac");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByText("WS-201")).toBeInTheDocument();
  expect(calls.some((call) => call.url.includes("/devices/?") && call.url.includes("page=2"))).toBe(true);
  expect(screen.queryByRole("button", { name: "Export update records" })).not.toBeInTheDocument();
});

it("coverage search/export use the coverage population and reset paging", async () => {
  const { calls } = setup();
  renderApp("/windows-updates?view=coverage&status=not_collected&page=2");
  fireEvent.change(await screen.findByLabelText("Find device"), { target: { value: "WS-001" } });
  await waitFor(() => expect(calls.some((call) => call.url.includes("search=WS-001") && call.url.includes("page=1"))).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "Export device coverage" }));
  const sent = calls.find((call) => call.method === "POST");
  expect(JSON.parse(String(sent?.init?.body))).toMatchObject({ report_type: "os_update_coverage", filters: { available_status: "not_collected", search: "WS-001" } });
});

it("shows collection API failure without inventing zero device rows", async () => {
  setup(true);
  renderApp("/windows-updates?view=coverage");
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load data");
  expect(screen.queryByRole("table", { name: "Device collection coverage" })).not.toBeInTheDocument();
});
