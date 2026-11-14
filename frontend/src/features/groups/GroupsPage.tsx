import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Notice, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { Customer, HierarchyResponse, NodeCounts } from "../../lib/types";
import { DataSources } from "../inventory/DataSources";
import { SelectCustomer } from "../../components/SelectCustomer";

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

function Tree({ customer }: { customer: Customer }) {
  const [staleDays, setStaleDays] = useState(7);
  const query = useQuery({
    queryKey: ["hierarchy", customer.id, staleDays],
    queryFn: ({ signal }) => api.get<HierarchyResponse>(`/customers/${customer.id}/hierarchy/`, { stale_days: staleDays }, signal),
  });
  return (
    <>
      <div className="mb-3 flex items-center gap-2 text-xs">
        <label className="flex items-center gap-2">
          “Not seen recently” after
          <select className="input py-1" value={staleDays} onChange={(e) => setStaleDays(Number(e.target.value))}>
            {[1, 7, 14, 30, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </label>
      </div>
      <QueryBoundary query={query} isEmpty={(h) => h.organizations.length === 0}
        empty={<EmptyState title="No hierarchy in the current dataset.">Run a sync after a source mapping is approved.</EmptyState>}>
        {(h) => (
          <>
            {h.hierarchy_status.includes("not_collected") ? (
              <Notice tone="warn">The organisation/site/group lists were not collected for at least one source in the current dataset.</Notice>
            ) : null}
            <p className="mb-2 text-xs text-slate-500">
              As of {h.as_of.map(formatUtc).join(", ")} · data basis {h.data_basis.join(", ")} · {h.note}
              {h.devices_without_asset ? ` · ${h.devices_without_asset} device-list entries had no inventory record (e.g. MDM-only).` : ""}
            </p>
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
            {h.unassigned.devices ? (
              <Notice tone="warn">
                {h.unassigned.devices} device(s) are not in any listed active group (absent from the device list or in a
                group VSA did not return as active). They are not hidden: see Assets.
              </Notice>
            ) : null}
          </>
        )}
      </QueryBoundary>
    </>
  );
}

export function GroupsPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Groups & network" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? <SelectCustomer /> : (
        <>
          <DataSources customer={selected} />
          <Tree key={selected.id} customer={selected} />
        </>
      )}
    </>
  );
}
