import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import { PROVIDER_LABEL, type Customer, type IntegrationOption, type Paginated, type SourceMapping } from "../../lib/types";

export const mappingColumns: ColumnDef<SourceMapping, unknown>[] = [
  {
    header: "Source",
    cell: ({ row }) => (
      <span>
        {row.original.integration.name}
        {row.original.integration.is_fixture ? (
          <span className="ml-1">
            <Badge tone="info">fixture</Badge>
          </span>
        ) : null}
        <span className="block text-xs text-slate-500">{PROVIDER_LABEL[row.original.integration.provider]}</span>
      </span>
    ),
  },
  { header: "External org ID", accessorKey: "external_org_id", cell: ({ getValue }) => <code className="text-xs">{String(getValue())}</code> },
  { header: "Name (informational)", accessorKey: "external_org_name", cell: ({ getValue }) => String(getValue() || "—") },
  { header: "Status", accessorKey: "mapping_status", cell: ({ getValue }) => <Badge tone={statusTone[String(getValue())]}>{String(getValue())}</Badge> },
  { header: "Proposed by", accessorKey: "proposed_by", cell: ({ getValue }) => String(getValue() ?? "—") },
  {
    header: "Reviewed",
    cell: ({ row }) => (row.original.reviewed_by ? `${row.original.reviewed_by}, ${formatUtc(row.original.reviewed_at)}` : "Not reviewed"),
  },
];

export function MappingsPanel({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const path = `/customers/${customer.id}/mappings/`;
  const key = ["mappings", customer.id];
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => api.get<Paginated<SourceMapping>>(path, undefined, signal) });
  const options = useQuery({ queryKey: ["integration-options"], queryFn: () => api.get<IntegrationOption[]>("/integrations/options/") });
  const [integration, setIntegration] = useState("");
  const [externalId, setExternalId] = useState("");
  const [externalName, setExternalName] = useState("");
  const propose = useMutation({
    mutationFn: () =>
      api.post<SourceMapping>(path, { integration_instance: integration, external_org_id: externalId, external_org_name: externalName }),
    onSuccess: () => {
      setExternalId("");
      setExternalName("");
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    propose.mutate();
  };

  return (
    <div className="space-y-4">
      <Notice tone="warn">
        Only <strong>approved</strong> mappings route source data to this customer. Proposals are reviewed by a super
        administrator. Match on the vendor organisation <em>ID</em>, never on display name.
      </Notice>
      <form onSubmit={submit} aria-label="Propose source mapping" className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
        <Field label="Integration">
          {(id) => (
            <select id={id} className="input w-64" required value={integration} onChange={(e) => setIntegration(e.target.value)}>
              <option value="">{options.isPending ? "Loading…" : "Select…"}</option>
              {(options.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} ({PROVIDER_LABEL[o.provider]}
                  {o.is_fixture ? ", fixture" : ""})
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="External organisation ID">
          {(id) => <input id={id} className="input w-48" required maxLength={128} value={externalId} onChange={(e) => setExternalId(e.target.value)} />}
        </Field>
        <Field label="External name (optional)">
          {(id) => <input id={id} className="input w-56" maxLength={255} value={externalName} onChange={(e) => setExternalName(e.target.value)} />}
        </Field>
        <button type="submit" className="btn-primary" disabled={propose.isPending}>
          Propose mapping
        </button>
        {propose.isError ? (
          <p role="alert" className="w-full text-sm text-red-700">
            {describeError(propose.error)}
          </p>
        ) : null}
      </form>
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable
            caption={`${customer.code} source mappings`}
            columns={mappingColumns}
            rows={data.results}
            total={data.count}
            getRowId={(m) => m.id}
            emptyTitle="No source mappings yet."
            emptyHint="Without an approved mapping, no vendor data can be attributed to this customer."
          />
        )}
      </QueryBoundary>
    </div>
  );
}
