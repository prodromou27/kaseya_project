import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader, statusTone } from "../../components/ui";
import { api, apiUpload, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  type Customer,
  type OnboardingEligibility,
  type OnboardingPreview,
  type OnboardingUpload,
  type Paginated,
  type ReconciliationRun,
} from "../../lib/types";
import { SelectCustomer } from "../../components/SelectCustomer";

function Eligibility({ customer }: { customer: Customer }) {
  const query = useQuery({
    queryKey: ["onboarding-eligibility", customer.id],
    queryFn: ({ signal }) => api.get<OnboardingEligibility>(`/customers/${customer.id}/onboarding/runs/eligibility/`, undefined, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(e) => (
        <section aria-label="Snapshot used for comparison" className="mb-4 text-sm">
          {e.generations.map((g) => (
            <p key={g.id}>
              Compared against VSA snapshot from <strong>{g.instance}</strong> published {formatUtc(g.published_at)} ·{" "}
              {g.row_count} devices · data basis <Badge tone={g.data_basis === "live" ? "good" : "info"}>{g.data_basis}</Badge>
            </p>
          ))}
          {e.blocked ? <Notice tone="warn">Comparison blocked: {e.blocked.detail}</Notice> : null}
          {!e.blocked && e.stale ? <Notice tone="warn">The snapshot is stale. You can sync again, or acknowledge it when starting.</Notice> : null}
        </section>
      )}
    </QueryBoundary>
  );
}

function NewComparison({ customer }: { customer: Customer }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [upload, setUpload] = useState<OnboardingUpload | null>(null);
  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [mapping, setMapping] = useState<Record<string, number | null> | null>(null);
  const [allowStale, setAllowStale] = useState(false);
  const base = `/customers/${customer.id}/onboarding`;

  const send = useMutation({
    mutationFn: (file: File) => apiUpload<OnboardingUpload>(`${base}/uploads/`, file),
    onSuccess: (u) => {
      setUpload(u);
      setSheet(u.sheets[0]?.name ?? "");
      setHeaderRow(1);
      setMapping(null);
    },
  });
  const preview = useQuery({
    queryKey: ["onboarding-preview", upload?.id, sheet, headerRow, mapping],
    queryFn: () =>
      api.post<OnboardingPreview>(`${base}/uploads/${upload?.id}/preview/`, {
        sheet,
        header_row: headerRow,
        ...(mapping ? { mapping } : {}),
      }),
    enabled: upload !== null && sheet !== "",
    retry: false,
  });
  const start = useMutation({
    mutationFn: () =>
      api.post<ReconciliationRun>(`${base}/runs/`, {
        upload: upload?.id,
        sheet,
        header_row: headerRow,
        mapping: mapping ?? preview.data?.mapping ?? {},
        allow_stale: allowStale,
      }),
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ["onboarding-runs", customer.id] });
      void navigate(`/onboarding/${run.id}`);
    },
  });
  const p = preview.data;
  const current = mapping ?? p?.mapping ?? {};

  return (
    <section aria-labelledby="new-h" className="mb-6 rounded border border-slate-200 bg-white p-4">
      <h2 id="new-h" className="mb-2 font-semibold">New comparison</h2>
      <p className="mb-3 text-xs text-slate-500">
        Upload the customer's expected device list (.xlsx or .csv, at most 5 MB). Macro-enabled and legacy formats are refused,
        formulas are never evaluated, and the file is deleted automatically after 72 hours.
      </p>
      <Field label="Expected inventory file">
        {(id) => (
          <input id={id} type="file" accept=".xlsx,.csv" className="text-sm"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) send.mutate(f); }} />
        )}
      </Field>
      {send.isPending ? <p className="mt-2 text-sm">Checking file…</p> : null}
      {send.isError ? <p role="alert" className="mt-2 text-sm text-red-700">{describeError(send.error)}</p> : null}

      {upload ? (
        <div className="mt-4 space-y-3">
          <p className="text-sm">
            <strong>{upload.display_name}</strong> · {upload.file_format.toUpperCase()} · sha256 <code className="text-xs">{upload.sha256.slice(0, 12)}…</code>
          </p>
          <div className="flex flex-wrap gap-3">
            <Field label="Worksheet">
              {(id) => (
                <select id={id} className="input" value={sheet} onChange={(e) => { setSheet(e.target.value); setMapping(null); }}>
                  {upload.sheets.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.rows} rows)</option>)}
                </select>
              )}
            </Field>
            <Field label="Header row">
              {(id) => (
                <input id={id} type="number" min={1} max={50} className="input w-24" value={headerRow}
                  onChange={(e) => { setHeaderRow(Math.max(1, Math.min(50, Number(e.target.value) || 1))); setMapping(null); }} />
              )}
            </Field>
          </div>
          {preview.isError ? <p role="alert" className="text-sm text-red-700">{describeError(preview.error)}</p> : null}
          {p ? (
            <>
              <fieldset className="rounded border border-slate-200 p-3">
                <legend className="px-1 text-sm font-semibold">Column mapping</legend>
                <p className="mb-2 text-xs text-slate-500">Suggested from exact header names only. Map at least one identifier.</p>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {p.fields.map((f) => (
                    <Field key={f.key} label={`${f.label}${p.identifier_fields.includes(f.key) ? " (identifier)" : ""}`}>
                      {(id) => (
                        <select id={id} className="input" value={current[f.key] ?? ""}
                          onChange={(e) => setMapping({ ...current, [f.key]: e.target.value === "" ? null : Number(e.target.value) })}>
                          <option value="">— not mapped —</option>
                          {p.headers.map((h, i) => <option key={`${h}-${i}`} value={i}>{h}</option>)}
                        </select>
                      )}
                    </Field>
                  ))}
                </div>
              </fieldset>
              <p className="text-sm">
                {p.data_rows} data rows · {p.rows_without_identifier} without a usable identifier · {p.rows_with_problems} with malformed values
                {p.formula_cells_ignored ? <> · <Badge tone="warn">{p.formula_cells_ignored} formula cells ignored</Badge></> : null}
              </p>
              <DataTable caption="Preview of mapped rows" rows={p.sample} getRowId={(r) => String(r.row)}
                emptyTitle="No data rows below the header row."
                columns={[
                  { header: "Row", accessorKey: "row" },
                  ...Object.keys(p.mapping).map((k) => ({
                    header: p.fields.find((f) => f.key === k)?.label ?? k,
                    cell: ({ row }: { row: { original: OnboardingPreview["sample"][number] } }) => (
                      <span>{row.original.values[k]}{row.original.problems[k] ? <span className="ml-1"><Badge tone="warn">{row.original.problems[k]}</Badge></span> : null}</span>
                    ),
                  })),
                ]} />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={allowStale} onChange={(e) => setAllowStale(e.target.checked)} />
                Compare even if the snapshot is stale (every row is then flagged STALE_SOURCE)
              </label>
              <button type="button" className="btn-primary" disabled={start.isPending} onClick={() => start.mutate()}>
                Start comparison
              </button>
              {start.isError ? <p role="alert" className="text-sm text-red-700">{describeError(start.error)}</p> : null}
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function Runs({ customer }: { customer: Customer }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["onboarding-runs", customer.id, page],
    queryFn: ({ signal }) => api.get<Paginated<ReconciliationRun>>(`/customers/${customer.id}/onboarding/runs/`, { page }, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(data) => (
        <DataTable caption="Previous comparisons" rows={data.results} total={data.count} page={page} onPageChange={setPage}
          getRowId={(r) => r.id} emptyTitle="No comparisons yet."
          columns={[
            { header: "Started", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/onboarding/${row.original.id}`}>{formatUtc(row.original.created_at)}</Link> },
            { header: "File", cell: ({ row }) => `${row.original.upload_name} · ${row.original.sheet}` },
            { header: "State", cell: ({ row }) => <Badge tone={statusTone[row.original.state] ?? "neutral"}>{row.original.state}</Badge> },
            { header: "Rows", cell: ({ row }) => row.original.summary.expected_rows ?? "—" },
            { header: "Matched (any placement)", cell: ({ row }) => row.original.summary.matched_devices ?? "—" },
            { header: "Not found", cell: ({ row }) => row.original.summary.classifications?.NOT_FOUND_IN_COMPLETE_SNAPSHOT ?? (row.original.state === "completed" ? 0 : "—") },
            { header: "By", accessorKey: "requested_by" },
          ]} />
      )}
    </QueryBoundary>
  );
}

export function OnboardingPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Onboarding check"
        subtitle="Compare a customer's expected device list with the latest complete VSA X snapshot. Read-only: nothing is changed in VSA X." />
      {!selected ? (
        <SelectCustomer />
      ) : (
        <>
          <Eligibility customer={selected} />
          {selected.my_capabilities.includes(CAP.sync) ? <NewComparison customer={selected} /> : (
            <Notice tone="info">Starting a comparison requires the engineer or administrator role for this customer.</Notice>
          )}
          <h2 className="mb-2 mt-4 text-sm font-semibold">Previous comparisons</h2>
          <Runs customer={selected} />
        </>
      )}
    </>
  );
}
