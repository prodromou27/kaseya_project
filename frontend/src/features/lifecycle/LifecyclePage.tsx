import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { SelectCustomer } from "../../components/SelectCustomer";
import { QueryBoundary } from "../../components/States";
import { Badge, Notice, PageHeader, type Tone } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import type { Customer, LifecycleGroup, LifecycleRow, LifecycleStatus, LifecycleSummary } from "../../lib/types";

const STATUSES: LifecycleStatus[] = ["end_of_support", "ending_soon", "supported", "unknown"];
const DOT: Record<LifecycleStatus, string> = { end_of_support: "bg-red-600", ending_soon: "bg-amber-500", supported: "bg-emerald-600", unknown: "bg-slate-400" };
export const LIFECYCLE_TONE: Record<LifecycleStatus, Tone> = { end_of_support: "bad", ending_soon: "warn", supported: "good", unknown: "neutral" };

type Kind = "os" | "software";

function Totals({ summary, kind, onPick }: { summary: LifecycleSummary; kind: Kind; onPick: (s: LifecycleStatus) => void }) {
  const part = kind === "os" ? summary.os : summary.software;
  const total = kind === "os" ? summary.os.devices : summary.software.installations;
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {STATUSES.map((s) => (
        <button key={s} type="button" onClick={() => onPick(s)}
                className="rounded border border-slate-200 bg-white p-3 text-left hover:border-sky-300 focus:outline-none focus:ring-2 focus:ring-sky-500">
          <span className="flex items-center justify-between gap-2 text-xs font-medium text-slate-600">
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${DOT[s]}`} />
              {summary.labels[s]}
            </span>
          </span>
          <span className="mt-1 block text-2xl font-semibold tabular-nums">{part.totals[s]}</span>
          <span className="block text-xs text-slate-500">of {total} {kind === "os" ? "devices" : "installations"}</span>
        </button>
      ))}
    </div>
  );
}

function groupColumns(summary: LifecycleSummary, kind: Kind): ColumnDef<LifecycleGroup, unknown>[] {
  return [
    { header: "Status", cell: ({ row }) => <Badge tone={LIFECYCLE_TONE[row.original.status]}>{summary.labels[row.original.status]}</Badge> },
    {
      header: kind === "os" ? "Release" : "Product version line",
      cell: ({ row }) => row.original.entry
        ? <span>{row.original.entry.label}{row.original.entry.version_prefix ? <span className="block text-xs text-slate-500">version {row.original.entry.version_prefix}.*</span> : null}</span>
        : <span>{row.original.reported || "(not reported)"} <span className="block text-xs text-slate-500">{summary.reasons[row.original.reason] ?? row.original.reason}</span></span>,
    },
    { header: kind === "os" ? "Devices" : "Installations", cell: ({ row }) => <span className="tabular-nums">{row.original.count}</span> },
    { header: "End of support", cell: ({ row }) => row.original.entry?.end_of_support ?? "—" },
    { header: "Extended support until", cell: ({ row }) => row.original.entry?.extended_until ?? "—" },
    {
      header: "Source",
      cell: ({ row }) => row.original.entry
        ? <span className="text-xs"><a href={row.original.entry.source_url} target="_blank" rel="noreferrer noopener" className="text-sky-800 underline">{row.original.entry.source_type.replace(/_/g, " ")}</a><span className="block text-slate-500">checked {row.original.entry.source_checked_at}</span></span>
        : <span className="text-xs text-slate-400">no cited entry</span>,
    },
  ];
}

function Devices({ customer, kind, status, summary }: { customer: Customer; kind: Kind; status: LifecycleStatus; summary: LifecycleSummary }) {
  const query = useQuery({
    queryKey: ["lifecycle", customer.id, "devices", kind, status],
    queryFn: ({ signal }) => api.get<{ count: number; results: LifecycleRow[] }>(`/customers/${customer.id}/lifecycle/devices/`, { kind, status }, signal),
  });
  const columns: ColumnDef<LifecycleRow, unknown>[] = [
    { header: "Device", cell: ({ row }) => <Link to={`/assets/${row.original.asset_id}`} className="text-sky-800 hover:underline">{row.original.hostname || "(no hostname)"}</Link> },
    { header: kind === "os" ? "Reported OS" : "Software", cell: ({ row }) => (kind === "os" ? row.original.os_name : row.original.name) || "—" },
    { header: "Reported version", cell: ({ row }) => <code className="text-xs">{(kind === "os" ? row.original.os_version : row.original.installed_version) || "—"}</code> },
    { header: "Lifecycle entry", cell: ({ row }) => row.original.entry?.label ?? (summary.reasons[row.original.reason] ?? row.original.reason) },
    { header: "End of support", cell: ({ row }) => row.original.entry?.end_of_support ?? "—" },
  ];
  return (
    <QueryBoundary query={query}>
      {(data) => (
        <DataTable caption={`${kind === "os" ? "Devices" : "Installations"}: ${summary.labels[status]}`} columns={columns} rows={data.results}
                   total={data.count} getRowId={(r) => `${r.asset_id}-${r.name ?? ""}-${r.installed_version ?? ""}`} emptyTitle="None." />
      )}
    </QueryBoundary>
  );
}

function View({ customer }: { customer: Customer }) {
  const [kind, setKind] = useState<Kind>("os");
  const [status, setStatus] = useState<LifecycleStatus | null>(null);
  const query = useQuery({
    queryKey: ["lifecycle", customer.id],
    queryFn: ({ signal }) => api.get<LifecycleSummary>(`/customers/${customer.id}/lifecycle/`, undefined, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(s) => {
        const part = kind === "os" ? s.os : s.software;
        return (
          <div className="space-y-4">
            <Notice tone="info">
              Support status is taken only from the reviewed lifecycle catalog: an entry needs an official vendor source and a
              second administrator's approval. Anything without one is shown as <strong>unknown</strong> and is never
              counted as supported. Evaluated on {s.evaluated_on}; ending soon = within {s.ending_soon_days} days. This is
              not a patch or vulnerability statement.
              {s.data_basis.includes("fixture") ? " Demo data: the dates come from illustrative DEMO entries." : ""}
            </Notice>
            <div role="tablist" aria-label="Lifecycle scope" className="flex gap-2">
              {(["os", "software"] as Kind[]).map((k) => (
                <button key={k} type="button" role="tab" aria-selected={kind === k}
                        className={kind === k ? "btn-primary" : "btn-secondary"} onClick={() => { setKind(k); setStatus(null); }}>
                  {k === "os" ? "Operating systems" : "Software"}
                </button>
              ))}
            </div>
            <Totals summary={s} kind={kind} onPick={setStatus} />
            {kind === "software" ? (
              <p className="text-xs text-slate-500">
                {s.software.devices_with_end_of_support} device(s) have at least one software installation past end of support.
                Only installations matched to a reviewed catalog product can be classified.
              </p>
            ) : null}
            <DataTable caption={kind === "os" ? "Operating system releases" : "Software version lines"} columns={groupColumns(s, kind)}
                       rows={part.groups} getRowId={(g) => `${g.status}-${g.entry?.id ?? g.reason}-${g.reported}`}
                       emptyTitle={kind === "os" ? "No devices in the current snapshot." : "No software installations in the current snapshot."} />
            {status ? (
              <section aria-label="Lifecycle devices" className="space-y-2">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold">{s.labels[status]}</h2>
                  <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => setStatus(null)}>Close</button>
                </div>
                <Devices customer={customer} kind={kind} status={status} summary={s} />
              </section>
            ) : null}
          </div>
        );
      }}
    </QueryBoundary>
  );
}

export function LifecyclePage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Lifecycle" subtitle="End-of-support dates for operating systems and software, with the cited source." />
      {!selected ? <SelectCustomer /> : <View customer={selected} />}
    </>
  );
}
