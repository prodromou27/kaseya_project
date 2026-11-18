import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CfItem, CfJob, CustomFieldDef } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const engineerCaps = ["customer.read", "customer.export", "customer.custom_field.assign"];
const adminCaps = [...engineerCaps, "customer.custom_field.bulk_assign", "customer.custom_field.approve"];
const field = (over: Partial<CustomFieldDef> = {}): CustomFieldDef => ({
  id: "f1", external_id: "901", name: "PatchRing", description: "Patch deployment ring", type: "Text", default_value: "Ring 2",
  is_read_only: false, contexts: ["Organization", "Device"], expiration_date: null, present: true, fetched_at: "2026-11-18T08:00:00Z",
  portal_writable: true, requires_approval: false, integration: "VSA", editable: true, device_capable: true, reason: "", ...over,
});
const job = (over: Partial<CfJob> = {}): CfJob => ({
  id: "j1", field: "f1", field_name: "PatchRing", field_type: "Text", field_external_id: "901", integration: "VSA", value: "Ring 0",
  per_device_values: false, source: "list", source_label: "Pasted list", source_filename: "", retry_of: null, state: "draft",
  state_label: "Draft (review matches)", created_by: "eng@example.test", created_at: "2026-11-18T09:00:00Z", previewed_at: null,
  confirmed_by: null, confirmed_at: null, approval_required: false, approved_by: null, approved_at: null, cancel_requested: false,
  started_at: null, finished_at: null, error_code: "", counts: { items: 3, match: { matched: 2, not_found: 1 } },
  writes: { available: true, reason: "" }, ...over,
});
const item = (over: Partial<CfItem>): CfItem => ({
  id: "i1", position: 0, input_identifier: "WS-FIN-001", input_kind: "hostname", input_row: null, match_status: "matched",
  match_label: "Matched", match_note: "", candidates: [], asset: "a1", device_external_id: "d1", hostname: "WS-FIN-001", site: "HQ",
  group: "Workstations", requested_value: "Ring 0", included: true, current_value: null, current_source: "", device_assigned: null,
  action: "", action_label: "Not previewed", action_note: "", result: "pending", result_label: "Pending", final_value: null,
  http_status: null, error_code: "", finished_at: null, ...over,
});

function routes(extra: Record<string, unknown> = {}, caps: string[] = adminCaps) {
  const me = { ...customerA, my_capabilities: caps };
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe({ memberships: [{ customer: { id: customerA.id, code: "ACME", name: "Acme Ltd" }, role: caps === adminCaps ? "admin" : "engineer", capabilities: caps }] }) },
    "GET /api/v1/customers/": { body: page([me]) },
    [`GET ${base}/custom-fields/`]: { body: [field(), field({ id: "f2", name: "Cost Center", type: "Number" })] },
    [`GET ${base}/custom-field-jobs/`]: { body: page([]) },
    [`GET ${base}/assets/`]: { body: page([]) },
    ...extra,
  } as never);
}

