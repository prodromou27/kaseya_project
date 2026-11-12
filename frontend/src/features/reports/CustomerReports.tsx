import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Notice, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import { CAP, type Customer, type Paginated, type ReportRun } from "../../lib/types";

const columns: ColumnDef<ReportRun, unknown>[] = [
  { header: "Requested", accessorKey: "created_at", cell: ({ getValue }) => formatUtc(String(getValue())) },
  { header: "Report", accessorKey: "report_type" },
  { header: "By", accessorKey: "requested_by" },
  {
    header: "State",
    cell: ({ row }) => (
      <span>
        <Badge tone={statusTone[row.original.state]}>{row.original.state}</Badge>
        {row.original.error_code ? <span className="ml-1 text-xs text-red-700">{row.original.error_code}</span> : null}
      </span>
    ),
  },
  { header: "Rows", accessorKey: "row_count", cell: ({ getValue }) => (getValue() === null ? "—" : String(getValue())) },
  { header: "Data basis", accessorKey: "data_basis", cell: ({ getValue }) => <Badge tone="neutral">{String(getValue())}</Badge> },
  {
    header: "File",
    cell: ({ row }) =>
      row.original.download_available ? (
        // Plain link: the server re-authorises on every download and streams the private artifact.
        <a className="text-sky-800 underline" href={`/api/v1/reports/${row.original.id}/download/`}>
          Download CSV
        </a>
      ) : (
        <span className="text-xs text-slate-400">{row.original.state === "completed" ? "Expired" : "Not available"}</span>
      ),
  },
];

export function CustomerReports({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const path = `/customers/${customer.id}/reports/`;
  const key = ["reports", customer.id];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api.get<Paginated<ReportRun>>(path, undefined, signal),
    refetchInterval: (q) => (q.state.data?.results.some((r) => r.state === "queued" || r.state === "running") ? 2000 : false),
  });
  const canAuditReport = customer.my_capabilities.includes(CAP.auditRead);
  const request = useMutation({
    mutationFn: () => api.post<ReportRun>(path, { report_type: "customer_audit_log", format: "csv" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key }),
  });

  return (
    <div className="space-y-3">
      <Notice tone="info">
        Inventory, software and OS-update reports arrive with P1/P2. The audit-log export below exercises the same
        customer-scoped job, private storage and re-authorised download path.
      </Notice>
      {canAuditReport ? (
        <div className="flex items-center gap-3">
          <button type="button" className="btn-primary" disabled={request.isPending} onClick={() => request.mutate()}>
            Generate audit log CSV
          </button>
          {request.isError ? (
            <span role="alert" className="text-sm text-red-700">
              {describeError(request.error)}
            </span>
          ) : null}
        </div>
      ) : null}
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable caption={`${customer.code} reports`} columns={columns} rows={data.results} total={data.count} getRowId={(r) => r.id} emptyTitle="No reports generated yet." />
        )}
      </QueryBoundary>
    </div>
  );
}
