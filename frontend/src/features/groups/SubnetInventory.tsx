import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { CAP, type Customer } from "../../lib/types";

type Status = "assigned" | "contained" | "unassigned";
type Subnet = {
  cidr: string; version: number; kind: string; prefix_length: number; device_count: number;
  groups: { group_external_id: string; group_name: string; devices: number }[];
  sites: { site_external_id: string; site_name: string; devices: number }[];
  dominant_group: { group_external_id: string; group_name: string; share_pct: number };
  gateways: string[]; dhcp: Record<string, number>; status: Status;
  expected: { id: string; cidr: string; scope_type: "site" | "group"; scope_external_id: string } | null;
  proposed: { id: string; scope_type: "site" | "group"; scope_external_id: string }[];
  outside_expected: number; mixed_groups: boolean;
};
type Listing = { subnets: number; by_status: Record<Status, number>; mixed_groups: number; devices_outside_expected: number; count: number; results: Subnet[] };
type Device = { asset_id: string; hostname: string; address: string; group_external_id: string; group_name: string; site_name: string; outside_expected: boolean };

const STATUS: Record<Status, { label: string; tone: "good" | "info" | "warn" }> = {
  assigned: { label: "Approved subnet", tone: "good" }, contained: { label: "Inside an approved range", tone: "info" }, unassigned: { label: "Not in any approved subnet", tone: "warn" },
};

function SubnetDevices({ customer, subnet, onClose }: { customer: Customer; subnet: Subnet; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["subnets", customer.id, "devices", subnet.cidr],
    queryFn: ({ signal }) => api.get<{ results: Device[] }>(`/customers/${customer.id}/subnets/devices/`, { cidr: subnet.cidr }, signal),
  });
  const expectedScope = subnet.expected ? `${subnet.expected.scope_type} ${subnet.expected.scope_external_id}` : "";
  return (
    <section aria-label={`Devices in ${subnet.cidr}`} className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Devices in {subnet.cidr}{expectedScope ? <span className="font-normal text-slate-500"> · approved for {expectedScope} ({subnet.expected?.cidr})</span> : null}</h3>
        <button type="button" className="btn-secondary" onClick={onClose}>Close</button>
      </div>
      <QueryBoundary query={query}>
        {(d) => <DataTable caption={`Devices in subnet ${subnet.cidr}`} rows={d.results} getRowId={(r) => `${r.asset_id}-${r.address}`} columns={[
          { header: "Device", cell: ({ row }) => <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
          { header: "Address", cell: ({ row }) => <span className="nowrap font-mono text-xs">{row.original.address}</span> },
          { header: "Site / group", cell: ({ row }) => `${row.original.site_name || "—"} / ${row.original.group_name || "no group"}` },
          { header: "Review", cell: ({ row }) => row.original.outside_expected ? <Badge tone="warn">Outside the approved {subnet.expected?.scope_type}</Badge> : <span className="text-xs text-slate-500">—</span> },
        ]} />}
      </QueryBoundary>
      <p className="text-xs text-slate-500">"Outside" is a review signal from reported addresses, not proof of misplacement; nothing is moved automatically.</p>
    </section>
  );
}

