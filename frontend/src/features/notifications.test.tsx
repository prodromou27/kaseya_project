import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { NotificationRow, NotificationSummary } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const base = `/api/v1/customers/${customerA.id}`;
const summary: NotificationSummary = {
  as_of: ["2026-11-13T09:00:00Z"], window_days: 14, per_device_limit: 50, devices: 130,
  collection_status: { collected: 100, not_requested: 25, failed: 5 }, devices_without_fetch_row: 0,
  notifications: 40, devices_with_notifications: 32, by_priority: { critical: 3, elevated: 37 },
  recurring: [{ pattern: "The free space on disk drive C: on the computer '…' is below #%", count: 31, devices: 29 }],
  note: "Device notifications from VSA X within the retention window. Devices not collected are not 'without notifications'.",
};
const row: NotificationRow = {
  id: "n1", asset: "a1", hostname: "PC1", vendor_id: "10", priority: "critical", occurred_at: "2026-11-13T08:00:00Z",
  occurred_raw: "2026-11-13T08:00:00Z", message: "Logon failure for [account] reported by [email]", redactions: 2,
};

function routes(caps: string[] = customerA.my_capabilities) {
  const customer = { ...customerA, my_capabilities: caps };
  window.sessionStorage.setItem("okp.selectedCustomer", customer.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customer]) },
    [`GET ${base}/notifications/summary/`]: { body: summary },
    [`GET ${base}/notifications/`]: { body: page([row]) },
    [`GET /api/v1/customers/${customer.id}/`]: { body: customer },
    [`GET ${base}/custom-field-allowlist/`]: { body: [] },
    [`POST ${base}/custom-field-allowlist/`]: {
      status: 400,
      body: { error: { code: "validation_error", message: "The request was invalid.", details: { name: ["Credential-like fields (passwords, keys, tokens, PINs...) cannot be approved."] } } },
    },
  } as never);
}

describe("notifications", () => {
  it("separates not-collected devices and shows redaction", async () => {
    routes();
    renderApp("/notifications");
    expect(await screen.findByText("Devices not collected")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument(); // 25 not requested + 5 failed
    expect(screen.getByText(/not 'without notifications'/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Recurring notifications" })).toHaveTextContent("below #%");
    const table = await screen.findByRole("table", { name: "Device notifications" });
    expect(table).toHaveTextContent("[account]");
    expect(table).toHaveTextContent("2 redacted");
  });

  it("refuses credential-like custom field names with a clear message", async () => {
    routes([...customerA.my_capabilities, "customer.manage_exceptions"]);
    renderApp(`/customers/${customerA.id}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Custom fields" }));
    expect(await screen.findByText(/No custom fields approved: none are collected/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Custom field name (exact)"), "Local Admin Password");
    await userEvent.type(screen.getByLabelText("Reason"), "convenience");
    await userEvent.click(screen.getByRole("button", { name: "Propose field" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot be approved");
  });
});
