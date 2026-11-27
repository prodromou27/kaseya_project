import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const admin = { ...customerA, my_capabilities: ["customer.read", "customer.group_move.propose", "customer.group_move.approve"] };
const base = `/api/v1/customers/${customerA.id}/group-moves`;
const row = (line: number, input: string, status: string, note: string, asset: string | null) => ({
  line, input, status, note, asset_id: asset, hostname: asset ? input : "", current_group: asset ? "Onboarding" : "", site: "", has_pending_suggestion: false,
});
const check = (moveNowAllowed: boolean) => ({
  target: { id: "g52", name: "Sales", external_id: "52", organization: "1001" },
  rows: [row(1, "WS-01", "move", "Will be moved", "a1"), row(2, "WS-02", "move", "Will be moved", "a2"), row(3, "GHOST-PC", "not_in_vsa", "Not in VSA X (not onboarded) - skipped", null)],
  counts: { move: 2, not_in_vsa: 1 }, to_move: 2,
  execution_available: moveNowAllowed, execution_unavailable_reason: moveNowAllowed ? "" : "Moving is switched off.", move_now_allowed: moveNowAllowed,
});
const moved = (errorCode = "") => ({
  id: "p1", asset: "a1", target_group: "g52", device_name: "WS-01", source_group_name: "Onboarding", target_group_name: "Sales", target_group_external_id: "52",
  reason: "", policy_impact: "", state: "approved", requested_by: "admin@example.test", reviewed_by: "admin@example.test", review_reason: "",
  created_at: "2026-11-27T08:00:00Z", expires_at: "2026-11-28T08:00:00Z", expired: false, execution_enabled: false, execution_available: true, execution_blocked_reason: "",
  execution: { state: errorCode ? "failed" : "succeeded", executed_by: "admin@example.test", started_at: "2026-11-27T09:00:00Z", finished_at: "2026-11-27T09:00:01Z",
    http_status: 200, error_code: errorCode, observed_group_id: errorCode ? "51" : "52", verified_at: "2026-11-27T09:00:01Z",
    answer: errorCode ? { documented_answer: false, content_type: "text/html; charset=utf-8", content_length: 5120, answered_by: 'page title "Request Rejected"; Server: BigIP' } : null },
});

function routes(moveNowAllowed: boolean, errorCode = "") {
  window.sessionStorage.setItem("okp.selectedCustomer", customerA.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe({ email: "admin@example.test" }) },
    "GET /api/v1/customers/": { body: page([admin]) },
    [`GET ${base}/`]: { body: page([]) },
    [`GET ${base}/destinations/`]: { body: { groups: [{ id: "g52", name: "Sales", external_id: "52", site: "2001", organization: "1001", source: "VSA" }] } },
    [`POST ${base}/check-list/`]: { body: check(moveNowAllowed) },
    [`POST ${base}/move-now/`]: { body: moved(errorCode) },
    [`POST ${base}/`]: { body: { ...moved(), state: "pending", execution: null } },
  } as never);
}

async function checkList() {
  renderApp("/group-moves?tab=list");
  await userEvent.type(await screen.findByLabelText("Devices"), "WS-01\nWS-02\nGHOST-PC");
  const select = screen.getByLabelText("Move to group");
  await within(select).findByRole("option", { name: /Sales/ });
  await userEvent.selectOptions(select, "g52");
  await userEvent.click(screen.getByRole("button", { name: "Check list" }));
  return screen.findByRole("region", { name: "List check" });
}

describe("move a list of devices (MOV-02)", () => {
  it("checks the list, skips devices not in VSA X and moves the rest one by one after confirmation", async () => {
    const { calls } = routes(true);
    const result = await checkList();
    expect(result).toHaveTextContent("2 will be moved");
    expect(result).toHaveTextContent("1 skipped: not in VSA X");
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/check-list/"))?.init?.body))).toEqual({ text: "WS-01\nWS-02\nGHOST-PC", target_group: "g52" });
    const move = screen.getByRole("button", { name: "Move 2 devices" });
    expect(move).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/Move 2 devices to Sales in VSA X now/));
    await userEvent.click(move);
    await waitFor(() => expect(screen.getByRole("list", { name: "Move results" }).querySelectorAll("li")).toHaveLength(2));
    const posts = calls.filter((c) => c.method === "POST" && c.url.endsWith("/move-now/")).map((c) => JSON.parse(String(c.init?.body)).asset);
    expect(posts).toEqual(["a1", "a2"]);
  });

  it("stops the list when VSA X answers OK without applying the move", async () => {
    const { calls } = routes(true, "accepted_not_applied");
    await checkList();
    await userEvent.click(screen.getByLabelText(/Move 2 devices to Sales/));
    await userEvent.click(screen.getByRole("button", { name: "Move 2 devices" }));
    expect(await screen.findByText(/the remaining 1 device\(s\) were not sent/)).toBeInTheDocument();
    expect(calls.filter((c) => c.url.endsWith("/move-now/"))).toHaveLength(1);
    const results = screen.getByRole("list", { name: "Move results" });
    expect(results).toHaveTextContent(
      "VSA X's answer: HTTP 200, text/html; charset=utf-8, 5120 bytes - not the documented API answer (an HTML page usually means a proxy",
    );
    expect(results).toHaveTextContent('Answered by: page title "Request Rejected"; Server: BigIP.');
  });

  it("records suggestions with a reason when moving directly is not available", async () => {
    const { calls } = routes(false);
    await checkList();
    expect(screen.getByText(/Moving in VSA X is not available: Moving is switched off/)).toBeInTheDocument();
    const suggest = screen.getByRole("button", { name: "Suggest 2 moves" });
    expect(suggest).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Reason/), "New site for finance");
    await userEvent.click(suggest);
    await waitFor(() => expect(calls.filter((c) => c.method === "POST" && c.url === `${base}/`)).toHaveLength(2));
  });
});