/** Every subnet observed on the customer's devices, how it spreads across groups, and its approved-subnet match. */
export function SubnetInventory({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const canPropose = customer.my_capabilities.includes(CAP.manageExceptions);
  const propose = useMutation({
    mutationFn: (s: Subnet) => api.post(`/customers/${customer.id}/expected-subnets/`, {
      scope_type: "group", scope_external_id: s.dominant_group.group_external_id, cidr: s.cidr,
      reason: `Identified from observed subnet: ${s.dominant_group.share_pct}% of ${s.device_count} devices in ${s.dominant_group.group_name || "this group"}`,
    }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["subnets", customer.id] }),
  });
  const [status, setStatus] = useState<Status | "">("");
  const [mixed, setMixed] = useState(false);
  const [outside, setOutside] = useState(false);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Subnet | null>(null);
  const term = useDebouncedValue(search, 300);
  const query = useQuery({
    queryKey: ["subnets", customer.id, status, mixed, outside, term],
    queryFn: ({ signal }) => api.get<Listing>(`/customers/${customer.id}/subnets/`, { status, mixed: mixed ? "true" : "", outside: outside ? "true" : "", search: term }, signal),
  });
  const columns: ColumnDef<Subnet, unknown>[] = [
    { header: "Subnet", cell: ({ row }) => <span><span className="nowrap font-mono text-sm font-medium text-slate-900">{row.original.cidr}</span><span className="block text-xs text-slate-500">{row.original.kind}{row.original.gateways.length ? ` · gateway ${row.original.gateways.join(", ")}` : ""}</span></span> },
    { header: "Devices", cell: ({ row }) => <span className="tabular-nums">{row.original.device_count}</span> },
    { header: "Groups", cell: ({ row }) => (
      <span className="text-xs">
        {row.original.groups.slice(0, 3).map((g) => <span key={g.group_external_id} className="mr-2 inline-block">{g.group_name || "no group"} <span className="text-slate-500">({g.devices})</span></span>)}
        {row.original.groups.length > 3 ? <span className="text-slate-500">+{row.original.groups.length - 3} more</span> : null}
        {row.original.mixed_groups ? <span className="block text-amber-800">Spans {row.original.groups.length} groups · {row.original.dominant_group.share_pct}% in {row.original.dominant_group.group_name || "no group"}</span> : null}
      </span>
    ) },
    { header: "Sites", cell: ({ row }) => <span className="text-xs">{row.original.sites.map((s) => s.site_name || s.site_external_id || "—").join(", ")}</span> },
    { header: "DHCP", cell: ({ row }) => <span className="text-xs">{row.original.dhcp.yes ? `${row.original.dhcp.yes} DHCP` : ""}{row.original.dhcp.yes && row.original.dhcp.no ? " · " : ""}{row.original.dhcp.no ? `${row.original.dhcp.no} static` : ""}{!row.original.dhcp.yes && !row.original.dhcp.no ? "not reported" : ""}</span> },
    { header: "Approved subnet", cell: ({ row }) => (
      <span className="flex flex-col gap-0.5">
        <Badge tone={STATUS[row.original.status].tone}>{STATUS[row.original.status].label}</Badge>
        {row.original.expected ? <span className="text-xs text-slate-500">{row.original.expected.scope_type} {row.original.expected.scope_external_id}</span> : null}
        {row.original.outside_expected ? <span className="text-xs font-medium text-amber-800">{row.original.outside_expected} device(s) outside</span> : null}
        {row.original.proposed.length ? <span className="text-xs text-sky-800">Proposed for {row.original.proposed.map((p) => `${p.scope_type} ${p.scope_external_id}`).join(", ")}; awaiting approval</span> : null}
        {canPropose && row.original.status === "unassigned" && !row.original.proposed.length && row.original.dominant_group.group_external_id ? (
          <button type="button" className="w-fit text-xs font-medium text-sky-800 underline disabled:opacity-50" disabled={propose.isPending}
            onClick={() => propose.mutate(row.original)}>Propose for {row.original.dominant_group.group_name || `group ${row.original.dominant_group.group_external_id}`}</button>
        ) : null}
      </span>
    ) },
    { header: "", id: "open", cell: ({ row }) => <button type="button" className="btn-secondary" onClick={() => setOpen(row.original)}>Devices</button> },
  ];
  return (
    <QueryBoundary query={query}>
      {(l) => (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              ["Subnets observed", l.subnets, "From addresses reported with a mask"],
              ["Not in an approved subnet", l.by_status.unassigned, "No approved site/group subnet covers it"],
              ["Span several groups", l.mixed_groups, "Devices of one subnet in different groups"],
              ["Devices outside approved scope", l.devices_outside_expected, "Address in a subnet approved for another group/site"],
            ].map(([label, value, hint]) => (
              <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-slate-600">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</p><p className="mt-0.5 text-xs text-slate-500">{hint}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="list-label">Search<input type="search" className="input w-64" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Subnet, group or gateway" /></label>
            <label className="list-label">Approved subnet
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
                <option value="">All</option><option value="unassigned">Not in any approved subnet</option><option value="contained">Inside an approved range</option><option value="assigned">Approved subnet</option>
              </select>
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={mixed} onChange={(e) => setMixed(e.target.checked)} />Spans several groups</label>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={outside} onChange={(e) => setOutside(e.target.checked)} />Has devices outside approved scope</label>
          </div>
          {propose.isError ? <p role="alert" className="text-sm text-red-700">{describeError(propose.error)}</p> : null}
          <DataTable caption="Observed subnets" columns={columns} rows={l.results} getRowId={(s) => s.cidr} emptyTitle="No subnets match. Subnets appear when VSA X reports addresses with a subnet mask." />
          {open ? <SubnetDevices key={open.cidr} customer={customer} subnet={open} onClose={() => setOpen(null)} /> : null}
          <p className="text-xs text-slate-500">Subnets are derived from endpoint-reported addresses and masks, not from network topology. Proposals are approved under the group's network page; approved subnets drive onboarding destination suggestions and the "outside" review signal.</p>
        </div>
      )}
    </QueryBoundary>
  );
}
