import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";

import { GroupSuggestions } from "./groups/GroupSuggestions";
import { customerA, mockFetch, page } from "../test/utils";

function setup(results: unknown[] = [], status = 200, count = results.length) {
  const calls = mockFetch({ [`GET /api/v1/customers/${customerA.id}/groups/51/suggestions/`]: { status, body: {
    ...page(results), count, is_onboarding: true, suggestion_note: "Network first. Manual transfer only.",
  } } }).calls;
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><GroupSuggestions customer={customerA} groupId="51" instance="source-a" /></MemoryRouter>
  </QueryClientProvider>);
  return calls;
}

it("shows network evidence before weaker naming hints on the onboarding group", async () => {
  const calls = setup([{ asset_id: "a1", hostname: "NIC-PC001", suggestions_ambiguous: true, suggestions: [
    { id: "g1", name: "Office LAN", basis: "observed_subnet", matches: [{ cidr: "10.4.0.0/24", addresses: ["10.4.0.9"], basis: "observed_subnet", peer_devices: 4 }] },
    { id: "g2", name: "NIC Office", basis: "naming", matches: [], naming_evidence: ["Device naming token 'nic' matches the group name."] },
  ] }]);
  const table = await screen.findByRole("table", { name: "Onboarding device suggestions" });
  expect(table).toHaveTextContent("Office LANObserved subnet");
  expect(table).toHaveTextContent("NIC OfficeNaming only");
  expect(within(table).getByText(/observed on 4 destination device/)).toBeInTheDocument();
  expect(within(table).getByText(/Several groups match/)).toBeInTheDocument();
  expect(within(table).getByRole("link", { name: "NIC-PC001" })).toHaveAttribute("href", "/assets/a1?tab=operations");
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
});

it("keeps devices without evidence visible without inventing a destination", async () => {
  setup([{ asset_id: "a1", hostname: "Unknown-device", suggestions_ambiguous: false, suggestions: [] }]);
  expect(await screen.findByText(/No matching subnet or naming evidence/)).toBeInTheDocument();
  expect(screen.getByText(/Placement is not classified as incorrect/)).toBeInTheDocument();
});

it("pages and filters the complete source-qualified onboarding population", async () => {
  const calls = setup([{ asset_id: "a1", hostname: "NIC-PC001", suggestions_ambiguous: false, suggestions: [] }], 200, 205);
  await screen.findByRole("table", { name: "Onboarding device suggestions" });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(calls.some((call) => call.url.includes("page=2"))).toBe(true));
  await userEvent.type(screen.getByRole("searchbox", { name: "Find onboarding device" }), "NIC");
  await waitFor(() => expect(calls.some((call) => call.url.includes("search=NIC") && call.url.includes("page=1") && call.url.includes("instance=source-a"))).toBe(true));
});

it("shows API failure with no fabricated placement hint", async () => {
  setup([], 503);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
