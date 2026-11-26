import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link, useLocation } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, PageHeader } from "../../components/ui";
import { useUrlFilters } from "../../lib/useUrlFilters";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { AssetRow, Customer, ListLayout, Paginated } from "../../lib/types";
import { ExportButton } from "../reports/ExportButton";
import { DataSources } from "./DataSources";
import { SavedViews } from "./SavedViews";
import { SelectCustomer } from "../../components/SelectCustomer";
import { CONDITIONS } from "../customfields/CustomFieldCondition";
import { advancedParams, ADVANCED_KEYS, CF_KEYS, describeFilter, DeviceFilters, EMPTY_ADVANCED, FILTER_LABELS } from "./DeviceFilters";

function DeviceLink({ asset }: { asset: AssetRow }) {
  const { search } = useLocation();
  return <Link to={`/assets/${asset.id}${search ? `?inventory=${encodeURIComponent(search)}` : ""}`} className="whitespace-nowrap font-semibold text-sky-800 hover:underline">{asset.hostname || "(no name)"}</Link>;
}

const columns: ColumnDef<AssetRow, unknown>[] = [
  { id: "hostname", header: "Device", cell: ({ row }) => <DeviceLink asset={row.original} /> },
  { header: "Site", accessorKey: "site_name" },
  { header: "Group", accessorKey: "group_name", cell: ({ row }) => row.original.group_external_id ? <Link className="block max-w-56 truncate text-sky-800 hover:underline" title={row.original.group_name} to={`/groups/${row.original.group_external_id}${row.original.instance_id ? `?instance=${row.original.instance_id}` : ""}`}>{row.original.group_name || row.original.group_external_id}</Link> : <span className="text-slate-500">Not reported</span> },
  { id: "os", header: "OS", cell: ({ row }) => <span className="block max-w-52 truncate" title={row.original.os_name}>{row.original.os_name || "Not reported"}</span> },
  { header: "Type", accessorKey: "device_type" },
  { id: "last_seen", header: "Last seen", cell: ({ row }) => <span className="whitespace-nowrap text-xs">{formatUtc(row.original.last_seen_online)} {row.original.last_seen_stale ? <Badge tone="warn">{row.original.last_seen_online ? "offline" : "never seen"}</Badge> : null}</span> },
  { id: "software", header: "Software", cell: ({ row }) => row.original.software_status === "not_collected" ? <Badge tone="warn">not collected</Badge> : `${row.original.software_count ?? 0} items` },
  { header: "Agent", accessorKey: "client_version" },
];
const DEFAULT_COLUMNS = ["hostname", "site_name", "group_name", "os", "last_seen", "software"];
const DEFAULT_FILTERS = {
  search: "", group: "", os: "", offline: "", ordering: "hostname", group_id: "",
  site: "", device_type: "", organization: "", instance: "", software_status: "", offline_days: "7",
  ...EMPTY_ADVANCED,
  page_size: "50", view: "", columns: DEFAULT_COLUMNS.join(","), density: "compact",
};
type Filters = typeof DEFAULT_FILTERS;
type SourceFacet = { generation__integration_instance_id: string; generation__integration_instance__name: string };
type SiteFacet = SourceFacet & { site_external_id: string; site_name: string };
type GroupFacet = SourceFacet & { group_external_id: string; group_name: string; site_name: string };
type Facets = { group: string[]; os: string[]; site: string[]; device_type: string[]; sites?: SiteFacet[]; groups?: GroupFacet[] };

