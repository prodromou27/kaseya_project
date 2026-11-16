import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { SelectCustomer } from "../../components/SelectCustomer";
import { QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, PageHeader } from "../../components/ui";
import { api } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import { useUrlFilters } from "../../lib/useUrlFilters";
import type { Customer } from "../../lib/types";

type Collection = { integration: string; status: string; error_code: string; last_success_at: string | null };
type WorkflowRow = { workflow_id: string; name: string; runs: number; failed: number; success_pct: number | null; last_failure_at: string | null };
type Execution = { id: string; workflow_id: string; workflow: string; asset_id: string | null; hostname: string; status: string; trigger_type: string; created_at: string; completed_at: string | null; failed_step: string };
type Health = { days: number; totals: { runs: number; failed: number; devices_with_failures: number }; workflows: WorkflowRow[]; executions: Execution[]; collection: Collection[]; task_limitation: string };
type Catalog = {
  workflows: { integration: string; id: string; name: string; enabled: boolean | null; trigger: string; context: string; folder: string; updated: string }[];
  tasks: { integration: string; id: string; name: string; enabled: boolean | null; scheduled: boolean | null; scope: string; state: string; scripts: number | null; built_in: boolean | null; folder: string; updated: string }[];
  scopes: { integration: string; id: string; name: string; description: string; criteria: { type: string; identifier: string }[]; total_devices: number | null; used_by: { type: string; id: string; name: string }[] }[];
  global_rules: { integration: string; os_rules: Record<string, unknown>[]; software_rules: Record<string, unknown>[]; fetched_at: string }[];
  collection: Collection[]; task_limitation: string;
};

function ruleText(rule: Record<string, unknown>): string {
  const product = rule.ProductName ?? rule.ProductId;
  const action = typeof rule.Action === "string" ? rule.Action.replaceAll("_", " ").toLowerCase() : "";
  if (product) return `${String(product)}${action ? ` → ${action}` : ""}`;
  const parts = Object.entries(rule).filter(([k]) => k !== "Action").map(([, v]) => String(v)).join(" ");
  return `${parts}${action ? ` → ${action}` : ""}`;
}

const STATUS_TEXT: Record<string, string> = {
  ok: "collected", never: "not collected yet", not_permitted: "API token has no automation permission", unavailable: "VSA X did not answer", failed: "collection failed",
};

function CollectionNote({ rows }: { rows: Collection[] }) {
  if (!rows.length) return <p className="text-xs text-slate-500">Automation data is collected after the next successful sync.</p>;
  return (
    <p className="text-xs text-slate-500">
      {rows.map((c) => (
        <span key={c.integration} className="mr-3">
          {c.integration}: <span className={c.status === "ok" ? "" : "font-medium text-amber-800"}>{STATUS_TEXT[c.status] ?? c.status}</span>
          {c.last_success_at ? ` · last collected ${formatUtc(c.last_success_at)}` : ""}
        </span>
      ))}
    </p>
  );
}

