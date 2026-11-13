import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const admin = makeMe({ is_super_admin: true, memberships: [], global_capabilities: ["system.manage", "system.cross_customer"] });

function routes(outcome = "ok") {
  return mockFetch({
    "GET /api/v1/auth/me/": { body: admin },
    "GET /api/v1/customers/": { body: page([customerA]) },
    "POST /api/v1/integrations/connect/": {
      body: {
        integration_id: "i9",
        connection: { outcome, message: outcome === "ok" ? "Connected." : "The VSA X server rejected the credentials.", data_basis: "live", latency_ms: 5 },
        organizations: outcome === "ok"
          ? [
              { external_org_id: "1", name: "Head Office", mapping: null },
              { external_org_id: "2", name: "Branch", mapping: null },
              { external_org_id: "3", name: "Old Org", mapping: { status: "approved", customer: { code: "OLD" } } },
            ]
          : [],
      },
    },
    "POST /api/v1/integrations/i9/import-orgs/": {
      body: { imported: [{ external_org_id: "1", customer: "HEAD-OFFICE", status: "linked", sync: "started" }], syncs_started: 1 },
    },
  } as never);
}

async function connect() {
  const form = await screen.findByRole("form", { name: "Connect VSA" });
  await userEvent.type(within(form).getByLabelText("VSA X address"), "https://tenant.vsax.example");
  await userEvent.type(within(form).getByLabelText("API token ID"), "id-1");
  await userEvent.type(within(form).getByLabelText("API token secret"), "FAKE-SECRET");
  await userEvent.click(within(form).getByRole("button", { name: "Connect" }));
}

describe("connect VSA wizard", () => {
  it("connects, imports the ticked organisations and never shows the secret again", async () => {
    const { calls } = routes();
    renderApp("/setup");
    await connect();
    const list = await screen.findByRole("list", { name: "VSA organisations" });
    expect(list).toHaveTextContent("already linked to OLD");
    // Untick Branch, link nothing else: only Head Office is imported, as a new customer.
    await userEvent.click(within(list).getByRole("checkbox", { name: /Branch/ }));
    await userEvent.click(screen.getByRole("button", { name: "Import 1 organisation(s)" }));
    expect(await screen.findByRole("region", { name: "Done" })).toHaveTextContent("HEAD-OFFICE");
    const post = calls.find((c) => c.url.endsWith("/import-orgs/"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ organizations: [{ external_org_id: "1", name: "Head Office" }] });
    const connectBody = JSON.parse(String(calls.find((c) => c.url.endsWith("/connect/"))?.init?.body));
    expect(connectBody).toEqual({ base_url: "https://tenant.vsax.example", token_id: "id-1", token_secret: "FAKE-SECRET" });
    expect(document.body).not.toHaveTextContent("FAKE-SECRET");
  }, 20_000); // many keystrokes: slower than the 5 s default on a loaded machine

  it("stays on the first step and explains a failed connection", async () => {
    routes("auth_failed");
    renderApp("/setup");
    await connect();
    expect(await screen.findByRole("alert")).toHaveTextContent("rejected the credentials");
    expect(screen.getByLabelText("API token secret")).toHaveValue("");
  }, 20_000);
});