function AssetTable({ customer }: { customer: Customer }) {
  const { filters, update, page, setPage } = useUrlFilters(DEFAULT_FILTERS);
  const { view, page_size, columns: selectedColumns, density, ...reportFilters } = filters;
  const pageSize = [25, 50, 100, 200].includes(Number(page_size)) ? Number(page_size) : 50;
  const knownColumns = ["hostname", "site_name", "group_name", "os", "device_type", "last_seen", "software", "client_version"];
  const validColumns = selectedColumns.split(",").filter((id) => knownColumns.includes(id));
  const layout: ListLayout = { columns: validColumns.length ? Array.from(new Set(validColumns)) : DEFAULT_COLUMNS, density: density === "comfortable" ? "comfortable" : "compact" };
  const search = useDebouncedValue(filters.search);
  const facets = useQuery({ queryKey: ["assets", customer.id, "facets"], queryFn: ({ signal }) => api.get<Facets>(`/customers/${customer.id}/assets/facets/`, undefined, signal) });
  // FLT-01: the extra filters are sent only when complete (a custom field rule needs its value, a program its name).
  const extra = new Set<string>([...ADVANCED_KEYS, ...CF_KEYS]);
  const plainFilters = Object.fromEntries(Object.entries(reportFilters).filter(([key]) => !extra.has(key)));
  const cfValues = useDebouncedValue(CF_KEYS.map((k) => filters[k as keyof Filters]).join("\u0000"));
  const condition = advancedParams({ ...reportFilters, ...Object.fromEntries(CF_KEYS.map((k, i) => [k, cfValues.split("\u0000")[i] ?? ""])) });
  const requestFilters = { ...plainFilters, ...condition, search };
  const exportFilters = { ...plainFilters, ...condition };
  const query = useQuery({
    queryKey: ["assets", customer.id, requestFilters, page, pageSize],
    queryFn: ({ signal }) => api.get<Paginated<AssetRow>>(`/customers/${customer.id}/assets/`, { ...requestFilters, page, page_size: pageSize }, signal),
    placeholderData: (prev) => prev,
  });
  const busy = query.isFetching || search !== filters.search;
  const set = (key: keyof Filters, value: string) => update({ [key]: value, view: "" }, key === "search");
  const clear = () => update({ ...DEFAULT_FILTERS, page_size: String(pageSize), columns: selectedColumns, density });
  const hidden = ["ordering", "offline_days", "software_presence", ...CF_KEYS.filter((k) => !/^custom_field(_\d)?$/.test(k))];
  const active = Object.entries(reportFilters).filter(([key, value]) => value && !hidden.includes(key));
  const group = facets.data?.groups?.find((g) => g.group_external_id === filters.group_id && (!filters.instance || g.generation__integration_instance_id === filters.instance));
  const site = facets.data?.sites?.find((s) => s.site_external_id === filters.site && (!filters.instance || s.generation__integration_instance_id === filters.instance));
  const source = [...(facets.data?.sites ?? []), ...(facets.data?.groups ?? [])].find((row) => row.generation__integration_instance_id === filters.instance);
  const labels: Record<string, string> = { ...FILTER_LABELS, search: "Search", group: "Group", os: "OS", offline: "Last seen", site: "Site", device_type: "Type", group_id: "Group", instance: "Source", organization: "Organization", software_status: "Software" };
  const describeBase = (key: string, value: string) => key === "group_id" ? group?.group_name || value : key === "site" ? site?.site_name || value : key === "instance" ? source?.generation__integration_instance__name || value : key === "offline" ? value === "true" ? `Over ${filters.offline_days} days / never` : `Within ${filters.offline_days} days` : describeFilter(key, value);
  const describe = (key: string, value: string) => {
    const sfx = key.match(/^custom_field(_\d)?$/)?.[1];
    if (sfx !== undefined || key === "custom_field") {
      const s2 = sfx ?? "";
      const state = filters[`custom_field_state${s2}` as keyof Filters] || "missing";
      const label = CONDITIONS.find((c) => c.id === state)?.label.replace("…", "") ?? state;
      const cmp = filters[`custom_field_value${s2}` as keyof Filters];
      return `${value} ${label}${cmp ? ` ${cmp}` : ""}`.trim();
    }
    if (key === "software") return `${value} ${(filters as Record<string, string>).software_presence === "not_installed" ? "not installed" : "installed"}`;
    return describeBase(key, value);
  };
  const remove = (key: string) => {
    if (key === "instance") return update({ instance: "", site: "", group_id: "", view: "" });
    const sfx = key.match(/^custom_field(_\d)?$/);
    if (sfx) { const s2 = sfx[1] ?? ""; return update({ [`custom_field${s2}`]: "", [`custom_field_state${s2}`]: "", [`custom_field_value${s2}`]: "", view: "" }); }
    if (key === "software") return update({ software: "", software_presence: "", view: "" } as Partial<Filters>);
    return set(key as keyof Filters, "");
  };
  return <section className="space-y-3" aria-label="Device inventory">
    <div className="list-workspace">
      <div className="flex flex-wrap items-end gap-3">
        <label className="list-label min-w-48 flex-1">Search<input className="input w-full" type="search" maxLength={100} placeholder="Find a device by name, serial, ID, MAC or IP" value={filters.search} onChange={(event) => set("search", event.target.value)} /></label>
        <label className="list-label">Site<select className="input max-w-56" value={filters.site ? `${filters.instance}:${filters.site}` : ""} onChange={(event) => {
          const [instance, site] = event.target.value.split(":"); update({ site: site ?? "", instance: instance ?? "", group: "", group_id: "", view: "" });
        }}><option value="">All sites</option>{(facets.data?.sites ?? facets.data?.site?.map((id) => ({ site_external_id: id, site_name: id, generation__integration_instance_id: "", generation__integration_instance__name: "" })) ?? []).map((row) => <option key={`${row.generation__integration_instance_id}:${row.site_external_id}`} value={`${row.generation__integration_instance_id}:${row.site_external_id}`}>{row.site_name || row.site_external_id}{row.generation__integration_instance__name ? ` / ${row.generation__integration_instance__name}` : ""}</option>)}</select></label>
        <label className="list-label">Online state<select className="input" value={filters.offline} onChange={(event) => set("offline", event.target.value)}><option value="">Any last seen</option><option value="false">Seen within {filters.offline_days} days</option><option value="true">Offline &gt; {filters.offline_days} days / never</option></select></label>
        {customer.my_capabilities.includes("customer.export") ? <ExportButton customer={customer} reportType="asset_inventory" label="Export inventory" filters={exportFilters} /> : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-2" aria-label="Device quick filters">
        <button type="button" className="list-preset" aria-pressed={active.length === 0} onClick={clear}>All devices</button>
        <button type="button" className="list-preset" aria-pressed={filters.offline === "true"} onClick={() => update({ offline: filters.offline === "true" ? "" : "true", view: "" })}>Offline / never seen</button>
        <button type="button" className="list-preset" aria-pressed={filters.software_status === "not_collected"} onClick={() => update({ software_status: filters.software_status === "not_collected" ? "" : "not_collected", view: "" })}>Software not collected</button>
        {active.length ? <button type="button" className="ml-auto text-xs font-medium text-sky-800 underline" onClick={clear}>Clear filters</button> : null}
      </div>
      <div className="list-options mt-3 flex flex-wrap items-start gap-x-6 gap-y-3">
      <details className="list-disclosure"><summary>More filters</summary><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="list-label">Group<select className="input" value={filters.group_id ? `${filters.instance}:${filters.group_id}` : filters.group} onChange={(event) => {
          if (event.target.value.includes(":")) { const [instance, group_id] = event.target.value.split(":"); update({ instance, group_id, group: "", site: "", view: "" }); }
          else update({ group: event.target.value, group_id: "", view: "" });
        }}><option value="">All groups</option>{facets.data?.groups ? facets.data.groups.map((row) => <option key={`${row.generation__integration_instance_id}:${row.group_external_id}`} value={`${row.generation__integration_instance_id}:${row.group_external_id}`}>{row.group_name || row.group_external_id} ? {row.site_name}</option>) : facets.data?.group?.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
        <label className="list-label">OS<select className="input" value={filters.os} onChange={(event) => set("os", event.target.value)}><option value="">All operating systems</option>{facets.data?.os?.map((os) => <option key={os} value={os}>{os}</option>)}</select></label>
        <label className="list-label">Device type<select className="input" value={filters.device_type} onChange={(event) => set("device_type", event.target.value)}><option value="">All types</option>{facets.data?.device_type?.map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
        <div className="border-t border-slate-100 pt-3 sm:col-span-2 lg:col-span-4">
          <DeviceFilters customer={customer} values={filters} onChange={(next) => update({ ...next, view: "" })} />
        </div>
        <label className="list-label">Last-seen window (days)<select className="input" value={filters.offline_days} onChange={(event) => set("offline_days", event.target.value)}>{Array.from(new Set([1, 7, 14, 30, 90, Number(filters.offline_days)])).filter((day) => Number.isInteger(day) && day >= 1 && day <= 365).sort((a, b) => a - b).map((day) => <option key={day} value={day}>{day} days</option>)}</select></label>
      </div></details>
      <SavedViews customer={customer} viewType="assets" current={exportFilters} layout={{ ...layout, page_size: pageSize }} selectedId={view} onLoad={(f, savedLayout, id) => {
        update({ ...DEFAULT_FILTERS, ...f, page_size: String(savedLayout.page_size ?? pageSize), view: id,
          columns: (savedLayout.columns ?? DEFAULT_COLUMNS).join(","), density: savedLayout.density ?? "compact" });
      }} />
      </div>
      {facets.isError ? <p role="alert" className="mt-2 text-xs text-red-700">Filter options could not load. <button type="button" className="underline" onClick={() => void facets.refetch()}>Retry filters</button></p> : null}
    </div>
    {active.length ? <div className="flex flex-wrap items-center gap-2" aria-label="Active device filters">{active.map(([key, value]) => <button key={key} type="button" className="filter-chip" aria-label={`Remove ${labels[key] ?? key} filter`} onClick={() => remove(key)}><span className="text-slate-500">{labels[key] ?? key}:</span> {describe(key, value)} <span aria-hidden="true">&times;</span></button>)}</div> : null}
    {query.isError && page > 1 ? <button type="button" className="btn-secondary" onClick={() => setPage(1)}>Return to first page</button> : null}
    <QueryBoundary query={query}>{(data) => <DataTable key={`${page}:${JSON.stringify(requestFilters)}:${pageSize}`} columnChooser selectable caption={`${customer.code} assets`} columns={columns} rows={data.results} total={data.count}
      visibleColumns={layout.columns ?? DEFAULT_COLUMNS} onVisibleColumnsChange={(columns) => update({ columns: columns.join(","), view: "" }, false, false)}
      density={layout.density} onDensityChange={(density) => update({ density, view: "" }, false, false)}
      sorting={filters.ordering} sortableColumns={{ hostname: "hostname", group_name: "group_name", os: "os_name", last_seen: "last_seen_online" }} onSort={(field) => set("ordering", filters.ordering === field ? `-${field}` : field)}
      loading={busy} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={(size) => update({ page_size: String(size), view: "" })} getRowId={(row) => row.id}
      selectionActions={customer.my_capabilities.includes("customer.export") ? (rows) => <ExportButton customer={customer} reportType="asset_inventory" label="Export selected devices" filters={{ ...exportFilters, asset_ids: rows.map((row) => row.id).join(",") }} /> : undefined}
      emptyTitle="No devices match your filters." emptyHint={<button type="button" className="text-sky-800 underline" onClick={clear}>Clear filters and show all devices</button>} />}</QueryBoundary>
  </section>;
}

export function AssetsPage() {
  const { selected } = useCustomers();
  return <><PageHeader title="Devices" subtitle={selected ? `${selected.code} / ${selected.name}` : undefined} />{!selected ? <SelectCustomer>Inventory is always shown for exactly one customer.</SelectCustomer> : <><DataSources customer={selected} compact /><AssetTable key={selected.id} customer={selected} /></>}</>;
}
