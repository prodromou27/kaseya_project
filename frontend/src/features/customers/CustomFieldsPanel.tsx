import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { CAP, type Customer, type CustomFieldAllow } from "../../lib/types";

/** VSA-18: customer-approved VSA custom field names. Nothing else is fetched or stored. */
export function CustomFieldsPanel({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const base = `/customers/${customer.id}/custom-field-allowlist/`;
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const list = useQuery({ queryKey: ["custom-field-allowlist", customer.id], queryFn: ({ signal }) => api.get<CustomFieldAllow[]>(base, undefined, signal) });
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["custom-field-allowlist", customer.id] });
  const propose = useMutation({ mutationFn: () => api.post<CustomFieldAllow>(base, { name, reason }), onSuccess: () => { setName(""); setReason(""); refresh(); } });
  const act = useMutation({ mutationFn: ({ id, verb }: { id: string; verb: string }) => api.post<CustomFieldAllow>(`${base}${id}/${verb}/`), onSuccess: refresh });
  return (
    <div className="space-y-3">
      <Notice tone="info">
        Only the VSA custom fields named here are read and stored for this customer; values of every other field are never kept.
        Credential-like fields (passwords, keys, tokens, PINs, recovery keys) cannot be approved. A different administrator must approve each name.
      </Notice>
      <QueryBoundary query={list}>
        {(rows) => (
          <DataTable caption="Approved custom fields" rows={rows} getRowId={(r) => r.id} emptyTitle="No custom fields approved: none are collected."
            columns={[
              { header: "Field name", accessorKey: "name" },
              { header: "Reason", accessorKey: "reason" },
              { header: "State", cell: ({ row }) => <Badge tone={statusTone[row.original.state] ?? "neutral"}>{row.original.state}</Badge> },
              { header: "Proposed / reviewed", cell: ({ row }) => <span className="text-xs">{row.original.proposed_by}{row.original.reviewed_by ? ` / ${row.original.reviewed_by}` : ""}</span> },
              { header: "", id: "act", cell: ({ row }) => canManage ? (
                <span className="flex gap-1">
                  {row.original.state === "proposed" ? <>
                    <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "approve" })}>Approve</button>
                    <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "reject" })}>Reject</button>
                  </> : null}
                  {row.original.state === "approved" ? <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "retire" })}>Retire</button> : null}
                </span>) : null },
            ]} />
        )}
      </QueryBoundary>
      {act.isError ? <p role="alert" className="text-sm text-red-700">{describeError(act.error)}</p> : null}
      {canManage ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); propose.mutate(); }}>
          <Field label="Custom field name (exact)">{(id) => <input id={id} className="input" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} required />}</Field>
          <Field label="Reason">{(id) => <input id={id} className="input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} required />}</Field>
          <button type="submit" className="btn-primary" disabled={propose.isPending}>Propose field</button>
          {propose.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(propose.error)}</p> : null}
        </form>
      ) : null}
    </div>
  );
}
