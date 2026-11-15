import { useQuery } from "@tanstack/react-query";
import { useUrlFilters } from "../../lib/useUrlFilters";

import { Tabs } from "../../components/Tabs";
import { InvestigationDeviceLink } from "../../components/InvestigationDeviceLink";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader, statusTone } from "../../components/ui";
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
import { SelectCustomer } from "../../components/SelectCustomer";

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

function Summary({ s, onStatus }: { s: OsUpdateSummary; onStatus: (st: UpdateStatus) => void }) {
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
      <details className="mb-3 text-xs text-slate-500">
        <summary className="w-fit cursor-pointer hover:text-sky-800">Installed-update history collection · as of {s.as_of.map(formatUtc).join(", ") || "—"}</summary>
        <p className="mt-1">
          Collected per device within each sync's call budget:{" "}
          {STATUSES.filter((st) => s.installed_section[st]).map((st) => `${UPDATE_STATUS_LABEL[st]} ${s.installed_section[st]}`).join(" · ") || "none"}.
          Data basis {s.data_basis.join(", ") || "none"}.
        </p>
      </details>

    </>
  );
}

function CommonUpdates({ s, onKb }: { s: OsUpdateSummary; onKb: (kb: string) => void }) {
  return (
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
  );
}

function UpdateRows({ customer, kb, state, severity, searchText }: { customer: Customer; kb: string; state: string; severity: string; searchText: string }) {
  const { filters, update, page, setPage } = useUrlFilters({ page_size: "50" });
  const pageSize = [25, 50, 100, 200].includes(Number(filters.page_size)) ? Number(filters.page_size) : 50;
  const search = useDebouncedValue(searchText);
  const query = useQuery({ queryKey: ["os-updates", customer.id, "rows", kb, state, severity, search, page, pageSize],
    queryFn: ({ signal }) => api.get<Paginated<DeviceOsUpdateRow>>(`/customers/${customer.id}/os-updates/`, { kb, state, severity, search, page, page_size: pageSize }, signal), placeholderData: (prev) => prev });
  return <>
    {query.isError && page > 1 ? <button type="button" className="btn-secondary" onClick={() => setPage(1)}>Return to first page</button> : null}
    <QueryBoundary query={query}>{(data) => <DataTable columnChooser caption="Device updates" rows={data.results} total={data.count} page={page} pageSize={pageSize} loading={query.isFetching || search !== searchText} onPageChange={setPage} onPageSizeChange={(size) => update({ page_size: String(size) })} getRowId={(row) => row.id} emptyTitle="No matching update records."
      columns={[
        { header: "Device", cell: ({ row }) => <InvestigationDeviceLink assetId={row.original.asset_id} name={row.original.hostname} tab="os-updates" /> },
        { header: "State", cell: ({ row }) => <Badge tone={row.original.state === "available" ? "warn" : "good"}>{row.original.state}</Badge> },
        { header: "KB", cell: ({ row }) => row.original.kb_article ? `KB${row.original.kb_article}` : "Not reported" },
        { header: "Title", accessorKey: "title" }, { header: "Severity", accessorKey: "severity" }, { header: "Released", cell: ({ row }) => <span className="nowrap">{row.original.release_date ?? "—"}</span> },
        { header: "Installed at (source timezone unspecified)", cell: ({ row }) => row.original.installed_at_raw || "Not reported" },
      ]} />}</QueryBoundary>
  </>;
}

