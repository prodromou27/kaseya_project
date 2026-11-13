import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Notice, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { Adapter, Customer, GroupNetwork } from "../../lib/types";
import { NetworkReview } from "./ExpectedSubnets";

export function AdapterList({ adapters }: { adapters: Adapter[] }) {
  if (adapters.length === 0) return <span className="text-xs text-slate-400">no adapters reported</span>;
  return (
    <ul className="space-y-1 text-xs">
      {adapters.map((a, i) => (
        <li key={`${a.mac}-${a.name}-${i}`}>
          <span className="font-medium">{a.name || "(unnamed adapter)"}</span>{" "}
          {a.mac ? <code>{a.mac.match(/.{2}/g)?.join(":")}</code> : <span className="text-slate-400">no MAC</span>}
          {a.mac_locally_administered ? <span className="ml-1"><Badge tone="info">locally administered</Badge></span> : null}
          {a.dhcp_enabled !== null ? <span className="ml-1 text-slate-500">DHCP {a.dhcp_enabled ? "on" : "off"}</span> : null}
          <div className="ml-3">
            {a.addresses.map((ip) => (
              <div key={ip.raw}>
                <code>{ip.raw}</code>{" "}
                {ip.network_cidr ? <span className="text-slate-600">→ {ip.network_cidr}</span>
                  : <span className="text-slate-400">({ip.cidr_status.replace(/_/g, " ")})</span>}{" "}
                <span className="text-slate-400">{ip.kind}</span>
              </div>
            ))}
            {a.gateways.length ? <div className="text-slate-500">gateway {a.gateways.join(", ")}</div> : null}
            {a.dns_servers.length ? <div className="text-slate-500">DNS {a.dns_servers.join(", ")}</div> : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

function View({ customer, groupId }: { customer: Customer; groupId: string }) {
  const query = useQuery({
    queryKey: ["group-network", customer.id, groupId],
    queryFn: ({ signal }) => api.get<GroupNetwork>(`/customers/${customer.id}/groups/${groupId}/network/`, undefined, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(n) => (
        <>
          <PageHeader title={n.group?.name || `Group ${groupId}`}
            subtitle={<span>group {groupId} · site {n.group?.site_external_id ?? "?"} · org {n.group?.organization_external_id ?? "?"}{" "}
              · as of {n.as_of.map(formatUtc).join(", ")} · data basis {n.data_basis.join(", ")}</span>}
            actions={<Link className="btn-secondary" to={`/assets?group_id=${groupId}`}>Open in Assets</Link>} />
          <Notice tone="info">{n.note}</Notice>
          <div className="my-3 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            {[
              ["Devices in group", n.counts.devices],
              ["With reported addresses", n.counts.with_reported_addresses],
              ["Network section not collected", n.counts.network_not_collected],
              ["Devices with several active adapters", n.counts.multi_adapter],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded border border-slate-200 bg-white px-3 py-2">
                <div className="text-xs text-slate-500">{label}</div>
                <div className="text-lg font-semibold">{value}</div>
              </div>
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <DataTable caption="Derived subnets" rows={n.subnets} getRowId={(r) => r.cidr}
              emptyTitle="No subnet could be derived (no IPv4 address reported with a valid mask)."
              columns={[
                { header: "Subnet (derived)", accessorKey: "cidr" },
                { header: "Devices", accessorKey: "devices" },
                { header: "Addresses", accessorKey: "addresses" },
              ]} />
            <section aria-labelledby="flags-h" className="rounded border border-slate-200 bg-white p-3 text-sm">
              <h2 id="flags-h" className="mb-1 font-semibold">Review flags</h2>
              <p className="mb-2 text-xs text-slate-500">{n.flags_note}</p>
              {n.duplicate_ips.length === 0 && n.mac_reuse.length === 0 ? <p className="text-slate-500">No duplicate addresses or reused MACs among this group's devices.</p> : null}
              <ul className="space-y-1">
                {n.duplicate_ips.map((d) => (
                  <li key={d.address}><Badge tone="warn">duplicate IP</Badge> <code>{d.address}</code> on{" "}
                    {d.devices.map((x, i) => <span key={x.asset_id}>{i ? ", " : ""}<Link className="text-sky-800 underline" to={`/assets/${x.asset_id}`}>{x.hostname}</Link>{x.group_external_id !== groupId ? ` (group ${x.group_external_id || "?"})` : ""}</span>)}
                  </li>
                ))}
                {n.mac_reuse.map((m) => <li key={m.mac}><Badge tone="warn">MAC reused</Badge> <code>{m.mac}</code> on {m.device_count} devices</li>)}
              </ul>
              {Object.keys(n.addresses_without_derived_subnet).length ? (
                <p className="mt-2 text-xs text-slate-500">Addresses without a derived subnet: {Object.entries(n.addresses_without_derived_subnet).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</p>
              ) : null}
              <p className="mt-2 text-xs text-slate-600">Gateways: {n.gateways.map((g) => `${g.value} (${g.adapters})`).join(", ") || "none reported"}</p>
              <p className="text-xs text-slate-600">DNS: {n.dns_servers.map((g) => `${g.value} (${g.adapters})`).join(", ") || "none reported"}</p>
              <p className="text-xs text-slate-600">Public IPs: {n.public_ips.map((g) => `${g.value} (${g.devices})`).join(", ") || "none reported"}</p>
            </section>
          </div>
          <div className="mt-4"><NetworkReview customer={customer} groupId={groupId} net={n} /></div>
          <h2 className="mb-2 mt-4 text-sm font-semibold">Devices and reported adapters</h2>
          <DataTable caption="Group devices" rows={n.devices} getRowId={(d) => d.asset_id} emptyTitle="No devices in this group."
            columns={[
              { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
              { header: "Last seen", cell: ({ row }) => formatUtc(row.original.last_seen_online) },
              { header: "Adapters", cell: ({ row }) => row.original.network_status === "not_collected"
                  ? <Badge tone="warn">network not collected</Badge> : <AdapterList adapters={row.original.adapters} /> },
            ]} />
        </>
      )}
    </QueryBoundary>
  );
}

export function GroupNetworkPage() {
  const { groupId = "" } = useParams();
  const { selected } = useCustomers();
  return (
    <>
      <p className="mb-1 text-sm"><Link to="/groups" className="text-sky-800 hover:underline">← Groups & network</Link></p>
      {!selected ? <EmptyState title="Select a customer" /> : <View customer={selected} groupId={groupId} />}
    </>
  );
}
