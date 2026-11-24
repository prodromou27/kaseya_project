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
  expect(screen.getByRole("button", { name: "Suggest move" })).toBeDisabled();
});

it("shows overlap evidence and selecting a suggestion does not submit a proposal", async () => {
  const calls = setup([{ id: "g1", name: "Office", matches: [{ cidr: "10.0.1.0/24", addresses: ["10.0.1.10"] }] }], true);
  expect(await screen.findByText(/Several groups match/)).toBeInTheDocument();
  expect(screen.getByText(/10.0.1.10 in 10.0.1.0\/24/)).toBeInTheDocument();
  const use = screen.getByRole("button", { name: "Use Office" });
  use.focus();
  await userEvent.keyboard("{Enter}");
  expect(screen.getByLabelText("Destination group")).toHaveValue("g1");
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
});

it("shows API failures without inventing suggestions", async () => {
  setup([], false, 503);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use Office" })).not.toBeInTheDocument();
});

it("distinguishes identical destination names by stable group ID", async () => {
  const calls = setup([
    { id: "g1", name: "Office", external_id: "52", site: "5", basis: "naming", matches: [] },
    { id: "g2", name: "Office", external_id: "61", site: "6", basis: "naming", matches: [] },
  ], true);
  await userEvent.click(await screen.findByRole("button", { name: "Use Office · ID 52" }));
  expect(screen.getByLabelText("Destination group")).toHaveValue("g1");
  expect(screen.getByRole("button", { name: "Use Office · ID 61" })).toBeInTheDocument();
  expect(screen.getByText("Site 5 · group ID 52")).toBeInTheDocument();
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
});

it("lets an administrator move the device in one step after one confirmation", async () => {
  const calls = mockFetch({
    [`GET /api/v1/customers/${customerA.id}/group-moves/options/`]: { body: {
      source_group: "Onboarding", source_is_onboarding: true, execution_enabled: true, move_now_allowed: true,
      policy_impact: "", suggestion_note: "", suggestions: [], suggestions_ambiguous: false,
      groups: [{ id: "g1", name: "Office", site: "5", external_id: "52" }],
    } },
    [`POST /api/v1/customers/${customerA.id}/group-moves/move-now/`]: { body: { id: "p1", execution: {
      state: "succeeded", executed_by: "admin@example.test", started_at: "2026-11-24T10:00:00Z", finished_at: "2026-11-24T10:00:01Z",
      http_status: 200, error_code: "", observed_group_id: "52", verified_at: "2026-11-24T10:00:01Z" } } },
  }).calls;
  const admin = { ...customerA, my_capabilities: ["customer.read", "customer.group_move.propose", "customer.group_move.approve"] };
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><ProposeGroupMove customer={admin} assetId="device-1" /></MemoryRouter>
  </QueryClientProvider>);
  await userEvent.selectOptions(await screen.findByLabelText("Destination group"), "g1");
  await userEvent.click(screen.getByRole("button", { name: "Move in VSA X…" }));
  expect(screen.getByRole("group", { name: "Confirm move" })).toHaveTextContent("from Onboarding to Office (ID 52)");
  await userEvent.click(screen.getByRole("button", { name: "Move now" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Moved in VSA X");
  const posts = calls.filter((c) => c.method === "POST");
  expect(posts.map((c) => c.url)).toEqual([`/api/v1/customers/${customerA.id}/group-moves/move-now/`]);
  expect(JSON.parse(String(posts[0]?.init?.body))).toEqual({ asset: "device-1", target_group: "g1", reason: "" });
});
