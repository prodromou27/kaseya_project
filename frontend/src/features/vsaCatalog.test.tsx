import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { makeMe, mockFetch, page, renderApp } from "../test/utils";

const row = { vendor: "Google LLC", product: "Google Chrome", reference_version: "131.0.6778.86" };
const result = {
  stats: { catalog_entries: 5, matched_programs: 1, already_current: 0, not_installed: 2, skipped: 2 },
  rows: [row],
  matched: [{
    catalog_names: ["Google Chrome (32-bit)", "Google Chrome (64-bit)"], vendor: "Google LLC", tier: "1", reference_version: "131.0.6778.86",
    release_date: "2026-11-05", installed_names: ["Google Chrome"], installs: 6, older: 3, newer: 0,
    top_versions: [{ version: "131.0.6778.86", installs: 3 }, { version: "130.0.1.1", installs: 3 }], warnings: [],
  }],
  skipped: [{ application: "Contoso Tool x64 / Contoso Tool x86", reason: "Catalog versions differ between its entries" }],
  preview: [], valid: true,
};

describe("VSA application catalog import", () => {
  it("matches a pasted table to installed programs and submits it for review", async () => {
    const { calls } = mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe({ is_super_admin: true, global_capabilities: ["system.manage", "system.cross_customer"] }) },
      "GET /api/v1/customers/": { body: page([]) },
      "GET /api/v1/catalog/imports/": { body: page([]) },
      "GET /api/v1/catalog/products/": { body: page([]) },
      "GET /api/v1/catalog/aliases/": { body: page([]) },
      "POST /api/v1/catalog/imports/from-vsa-catalog/": { body: result },
      "POST /api/v1/catalog/imports/": { status: 201, body: { id: "imp-1" } },
    } as never);
    renderApp("/admin?tab=catalog");
    expect(await screen.findByRole("heading", { name: "Import from the VSA application catalog" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "VSA 10 application catalog" })).toHaveAttribute("href", expect.stringContaining("application-catalog.htm"));
    await userEvent.type(screen.getByLabelText("VSA application catalog table"), "Google Chrome (64-bit)\tGoogle LLC\t1\t131.0.6778.86");
    await userEvent.click(screen.getByRole("button", { name: "Match installed programs" }));
    expect(await screen.findByText(/1 installed program to add or update/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Matched programs" });
    expect(within(table).getByText("Google Chrome (32-bit) / Google Chrome (64-bit)")).toBeInTheDocument();
    expect(within(table).getByText("3 older / 0 newer")).toBeInTheDocument();
    expect(screen.getByText("Skipped (1)")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Submit 1 program for review" }));
    expect(await screen.findByText(/A different administrator must approve it/)).toBeInTheDocument();
    const submitted = calls.find((c) => c.method === "POST" && c.url === "/api/v1/catalog/imports/");
    expect(JSON.parse(String(submitted?.init?.body))).toEqual({ rows: [row] });
  });
});
