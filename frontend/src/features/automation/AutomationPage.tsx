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
  collection: Collection[]; task_limitation: string;
};

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