function Health({ customer }: { customer: Customer }) {
  const { filters, update } = useUrlFilters({ days: "7", status: "Failed", workflow: "" });
  const query = useQuery({
    queryKey: ["automation", customer.id, filters.days, filters.status, filters.workflow],
    queryFn: ({ signal }) => api.get<Health>(`/customers/${customer.id}/automation/`, { days: filters.days, status: filters.status, workflow: filters.workflow }, signal),
  });
  const runColumns: ColumnDef<Execution, unknown>[] = [
    { header: "When", cell: ({ row }) => <span className="nowrap">{formatUtc(row.original.created_at)}</span> },
    { header: "Device", cell: ({ row }) => row.original.asset_id ? <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> : row.original.hostname },
    { header: "Workflow", accessorKey: "workflow" },
    { header: "Result", cell: ({ row }) => <Badge tone={row.original.status === "Failed" ? "bad" : row.original.status === "Success" ? "good" : "neutral"}>{row.original.status}</Badge> },
    { header: "Failed step", cell: ({ row }) => <span className="text-xs text-slate-700">{row.original.failed_step || "—"}</span> },
  ];
  return (
    <QueryBoundary query={query}>
      {(h) => (
        <div className="space-y-4">
          <CollectionNote rows={h.collection} />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[["Workflow runs", h.totals.runs, `last ${h.days} days`], ["Failed runs", h.totals.failed, "need a look"], ["Devices with failures", h.totals.devices_with_failures, "distinct devices"]].map(([label, value, hint]) => (
              <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-slate-600">{label}</p>
                <p className={`mt-1 text-2xl font-semibold tabular-nums ${label === "Failed runs" && Number(value) > 0 ? "text-amber-800" : "text-slate-900"}`}>{value}</p>
                <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="list-label">Period
              <select className="input" value={filters.days} onChange={(e) => update({ days: e.target.value })}>
                {[1, 7, 14, 30, 90].map((d) => <option key={d} value={d}>{d === 1 ? "Last 24 hours" : `Last ${d} days`}</option>)}
              </select>
            </label>
            <label className="list-label">Result
              <select className="input" value={filters.status} onChange={(e) => update({ status: e.target.value })}>
                <option value="Failed">Failed</option><option value="Success">Successful</option><option value="">All</option>
              </select>
            </label>
            {filters.workflow ? <button type="button" className="filter-chip" onClick={() => update({ workflow: "" })}>Workflow {h.workflows.find((w) => w.workflow_id === filters.workflow)?.name ?? filters.workflow} ✕</button> : null}
          </div>
          <DataTable caption="Workflows" rows={h.workflows} getRowId={(w) => w.workflow_id} emptyTitle="No workflow ran on this customer's devices in this period." columns={[
            { header: "Workflow", cell: ({ row }) => <button type="button" className="text-left font-medium text-sky-800 hover:underline" onClick={() => update({ workflow: row.original.workflow_id, status: "" })}>{row.original.name}</button> },
            { header: "Runs", accessorKey: "runs" },
            { header: "Failed", cell: ({ row }) => <span className={row.original.failed ? "font-semibold text-amber-800" : ""}>{row.original.failed}</span> },
            { header: "Success", cell: ({ row }) => row.original.success_pct === null ? "—" : `${row.original.success_pct}%` },
            { header: "Last failure", cell: ({ row }) => row.original.last_failure_at ? <span className="nowrap">{formatUtc(row.original.last_failure_at)}</span> : "—" },
          ]} />
          <DataTable caption="Workflow runs" rows={h.executions} columns={runColumns} getRowId={(e) => e.id}
            emptyTitle={filters.status === "Failed" ? "No failed runs in this period." : "No runs match."} />
          <p className="text-xs text-slate-500">{h.task_limitation} Only runs on this customer's own devices are shown.</p>
        </div>
      )}
    </QueryBoundary>
  );
}

function CatalogView() {
  const query = useQuery({ queryKey: ["automation", "catalog"], queryFn: ({ signal }) => api.get<Catalog>("/automation/catalog/", undefined, signal) });
  const yes = (v: boolean | null) => (v === null ? "—" : v ? "Yes" : "No");
  return (
    <QueryBoundary query={query}>
      {(c) => (
        <div className="space-y-4">
          <CollectionNote rows={c.collection} />
          <DataTable caption="Tasks" rows={c.tasks} getRowId={(t) => `${t.integration}-${t.id}`} emptyTitle="No tasks collected." columns={[
            { header: "Task", cell: ({ row }) => <span><span className="font-medium">{row.original.name}</span><span className="block text-xs text-slate-500">{row.original.folder}</span></span> },
            { header: "Enabled", cell: ({ row }) => yes(row.original.enabled) },
            { header: "Scheduled", cell: ({ row }) => yes(row.original.scheduled) },
            { header: "Scope", cell: ({ row }) => row.original.scope || "—" },
            { header: "Scripts", cell: ({ row }) => row.original.scripts ?? "—" },
            { header: "State", cell: ({ row }) => row.original.state || "—" },
          ]} />
          <DataTable caption="Workflow definitions" rows={c.workflows} getRowId={(w) => `${w.integration}-${w.id}`} emptyTitle="No workflows collected." columns={[
            { header: "Workflow", cell: ({ row }) => <span><span className="font-medium">{row.original.name}</span><span className="block text-xs text-slate-500">{row.original.folder}</span></span> },
            { header: "Enabled", cell: ({ row }) => yes(row.original.enabled) },
            { header: "Trigger", accessorKey: "trigger" },
            { header: "Runs on", accessorKey: "context" },
          ]} />
          <DataTable caption="Scopes" rows={c.scopes} getRowId={(x) => `${x.integration}-${x.id}`} emptyTitle="No scopes collected." columns={[
            { header: "Scope", cell: ({ row }) => <span><span className="font-medium">{row.original.name}</span>{row.original.description ? <span className="block text-xs text-slate-500">{row.original.description}</span> : null}</span> },
            { header: "Matches", cell: ({ row }) => row.original.criteria.length ? <ul className="text-xs text-slate-700">{row.original.criteria.map((k, i) => <li key={i}>{k.type}{k.identifier ? `: ${k.identifier}` : ""}</li>)}</ul> : "—" },
            { header: "Devices", cell: ({ row }) => row.original.total_devices ?? "—" },
            { header: "Used by", cell: ({ row }) => row.original.used_by.length ? <ul className="text-xs text-slate-700">{row.original.used_by.map((u) => <li key={`${u.type}-${u.id}`}>{u.type}: {u.name || `#${u.id}`}</li>)}</ul> : <span className="text-xs text-amber-800">Not used</span> },
          ]} />
          <section aria-labelledby="global-rules-heading" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 id="global-rules-heading" className="text-sm font-semibold text-slate-900">Patch global rules</h2>
            <p className="mt-0.5 text-xs text-slate-500">Tenant-wide configuration that applies to every patch-managed device. Software rules here count as third-party coverage. Whether VSA deployed an update is not available from the API.</p>
            {c.global_rules.length === 0 ? <p className="mt-2 text-sm text-slate-600">No global rules collected.</p> : c.global_rules.map((g) => (
              <div key={g.integration} className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {([["Operating-system rules", g.os_rules], ["Software rules", g.software_rules]] as const).map(([label, list]) => (
                  <div key={label}>
                    <h3 className="text-xs font-medium text-slate-600">{label} ({list.length}) · {g.integration}</h3>
                    {list.length ? <ul className="mt-1 list-disc pl-5 text-sm text-slate-800">{list.slice(0, 50).map((rule, i) => <li key={i}>{ruleText(rule)}</li>)}</ul> : <p className="mt-1 text-sm text-slate-600">None.</p>}
                  </div>
                ))}
              </div>
            ))}
          </section>
          <p className="text-xs text-slate-500">{c.task_limitation}</p>
        </div>
      )}
    </QueryBoundary>
  );
}

export function AutomationPage() {
  const me = useMe();
  const { selected } = useCustomers();
  const { filters, update } = useUrlFilters({ tab: "health" });
  const health = !selected ? <SelectCustomer>Workflow results are shown for one customer at a time.</SelectCustomer> : <Health key={selected.id} customer={selected} />;
  return (
    <>
      <PageHeader title="Automation" subtitle="VSA X workflow results on your customers' devices, and the automation catalog." />
      {me.is_super_admin ? (
        <Tabs label="Automation sections" active={filters.tab} onChange={(tab) => update({ tab })} tabs={[
          { id: "health", label: "Workflow results", content: health },
          { id: "catalog", label: "Catalog (all tenants)", content: <CatalogView /> },
        ]} />
      ) : health}
    </>
  );
}
