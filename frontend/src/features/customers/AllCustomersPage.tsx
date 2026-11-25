import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { QueryBoundary } from "../../components/States";
import { Badge, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";

type Row = {
  id: string; code: string; name: string; status: string; devices: number; offline: number; disk_critical: number;
  antivirus_issues: number; critical_updates: number | null; outdated_software_devices: number | null;
  compliance_pct: number | null; baselines: number; as_of: string | null; stale: boolean;
};
type Key = "code" | "devices" | "offline" | "disk_critical" | "antivirus_issues" | "critical_updates" | "outdated_software_devices" | "compliance_pct";

const COLUMNS: { key: Key; label: string; attention?: boolean; hint?: string }[] = [
  { key: "code", label: "Customer" },
  { key: "devices", label: "Devices" },
  { key: "offline", label: "Offline / not seen", attention: true },
  { key: "disk_critical", label: "Disk critical", attention: true },
  { key: "antivirus_issues", label: "Antivirus issues", attention: true },
  { key: "critical_updates", label: "Critical updates", attention: true, hint: "Devices with available Critical OS updates" },
  { key: "outdated_software_devices", label: "Outdated software", attention: true, hint: "Devices with outdated catalogued software" },
  { key: "compliance_pct", label: "Compliance", hint: "Lowest baseline score" },
];

function csv(rows: Row[]) {
  const cell = (v: unknown) => { const s = v === null || v === undefined ? "" : String(v); return `"${(/^[=+\-@]/.test(s) ? `'${s}` : s).replace(/"/g, '""')}"`; };
  const lines = [["customer", "name", ...COLUMNS.slice(1).map((c) => c.key), "data_as_of", "stale"].join(",")];
  for (const r of rows) lines.push([r.code, r.name, ...COLUMNS.slice(1).map((c) => r[c.key]), r.as_of ?? "", r.stale ? "yes" : "no"].map(cell).join(","));
  const url = URL.createObjectURL(new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "all-customers.csv";
  a.click();
  URL.revokeObjectURL(url);
}

const needsAttention = (r: Row) =>
  COLUMNS.some((c) => c.attention && typeof r[c.key] === "number" && (r[c.key] as number) > 0) || (r.compliance_pct !== null && r.compliance_pct < 80);

/** Four totals across the listed customers, above the table. */
function Totals({ rows }: { rows: Row[] }) {
  const devices = rows.reduce((n, r) => n + r.devices, 0);
  const attention = rows.filter(needsAttention).length;
  const stale = rows.filter((r) => r.stale).length;
  const items: { label: string; value: number; warn?: boolean; sub: string }[] = [
    { label: "Customers", value: rows.length, sub: "you can access" },
    { label: "Devices", value: devices, sub: "across these customers" },
    { label: "Need attention", value: attention, warn: attention > 0, sub: "with at least one amber figure" },
    { label: "Out-of-date data", value: stale, warn: stale > 0, sub: "never synced, or not recently" },
  ];
  return (
    <dl aria-label="Totals" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((i) => (
        <div key={i.label} className={`rounded-xl border bg-white px-3 py-2.5 shadow-sm ${i.warn ? "border-amber-200" : "border-slate-200"}`}>
          <dt className="text-xs font-medium text-slate-600">{i.label}</dt>
          <dd className="flex items-baseline gap-1.5">
            <span className={`text-2xl font-semibold tabular-nums tracking-tight ${i.warn ? "text-amber-800" : "text-slate-900"}`}>{i.value}</span>
            <span className="truncate text-xs text-slate-500">{i.sub}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Every customer the user can read, side by side, with drill-down into the customer's summary. ``embedded`` (the
 * dashboard with no customer selected): no page header, and a click selects the customer and opens its dashboard.
 */
export function AllCustomersPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { select } = useCustomers();
  const [sort, setSort] = useState<{ key: Key; desc: boolean }>({ key: "code", desc: false });
  const query = useQuery({
    queryKey: ["customers", "overview"],
    queryFn: ({ signal }) => api.get<{ results: Row[]; count: number; truncated: boolean }>("/customers/overview/", undefined, signal),
  });
  const sorted = (rows: Row[]) => [...rows].sort((a, b) => {
    const x = a[sort.key], y = b[sort.key];
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return sort.desc ? -c : c;
  });
  return (
    <>
      {embedded
        ? <h2 className="sr-only">Your customers</h2>
        : <PageHeader title="All customers" subtitle="Key measures for every customer you can access. Select a customer to open its summary." />}
      <QueryBoundary query={query}>
        {(d) => (
          <div className="space-y-3">
            <Totals rows={d.results} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-slate-600">{d.count} customer(s){d.truncated ? " · showing the first 200" : ""}. Amber figures need attention; “—” means no data. {embedded ? "Pick a customer to open its dashboard." : ""}</p>
              <button type="button" className="btn-secondary" disabled={!d.results.length} onClick={() => csv(sorted(d.results))}>Download (CSV)</button>
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">All customers</caption>
                <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-600">
                  <tr>
                    {COLUMNS.map((c) => (
                      <th key={c.key} scope="col" className="px-3 py-2.5 font-semibold" title={c.hint}
                        aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : undefined}>
                        <button type="button" className="inline-flex items-center gap-1 hover:text-sky-800" onClick={() => setSort({ key: c.key, desc: sort.key === c.key ? !sort.desc : c.key !== "code" })}>
                          {c.label}<span aria-hidden="true">{sort.key === c.key ? (sort.desc ? "↓" : "↑") : "↕"}</span>
                        </button>
                      </th>
                    ))}
                    <th scope="col" className="px-3 py-2.5 font-semibold">Data</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sorted(d.results).map((r) => (
                    <tr key={r.id} className="hover:bg-slate-50">
                      <td className="px-3 py-2">
                        <Link className="font-medium text-sky-800 hover:underline" to={embedded ? "/" : `/customers/${r.id}`} onClick={() => select(r.id)}>{r.code}</Link>
                        <span className="block text-xs text-slate-500">{r.name}</span>
                      </td>
                      {COLUMNS.slice(1).map((c) => {
                        const v = r[c.key];
                        const warn = c.attention && typeof v === "number" && v > 0;
                        const low = c.key === "compliance_pct" && typeof v === "number" && v < 80;
                        const shown = v === null || v === undefined ? "—" : c.key === "compliance_pct" ? `${v}%` : v;
                        return <td key={c.key} className="px-3 py-2 tabular-nums">
                          {warn || low
                            ? <span className="inline-block min-w-8 rounded bg-amber-50 px-1.5 py-0.5 text-center font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">{shown}</span>
                            : <span className={`inline-block min-w-8 px-1.5 text-center ${v === null || v === undefined ? "text-slate-400" : "text-slate-900"}`}>{shown}</span>}
                        </td>;
                      })}
                      <td className="px-3 py-2 text-xs">
                        {r.stale ? <Badge tone="warn">{r.as_of ? "out of date" : "never synced"}</Badge> : <Badge tone="good">fresh</Badge>}
                        {r.as_of ? <span className="ml-1 text-slate-500">{formatUtc(r.as_of)}</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