describe("Custom fields", () => {
  it("pastes a list, reviews matches, previews and applies only after explicit confirmation", async () => {
    let state = job();
    const items = { current: [item({}), item({ id: "i2", position: 1, input_identifier: "WS-HR-005", hostname: "WS-HR-005" }), item({ id: "i3", position: 2, input_identifier: "NOPE", match_status: "not_found", match_label: "Not found", hostname: "", included: false })] };
    const { calls } = routes({
      [`POST ${base}/custom-field-jobs/`]: { status: 201, body: state },
      [`GET ${base}/custom-field-jobs/j1/`]: () => ({ body: state }),
      [`GET ${base}/custom-field-jobs/j1/items/`]: () => ({ body: page(items.current) }),
      [`POST ${base}/custom-field-jobs/j1/preview/`]: () => {
        state = job({ state: "previewed", state_label: "Preview ready", counts: { items: 3, action: { update: 1, assign: 1 }, to_change: 2, updates: 1 } });
        items.current = [
          item({ action: "update", action_label: "Update", current_value: "Ring 1", current_source: "device", device_assigned: true }),
          item({ id: "i2", position: 1, input_identifier: "WS-HR-005", hostname: "WS-HR-005", action: "assign", action_label: "Assign", current_value: "Ring 2", current_source: "inherited" }),
        ];
        return { body: state };
      },
      [`POST ${base}/custom-field-jobs/j1/confirm/`]: () => {
        state = job({ state: "completed", state_label: "Completed", counts: { items: 3, result: { verified: 2, not_run: 1 }, to_change: 2 } });
        items.current = [item({ result: "verified", result_label: "Verified success", final_value: "Ring 0" }), item({ id: "i2", position: 1, hostname: "WS-HR-005", input_identifier: "WS-HR-005", result: "verified", result_label: "Verified success", final_value: "Ring 0" })];
        return { body: state };
      },
    });
    renderApp("/custom-fields");
    await userEvent.click(await screen.findByRole("tab", { name: "Import list" }));
    await userEvent.type(screen.getByLabelText(/Workstations \(one per line/), "WS-FIN-001{enter}WS-HR-005{enter}NOPE");
    await userEvent.selectOptions(screen.getByLabelText("Custom field"), "f1");
    await userEvent.type(screen.getByLabelText("Value"), "Ring 0");
    await userEvent.click(screen.getByRole("button", { name: "Find devices" }));
    const created = calls.find((c) => c.method === "POST" && c.url === `${base}/custom-field-jobs/`);
    expect(JSON.parse(String(created?.init?.body))).toEqual({ field: "f1", value: "Ring 0", source: "list", text: "WS-FIN-001\nWS-HR-005\nNOPE" });

    expect(await screen.findByRole("table", { name: "Matched devices" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Preview changes" }));
    const preview = await screen.findByRole("table", { name: "Preview of changes" });
    expect(within(preview).getByText("Ring 1")).toBeInTheDocument();
    expect(within(preview).getByText("inherited")).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: "Apply changes" });
    expect(apply).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I confirm setting/));
    expect(apply).toBeDisabled(); // the overwrite still needs acknowledging
    await userEvent.click(screen.getByLabelText(/has a different value set on the device/));
    await userEvent.click(apply);
    const confirmCall = calls.find((c) => c.url === `${base}/custom-field-jobs/j1/confirm/`);
    expect(JSON.parse(String(confirmCall?.init?.body))).toEqual({ confirm: true, acknowledge_overwrite: true });
    const results = await screen.findByRole("table", { name: "Results" });
    expect(within(results).getAllByText("Verified success")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Download results (Excel)" })).toHaveAttribute("href", `${base}/custom-field-jobs/j1/report/?type=xlsx`);
  });

  it("keeps the device selection across pages and sends a fixed list", async () => {
    const dev = (i: number) => ({ id: `a${i}`, hostname: `WS-${i}`, site_name: "HQ", site_external_id: "1", group_name: "WS", os_name: "Windows 11", serial_number: `S${i}` });
    const { calls } = routes({
      [`GET ${base}/assets/`]: (_init: unknown, url: URL) => ({ body: url.search.includes("page=2")
        ? { count: 3, next: null, previous: "p1", results: [dev(3)] }
        : { count: 3, next: "p2", previous: null, results: [dev(1), dev(2)] } }),
      [`POST ${base}/custom-field-jobs/`]: { status: 201, body: job({ source: "selection" }) },
      [`GET ${base}/custom-field-jobs/j1/`]: { body: job() },
      [`GET ${base}/custom-field-jobs/j1/items/`]: { body: page([]) },
    });
    renderApp("/custom-fields");
    await userEvent.click(await screen.findByLabelText("Select WS-1"));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(await screen.findByLabelText("Select WS-3"));
    expect(screen.getByText(/2 devices selected/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Custom field"), "f2");
    expect(screen.getByLabelText("Value")).toHaveAttribute("type", "number");
    await userEvent.type(screen.getByLabelText("Value"), "42");
    await userEvent.click(screen.getByRole("button", { name: "Review devices" }));
    const created = calls.find((c) => c.method === "POST" && c.url === `${base}/custom-field-jobs/`);
    expect(JSON.parse(String(created?.init?.body))).toEqual({ field: "f2", value: "42", source: "selection", assets: ["a1", "a3"] });
  });

  it("explains why the change cannot be applied while writes are off", async () => {
    routes({
      [`GET ${base}/custom-field-jobs/`]: { body: page([job({ state: "previewed", state_label: "Preview ready", counts: { to_change: 1, action: { assign: 1 } }, writes: { available: false, reason: "Writing custom fields to VSA X is switched off on this server." } })]) },
      [`GET ${base}/custom-field-jobs/j1/`]: { body: job({ state: "previewed", state_label: "Preview ready", counts: { to_change: 1, action: { assign: 1 } }, writes: { available: false, reason: "Writing custom fields to VSA X is switched off on this server." } }) },
      [`GET ${base}/custom-field-jobs/j1/items/`]: { body: page([item({ action: "assign", action_label: "Assign", current_source: "none" })]) },
    });
    renderApp("/custom-fields");
    await userEvent.click(await screen.findByRole("tab", { name: "Assignment history" }));
    await userEvent.click(await screen.findByRole("button", { name: "PatchRing = Ring 0" }));
    expect(await screen.findByText(/Cannot apply yet: Writing custom fields to VSA X is switched off/)).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/I confirm setting/));
    expect(screen.getByRole("button", { name: "Apply changes" })).toBeDisabled();
  });

  it("lets engineers preview but leaves applying to an administrator", async () => {
    const previewed = job({ state: "previewed", state_label: "Preview ready", counts: { to_change: 1, action: { assign: 1 } } });
    routes({
      [`GET ${base}/custom-field-jobs/`]: { body: page([previewed]) },
      [`GET ${base}/custom-field-jobs/j1/`]: { body: previewed },
      [`GET ${base}/custom-field-jobs/j1/items/`]: { body: page([item({ action: "assign", action_label: "Assign", current_source: "none" })]) },
    }, engineerCaps);
    renderApp("/custom-fields");
    await userEvent.click(await screen.findByRole("tab", { name: "Assignment history" }));
    await userEvent.click(await screen.findByRole("button", { name: "PatchRing = Ring 0" }));
    expect(await screen.findByText("An administrator applies these changes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply changes" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/I confirm setting/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview again" })).toBeEnabled();
  });

  it("shows read-only users the history and field overview only", async () => {
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA]) },
      [`GET ${base}/custom-fields/`]: { body: [field(), field({ id: "f3", name: "Script Managed Tag", editable: false, device_capable: false, reason: "Read-only in VSA X", portal_writable: false })] },
      [`GET ${base}/custom-field-jobs/`]: { body: page([]) },
    } as never);
    renderApp("/custom-fields");
    expect(await screen.findByRole("tab", { name: "Assignment history" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Import list" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Field overview" }));
    const table = await screen.findByRole("table", { name: "Custom fields in VSA X" });
    expect(within(table).getByText("Read-only in VSA X")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read fields from VSA X" })).not.toBeInTheDocument();
  });
});
