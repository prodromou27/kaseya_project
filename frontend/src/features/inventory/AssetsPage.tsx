import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { AssetRow, Customer, Paginated } from "../../lib/types";
import { ExportButton } from "../reports/ExportButton";
import { DataSources } from "./DataSources";

const PAGE_SIZE = 50;

const columns: ColumnDef<AssetRow, unknown>[] = [
  {
    header: "Hostname",
    cell: ({ row }) => (
      <Link to={`/assets/${row.original.id}`} className="font-medium text-sky-800 hover:underline">
        {row.original.hostname || "(no name)"}
      </Link>
    ),
  },
  { header: "Group", accessorKey: "group_name" },
  { header: "OS", cell: ({ row }) => row.original.os_name || <span className="text-slate-400">not reported</span> },
  { header: "Type", accessorKey: "device_type" },
  {
    header: "Last seen",
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {formatUtc(row.original.last_seen_online)}{" "}
        {row.original.last_seen_stale ? <Badge tone="warn">offline</Badge> : null}
      </span>
    ),
  },
  {
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

type Filters = { search: string; group: string; os: string; offline: string; ordering: string };

function AssetTable({ customer }: { customer: Customer }) {
  const [filters, setFilters] = useState<Filters>({ search: "", group: "", os: "", offline: "", ordering: "hostname" });
  const [page, setPage] = useState(1);
  const facets = useQuery({
    queryKey: ["assets", customer.id, "facets"],
    queryFn: () => api.get<{ group: string[]; os: string[] }>(`/customers/${customer.id}/assets/facets/`),
  });
  const query = useQuery({
    queryKey: ["assets", customer.id, filters, page],
    queryFn: ({ signal }) =>
      api.get<Paginated<AssetRow>>(`/customers/${customer.id}/assets/`, { ...filters, page, page_size: PAGE_SIZE }, signal),
    placeholderData: (prev) => prev,
  });
  const set = (key: keyof Filters) => (value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  };
  const first = query.data?.results[0];

  return (
    <>
      <div className="mb-3 flex flex-wrap items-end gap-3" role="search" aria-label="Filter assets">
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Search
          <input className="input w-56" type="search" maxLength={100} placeholder="Hostname, serial or device ID"
                 value={filters.search} onChange={(e) => set("search")(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-700">
          Group
          <select className="input w-56" value={filters.group} onChange={(e) => set("group")(e.target.value)}>
            <option value="">All groups</option>
            {(facets.data?.group ?? []).map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
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
        {customer.my_capabilities.includes("customer.export") ? (
          <ExportButton customer={customer} reportType="asset_inventory" label="Export inventory CSV"
                        filters={{ search: filters.search, group: filters.group, os: filters.os }} />
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
            <DataTable caption={`${customer.code} assets`} columns={columns} rows={data.results} total={data.count}
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
      <PageHeader title="Assets" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? (
        <EmptyState title="Select a customer">Inventory is always shown for exactly one customer.</EmptyState>
      ) : (
        <>
          <DataSources customer={selected} />
          <AssetTable customer={selected} />
        </>
      )}
    </>
  );
}
