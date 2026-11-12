import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, statusTone } from "../../components/ui";
import { api } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import type { AuditEvent, Paginated } from "../../lib/types";

const PAGE_SIZE = 50;

const columns: ColumnDef<AuditEvent, unknown>[] = [
  { header: "Time", accessorKey: "created_at", cell: ({ getValue }) => <span className="whitespace-nowrap">{formatUtc(String(getValue()))}</span> },
  { header: "Action", accessorKey: "action", cell: ({ getValue }) => <code className="text-xs">{String(getValue())}</code> },
  { header: "Outcome", accessorKey: "outcome", cell: ({ getValue }) => <Badge tone={statusTone[String(getValue())]}>{String(getValue())}</Badge> },
  { header: "Actor", accessorKey: "actor_label", cell: ({ getValue }) => String(getValue() || "system") },
  { header: "Customer", accessorKey: "customer_code", cell: ({ getValue }) => String(getValue() ?? "—") },
  { header: "Target", cell: ({ row }) => (row.original.target_type ? `${row.original.target_type}:${row.original.target_id}` : "—") },
  { header: "Request", accessorKey: "request_id", cell: ({ getValue }) => <code className="text-[11px] text-slate-500">{String(getValue() || "—")}</code> },
];

export function AuditTable({ path, caption }: { path: string; caption: string }) {
  const [page, setPage] = useState(1);
  const [outcome, setOutcome] = useState("");
  const [action, setAction] = useState("");
  const query = useQuery({
    queryKey: ["audit", path, page, outcome, action],
    queryFn: ({ signal }) => api.get<Paginated<AuditEvent>>(path, { page, page_size: PAGE_SIZE, outcome, action }, signal),
    placeholderData: (prev) => prev,
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm">
          Outcome
          <select className="input" value={outcome} onChange={(e) => { setOutcome(e.target.value); setPage(1); }}>
            <option value="">All</option>
            <option value="success">success</option>
            <option value="denied">denied</option>
            <option value="failure">failure</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          Action prefix
          <input className="input w-48" maxLength={64} value={action} placeholder="e.g. membership." onChange={(e) => { setAction(e.target.value); setPage(1); }} />
        </label>
      </div>
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable caption={caption} columns={columns} rows={data.results} total={data.count} page={page} pageSize={PAGE_SIZE} onPageChange={setPage} getRowId={(e) => e.id} emptyTitle="No audit events match." />
        )}
      </QueryBoundary>
    </div>
  );
}
