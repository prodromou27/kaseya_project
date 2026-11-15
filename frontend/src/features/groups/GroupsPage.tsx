import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Notice, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { useUrlFilters } from "../../lib/useUrlFilters";
import { formatUtc } from "../../lib/format";
import type { Customer, GroupTreeNode, HierarchyResponse, NodeCounts } from "../../lib/types";
import { DataSources } from "../inventory/DataSources";
import { SelectCustomer } from "../../components/SelectCustomer";
import { Tabs } from "../../components/Tabs";
import { SubnetInventory } from "./SubnetInventory";

function Counts({ c }: { c: NodeCounts }) {
  return (
    <span className="flex flex-wrap gap-1 text-[11px] text-slate-600">
      <span className="font-medium text-slate-800">{c.devices} devices</span>
      {c.stale ? <Badge tone="warn">{c.stale} not seen recently</Badge> : null}
      {c.never_seen ? <Badge tone="warn">{c.never_seen} never seen</Badge> : null}
      {c.agent_not_installed ? <Badge tone="warn">{c.agent_not_installed} no agent</Badge> : null}
      {c.no_network_data ? <Badge tone="neutral">{c.no_network_data} no network data</Badge> : null}
      {c.no_update_data ? <Badge tone="neutral">{c.no_update_data} no update data</Badge> : null}
    </span>
  );
}

