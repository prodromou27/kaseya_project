import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const device = { id: "d1", hostname: "WS-001", group_name: "Workstations", group_external_id: "52", site_name: "HQ", os_name: "Windows", software_status: "collected", software_count: 3, instance_id: "source-a" };
const layout = { columns: ["hostname", "site_name"], density: "comfortable", page_size: 25 };
const saved = { id: "v1", name: "My investigation", view_type: "assets", owner: "eng@example.test", filters: { offline: "true", ordering: "-hostname" }, shared: false, layout };
function setup(failPage = false) {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() }, "GET /api/v1/customers/": { body: page([customerA]) },
    [`GET ${base}/datasets/`]: { body: [] },
    [`GET ${base}/assets/facets/`]: { body: { group: [], os: [], device_type: [], site: [] } },
    [`GET ${base}/assets/`]: (_init, url) => failPage && Number(url.searchParams.get("page") ?? "1") > 1 ? { status: 404 } : { body: { ...page([device]), count: 130 } },
    [`GET ${base}/saved-views/`]: { body: page([saved]) },
    [`GET ${base}/saved-views/v1/`]: { body: saved },
    [`POST ${base}/saved-views/`]: { status: 201, body: saved },
    [`PATCH ${base}/saved-views/v1/`]: { body: saved },
  });
}

it("restores a persisted layout URL with private filters, columns, density and bounded page size", async () => {
  const { calls } = setup();
  renderApp("/assets?view=v1");
  await waitFor(() => expect(screen.getByLabelText("Density")).toHaveValue("comfortable"));
  expect(screen.getByLabelText("Rows per page")).toHaveValue("25");
  const table = screen.getByRole("table", { name: "ACME assets" });
  expect(within(table).queryByRole("columnheader", { name: "Software" })).not.toBeInTheDocument();
  expect(within(table).getByRole("columnheader", { name: /Device/ })).toHaveAttribute("aria-sort", "descending");
  await waitFor(() => expect(calls.some((call) => call.url.includes("offline=true") && call.url.includes("page_size=25"))).toBe(true));
});

it("keeps chosen columns when paging and saves the complete presentation with an inline form", async () => {
  const { calls } = setup();
  renderApp("/assets");
  await screen.findByRole("table", { name: "ACME assets" });
  await userEvent.click(screen.getByText("Columns", { exact: true }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Site" }));
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(screen.queryByRole("columnheader", { name: "Site" })).not.toBeInTheDocument());
  await userEvent.selectOptions(screen.getByLabelText("Density"), "comfortable");
  await userEvent.click(screen.getByText("Saved views", { exact: true }));
  await userEvent.type(screen.getByLabelText("View name"), "My investigation");
  await userEvent.click(screen.getByRole("button", { name: "Save view" }));
  await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
  const posted = calls.find((call) => call.method === "POST");
  const body = JSON.parse(String(posted?.init?.body));
  expect(body.layout.columns).not.toContain("site_name");
  expect(body.layout).toMatchObject({ density: "comfortable", page_size: 50 });
  expect(body.shared).toBe(false);
  expect(body.filters).not.toHaveProperty("page_size");
});

it("debounces search, exposes removable scope and sorts on the server", async () => {
  const { calls } = setup();
  renderApp("/assets?group_id=52&instance=source-a");
  await screen.findByRole("table", { name: "ACME assets" });
  const input = screen.getByRole("searchbox", { name: "Search" });
  fireEvent.change(input, { target: { value: "WS" } });
  fireEvent.change(input, { target: { value: "WS-001" } });
  await waitFor(() => expect(calls.some((call) => call.url.includes("search=WS-001"))).toBe(true));
  expect(calls.some((call) => /[?&]search=WS&/.test(call.url))).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "Remove Group filter" }));
  expect(screen.queryByRole("button", { name: "Remove Group filter" })).not.toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("table", { name: "ACME assets" })).getByRole("button", { name: "Device" }));
  await waitFor(() => expect(calls.some((call) => call.url.includes("ordering=-hostname"))).toBe(true));
});


it("recovers a server-rejected out-of-range page without discarding filters", async () => {
  const { calls } = setup(true);
  renderApp("/assets?page=999&offline=true");
  await userEvent.click(await screen.findByRole("button", { name: "Return to first page" }));
  expect(await screen.findByRole("table", { name: "ACME assets" })).toBeInTheDocument();
  expect(calls.some((call) => call.url.includes("offline=true") && !call.url.includes("page=999"))).toBe(true);
});
