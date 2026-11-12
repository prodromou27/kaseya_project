import { useQuery } from "@tanstack/react-query";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Notice } from "../../components/ui";
import { api } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import type { Paginated, QuarantineRow } from "../../lib/types";

export function QuarantinePanel() {
  const query = useQuery({ queryKey: ["quarantine"], queryFn: () => api.get<Paginated<QuarantineRow>>("/sync-quarantine/", { page_size: 200 }) });
  return (
    <div className="space-y-3">
      <Notice tone="info">
        Source records that could not be safely attributed to a customer (organisation mismatch, ID conflict) or failed
        validation. They are never shown in customer views or reports. Only minimal identifiers are retained.
      </Notice>
      <QueryBoundary query={query}>
        {(data) => <DataTable caption="Quarantined source records" rows={data.results} total={data.count} getRowId={(r) => r.id}
          emptyTitle="Nothing quarantined." columns={[
            { header: "When", cell: ({ row }) => formatUtc(row.original.created_at) },
            { header: "Integration", accessorKey: "integration" },
            { header: "Reason", cell: ({ row }) => <Badge tone="warn">{row.original.reason}</Badge> },
            { header: "External ID", cell: ({ row }) => <code className="text-xs">{row.original.external_id || "—"}</code> },
            { header: "Source org", accessorKey: "external_org_id" },
            { header: "Name", cell: ({ row }) => row.original.snapshot.Name || "—" },
          ]} />}
      </QueryBoundary>
    </div>
  );
}