function Hierarchy({ h }: { h: HierarchyResponse }) {
  return (
            <ul className="space-y-3" aria-label="Organisations">
              {h.organizations.map((o) => (
                <li key={`${o.instance_id ?? ""}-${o.external_id}`} className="rounded border border-slate-200 bg-white p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{o.name || "(unnamed organisation)"}</span>
                    <code className="text-[11px] text-slate-500">org {o.external_id}{o.source ? ` / ${o.source}` : ""}</code>
                    <Counts c={o.counts} />
                  </div>
                  <ul className="ml-4 space-y-2" aria-label={`Sites of ${o.name}`}>
                    {o.sites.map((s) => (
                      <li key={s.external_id}>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{s.name || "(unnamed site)"}</span>
                          <code className="text-[11px] text-slate-500">site {s.external_id}</code>
                          <Counts c={s.counts} />
                        </div>
                        <ul className="ml-4 mt-1 space-y-1" aria-label={`Groups of ${s.name}`}>
                          {s.groups.map((g) => (
                            <li key={g.external_id} className="flex flex-wrap items-center gap-2">
                              <Link className="text-sky-800 hover:underline" to={`/groups/${g.external_id}${g.instance_id ? `?instance=${g.instance_id}` : ""}`}>{g.name || "(unnamed group)"}</Link>
                              <code className="text-[11px] text-slate-500">group {g.external_id}</code>
                              {g.is_active === false ? <Badge tone="neutral">inactive</Badge> : null}
                              <Counts c={g.counts} />
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
  );
}

type GroupRow = GroupTreeNode & { site: string; siteId: string; organization: string; source: string };
function Directory({ h }: { h: HierarchyResponse }) {
  const { filters, update, reset, page, setPage } = useUrlFilters({ search: "", site: "", purpose: "", sort: "name" });
  const rows: GroupRow[] = h.organizations.flatMap((org) => org.sites.flatMap((site) => site.groups.map((group) => ({ ...group, instance_id: group.instance_id ?? org.instance_id, site: site.name, siteId: site.external_id, organization: org.name, source: org.source ?? "" }))));
  const sites = Array.from(new Map(rows.map((row) => [`${row.instance_id}:${row.siteId}`, row])).entries());
  const needle = filters.search.trim().toLocaleLowerCase();
  const filtered = rows.filter((row) => (!needle || [row.name, row.external_id, row.site, row.organization, row.source].some((value) => value.toLocaleLowerCase().includes(needle))) && (!filters.site || `${row.instance_id}:${row.siteId}` === filters.site) && (!filters.purpose || (filters.purpose === "onboarding" ? row.is_onboarding : !row.is_onboarding)));
  const field = filters.sort.replace(/^-/, "");
  filtered.sort((a, b) => {
    const compared = field === "devices" ? a.counts.devices - b.counts.devices : (field === "site" ? a.site.localeCompare(b.site) : a.name.localeCompare(b.name));
    return (filters.sort.startsWith("-") ? -compared : compared) || `${a.instance_id}:${a.external_id}`.localeCompare(`${b.instance_id}:${b.external_id}`);
  });
  const link = (row: GroupRow, devices = false) => devices ? `/assets?${new URLSearchParams({ group_id: row.external_id, ...(row.instance_id ? { instance: row.instance_id } : {}) })}` : `/groups/${row.external_id}${row.instance_id ? `?instance=${row.instance_id}` : ""}`;
  return <div className="space-y-3">
    <div className="list-workspace flex flex-wrap items-end gap-3" role="search" aria-label="Find groups">
      <label className="list-label min-w-48 flex-1">Search groups<input className="input w-full" type="search" maxLength={100} placeholder="Group, site, organization, source or ID" value={filters.search} onChange={(event) => update({ search: event.target.value }, true)} /></label>
      <label className="list-label">Site<select className="input max-w-64" value={filters.site} onChange={(event) => update({ site: event.target.value })}><option value="">All sites</option>{sites.map(([key, row]) => <option key={key} value={key}>{row.site} / {row.source}</option>)}</select></label>
      <label className="list-label">Group purpose<select className="input" value={filters.purpose} onChange={(event) => update({ purpose: event.target.value })}><option value="">All groups</option><option value="onboarding">Onboarding</option><option value="standard">Standard</option></select></label>
      {filters.search || filters.site || filters.purpose ? <button type="button" className="btn-secondary" onClick={reset}>Clear group filters</button> : null}
    </div>
    <DataTable caption="Agent groups" rows={filtered.slice((page - 1) * 50, page * 50)} total={filtered.length} page={page} onPageChange={setPage} getRowId={(row) => `${row.instance_id}:${row.external_id}`}
      sorting={filters.sort} sortableColumns={{ name: "name", site: "site", devices: "devices" }} onSort={(field) => update({ sort: filters.sort === field ? `-${field}` : field })}
      emptyTitle="No groups match your filters." emptyHint={<button type="button" className="text-sky-800 underline" onClick={reset}>Clear group filters</button>}
      columns={[
        { id: "name", header: "Group", cell: ({ row }) => <div><Link className="font-semibold text-sky-800 hover:underline" to={link(row.original)}>{row.original.name || "Unnamed group"}</Link><p className="mt-1 text-xs text-slate-500">ID {row.original.external_id}{row.original.is_active === false ? " / inactive" : ""}</p></div> },
        { id: "site", header: "Site / source", cell: ({ row }) => <div><span className="font-medium">{row.original.site || "Site not reported"}</span><p className="mt-1 text-xs text-slate-500">{row.original.organization} / {row.original.source}</p></div> },
        { id: "devices", header: "Devices", cell: ({ row }) => <Link className="font-semibold text-sky-800 underline" aria-label={`${row.original.counts.devices} devices in ${row.original.name} at ${row.original.site}`} to={link(row.original, true)}>{row.original.counts.devices}</Link> },
        { id: "last_seen", header: "Not seen recently", cell: ({ row }) => <Badge tone={row.original.counts.stale || row.original.counts.never_seen ? "warn" : "neutral"}>{row.original.counts.stale + row.original.counts.never_seen}</Badge> },
        { id: "purpose", header: "Purpose", cell: ({ row }) => <Badge tone={row.original.is_onboarding ? "info" : "neutral"}>{row.original.is_onboarding ? "Onboarding" : "Standard"}</Badge> },
      ]} />
  </div>;
}

function Workspace({ customer }: { customer: Customer }) {
  const { filters, update } = useUrlFilters({ view: "list", stale_days: "7" });
  const days = [1, 7, 14, 30, 90].includes(Number(filters.stale_days)) ? Number(filters.stale_days) : 7;
  const query = useQuery({ queryKey: ["hierarchy", customer.id, days], queryFn: ({ signal }) => api.get<HierarchyResponse>(`/customers/${customer.id}/hierarchy/`, { stale_days: days }, signal) });
  return <QueryBoundary query={query} isEmpty={(h) => h.organizations.length === 0} empty={<EmptyState title="No groups in the current dataset.">Run a sync after a source mapping is approved.</EmptyState>}>{(h) => <div className="space-y-3">
    {h.hierarchy_status.includes("not_collected") ? <Notice tone="warn">Some source hierarchy lists were not collected. This directory may be incomplete.</Notice> : null}
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><p>As of {h.as_of.map(formatUtc).join(", ")} / {h.data_basis.join(", ")}</p><label className="flex items-center gap-2">Not seen recently after<select className="input py-1" value={days} onChange={(event) => update({ stale_days: event.target.value })}>{[1, 7, 14, 30, 90].map((day) => <option key={day} value={day}>{day} days</option>)}</select></label></div>
    <Tabs label="Group navigation" active={filters.view} onChange={(view) => update({ view })} tabs={[
      { id: "list", label: "Group list", content: <Directory h={h} /> },
      { id: "hierarchy", label: "Hierarchy", content: <Hierarchy h={h} /> },
      { id: "subnets", label: "Subnets", content: <SubnetInventory customer={customer} /> },
    ]} />
    {h.unassigned.devices ? <Notice tone="warn">{h.unassigned.devices} device(s) are outside the listed groups. <Link className="underline" to="/assets">Open device inventory</Link>.</Notice> : null}
    {h.devices_without_asset ? <p className="text-xs text-slate-500">{h.devices_without_asset} source device-list entries have no inventory record and are not included in device totals.</p> : null}
  </div>}</QueryBoundary>;
}

export function GroupsPage() {
  const { selected } = useCustomers();
  return <><PageHeader title="Groups & network" subtitle="Find a group, open its devices or inspect reported network evidence." />{!selected ? <SelectCustomer /> : <><DataSources customer={selected} compact /><Workspace key={selected.id} customer={selected} /></>}</>;
}
