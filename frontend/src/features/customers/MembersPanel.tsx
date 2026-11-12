import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { formatUtc } from "../../lib/format";
import type { Customer, Membership, Paginated } from "../../lib/types";

type Role = Membership["role"];

export function MembersPanel({ customer }: { customer: Customer }) {
  const me = useMe();
  const queryClient = useQueryClient();
  const key = ["memberships", customer.id];
  const path = `/customers/${customer.id}/memberships/`;
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => api.get<Paginated<Membership>>(path, undefined, signal) });
  const grantableRoles: Role[] = me.is_super_admin ? ["admin", "engineer", "viewer"] : ["engineer", "viewer"];

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [canExport, setCanExport] = useState(false);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });

  const grant = useMutation({
    mutationFn: () => api.post<Membership>(path, { email, role, can_export: canExport }),
    onSuccess: () => {
      setEmail("");
      void invalidate();
    },
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.del<undefined>(`${path}${id}/`), onSuccess: () => void invalidate() });

  const columns: ColumnDef<Membership, unknown>[] = [
    { header: "User", cell: ({ row }) => row.original.user.display_name || row.original.user.email },
    { header: "Email", cell: ({ row }) => row.original.user.email },
    { header: "Role", accessorKey: "role" },
    { header: "Export", cell: ({ row }) => (row.original.role === "viewer" ? (row.original.can_export ? "Granted" : "No") : "By role") },
    { header: "Granted", cell: ({ row }) => `${formatUtc(row.original.granted_at)}${row.original.granted_by ? ` by ${row.original.granted_by}` : ""}` },
    {
      header: "Actions",
      cell: ({ row }) => {
        const m = row.original;
        const allowed = m.user.id !== me.id && (me.is_super_admin || m.role !== "admin");
        return allowed ? (
          <button
            type="button"
            className="btn-danger"
            disabled={revoke.isPending}
            onClick={() => {
              if (window.confirm(`Revoke ${m.user.email}'s access to ${customer.code}?`)) revoke.mutate(m.id);
            }}
          >
            Revoke
          </button>
        ) : (
          <span className="text-xs text-slate-400">—</span>
        );
      },
    },
  ];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    grant.mutate();
  };

  return (
    <div className="space-y-4">
      <form onSubmit={submit} aria-label="Grant access" className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
        <Field label="User email" hint="The user must already exist (SSO-provisioned or created by a super administrator).">
          {(id, hint) => (
            <input id={id} aria-describedby={hint} className="input w-72" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          )}
        </Field>
        <Field label="Role">
          {(id) => (
            <select id={id} className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {grantableRoles.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          )}
        </Field>
        {role === "viewer" ? (
          <label className="flex items-center gap-2 pb-1.5 text-sm">
            <input type="checkbox" checked={canExport} onChange={(e) => setCanExport(e.target.checked)} />
            Allow export
          </label>
        ) : null}
        <button type="submit" className="btn-primary" disabled={grant.isPending}>
          Grant access
        </button>
        {grant.isError ? (
          <p role="alert" className="w-full text-sm text-red-700">
            {describeError(grant.error)}
          </p>
        ) : null}
      </form>
      {revoke.isError ? (
        <p role="alert" className="text-sm text-red-700">
          {describeError(revoke.error)}
        </p>
      ) : null}
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable caption={`${customer.code} members`} columns={columns} rows={data.results} total={data.count} getRowId={(m) => m.id} emptyTitle="No active members." />
        )}
      </QueryBoundary>
    </div>
  );
}
