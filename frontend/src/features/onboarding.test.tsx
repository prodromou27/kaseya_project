import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { OnboardingPreview, OnboardingUpload, ReconciliationResult, ReconciliationRun } from "../lib/types";
import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const engineer = { ...customerA, my_capabilities: ["customer.read", "customer.export", "customer.sync"] };
const base = `/api/v1/customers/${customerA.id}/onboarding`;

const upload: OnboardingUpload = {
  id: "u1", display_name: "expected.csv", file_format: "csv", sha256: "ab".repeat(32), bytes: 120,
  sheets: [{ name: "CSV", rows: 3, columns: 2, formula_cells_ignored: 0, truncated_cells: 0 }],
  uploaded_by: "eng@example.test", created_at: "2026-11-13T09:00:00Z", expires_at: "2026-11-16T09:00:00Z", purged_at: null, available: true,
};
const preview: OnboardingPreview = {
  sheet: "CSV", header_row: 1, headers: ["Computer Name", "Serial"],
  fields: [{ key: "hostname", label: "Hostname" }, { key: "serial_number", label: "Serial number" }],
  identifier_fields: ["hostname", "serial_number"], suggested_mapping: { hostname: 0, serial_number: 1 },
  mapping: { hostname: 0, serial_number: 1 }, data_rows: 2, rows_with_problems: 1, rows_without_identifier: 0,
  formula_cells_ignored: 1, truncated_cells: 0,
  sample: [
    { row: 2, values: { hostname: "<img src=x onerror=alert(1)>", serial_number: "SN1" }, problems: { hostname: "malformed hostname" }, has_identifier: true },
    { row: 3, values: { hostname: "PC2", serial_number: "" }, problems: {}, has_identifier: true },
  ],
};
const run: ReconciliationRun = {
  id: "r1", upload: "u1", upload_name: "expected.csv", upload_sha256: "ab".repeat(32), sheet: "CSV", header_row: 1,
  mapping: { hostname: 0 }, mapping_hash: "h", logic_version: "onboarding-match-1", generation: "g1234567-aaaa",
  data_basis: "fixture", stale_source_acknowledged: false, requested_by: "eng@example.test", state: "completed", error_code: "",
  created_at: "2026-11-13T09:00:00Z", completed_at: "2026-11-13T09:00:05Z",
  summary: {
    logic_version: "onboarding-match-1", expected_rows: 5,
    classifications: { MATCHED_CORRECT: 2, MATCHED_WRONG_GROUP: 1, NOT_FOUND_IN_COMPLETE_SNAPSHOT: 1, AMBIGUOUS: 1 },
    secondary_flags: { OFFLINE: 1 }, matched_devices: 3, snapshot_devices: 5, unexpected_vsa_assets: 1, unexpected_pending_review: 1,
    parameters: { offline_hours: 24, stale_agent_days: 7, stale_source: false, flags_not_evaluated: { OLD_AGENT: "no approved agent-version baseline is configured" } },
    notes: ["NOT_FOUND_IN_COMPLETE_SNAPSHOT is not proof that an agent is not installed."],
    generation: { id: "g1", published_at: "2026-11-13T08:00:00Z", data_basis: "fixture" },
  },
};
const ambiguous: ReconciliationResult = {
  id: "x1", kind: "expected", row_number: 4, input: { ip_address: "10.0.0.5" }, classification: "AMBIGUOUS",
  effective_classification: "AMBIGUOUS", flags: [], evidence: { reason: "IP-only match requires review" }, asset: null, actual: {},
  candidates: [{ asset_id: "a9", source_id: "g9", hostname: "PC9", organization_id: "11", organization: "Org", site_id: "5", site: "HQ", group_id: "51", group: "WS", last_seen_online: "" }],
  pending_review_row: null, review_state: "pending", reviewed_classification: "", reviewed_asset: null, reviewed_by: null, reviewed_at: null, review_note: "",
};