function DeviceStatusList({ customer }: { customer: Customer }) {
  const { filters, update, page, setPage } = useUrlFilters({ coverage_search: "", page_size: "50", status: "" });
  const pageSize = [25, 50, 100, 200].includes(Number(filters.page_size)) ? Number(filters.page_size) : 50;
  const status = STATUSES.includes(filters.status as UpdateStatus) ? filters.status : "";
  const search = useDebouncedValue(filters.coverage_search);
  const query = useQuery({ queryKey: ["os-updates", customer.id, "devices", status, search, page, pageSize],
    queryFn: ({ signal }) => api.get<Paginated<DevicePatchStatus>>(`/customers/${customer.id}/os-updates/devices/`, { available_status: status, search, page, page_size: pageSize }, signal), placeholderData: (previous) => previous });
  return <section className="space-y-3">
    <div className="list-workspace flex flex-wrap items-end gap-3">
      <Field label="Find device">{(id) => <input id={id} type="search" className="input" value={filters.coverage_search} maxLength={100} placeholder="Hostname or source device ID" onChange={(event) => update({ coverage_search: event.target.value }, true)} />}</Field>
      <Field label="Available-update collection">{(id) => <select id={id} className="input" value={status} onChange={(event) => update({ status: event.target.value })}><option value="">All collection states</option>{STATUSES.map((item) => <option key={item} value={item}>{UPDATE_STATUS_LABEL[item]}</option>)}</select>}</Field>
      <button type="button" className="btn-secondary" onClick={() => update({ status: "", coverage_search: "" })}>Clear coverage filters</button>
      {customer.my_capabilities.includes(CAP.export) ? <ExportButton customer={customer} reportType="os_update_coverage" label="Export device coverage" filters={{ available_status: status, search: filters.coverage_search }} /> : null}
    </div>
    <p className="text-xs text-slate-500">One row per device. Collection failures and missing evidence remain separate from a reported zero.</p>
    {query.isError && page > 1 ? <button type="button" className="btn-secondary" onClick={() => setPage(1)}>Return to first page</button> : null}
    <QueryBoundary query={query}>{(data) => <DataTable key={`${status}:${search}:${page}:${pageSize}`} caption={status ? `Devices: ${UPDATE_STATUS_LABEL[status as UpdateStatus]}` : "Device collection coverage"} rows={data.results} total={data.count} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={(size) => update({ page_size: String(size) })} loading={query.isFetching || search !== filters.coverage_search} getRowId={(row) => row.asset_id}
      emptyTitle="No devices match the coverage filters." columns={[
        { header: "Device", cell: ({ row }) => <InvestigationDeviceLink assetId={row.original.asset_id} name={row.original.hostname} tab="os-updates" /> },
        { header: "Type", accessorKey: "device_type" },
        { header: "OS", accessorKey: "os_name" },
        { header: "Available evidence", cell: ({ row }) => <Badge tone={statusTone[row.original.available_status]}>{UPDATE_STATUS_LABEL[row.original.available_status]}</Badge> },
        { header: "Available updates", cell: ({ row }) => row.original.available_count ?? "Unknown" },
        { header: "Installed evidence", cell: ({ row }) => <Badge tone={statusTone[row.original.installed_status]}>{UPDATE_STATUS_LABEL[row.original.installed_status]}</Badge> },
        { header: "Last seen", cell: ({ row }) => formatUtc(row.original.last_seen_online) },
      ]} />}</QueryBoundary>
  </section>;
}

function View({ customer }: { customer: Customer }) {
  const { filters, update } = useUrlFilters({ kb: "", state: "available", severity: "", status: "", search: "", view: "" });
  const { kb, state, severity, search } = filters;
  const status = STATUSES.includes(filters.status as UpdateStatus) ? filters.status : "";
  const active = filters.view || (status ? "coverage" : "records");
  const summary = useQuery({ queryKey: ["os-updates", customer.id, "summary"], queryFn: ({ signal }) => api.get<OsUpdateSummary>(`/customers/${customer.id}/os-updates/summary/`, undefined, signal) });
  return <>
    <DataSources customer={customer} compact />
    <QueryBoundary query={summary} isEmpty={(s) => s.devices_total === 0} empty={<EmptyState title="No devices in the current dataset." />}>{(s) => <Summary s={s} onStatus={(status) => update({ status, view: "coverage" })} />}</QueryBoundary>
    <Tabs label="Windows update workspace" active={active} onChange={(view) => update({ view })} tabs={[
      { id: "records", label: "Update records", content: <section className="space-y-3">
        <div className="list-workspace flex flex-wrap items-end gap-3">
          <Field label="Search updates">{(id) => <input id={id} className="input w-64" type="search" value={search} maxLength={100} placeholder="Title, KB or device" onChange={(event) => update({ search: event.target.value }, true)} />}</Field>
          <Field label="KB">{(id) => <input id={id} className="input w-32" value={kb} maxLength={12} placeholder="KB5099001" onChange={(event) => update({ kb: event.target.value }, true)} />}</Field>
          <Field label="State">{(id) => <select id={id} className="input" value={state} onChange={(event) => update({ state: event.target.value })}><option value="available">Available</option><option value="installed">Installed</option><option value="">All</option></select>}</Field>
          <Field label="Severity">{(id) => <select id={id} className="input" value={severity} onChange={(event) => update({ severity: event.target.value })}><option value="">All severities</option>{["Critical", "Important", "Moderate", "Low", "Unspecified"].map((item) => <option key={item}>{item}</option>)}</select>}</Field>
          <button type="button" className="btn-secondary" onClick={() => update({ kb: "", state: "", severity: "", search: "" })}>Clear filters</button>
          {customer.my_capabilities.includes(CAP.export) ? <ExportButton customer={customer} reportType="os_updates" label="Export update records" filters={{ kb, state, severity, search }} /> : null}
        </div>
        <p className="text-xs text-slate-500">Device-by-update records. One device may appear for several updates.</p>
        <UpdateRows customer={customer} kb={kb} state={state} severity={severity} searchText={search} />
      </section> },
      { id: "coverage", label: "Collection coverage", content: <DeviceStatusList customer={customer} /> },
      { id: "common", label: "Common updates", content: <QueryBoundary query={summary}>{(s) => <CommonUpdates s={s} onKb={(kb) => update({ kb, state: "available", severity: "", search: "", view: "records" })} />}</QueryBoundary> },
    ]} />
  </>;
}

export function WindowsUpdatesPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Windows updates" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? <SelectCustomer /> : <View key={selected.id} customer={selected} />}
    </>
  );
}
