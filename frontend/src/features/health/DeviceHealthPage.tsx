import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useUrlFilters } from "../../lib/useUrlFilters";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  type Customer,
  type HealthDimension,
  type HealthRow,
  type HealthSummary,
  type HealthThresholdsRow,
  type Paginated,
} from "../../lib/types";
import { SelectCustomer } from "../../components/SelectCustomer";

const DIMENSION_TITLE: Record<HealthDimension, string> = {
  connectivity: "Connectivity (last seen)",
  agent_installed: "Agent installed",
  agent_version: "Agent version",
  disk: "System disk free space",
  antivirus: "Antivirus",
  firewall: "Firewall",
};
const ATTENTION = new Set(["offline", "stale", "never_seen", "not_installed", "old", "warning", "critical", "disabled", "enabled_outdated"]);
const GOOD = new Set(["seen_recently", "installed", "current", "ok", "enabled_up_to_date", "enabled"]);
const tone = (v: string) => (GOOD.has(v) ? "good" : ATTENTION.has(v) ? "warn" : "neutral");

/** One dimension = one complete partition of the device population (counts always sum to the total). */
function Partition({ dim, summary, onPick }: { dim: HealthDimension; summary: HealthSummary; onPick: (dim: HealthDimension, v: string) => void }) {
  const values = summary.dimensions[dim];
  const total = summary.devices;
  return (
    <section aria-label={DIMENSION_TITLE[dim]} className="rounded border border-slate-200 bg-white p-3">
      <h3 className="mb-1 text-sm font-semibold">{DIMENSION_TITLE[dim]}</h3>
      <table className="w-full text-xs">
        <caption className="sr-only">{`${DIMENSION_TITLE[dim]} — ${total} devices`}</caption>
        <tbody>
          {Object.entries(values).map(([k, n]) => (
            <tr key={k}>
              <td className="py-0.5">
                <button type="button" className="text-left text-sky-800 hover:underline disabled:text-slate-400 disabled:no-underline" disabled={n === 0}
                  onClick={() => onPick(dim, k)}>{summary.labels[dim][k] ?? k}</button>
              </td>
              <td className="w-12 text-right"><Badge tone={n === 0 ? "neutral" : tone(k)}>{n}</Badge></td>
              <td className="w-12 text-right text-slate-500">{total ? `${Math.round((100 * n) / total)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-slate-500">of {total} devices</p>
    </section>
  );
}

function Thresholds({ customer, summary }: { customer: Customer; summary: HealthSummary }) {
  const qc = useQueryClient();
  const base = `/customers/${customer.id}/health-thresholds/`;
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const history = useQuery({ queryKey: ["health-thresholds", customer.id], queryFn: ({ signal }) => api.get<HealthThresholdsRow[]>(base, undefined, signal) });
  const t = summary.thresholds;
  const [form, setForm] = useState({
    offline_hours: String(t.offline_hours), stale_days: String(t.stale_days), disk_warning_free_pct: String(t.disk_warning_free_pct),
    disk_critical_free_pct: String(t.disk_critical_free_pct), minimum_agent_version: t.minimum_agent_version, reason: "",
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["health-thresholds", customer.id] });
    void qc.invalidateQueries({ queryKey: ["device-health", customer.id] });
  };
  const propose = useMutation({
    mutationFn: () => api.post<HealthThresholdsRow>(base, {
      offline_hours: Number(form.offline_hours), stale_days: Number(form.stale_days),
      disk_warning_free_pct: Number(form.disk_warning_free_pct), disk_critical_free_pct: Number(form.disk_critical_free_pct),
      minimum_agent_version: form.minimum_agent_version, reason: form.reason,
    }),
    onSuccess: refresh,
  });
  const act = useMutation({ mutationFn: ({ id, verb }: { id: string; verb: string }) => api.post<HealthThresholdsRow>(`${base}${id}/${verb}/`), onSuccess: refresh });
  const field = (key: keyof typeof form, label: string, type = "number") => (
    <Field label={label}>{(id) => <input id={id} className="input w-28" type={type} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />}</Field>
  );
  return (
    <section aria-labelledby="thr-h" className="rounded border border-slate-200 bg-white p-4">
      <h2 id="thr-h" className="mb-1 font-semibold">Thresholds</h2>
      <p className="mb-2 text-sm">
        {t.source === "approved" ? <Badge tone="good">approved</Badge> : <Badge tone="info">documented defaults</Badge>}{" "}
        offline after {t.offline_hours} h · stale after {t.stale_days} days · disk warning below {t.disk_warning_free_pct}% / critical below {t.disk_critical_free_pct}% ·
        minimum agent {t.minimum_agent_version || <em>not set (agent age not evaluated)</em>}
      </p>
      <QueryBoundary query={history}>
        {(rows) => rows.length ? (
          <DataTable caption="Threshold history" rows={rows} getRowId={(r) => r.id}
            columns={[
              { header: "Proposed", cell: ({ row }) => `${formatUtc(row.original.created_at)} by ${row.original.proposed_by}` },
              { header: "Values", cell: ({ row }) => <span className="text-xs">{row.original.offline_hours} h / {row.original.stale_days} d / {row.original.disk_warning_free_pct}% / {row.original.disk_critical_free_pct}% / agent ≥ {row.original.minimum_agent_version || "—"}</span> },
              { header: "Reason", accessorKey: "reason" },
              { header: "State", cell: ({ row }) => <Badge tone={statusTone[row.original.state] ?? "neutral"}>{row.original.state}</Badge> },
              { header: "", id: "act", cell: ({ row }) => canManage && row.original.state === "proposed" ? (
                <span className="flex gap-1">
                  <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "approve" })}>Approve</button>
                  <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "reject" })}>Reject</button>
                </span>) : null },
            ]} />
        ) : <p className="text-xs text-slate-500">No threshold changes have been proposed.</p>}
      </QueryBoundary>
      {act.isError ? <p role="alert" className="mt-2 text-sm text-red-700">{describeError(act.error)}</p> : null}
      {canManage ? (
        <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); propose.mutate(); }}>
          {field("offline_hours", "Offline after (hours)")}
          {field("stale_days", "Stale after (days)")}
          {field("disk_warning_free_pct", "Disk warning (% free)")}
          {field("disk_critical_free_pct", "Disk critical (% free)")}
          {field("minimum_agent_version", "Minimum agent version", "text")}
          <Field label="Reason">{(id) => <input id={id} className="input" value={form.reason} maxLength={500} onChange={(e) => setForm({ ...form, reason: e.target.value })} required />}</Field>
          <button type="submit" className="btn-primary" disabled={propose.isPending}>Propose thresholds</button>
          <p className="w-full text-xs text-slate-500">A different administrator must approve before the thresholds take effect.</p>
          {propose.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(propose.error)}</p> : null}
        </form>
      ) : null}
    </section>
  );
}

function Devices({ customer, summary, filter, setFilter }: {
  customer: Customer; summary: HealthSummary; filter: Partial<Record<HealthDimension, string>>; setFilter: (f: Partial<Record<HealthDimension, string>>) => void;
}) {
  const { page, setPage } = useUrlFilters({});
  const query = useQuery({
    queryKey: ["device-health", customer.id, "devices", filter, page],
    queryFn: ({ signal }) => api.get<Paginated<HealthRow>>(`/customers/${customer.id}/device-health/devices/`, { ...filter, page }, signal),
  });
  const active = Object.entries(filter).filter(([, v]) => v) as [HealthDimension, string][];
  return (
    <section aria-labelledby="dev-h">
      <h2 id="dev-h" className="mb-2 text-sm font-semibold">Devices</h2>
      {active.length ? (
        <p className="mb-2 flex flex-wrap items-center gap-1 text-sm">Filtered by
          {active.map(([d, v]) => <Badge key={d} tone="info">{DIMENSION_TITLE[d]}: {v.split(",").map((value) => summary.labels[d]?.[value] ?? value).join(" or ")}</Badge>)}
          <button type="button" className="text-xs text-sky-800 underline" onClick={() => setFilter({})}>clear</button>
        </p>
      ) : null}
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable caption="Device health" rows={data.results} total={data.count} page={page} onPageChange={setPage} getRowId={(r) => r.asset_id} emptyTitle="No devices match."
            columns={[
              { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
              { header: "Group", cell: ({ row }) => row.original.group_name || row.original.group_external_id || "no group" },
              { header: "Last seen", cell: ({ row }) => <span>{formatUtc(row.original.last_seen_online)}<span className="block text-xs text-slate-500">{row.original.connectivity.replace(/_/g, " ")}</span></span> },
              { header: "Agent", cell: ({ row }) => <span className="text-xs">{row.original.client_version || "—"} · {row.original.agent_version.replace(/_/g, " ")}</span> },
              { header: "Disk", cell: ({ row }) => <Badge tone={tone(row.original.disk)}>{row.original.disk.replace(/_/g, " ")}{row.original.worst_disk_free_pct !== null ? ` ${row.original.worst_disk_free_pct}%` : ""}</Badge> },
              { header: "Antivirus", cell: ({ row }) => <Badge tone={tone(row.original.antivirus)}>{row.original.antivirus.replace(/_/g, " ")}</Badge> },
              { header: "Firewall", cell: ({ row }) => <Badge tone={tone(row.original.firewall)}>{row.original.firewall.replace(/_/g, " ")}</Badge> },
            ]} />
        )}
      </QueryBoundary>
    </section>
  );
}

function View({ customer }: { customer: Customer }) {
  const { filters: filter, update, reset } = useUrlFilters({
    connectivity: "", agent_installed: "", agent_version: "", disk: "", antivirus: "", firewall: "",
  });
  const setFilter = (values: Partial<Record<HealthDimension, string>>) => {
    if (!Object.keys(values).length) reset();
    else update({ connectivity: "", agent_installed: "", agent_version: "", disk: "", antivirus: "", firewall: "", ...values });
  };
  const query = useQuery({
    queryKey: ["device-health", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<HealthSummary>(`/customers/${customer.id}/device-health/summary/`, undefined, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(s) => (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">{s.devices} devices · snapshot {s.as_of.map(formatUtc).join(", ") || "never"} · data basis {s.data_basis.join(", ") || "none"}</p>
          <Notice tone="info"><ul className="list-disc pl-4">{s.notes.map((n) => <li key={n}>{n}</li>)}</ul></Notice>
          <Devices customer={customer} summary={s} filter={filter} setFilter={setFilter} />
          {s.devices === 0 ? <EmptyState title="No devices in the current snapshot." /> : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {(Object.keys(s.dimensions) as HealthDimension[]).map((d) => (
                <Partition key={d} dim={d} summary={s} onPick={(dim, v) => setFilter({ [dim]: v })} />
              ))}
            </div>
          )}
          <DataTable caption="Attention by group" rows={s.by_group} getRowId={(r) => `${r.instance_id ?? ""}-${r.group_external_id}-${r.group_name}`} emptyTitle="No groups."
            columns={[
              { header: "Site", cell: ({ row }) => String(row.original.site || "—") },
              { header: "Group", cell: ({ row }) => row.original.group_external_id ? <Link className="text-sky-800 hover:underline" to={`/groups/${row.original.group_external_id}${row.original.instance_id ? `?instance=${row.original.instance_id}` : ""}`}>{row.original.group_name || row.original.group_external_id}</Link> : row.original.group_name },
              { header: "Devices", accessorKey: "devices" },
              { header: "Offline / stale / never seen", cell: ({ row }) => row.original.connectivity_attention ?? 0 },
              { header: "Agent not installed", cell: ({ row }) => row.original.agent_not_installed ?? 0 },
              { header: "Old agent", cell: ({ row }) => s.thresholds.minimum_agent_version ? (row.original.agent_version_attention ?? 0) : "n/e" },
              { header: "Disk warning / critical", cell: ({ row }) => row.original.disk_attention ?? 0 },
              { header: "AV disabled / outdated", cell: ({ row }) => row.original.antivirus_attention ?? 0 },
              { header: "Firewall disabled", cell: ({ row }) => row.original.firewall_attention ?? 0 },
              { header: "Explicit no patch policy", cell: ({ row }) => row.original.no_patch_policy ?? 0 },
            ]} />
          <Thresholds key={JSON.stringify(s.thresholds)} customer={customer} summary={s} />
        </div>
      )}
    </QueryBoundary>
  );
}

export function DeviceHealthPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Device health" subtitle="Agent connectivity and version, disk space and security state from the latest VSA X snapshot." />
      {!selected ? <SelectCustomer /> : <View key={selected.id} customer={selected} />}
    </>
  );
}