function routes(extra: Record<string, unknown> = {}, customer = engineer) {
  window.sessionStorage.setItem("okp.selectedCustomer", customer.id);
  return mockFetch({
    "GET /api/v1/auth/me/": { body: makeMe() },
    "GET /api/v1/customers/": { body: page([customer]) },
    [`GET ${base}/runs/eligibility/`]: { body: { generations: [{ id: "g1", instance: "VSA demo", published_at: "2026-11-13T08:00:00Z", data_basis: "fixture", hierarchy_status: "collected", row_count: 5 }], blocked: null, stale: false } },
    [`GET ${base}/runs/`]: { body: page([run]) },
    [`POST ${base}/uploads/`]: { status: 201, body: upload },
    [`POST ${base}/uploads/u1/preview/`]: { body: preview },
    [`POST ${base}/runs/`]: { status: 202, body: { ...run, state: "queued" } },
    [`GET ${base}/runs/r1/`]: { body: run },
    [`GET ${base}/runs/r1/results/`]: { body: page([ambiguous]) },
    [`POST ${base}/runs/r1/results/x1/review/`]: { body: { ...ambiguous, review_state: "decided", reviewed_classification: "MATCHED_CORRECT" } },
    ...extra,
  } as never);
}

describe("onboarding check", () => {
  it("uploads, previews untrusted cells as text, and starts a comparison", async () => {
    const { calls } = routes();
    renderApp("/onboarding");
    expect(await screen.findByText(/Compared against VSA snapshot/)).toBeInTheDocument();
    const file = new File(["Computer Name,Serial\nPC1,SN1\n"], "expected.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("Expected inventory file"), file);
    const table = await screen.findByRole("table", { name: "Preview of mapped rows" });
    expect(within(table).getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument(); // rendered as text
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("1 formula cells ignored")).toBeInTheDocument();
    expect(screen.getByLabelText("Hostname (identifier)")).toHaveValue("0");
    await userEvent.click(screen.getByRole("button", { name: "Start comparison" }));
    const post = calls.find((c) => c.method === "POST" && c.url === `${base}/runs/`);
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ upload: "u1", sheet: "CSV", mapping: { hostname: 0, serial_number: 1 }, allow_stale: false });
    const uploadCall = calls.find((c) => c.url === `${base}/uploads/`);
    expect(uploadCall?.init?.body).toBeInstanceOf(FormData);
  });

  it("shows why a comparison is blocked and hides the upload for viewers", async () => {
    routes({ [`GET ${base}/runs/eligibility/`]: { body: { generations: [], blocked: { code: "no_complete_generation", detail: "No complete VSA snapshot exists for this customer yet. Run a sync first." }, stale: false } } }, customerA);
    renderApp("/onboarding");
    expect(await screen.findByText(/Comparison blocked: No complete VSA snapshot/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Expected inventory file")).not.toBeInTheDocument();
    expect(screen.getByText(/requires the engineer or administrator role/)).toBeInTheDocument();
  });

  it("run page: honest summary, exports and reviewer decision", async () => {
    const { calls } = routes();
    renderApp("/onboarding/r1");
    expect(await screen.findByText("Onboarding check — expected.csv")).toBeInTheDocument();
    expect(screen.getByText(/is not proof that an agent is not installed/)).toBeInTheDocument();
    expect(screen.getByText(/Device moves are not performed by this portal/)).toBeInTheDocument();
    expect(screen.getByText(/OLD_AGENT not evaluated/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download workbook (XLSX)" })).toHaveAttribute("href", `${base}/runs/r1/export/?output=xlsx`);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm PC9" }));
    const review = calls.find((c) => c.method === "POST" && c.url.endsWith("/review/"));
    expect(JSON.parse(String(review?.init?.body))).toEqual({ decision: "match", asset: "a9", note: "" });
    await userEvent.click(screen.getByRole("button", { name: "Unexpected in VSA" }));
    expect(calls.some((c) => c.url.includes("kind=unexpected"))).toBe(true);
  });
});
