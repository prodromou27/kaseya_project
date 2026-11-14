import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";

import { ProposeGroupMove } from "./groups/GroupMovesPage";
import { customerA, mockFetch } from "../test/utils";

function setup(suggestions: unknown[] = [], ambiguous = false, status = 200) {
  const calls = mockFetch({ [`GET /api/v1/customers/${customerA.id}/group-moves/options/`]: { status, body: {
    source_group: "Generic installation", source_is_onboarding: true, execution_enabled: false,
    policy_impact: "Proposal only; no execution.", suggestion_note: "Manual administrator transfer.",
    suggestions, suggestions_ambiguous: ambiguous,
    groups: [{ id: "g1", name: "Office", site: "5", external_id: "52" }],
  } } }).calls;
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><ProposeGroupMove customer={{ ...customerA, my_capabilities: [...customerA.my_capabilities, "customer.group_move.propose"] }} assetId="device-1" /></MemoryRouter>
  </QueryClientProvider>);
  return calls;
}

it("shows a valid temporary onboarding destination and unknown placement without matching evidence", async () => {
  setup();
  expect(await screen.findByText(/valid temporary installation destination/)).toBeInTheDocument();
  expect(screen.getByText(/Placement is not classified as incorrect/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit proposal" })).toBeDisabled();
});

it("shows overlap evidence and selecting a suggestion does not submit a proposal", async () => {
  const calls = setup([{ id: "g1", name: "Office", matches: [{ cidr: "10.0.1.0/24", addresses: ["10.0.1.10"] }] }], true);
  expect(await screen.findByText(/Several groups match/)).toBeInTheDocument();
  expect(screen.getByText(/10.0.1.10 in 10.0.1.0\/24/)).toBeInTheDocument();
  const use = screen.getByRole("button", { name: "Use Office" });
  use.focus();
  await userEvent.keyboard("{Enter}");
  expect(screen.getByLabelText("Target group")).toHaveValue("g1");
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
});

it("shows API failures without inventing suggestions", async () => {
  setup([], false, 503);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use Office" })).not.toBeInTheDocument();
});
