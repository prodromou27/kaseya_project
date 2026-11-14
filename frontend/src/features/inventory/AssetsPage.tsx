import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link, useLocation } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, PageHeader } from "../../components/ui";
import { useUrlFilters } from "../../lib/useUrlFilters";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { AssetRow, Customer, Paginated } from "../../lib/types";
import { ExportButton } from "../reports/ExportButton";
import { DataSources } from "./DataSources";
import { SavedViews } from "./SavedViews";
import { SelectCustomer } from "../../components/SelectCustomer";

const PAGE_SIZE = 50;

function DeviceLink({ asset }: { asset: AssetRow }) {
  const { search } = useLocation();
  return <Link to={`/assets/${asset.id}${search ? `?inventory=${encodeURIComponent(search)}` : ""}`} className="font-medium text-sky-800 hover:underline">{asset.hostname || "(no name)"}</Link>;
}

const columns: ColumnDef<AssetRow, unknown>[] = [
  {
    id: "hostname",
    header: "Hostname",
    cell: ({ row }) => <DeviceLink asset={row.original} />,
  },
  { header: "Site", accessorKey: "site_name" },
  { header: "Group", accessorKey: "group_name" },
  { id: "os", header: "OS", cell: ({ row }) => row.original.os_name || <span className="text-slate-400">not reported</span> },
  { header: "Type", accessorKey: "device_type" },
  {
    id: "last_seen",
    header: "Last seen",
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {formatUtc(row.original.last_seen_online)}{" "}
        {row.original.last_seen_stale ? <Badge tone="warn">offline</Badge> : null}
      </span>
    ),
  },
  {
    id: "software",
    header: "Software",
    cell: ({ row }) =>
      row.original.software_status === "not_collected" ? (
        <Badge tone="warn">not collected</Badge>
      ) : (
        `${row.original.software_count ?? 0} items`
      ),
  },
  { header: "Agent", accessorKey: "client_version" },
];

const DEFAULT_FILTERS = {
  search: "", group: "", os: "", offline: "", ordering: "hostname", group_id: "",
  site: "", device_type: "", organization: "", instance: "", software_status: "", offline_days: "7",
};
type Filters = typeof DEFAULT_FILTERS;

function AssetTable({ customer }: { customer: Customer }) {
  const { filters, update, reset, page, setPage } = useUrlFilters(DEFAULT_FILTERS);
  const facets = useQuery({
    queryKey: ["assets", customer.id, "facets"],
    queryFn: () => api.get<{ group: string[]; os: string[]; site: string[]; device_type: string[] }>(`/customers/${customer.id}/assets/facets/`),
  });
  const query = useQuery({
    queryKey: ["assets", customer.id, filters, page],
    queryFn: ({ signal }) =>
      api.get<Paginated<AssetRow>>(`/customers/${customer.id}/assets/`, { ...filters, page, page_size: PAGE_SIZE }, signal),
    placeholderData: (prev) => prev,
  });
  const set = (key: keyof Filters) => (value: string) => update({ [key]: value }, key === "search");
  const first = query.data?.results[0];

  return (
    <>
      <div className="filter-bar mb-3 flex flex-wrap items-end gap-3" role="search" aria-label="Filter assets">
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Search
          <input className="input w-56" type="search" maxLength={100} placeholder="Hostname, serial, device ID, MAC or IP"
                 value={filters.search} onChange={(e) => set("search")(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Group
          <select className="input w-56" value={filters.group} onChange={(e) => set("group")(e.target.value)}>
            <option value="">All groups</option>
            {(facets.data?.group ?? []).map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        {filters.group_id ? (
          <span className="flex items-center gap-1 self-center text-xs">
            <Badge tone="info">VSA group {filters.group_id}</Badge>
            <button type="button" className="underline" onClick={() => set("group_id")("")}>clear</button>
          </span>
        ) : null}
        <label className="flex flex-col text-xs font-medium text-slate-700">
          OS
          <select className="input w-48" value={filters.os} onChange={(e) => set("os")(e.target.value)}>
            <option value="">All</option>
            {(facets.data?.os ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Online state
          <select className="input" value={filters.offline} onChange={(e) => set("offline")(e.target.value)}>
            <option value="">All</option>
            <option value="false">Seen in last 7 days</option>
            <option value="true">Offline &gt; 7 days / never</option>
          </select>
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Sort
          <select className="input" value={filters.ordering} onChange={(e) => set("ordering")(e.target.value)}>
            <option value="hostname">Hostname A–Z</option>
            <option value="-last_seen_online">Last seen (newest)</option>
            <option value="last_seen_online">Last seen (oldest)</option>
            <option value="group_name">Group</option>
          </select>
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Site
          <select className="input w-36" value={filters.site} onChange={(e) => set("site")(e.target.value)}>
            <option value="">All sites</option>
            {(facets.data?.site ?? []).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Device type
          <select className="input w-36" value={filters.device_type} onChange={(e) => set("device_type")(e.target.value)}>
            <option value="">All types</option>
            {(facets.data?.device_type ?? []).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button type="button" className="btn-secondary" onClick={reset}>Clear filters</button>
        <SavedViews customer={customer} viewType="assets" current={filters}
                    onLoad={(f) => update({ ...DEFAULT_FILTERS, ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, String(v)])) })} />
        {customer.my_capabilities.includes("customer.export") ? (
          <ExportButton customer={customer} reportType="asset_inventory" label="Export inventory"
                        filters={filters} />
        ) : null}
      </div>
      <QueryBoundary query={query}>
        {(data) => (
          <>
            {first ? (
              <p className="mb-2 text-xs text-slate-500">
                Source: {first.source} · as of {formatUtc(first.as_of)} · data basis <Badge tone={first.data_basis === "fixture" ? "info" : "warn"}>{first.data_basis}</Badge>
              </p>
            ) : null}
            <DataTable key={`${page}:${JSON.stringify(filters)}`} columnChooser selectable caption={`${customer.code} assets`} columns={columns} rows={data.results} total={data.count}
                       selectionActions={customer.my_capabilities.includes("customer.export") ? (rows) => <ExportButton customer={customer} reportType="asset_inventory" label="Export selected devices" filters={{ ...filters, asset_ids: rows.map((row) => row.id).join(",") }} /> : undefined}
                       page={page} pageSize={PAGE_SIZE} onPageChange={setPage} getRowId={(r) => r.id}
                       emptyTitle="No devices in the current published dataset match these filters." />
          </>
        )}
      </QueryBoundary>
    </>
  );
}

export function AssetsPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Devices" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? (
        <SelectCustomer>Inventory is always shown for exactly one customer.</SelectCustomer>
      ) : (
        <>
          <DataSources customer={selected} />
          <AssetTable key={selected.id} customer={selected} />
        </>
      )}
    </>
  );
}
