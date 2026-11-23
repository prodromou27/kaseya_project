import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const admin = { ...customerA, my_capabilities: ["customer.read", "customer.group_move.approve"] };
const proposal = {
  id: "p1", asset: "a1", device_name: "SALESPC01", source_group_name: "Onboarding", target_group_name: "Sales",
  target_group_external_id: "52", reason: "Correct onboarding placement", policy_impact: "Policies may change.",
  state: "approved", requested_by: "eng@example.test", reviewed_by: "admin@example.test", review_reason: "Checked",
  created_at: "2026-11-16T08:00:00Z", expires_at: "2026-11-17T08:00:00Z", expired: false,
  execution_enabled: true, execution_available: true, execution_blocked_reason: "", execution: null,
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

  it("offers to send again when reading the device back showed it never moved", async () => {
    const failed = { ...proposal, execution_enabled: true,
      execution: { state: "failed", executed_by: "admin@example.test", started_at: "2026-11-23T12:36:26Z", finished_at: "2026-11-23T12:40:00Z",
        http_status: null, error_code: "still_in_source_group", observed_group_id: "40", verified_at: "2026-11-23T12:40:00Z" } };
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([failed]) },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/execute/`]: { body: proposal },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    await userEvent.click(await screen.findByRole("button", { name: "Review proposal" }));
    const panel = screen.getByRole("region", { name: "Execute in VSA X" });
    expect(panel).toHaveTextContent("Not moved");
    expect(panel).toHaveTextContent("still in its old group, so you can send the move again");
    await userEvent.click(within(panel).getByRole("button", { name: "Execute move in VSA X…" }));
    await userEvent.click(within(panel).getByRole("button", { name: "Move device in VSA X" }));
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

  it("approves and moves one proposal in one step", async () => {
    const pending = { ...proposal, state: "pending", reviewed_by: null, review_reason: "", execution_enabled: false, execution_blocked_reason: "Only approved proposals can be executed." };
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([pending]) },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/review/`]: { body: { ...proposal } },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/execute/`]: { body: { ...proposal, execution: { state: "succeeded" } } },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    await userEvent.click(await screen.findByRole("button", { name: "Review proposal" }));
    const form = screen.getByRole("form", { name: "Independent move review" });
    await userEvent.type(within(form).getByLabelText("Review reason"), "Checked the subnet evidence");
    await userEvent.click(within(form).getByRole("button", { name: "Approve and move in VSA X" }));
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/execute/"))).toHaveLength(1));
    const review = calls.find((c) => c.url.includes("/review/"));
    expect(JSON.parse(String(review?.init?.body))).toEqual({ decision: "approved", reason: "Checked the subnet evidence" });
  });

  it("decides several selected proposals at once and skips the reviewer's own", async () => {
    const pend = (id: string, name: string, by = "eng@example.test") => ({ ...proposal, id, device_name: name, requested_by: by, state: "pending", reviewed_by: null, execution_enabled: false });
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([pend("p1", "PC1"), pend("p2", "PC2"), pend("p3", "PC3", "admin@example.test")]) },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/review/`]: { body: proposal },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p2/review/`]: { body: proposal },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/execute/`]: { body: { ...proposal, execution: { state: "succeeded" } } },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p2/execute/`]: { status: 400, body: { error: { code: "validation_error", message: "Invalid input.", details: { execute: ["Inventory is missing or stale. Synchronize before executing."] }, request_id: "r" } } },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    for (const n of [1, 2, 3]) await userEvent.click(await screen.findByLabelText(`Select row ${n}`));
    const bar = screen.getByRole("group", { name: "Decide selected proposals" });
    expect(bar).toHaveTextContent("1 selected proposal(s) skipped");
    await userEvent.type(within(bar).getByLabelText("Review reason (all selected)"), "Bulk onboarding review");
    const go = within(bar).getByRole("button", { name: "Approve and move (2)" });
    expect(go).toBeDisabled();
    await userEvent.click(within(bar).getByLabelText(/Move 2 devices in VSA X now/));
    await userEvent.click(go);
    const results = await screen.findByRole("list", { name: "Decision results" });
    await waitFor(() => expect(results).toHaveTextContent(/PC2: .*Inventory is missing or stale/));
    expect(results).toHaveTextContent("PC1: Moved in VSA X");
    expect(calls.filter((c) => c.url.includes("/p3/"))).toHaveLength(0);
  });

  it("lets a single administrator select all their own proposals and approve and move them", async () => {
    const own = (id: string, name: string) => ({ ...proposal, id, device_name: name, requested_by: "admin@example.test", state: "pending", reviewed_by: null, execution_enabled: false, self_approval_allowed: true });
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([own("p1", "PC1"), own("p2", "PC2")]) },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/review/`]: { body: proposal },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p2/review/`]: { body: proposal },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/execute/`]: { body: { ...proposal, execution: { state: "succeeded" } } },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p2/execute/`]: { body: { ...proposal, execution: { state: "succeeded" } } },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    await userEvent.click(await screen.findByLabelText("Select all rows on this page"));
    const bar = screen.getByRole("group", { name: "Decide selected proposals" });
    expect(bar).not.toHaveTextContent("skipped");
    await userEvent.type(within(bar).getByLabelText("Review reason (all selected)"), "Suggested destinations checked");
    await userEvent.click(within(bar).getByLabelText(/Move 2 devices in VSA X now/));
    await userEvent.click(within(bar).getByRole("button", { name: "Approve and move (2)" }));
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/execute/"))).toHaveLength(2));
    const list = calls.find((c) => c.method === "GET" && c.url.startsWith(`/api/v1/customers/${customerA.id}/group-moves/?`));
    expect(list?.url).toContain("view=waiting");
    expect(list?.url).toContain("page_size=200");
  });

  it("verifies all sent-but-unconfirmed moves at once without sending them again", async () => {
    const sent = (id: string, name: string) => ({ ...proposal, id, device_name: name, execution_enabled: false,
      execution: { state: "unknown", executed_by: "admin@example.test", started_at: "2026-11-23T13:12:57Z", finished_at: "2026-11-23T13:12:58Z",
        http_status: 200, error_code: "unreadable_response", observed_group_id: "", verified_at: null } });
    const moved = { ...proposal, execution: { state: "succeeded" } };
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([sent("p1", "PC1"), sent("p2", "PC2")]) },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p1/verify/`]: { body: moved },
      [`POST /api/v1/customers/${customerA.id}/group-moves/p2/verify/`]: { body: moved },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves?view=to_verify");
    await userEvent.click(await screen.findByLabelText("Select all rows on this page"));
    const bar = screen.getByRole("group", { name: "Decide selected proposals" });
    expect(bar).not.toHaveTextContent("skipped");
    await userEvent.click(within(bar).getByRole("button", { name: "Verify in VSA X (2)" }));
    expect(await within(bar).findByRole("list", { name: "Decision results" })).toHaveTextContent("PC2: Moved in VSA X");
    expect(calls.filter((c) => c.url.includes("/verify/"))).toHaveLength(2);
    expect(calls.some((c) => c.url.includes("/execute/"))).toBe(false);
    expect(calls.find((c) => c.method === "GET" && c.url.includes("/group-moves/?"))?.url).toContain("view=to_verify");
  });

  it("names the exact reason when moving is not available", async () => {
    const off = { ...proposal, state: "pending", reviewed_by: null, execution_enabled: false, execution_available: false, self_approval_allowed: true,
      execution_unavailable_reason: "Executing moves in VSA X is switched off on this server (VSA_GROUP_MOVE_EXECUTION_ENABLED=false in .env.prod; set it to true and redeploy)." };
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
      "GET /api/v1/customers/": { body: page([admin]) },
      [`GET /api/v1/customers/${customerA.id}/group-moves/`]: { body: page([off]) },
    } as never);
    window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
    renderApp("/group-moves");
    await userEvent.click(await screen.findByLabelText("Select all rows on this page"));
    const bar = screen.getByRole("group", { name: "Decide selected proposals" });
    expect(bar).toHaveTextContent("VSA_GROUP_MOVE_EXECUTION_ENABLED=false in .env.prod");
    expect(within(bar).queryByRole("button", { name: /Approve and move/ })).not.toBeInTheDocument();
  });
});
