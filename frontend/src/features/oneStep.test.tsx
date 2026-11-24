import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;

function setup(oneStep: boolean) {
  const customer = { ...customerA, my_capabilities: [...customerA.my_capabilities, "customer.manage_exceptions"] };
  window.sessionStorage.setItem("okp.selectedCustomer", customer.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: { ...makeMe(), one_step_approval: oneStep } },
    "GET /api/v1/customers/": { body: page([customer]) },
    [`GET ${base}/`]: { body: customer },
    [`GET ${base}/custom-field-allowlist/`]: { body: [] },
    [`POST ${base}/custom-field-allowlist/`]: { status: 201, body: { id: "f1", name: "Rack", state: "approved" } },
  } as never);
}

describe("one authorization (2026-11-24)", () => {
  it("adds a setting in one step when the server does not require a second approver", async () => {
    const { calls } = setup(true);
    renderApp(`/customers/${customerA.id}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Custom fields" }));
    expect(await screen.findByText(/No custom fields approved/)).toBeInTheDocument();
    expect(screen.queryByText(/A different administrator must approve/)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Custom field name (exact)"), "Rack");
    await userEvent.type(screen.getByLabelText("Reason"), "asset location");
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(calls.some((c) => c.url.includes("/approve/"))).toBe(false);
  });

  it("keeps the proposal wording when a second approver is required", async () => {
    setup(false);
    renderApp(`/customers/${customerA.id}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Custom fields" }));
    expect(await screen.findByRole("button", { name: "Propose field" })).toBeInTheDocument();
    expect(screen.getByText(/A different administrator must approve each name/)).toBeInTheDocument();
  });
});
