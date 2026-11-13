import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { ChangeDevice, ChangeItem, ChangeKind, ChangeSummary, ComparableSnapshot, Customer, Paginated } from "../../lib/types";
import { SelectCustomer } from "../../components/SelectCustomer";

export const CHANGE_LABEL: Record<ChangeKind, string> = {
  device_added: "Newly observed devices",
  device_removed: "No longer observed",
  hostname: "Hostname changed",
  group: "Group changed",
  site: "Site changed",
  os: "OS changed",
  agent_version: "Agent version changed",
  agent_installed: "Agent installed state changed",
  ip_addresses: "IP addresses changed",
  software: "Software changed",
};

function describe(c: ChangeItem): string {
  if (c.kind === "device_added" || c.kind === "device_removed") return "";
  if ("from" in c) return `${String(c.from ?? "—") || "—"} → ${String(c.to ?? "—") || "—"}`;
  const parts = [c.added?.length ? `+ ${c.added.join(", ")}` : "", c.removed?.length ? `− ${c.removed.join(", ")}` : ""];
  return parts.filter(Boolean).join("  ");
}

function View({ customer }: { customer: Customer }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [kind, setKind] = useState<ChangeKind | "">("");
  const [page, setPage] = useState(1);
  const pair = { from, to };
  const snaps = useQuery({
    queryKey: ["change-snapshots", customer.id],
    queryFn: ({ signal }) => api.get<ComparableSnapshot[]>(`/customers/${customer.id}/changes/snapshots/`, undefined, signal),
  });
  const summary = useQuery({
    queryKey: ["changes", customer.id, from, to],
    queryFn: ({ signal }) => api.get<ChangeSummary>(`/customers/${customer.id}/changes/`, pair, signal),
    retry: false,
  });
  const devices = useQuery({
    queryKey: ["changes", customer.id, from, to, "devices", kind, page],
    queryFn: ({ signal }) => api.get<Paginated<ChangeDevice>>(`/customers/${customer.id}/changes/devices/`, { ...pair, kind, page }, signal),
    enabled: summary.isSuccess,
    retry: false,
  });
  const options = snaps.data ?? [];
  const label = (s: ComparableSnapshot) => `${formatUtc(s.published_at)} · ${s.instance} · ${s.row_count} devices${s.is_current ? " (current)" : ""}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From snapshot">{(id) => (
          <select id={id} className="input" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }}>
            <option value="">Previous complete snapshot</option>
            {options.map((s) => <option key={s.id} value={s.id}>{label(s)}</option>)}
          </select>)}</Field>
        <Field label="To snapshot">{(id) => (
          <select id={id} className="input" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }}>
            <option value="">Current snapshot</option>
            {options.map((s) => <option key={s.id} value={s.id}>{label(s)}</option>)}
          </select>)}</Field>
      </div>
      <QueryBoundary query={summary}>
        {(s) => (
          <>
            <Notice tone="info">{s.note}</Notice>
            <p className="text-sm text-slate-600">
              Observed between {formatUtc(s.from.published_at)} ({s.from.devices} devices) and {formatUtc(s.to.published_at)} ({s.to.devices} devices) ·{" "}
              {s.devices_compared} devices in both · data basis {s.to.data_basis}
            </p>
            {s.not_compared.ip_addresses || s.not_compared.software ? (
              <p className="text-xs text-slate-500">Not compared (section missing in either snapshot): IP addresses {s.not_compared.ip_addresses} device(s), software {s.not_compared.software} device(s).</p>
            ) : null}
            <div role="group" aria-label="Change kinds" className="grid grid-cols-2 gap-2 text-sm md:grid-cols-5">
              {(Object.keys(s.counts) as ChangeKind[]).map((k) => (
                <button key={k} type="button" aria-pressed={kind === k} disabled={s.counts[k] === 0}
                  className={`rounded border px-3 py-2 text-left ${kind === k ? "border-sky-700 bg-sky-50" : "border-slate-200 bg-white"} disabled:opacity-50`}
                  onClick={() => { setKind(kind === k ? "" : k); setPage(1); }}>
                  <span className="block text-xs text-slate-500">{CHANGE_LABEL[k]}</span>
                  <span className="text-lg font-semibold">{s.counts[k]}</span>
                </button>
              ))}
            </div>
            <QueryBoundary query={devices}>
              {(d) => (
                <DataTable caption="Changed devices" rows={d.results} total={d.count} page={page} onPageChange={setPage} getRowId={(r) => r.asset_id}
                  emptyTitle="No differences between these snapshots."
                  columns={[
                    { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
                    { header: "Group", cell: ({ row }) => row.original.group_external_id || "—" },
                    { header: "Observed differences", cell: ({ row }) => (
                      <ul className="space-y-0.5 text-xs">
                        {row.original.changes.map((c, i) => (
                          <li key={`${c.kind}-${i}`}><Badge tone={c.kind === "device_removed" ? "warn" : c.kind === "device_added" ? "info" : "neutral"}>{CHANGE_LABEL[c.kind]}</Badge> <span className="break-all">{describe(c)}</span></li>
                        ))}
                      </ul>
                    ) },
                  ]} />
              )}
            </QueryBoundary>
          </>
        )}
      </QueryBoundary>
    </div>
  );
}

export function ChangesPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Inventory changes" subtitle="What differs between two complete VSA X snapshots: devices, placement, OS, agent, IP addresses and software." />
      {!selected ? <SelectCustomer /> : <View customer={selected} />}
    </>
  );
}
