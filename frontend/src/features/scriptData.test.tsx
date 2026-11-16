import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";

import { ScriptCollectorsPanel } from "./admin/ScriptCollectorsPanel";
import { DeviceScriptData } from "./inventory/DeviceScriptData";
import { mockFetch } from "../test/utils";

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>,
);

it("shows collected script values on the device page", async () => {
  mockFetch({ "GET /api/v1/customers/c1/script-values/": { body: { collectors: [], results: [
    { asset_id: "a1", collector: "BitLocker", state: "collected", executed_at: "2026-11-15T08:00:00Z", fetched_at: "2026-11-16T08:00:00Z",
      values: { BitLockerProtection: { value: "Off", type: "Text" } } },
  ] } } });
  wrap(<DeviceScriptData customerId="c1" assetId="a1" />);
  const card = await screen.findByRole("region", { name: "BitLocker" });
  expect(card).toHaveTextContent("BitLockerProtectionOff");
  expect(card).toHaveTextContent("collected");
});

it("lists script collectors with their allowed variables", async () => {
  mockFetch({
    "GET /api/v1/automation/scripts/": { body: [{ integration_instance: "i1", id: "s1", name: "BitLocker status", category: "Reporting", platforms: ["Windows"], folder: "" }] },
    "GET /api/v1/script-collectors/": { body: [{ id: "c1", integration_instance: "i1", script_external_id: "s1", script_name: "BitLocker status", label: "BitLocker", allowed_variables: ["BitLockerProtection"], enabled: true }] },
  });
  wrap(<ScriptCollectorsPanel />);
  const list = await screen.findByRole("list", { name: "Script collectors" });
  expect(within(list).getByText("BitLockerProtection")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "BitLocker status (Reporting)" })).toBeInTheDocument();
});
