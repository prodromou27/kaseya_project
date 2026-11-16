import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { SelectCustomer } from "../../components/SelectCustomer";
import { QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, Field, PageHeader, type Tone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import type { Customer, ReportRun } from "../../lib/types";
import { useUrlFilters } from "../../lib/useUrlFilters";

export type ServerRow = {
  asset_id: string; hostname: string; os_name: string; os_version: string; site: string; vsa_group: string;
  last_seen_online: string | null; server_source: "marked" | "detected" | "excluded" | ""; is_server: boolean; note: string;
  owner_group_id: string | null; owner_group: string; owner_name: string; owner_email: string;
  os_updates_status: string; updates_available: number | null; critical_available: number; important_available: number;
  patch_policy_state: string; patch_policy: string; outdated_programs: number;
  os_lifecycle: "end_of_support" | "ending_soon" | "supported" | "unknown"; os_end_of_support: string | null;
  needs_attention: boolean; reasons: string[];
};
type ServerList = {
  rows: ServerRow[]; count: number; detection_note: string;
  totals: { servers: number; needs_attention: number; unassigned: number; critical: number; out_of_support: number };
};
export type OwnerGroup = { id: string; name: string; owner_name: string; owner_email: string; notes: string; servers: number };

const PAGE = 50;
const SOURCE: Record<ServerRow["server_source"], { label: string; tone: Tone }> = {
  marked: { label: "Marked", tone: "info" }, detected: { label: "Detected", tone: "neutral" },
  excluded: { label: "Not a server", tone: "neutral" }, "": { label: "Not a server", tone: "neutral" },
};
const LIFECYCLE: Record<ServerRow["os_lifecycle"], { label: string; tone: Tone }> = {
  end_of_support: { label: "Out of support", tone: "bad" }, ending_soon: { label: "Ending soon", tone: "warn" },
  supported: { label: "Supported", tone: "good" }, unknown: { label: "Unknown", tone: "neutral" },
};

function UpdatesCell({ row }: { row: ServerRow }) {
  if (row.updates_available === null) return <span className="text-xs text-slate-500">Not collected</span>;
  if (row.updates_available === 0) return <Badge tone="good">Up to date</Badge>;
  return (
    <span className="text-sm">
      <span className="font-semibold tabular-nums">{row.updates_available}</span> available
      {row.critical_available ? <span className="block text-xs font-medium text-red-800">{row.critical_available} Critical</span> : null}
      {row.important_available ? <span className="block text-xs text-amber-900">{row.important_available} Important</span> : null}
    </span>
  );
}

function policyText(row: ServerRow): string {
  if (row.patch_policy) return row.patch_policy;
  return { explicit_none: "No policy (explicit)", not_reported: "No policy", assigned: "Assigned" }[row.patch_policy_state] ?? "Unknown";
}

function useReport(customer: Customer) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (filters: Record<string, string>) =>
      api.post<ReportRun>(`/customers/${customer.id}/reports/`, { report_type: "server_owner_patching", format: "pdf", filters }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports", customer.id] }),
  });
}

