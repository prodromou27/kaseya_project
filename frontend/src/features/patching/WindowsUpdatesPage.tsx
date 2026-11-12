import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Notice, PageHeader, statusTone } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  UPDATE_STATUS_LABEL,
  type Customer,
  type DeviceOsUpdateRow,
  type DevicePatchStatus,
  type OsUpdateSummary,
  type Paginated,
  type UpdateStatus,
} from "../../lib/types";
import { DataSources } from "../inventory/DataSources";
import { ExportButton } from "../reports/ExportButton";

const PAGE_SIZE = 50;
const STATUSES: UpdateStatus[] = ["collected", "not_collected", "not_supported", "failed", "not_requested", "carried_forward"];

function Tile({ label, value, hint }: { label: string; value: number | string; hint: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-slate-500">{hint}</div>
    </div>
  );
}

function Summary({ s, onKb, onStatus }: { s: OsUpdateSummary; onKb: (kb: string) => void; onStatus: (st: UpdateStatus) => void }) {
  const notReporting = s.devices_total - s.devices_reporting_updates;
  return (
    <>
      <Notice tone="info">{s.scope_note} {s.freshness_note}</Notice>
      <div className="my-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Tile label="Devices with available updates" value={s.devices_with_available_updates}
              hint={`of ${s.devices_reporting_updates} devices that reported the AvailableUpdates section`} />
        <Tile label="Devices with available Critical updates" value={s.devices_by_severity.Critical ?? 0}
              hint="severity as reported by the source" />
        <Tile label="Reported zero available updates" value={s.devices_with_zero_available}
              hint="only devices that returned an empty list" />
        <Tile label="No update data" value={notReporting}
              hint={`${s.available_section.not_collected} not collected · ${s.available_section.not_supported} non-Windows — never counted as zero`} />
      </div>
      <div className="mb-3 flex flex-wrap gap-2 text-sm" aria-label="Devices by AvailableUpdates status">
        {STATUSES.filter((st) => s.available_section[st]).map((st) => (
          <button key={st} type="button" className="btn-secondary" onClick={() => onStatus(st)}>
            <Badge tone={statusTone[st]}>{UPDATE_STATUS_LABEL[st]}</Badge> {s.available_section[st]}
          </button>
        ))}
      </div>
      <p className="mb-3 text-xs text-slate-500">
        Installed updates (per-device, budgeted collection):{" "}
        {STATUSES.filter((st) => s.installed_section[st]).map((st) => `${UPDATE_STATUS_LABEL[st]} ${s.installed_section[st]}`).join(" · ") || "none"}.
        As of {s.as_of.map(formatUtc).join(", ") || "—"} · data basis {s.data_basis.join(", ") || "none"}
      </p>
      <DataTable caption="Most common available updates" rows={s.top_available_updates} getRowId={(r) => r.os_update_id}
        emptyTitle="No available updates were reported by devices that returned update data."
        columns={[
          { header: "KB", cell: ({ row }) => row.original.kb_article
              ? <button type="button" className="text-sky-800 underline" onClick={() => onKb(row.original.kb_article)}>KB{row.original.kb_article}</button>
              : <span className="text-slate-400">no KB</span> },
          { header: "Title", accessorKey: "title" },
          { header: "Severity", accessorKey: "severity", cell: ({ getValue }) => String(getValue() || "not reported") },
          { header: "Devices", accessorKey: "devices" },
        ]} />
    </>
  );
}

