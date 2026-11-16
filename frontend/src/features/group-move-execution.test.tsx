import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const admin = { ...customerA, my_capabilities: ["customer.read", "customer.group_move.approve"] };
const proposal = {
  id: "p1", asset: "a1", device_name: "SALESPC01", source_group_name: "Onboarding", target_group_name: "Sales",
  target_group_external_id: "52", reason: "Correct onboarding placement", policy_impact: "Policies may change.",
  state: "approved", requested_by: "eng@example.test", reviewed_by: "admin@example.test", review_reason: "Checked",
  created_at: "2026-11-16T08:00:00Z", expires_at: "2026-11-17T08:00:00Z", expired: false,
  execution_enabled: true, execution_blocked_reason: "", execution: null,
};

describe("group move execution", () => {
  it("asks for confirmation, executes once and shows the confirmed result", async () => {
    const executed = { ...proposal, execution_enabled: false, execution_blocked_reason: "Already executed.",
      execution: { state: "succeeded", executed_by: "admin@example.test", started_at: "2026-11-16T09:00:00Z", finished_at: "2026-11-16T09:00:01Z",
        http_status: 200, error_code: "", observed_group_id: "52", verified_at: "2026-11-16T09:00:01Z" } };
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([proposal]) },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/execute/`]: { body: executed },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    await userEvent.click(await screen.findByRole("button", { name: "Review proposal" }));
    const panel = screen.getByRole("region", { name: "Execute in VSA X" });
    await userEvent.click(within(panel).getByRole("button", { name: "Execute move in VSA X…" }));
    const confirm = within(panel).getByRole("group", { name: "Confirm move" });
    expect(confirm).toHaveTextContent("SALESPC01");
    expect(confirm).toHaveTextContent("sent once");
    await userEvent.click(within(confirm).getByRole("button", { name: "Move device in VSA X" }));
    expect(calls.filter((c) => c.url.includes("/execute/")).length).toBe(1);
  });

  it("explains why execution is not available", async () => {
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([{ ...proposal, execution_enabled: false,
        execution_blocked_reason: "Executing moves in VSA X is switched off on this server." }]) },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    await userEvent.click(await screen.findByRole("button", { name: "Review proposal" }));
    expect(screen.getByText(/switched off on this server/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Execute move/ })).not.toBeInTheDocument();
  });
});
