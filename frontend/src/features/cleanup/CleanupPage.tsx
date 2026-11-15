import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { SelectCustomer } from "../../components/SelectCustomer";
import { QueryBoundary } from "../../components/States";
import { PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import { useUrlFilters } from "../../lib/useUrlFilters";
import type { Customer } from "../../lib/types";
import { DataSources } from "../inventory/DataSources";

type Finding = {
  category: string; asset_id: string; hostname: string; site: string; group: string; group_external_id: string;
  serial_number: string; last_seen: string | null; days_since_seen: number | null; detail: string;
};
type Cleanup = { days: number; categories: { key: string; label: string; count: number }[]; devices_with_findings: number; count: number; results: Finding[] };

function csvCell(v: string) {
  const safe = /^[=+\-@]/.test(v) ? `'${v}` : v;
  return `"${safe.replace(/"/g, '""')}"`;
}

function download(rows: Finding[], labels: Record<string, string>, code: string) {
  const lines = [["issue", "device", "site", "group", "serial", "last_seen", "detail"].join(",")];
  for (const r of rows) lines.push([labels[r.category] ?? r.category, r.hostname, r.site, r.group, r.serial_number, r.last_seen ?? "", r.detail].map(csvCell).join(","));
  const url = URL.createObjectURL(new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `cleanup-${code}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function Workspace({ customer }: { customer: Customer }) {
  const { filters, update } = useUrlFilters({ category: "", days: "90" });
  const query = useQuery({
    queryKey: ["cleanup", customer.id, filters.days, filters.category],
    queryFn: ({ signal }) => api.get<Cleanup>(`/customers/${customer.id}/cleanup/`, { days: filters.days, category: filters.category }, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(c) => {
        const labels = Object.fromEntries(c.categories.map((x) => [x.key, x.label]));
        const columns: ColumnDef<Finding, unknown>[] = [
          { header: "Device", cell: ({ row }) => <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname || "(no hostname)"}</Link> },
          { header: "Issue", cell: ({ row }) => labels[row.original.category] ?? row.original.category },
          { header: "Detail", cell: ({ row }) => <span className="text-xs text-slate-700">{row.original.detail}</span> },
          { header: "Site / group", cell: ({ row }) => `${row.original.site || "—"} / ${row.original.group || "no group"}` },
          { header: "Last seen", cell: ({ row }) => row.original.last_seen ? <span className="nowrap">{formatUtc(row.original.last_seen)}</span> : "never" },
        ];
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <p className="text-sm text-slate-700"><strong>{c.devices_with_findings}</strong> device(s) with something to tidy up in VSA X. Nothing here is changed automatically.</p>
              <label className="list-label">Not seen for more than
                <select className="input" value={filters.days} onChange={(e) => update({ days: e.target.value })}>
                  {[30, 60, 90, 180, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
                </select>
              </label>
            </div>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Cleanup categories">
              <button type="button" className="list-preset" aria-pressed={!filters.category} onClick={() => update({ category: "" })}>All</button>
              {c.categories.map((x) => (
                <button key={x.key} type="button" className="list-preset" aria-pressed={filters.category === x.key} disabled={!x.count} onClick={() => update({ category: x.key })}>
                  {x.label} <span className="ml-1 font-semibold tabular-nums">{x.count}</span>
                </button>
              ))}
            </div>
            <div className="flex justify-end">
              <button type="button" className="btn-secondary" disabled={!c.results.length} onClick={() => download(c.results, labels, customer.code)}>Download to-do list (CSV)</button>
            </div>
            <DataTable caption="Cleanup findings" columns={columns} rows={c.results} getRowId={(r) => `${r.category}-${r.asset_id}`}
              emptyTitle={filters.category ? "Nothing in this category." : "Nothing to clean up. Well done."} />
            <p className="text-xs text-slate-500">Placeholder serials (for example “To be filled by O.E.M.”) and virtual or randomised MAC addresses are not treated as duplicates. Findings come from the latest snapshot; remove or merge devices in VSA X, then sync.</p>
          </div>
        );
      }}
    </QueryBoundary>
  );
}

export function CleanupPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Cleanup" subtitle="Duplicates, forgotten agents and placement gaps to tidy up in VSA X." />
      {!selected ? <SelectCustomer /> : <><DataSources customer={selected} compact /><Workspace key={selected.id} customer={selected} /></>}
    </>
  );
}