function UpdateRows({ customer, kb, state }: { customer: Customer; kb: string; state: string }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["os-updates", customer.id, "rows", kb, state, page],
    queryFn: ({ signal }) => api.get<Paginated<DeviceOsUpdateRow>>(`/customers/${customer.id}/os-updates/`, { kb, state, page, page_size: PAGE_SIZE }, signal),
    placeholderData: (prev) => prev,
  });
  return (
    <QueryBoundary query={query}>
      {(data) => <DataTable caption="Device updates" rows={data.results} total={data.count} page={page} pageSize={PAGE_SIZE}
        onPageChange={setPage} getRowId={(r) => r.id} emptyTitle="No matching update records."
        columns={[
          { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
          { header: "State", cell: ({ row }) => <Badge tone={row.original.state === "available" ? "warn" : "good"}>{row.original.state}</Badge> },
          { header: "KB", cell: ({ row }) => (row.original.kb_article ? `KB${row.original.kb_article}` : "—") },
          { header: "Title", accessorKey: "title" },
          { header: "Severity", accessorKey: "severity" },
          { header: "Released", accessorKey: "release_date" },
          { header: "Installed at (as reported, timezone unspecified)", cell: ({ row }) => row.original.installed_at_raw || "—" },
        ]} />}
    </QueryBoundary>
  );
}

function DeviceStatusList({ customer, status }: { customer: Customer; status: UpdateStatus }) {
  const query = useQuery({
    queryKey: ["os-updates", customer.id, "devices", status],
    queryFn: () => api.get<Paginated<DevicePatchStatus>>(`/customers/${customer.id}/os-updates/devices/`, { available_status: status, page_size: 200 }),
  });
  return (
    <QueryBoundary query={query}>
      {(data) => <DataTable caption={`Devices: ${UPDATE_STATUS_LABEL[status]}`} rows={data.results} total={data.count} getRowId={(r) => r.asset_id}
        columns={[
          { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
          { header: "Type", accessorKey: "device_type" },
          { header: "OS", accessorKey: "os_name" },
          { header: "Last seen", cell: ({ row }) => formatUtc(row.original.last_seen_online) },
          { header: "Available", cell: ({ row }) => row.original.available_count ?? <span className="text-slate-400">no data</span> },
        ]} />}
    </QueryBoundary>
  );
}

function View({ customer }: { customer: Customer }) {
  const [kb, setKb] = useState("");
  const [state, setState] = useState("available");
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const summary = useQuery({
    queryKey: ["os-updates", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<OsUpdateSummary>(`/customers/${customer.id}/os-updates/summary/`, undefined, signal),
  });
  return (
    <>
      <DataSources customer={customer} />
      <QueryBoundary query={summary} isEmpty={(s) => s.devices_total === 0}
        empty={<EmptyState title="No devices in the current dataset.">Run a sync once a source mapping is approved.</EmptyState>}>
        {(s) => <Summary s={s} onKb={(k) => { setKb(k); setStatus(null); }} onStatus={setStatus} />}
      </QueryBoundary>
      <section aria-labelledby="rows-h" className="mt-6">
        <div className="mb-2 flex flex-wrap items-end gap-3">
          <h2 id="rows-h" className="text-sm font-semibold">{status ? `Devices · ${UPDATE_STATUS_LABEL[status]}` : "Update records"}</h2>
          {status ? <button type="button" className="btn-secondary" onClick={() => setStatus(null)}>Back to update records</button> : (
            <>
              <label className="flex items-center gap-1 text-xs">KB
                <input className="input w-28" value={kb} maxLength={12} placeholder="5099001" onChange={(e) => setKb(e.target.value)} />
              </label>
              <label className="flex items-center gap-1 text-xs">State
                <select className="input" value={state} onChange={(e) => setState(e.target.value)}>
                  <option value="available">Available</option>
                  <option value="installed">Installed</option>
                  <option value="">All</option>
                </select>
              </label>
            </>
          )}
          {customer.my_capabilities.includes(CAP.export) ? (
            <ExportButton customer={customer} reportType="os_updates" label="Export (RPT-04)" filters={{ kb, state }} />
          ) : null}
        </div>
        {status ? <DeviceStatusList customer={customer} status={status} /> : <UpdateRows customer={customer} kb={kb} state={state} />}
      </section>
    </>
  );
}

export function WindowsUpdatesPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Windows updates" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? <EmptyState title="Select a customer" /> : <View customer={selected} />}
    </>
  );
}