function BulkActions({ customer, rows, groups }: { customer: Customer; rows: ServerRow[]; groups: OwnerGroup[] }) {
  const qc = useQueryClient();
  const [owner, setOwner] = useState("");
  const change = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/customers/${customer.id}/servers/designate/`, { assets: rows.map((r) => r.asset_id), ...body }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["servers", customer.id] }); void qc.invalidateQueries({ queryKey: ["server-owner-groups", customer.id] }); },
  });
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="list-label">Owner group
        <select className="input" value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">No owner</option>
          {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
      </label>
      <button type="button" className="btn-primary" disabled={change.isPending} onClick={() => change.mutate({ owner_group: owner })}>Assign owner</button>
      <button type="button" className="btn-secondary" disabled={change.isPending} onClick={() => change.mutate({ marking: "server" })}>Mark as server</button>
      <button type="button" className="btn-secondary" disabled={change.isPending} onClick={() => change.mutate({ marking: "not_server" })}>Not a server</button>
      <button type="button" className="btn-secondary" disabled={change.isPending} onClick={() => change.mutate({ marking: "auto" })}>Use detection</button>
      {change.isError ? <span role="alert" className="text-sm text-red-700">{describeError(change.error)}</span> : null}
      {change.isSuccess ? <span role="status" className="text-sm text-emerald-800">Updated {rows.length} device{rows.length === 1 ? "" : "s"}.</span> : null}
    </div>
  );
}

function ServersTab({ customer, groups }: { customer: Customer; groups: OwnerGroup[] }) {
  const { filters, update } = useUrlFilters({ scope: "servers", owner: "", attention: "", search: "" });
  const [page, setPage] = useState(1);
  const canManage = customer.my_capabilities.includes("customer.manage_exceptions");
  const query = useQuery({
    queryKey: ["servers", customer.id, filters.scope, filters.owner, filters.attention, filters.search],
    queryFn: ({ signal }) => api.get<ServerList>(`/customers/${customer.id}/servers/`, {
      scope: filters.scope === "all" ? "all" : "", owner_group: filters.owner, attention: filters.attention, search: filters.search,
    }, signal),
  });
  const set = (patch: Record<string, string>) => { setPage(1); update(patch); };
  const columns: ColumnDef<ServerRow, unknown>[] = [
    { id: "device", header: "Server", cell: ({ row }) => (
      <span>
        <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link>
        <span className="block text-xs text-slate-500">{[row.original.os_name, row.original.os_version].filter(Boolean).join(" · ") || "OS not reported"}</span>
      </span>
    ) },
    { id: "owner", header: "Owner", cell: ({ row }) => row.original.owner_group
      ? <span><span className="font-medium">{row.original.owner_group}</span>{row.original.owner_name ? <span className="block text-xs text-slate-500">{row.original.owner_name}</span> : null}</span>
      : row.original.is_server ? <span className="text-xs font-medium text-amber-800">No owner</span> : <span className="text-xs text-slate-500">—</span> },
    { id: "source", header: "Server?", cell: ({ row }) => <Badge tone={SOURCE[row.original.server_source].tone}>{SOURCE[row.original.server_source].label}</Badge> },
    { id: "updates", header: "OS updates", cell: ({ row }) => <UpdatesCell row={row.original} /> },
    { id: "policy", header: "Patch policy", cell: ({ row }) => <span className={["explicit_none", "not_reported"].includes(row.original.patch_policy_state) ? "text-sm font-medium text-amber-800" : "text-sm"}>{policyText(row.original)}</span> },
    { id: "os", header: "OS support", cell: ({ row }) => (
      <span><Badge tone={LIFECYCLE[row.original.os_lifecycle].tone}>{LIFECYCLE[row.original.os_lifecycle].label}</Badge>
        {row.original.os_end_of_support ? <span className="block text-xs text-slate-500">ends {row.original.os_end_of_support}</span> : null}</span>
    ) },
    { id: "action", header: "Action needed", cell: ({ row }) => row.original.reasons.length
      ? <ul className="list-disc pl-4 text-xs text-slate-800">{row.original.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      : <span className="text-xs text-slate-500">{row.original.is_server ? "Nothing found" : "—"}</span> },
  ];
  return (
    <QueryBoundary query={query}>
      {(data) => (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {([
              ["Servers", data.totals.servers, false], ["Need attention", data.totals.needs_attention, true],
              ["Without an owner", data.totals.unassigned, true], ["With Critical updates", data.totals.critical, true],
              ["OS out of support", data.totals.out_of_support, true],
            ] as const).map(([label, value, warn]) => (
              <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-slate-600">{label}</p>
                <p className={`mt-1 text-2xl font-semibold tabular-nums ${warn && value > 0 ? "text-amber-800" : "text-slate-900"}`}>{value}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="list-label">Show
              <select className="input" value={filters.scope} onChange={(e) => set({ scope: e.target.value })}>
                <option value="servers">Servers</option><option value="all">All devices (to mark servers)</option>
              </select>
            </label>
            <label className="list-label">Owner
              <select className="input" value={filters.owner} onChange={(e) => set({ owner: e.target.value })}>
                <option value="">All owners</option><option value="none">No owner</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={filters.attention === "true"} onChange={(e) => set({ attention: e.target.checked ? "true" : "" })} />Needs attention only
            </label>
            <label className="list-label">Search
              <input className="input w-56" type="search" placeholder="Name, OS or owner" defaultValue={filters.search}
                onKeyDown={(e) => { if (e.key === "Enter") set({ search: (e.target as HTMLInputElement).value }); }} />
            </label>
          </div>
          <p className="text-xs text-slate-500">{data.detection_note} Markings and owners are kept in this portal only; nothing is changed in VSA X.</p>
          <DataTable caption="Servers" rows={data.rows.slice((page - 1) * PAGE, page * PAGE)} total={data.rows.length} page={page} pageSize={PAGE}
            onPageChange={setPage} getRowId={(r) => r.asset_id} columns={columns} selectable={canManage}
            selectionActions={canManage ? (rows) => <BulkActions customer={customer} rows={rows} groups={groups} /> : undefined}
            emptyTitle={filters.scope === "all" ? "No devices match." : "No servers match."}
            emptyHint={filters.scope === "all" ? undefined : "Choose Show → All devices to mark devices as servers."} />
        </div>
      )}
    </QueryBoundary>
  );
}

export function ownerEmail(group: OwnerGroup, customer: Customer, servers: ServerRow[]): string {
  const mine = servers.filter((s) => s.owner_group_id === group.id && s.needs_attention);
  const lines = mine.slice(0, 25).map((s) => `- ${s.hostname}: ${s.reasons.join("; ")}`);
  if (mine.length > 25) lines.push(`- and ${mine.length - 25} more (see the attached report)`);
  const body = [
    `Hello${group.owner_name ? ` ${group.owner_name}` : ""},`, "",
    mine.length
      ? `${mine.length} of your servers at ${customer.name} need patching or an upgrade:`
      : `None of your servers at ${customer.name} currently show missing updates or support issues.`,
    ...lines, "",
    "Please plan the updates and let us know when they are done. The full server patching report is attached.", "",
  ].join("\n");
  const subject = `Server patching: ${group.name} (${customer.name})`;
  return `mailto:${encodeURIComponent(group.owner_email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function GroupForm({ customer, group, onDone }: { customer: Customer; group?: OwnerGroup; onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: group?.name ?? "", owner_name: group?.owner_name ?? "", owner_email: group?.owner_email ?? "", notes: group?.notes ?? "" });
  const save = useMutation({
    mutationFn: () => group
      ? api.patch(`/customers/${customer.id}/server-owner-groups/${group.id}/`, form)
      : api.post(`/customers/${customer.id}/server-owner-groups/`, form),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["server-owner-groups", customer.id] }); void qc.invalidateQueries({ queryKey: ["servers", customer.id] }); onDone(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <form onSubmit={submit} aria-label={group ? `Edit ${group.name}` : "New owner group"} className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <Field label="Group name">{(id) => <input id={id} className="input w-56" required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
      <Field label="Owner">{(id) => <input id={id} className="input w-48" maxLength={120} value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} />}</Field>
      <Field label="Owner email">{(id) => <input id={id} className="input w-64" type="email" maxLength={254} value={form.owner_email} onChange={(e) => setForm({ ...form, owner_email: e.target.value })} />}</Field>
      <Field label="Notes">{(id) => <input id={id} className="input w-64" maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />}</Field>
      <button type="submit" className="btn-primary" disabled={save.isPending}>{group ? "Save" : "Add owner group"}</button>
      {group ? <button type="button" className="btn-secondary" onClick={onDone}>Cancel</button> : null}
      {save.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(save.error)}</p> : null}
    </form>
  );
}

function OwnersTab({ customer, groups }: { customer: Customer; groups: OwnerGroup[] }) {
  const qc = useQueryClient();
  const canManage = customer.my_capabilities.includes("customer.manage_exceptions");
  const canExport = customer.my_capabilities.includes("customer.export");
  const [editing, setEditing] = useState<string | null>(null);
  const report = useReport(customer);
  const servers = useQuery({
    queryKey: ["servers", customer.id, "servers", "", "", ""],
    queryFn: ({ signal }) => api.get<ServerList>(`/customers/${customer.id}/servers/`, {}, signal),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/customers/${customer.id}/server-owner-groups/${id}/`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["server-owner-groups", customer.id] }); void qc.invalidateQueries({ queryKey: ["servers", customer.id] }); },
  });
  const rows = servers.data?.rows ?? [];
  return (
    <div className="space-y-4">
      {canManage ? <GroupForm customer={customer} onDone={() => undefined} key={groups.length} /> : null}
      {canExport ? (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-secondary" disabled={report.isPending} onClick={() => report.mutate({})}>Report for all owners (PDF)</button>
          <button type="button" className="btn-secondary" disabled={report.isPending} onClick={() => report.mutate({ owner_group: "none" })}>Report: servers without an owner</button>
          {report.isSuccess ? <span role="status" className="text-sm text-emerald-800">Report requested; it appears under Reports when ready.</span> : null}
          {report.isError ? <span role="alert" className="text-sm text-red-700">{describeError(report.error)}</span> : null}
        </div>
      ) : null}
      <DataTable caption="Owner groups" rows={groups} getRowId={(g) => g.id}
        emptyTitle="No owner groups yet." emptyHint={canManage ? "Add one above, then assign servers on the Servers tab." : undefined}
        columns={[
          { id: "name", header: "Owner group", cell: ({ row }) => <span><span className="font-medium">{row.original.name}</span>{row.original.notes ? <span className="block text-xs text-slate-500">{row.original.notes}</span> : null}</span> },
          { id: "owner", header: "Owner", cell: ({ row }) => <span>{row.original.owner_name || "—"}{row.original.owner_email ? <span className="block text-xs text-slate-500">{row.original.owner_email}</span> : null}</span> },
          { id: "servers", header: "Servers", cell: ({ row }) => row.original.servers },
          { id: "attention", header: "Need attention", cell: ({ row }) => {
            const n = rows.filter((s) => s.owner_group_id === row.original.id && s.needs_attention).length;
            return servers.data ? <span className={n ? "font-semibold text-amber-800" : ""}>{n}</span> : "…";
          } },
          { id: "actions", header: "Actions", cell: ({ row }) => (
            <span className="flex flex-wrap gap-2">
              {canExport ? <button type="button" className="btn-secondary" disabled={report.isPending} onClick={() => report.mutate({ owner_group: row.original.id })}>Report (PDF)</button> : null}
              {row.original.owner_email && servers.data ? <a className="btn-secondary" href={ownerEmail(row.original, customer, rows)}>Email owner</a> : null}
              {canManage ? <button type="button" className="btn-secondary" onClick={() => setEditing(editing === row.original.id ? null : row.original.id)}>Edit</button> : null}
              {canManage ? <button type="button" className="btn-danger" disabled={remove.isPending}
                onClick={() => { if (window.confirm(`Delete ${row.original.name}? Its servers become unassigned.`)) remove.mutate(row.original.id); }}>Delete</button> : null}
            </span>
          ) },
        ]} />
      {editing ? (() => {
        const group = groups.find((g) => g.id === editing);
        return group ? <GroupForm key={group.id} customer={customer} group={group} onDone={() => setEditing(null)} /> : null;
      })() : null}
      <p className="text-xs text-slate-500">
        "Email owner" opens your own mail program with a summary of that owner's servers that need attention; the portal
        does not send email. Attach the owner's PDF report from Reports.
      </p>
    </div>
  );
}

function Servers({ customer }: { customer: Customer }) {
  const { filters, update } = useUrlFilters({ tab: "servers" });
  const groups = useQuery({
    queryKey: ["server-owner-groups", customer.id],
    queryFn: ({ signal }) => api.get<OwnerGroup[]>(`/customers/${customer.id}/server-owner-groups/`, undefined, signal),
  });
  return (
    <QueryBoundary query={groups}>
      {(g) => (
        <Tabs label="Server sections" active={filters.tab} onChange={(tab) => update({ tab })} tabs={[
          { id: "servers", label: "Servers", content: <ServersTab customer={customer} groups={g} /> },
          { id: "owners", label: `Owner groups (${g.length})`, content: <OwnersTab customer={customer} groups={g} /> },
        ]} />
      )}
    </QueryBoundary>
  );
}

export function ServersPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Servers & owners" subtitle="Which servers need patching or an upgrade, and who owns them. Owners and markings are kept in this portal." />
      {!selected ? <SelectCustomer /> : <Servers key={selected.id} customer={selected} />}
    </>
  );
}
