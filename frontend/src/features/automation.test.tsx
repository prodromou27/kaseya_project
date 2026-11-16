import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

describe("automation", () => {
  it("shows workflow failures for the customer's devices and the task limitation", async () => {
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA]) },
      [`GET /api/v1/customers/${customerA.id}/automation/`]: { body: {
        days: 7, totals: { runs: 28, failed: 4, devices_with_failures: 4 },
        workflows: [{ workflow_id: "501", name: "Clean temp files", runs: 21, failed: 3, success_pct: 85.7, last_failure_at: "2026-11-15T10:00:00Z" }],
        executions: [{ id: "e1", workflow_id: "501", workflow: "Clean temp files", asset_id: "a1", hostname: "PC-3", status: "Failed",
          trigger_type: "Ad-hoc and Scheduled", created_at: "2026-11-15T10:00:00Z", completed_at: null, failed_step: "Script exited with code 1" }],
        collection: [{ integration: "VSA", status: "ok", error_code: "", last_success_at: "2026-11-16T08:00:00Z" }],
        task_limitation: "VSA X does not offer a read-only way to list scheduled task runs, so task results are not shown; workflow results are.",
      } },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/automation");
    const runs = await screen.findByRole("table", { name: "Workflow runs" });
    expect(within(runs).getByRole("link", { name: "PC-3" })).toHaveAttribute("href", "/assets/a1");
    expect(runs).toHaveTextContent("Script exited with code 1");
    expect(screen.getByText(/list scheduled task runs/)).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("table", { name: "Workflows" })).getByRole("button", { name: "Clean temp files" }));
    expect(calls.some((c) => c.url.includes("workflow=501"))).toBe(true);
  });

  it("lists scopes with what uses them and the patch global rules", async () => {
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ is_super_admin: true }) },
      "GET /api/v1/customers/": { body: page([customerA]) },
      "GET /api/v1/automation/catalog/": { body: {
        workflows: [], tasks: [], collection: [], task_limitation: "",
        scopes: [
          { integration: "VSA", id: "71", name: "All workstations", description: "", criteria: [{ type: "Organization", identifier: "1001" }], total_devices: 118,
            used_by: [{ type: "Task", id: "601", name: "Weekly maintenance" }] },
          { integration: "VSA", id: "73", name: "Old scope", description: "", criteria: [], total_devices: 0, used_by: [] },
        ],
        global_rules: [{ integration: "VSA", fetched_at: "2026-11-16T08:00:00Z", os_rules: [],
          software_rules: [{ ProductId: "firefox-x64", ProductName: "Mozilla Firefox", Action: "INSTALL_AND_UPDATE" }] }],
      } },
    } as never);
    renderApp("/automation?tab=catalog");
    const scopes = await screen.findByRole("table", { name: "Scopes" });
    expect(scopes).toHaveTextContent("Task: Weekly maintenance");
    expect(scopes).toHaveTextContent("Not used");
    expect(screen.getByText("Mozilla Firefox → install and update")).toBeInTheDocument();
  });
});
