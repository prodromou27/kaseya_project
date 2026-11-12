import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import type { Paginated, SourceMapping } from "../../lib/types";

type SyncScheduleRow = {
  id: string;
  mapping: string;
  customer: { id: string; code: string };
  integration: string;
  external_org_id: string;
  interval_hours: number;
  enabled: boolean;
  next_run_at: string;
  last_run_at: string | null;
};

export function SyncSchedulesPanel() {
  const queryClient = useQueryClient();
  const schedules = useQuery({ queryKey: ["sync-schedules"], queryFn: () => api.get<Paginated<SyncScheduleRow>>("/sync-schedules/") });
  const approved = useQuery({
    queryKey: ["mapping-review", "approved"],
    queryFn: () => api.get<Paginated<SourceMapping>>("/mappings/", { status: "approved" }),
  });
  const [mapping, setMapping] = useState("");
  const [hours, setHours] = useState("24");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["sync-schedules"] });
  const create = useMutation({ mutationFn: () => api.post("/sync-schedules/", { mapping, interval_hours: Number(hours) }), onSuccess: refresh });
  const toggle = useMutation({ mutationFn: (s: SyncScheduleRow) => api.patch(`/sync-schedules/${s.id}/`, { enabled: !s.enabled }), onSuccess: refresh });
  const scheduled = new Set((schedules.data?.results ?? []).map((s) => s.mapping));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <div className="space-y-3">
      <Notice tone="info">
        Scheduled syncs are read-only collections run by the worker (Celery Beat). Only approved mappings can be
        scheduled; a mapping revoked later is skipped and audited.
      </Notice>
      <form onSubmit={submit} aria-label="Add sync schedule" className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
        <Field label="Approved mapping">
          {(id) => (
            <select id={id} className="input w-80" required value={mapping} onChange={(e) => setMapping(e.target.value)}>
              <option value="">Select…</option>
              {(approved.data?.results ?? []).filter((m) => !scheduled.has(m.id)).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.customer.code} · {m.integration.name} · org {m.external_org_id}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Every (hours)">
          {(id) => <input id={id} className="input w-20" type="number" min={1} max={168} value={hours} onChange={(e) => setHours(e.target.value)} />}
        </Field>
        <button type="submit" className="btn-primary" disabled={create.isPending}>Add</button>
        {create.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(create.error)}</p> : null}
      </form>
      <QueryBoundary query={schedules}>
        {(d) => (
          <DataTable caption="Sync schedules" rows={d.results} getRowId={(r) => r.id} emptyTitle="No sync schedules."
            columns={[
              { header: "Customer", cell: ({ row }) => row.original.customer.code },
              { header: "Source", cell: ({ row }) => `${row.original.integration} · org ${row.original.external_org_id}` },
              { header: "Interval", cell: ({ row }) => `${row.original.interval_hours} h` },
              { header: "Next run", cell: ({ row }) => formatUtc(row.original.next_run_at) },
              { header: "Last run", cell: ({ row }) => formatUtc(row.original.last_run_at) },
              { header: "Status", cell: ({ row }) => <Badge tone={row.original.enabled ? "good" : "neutral"}>{row.original.enabled ? "enabled" : "disabled"}</Badge> },
              { header: "", id: "act", cell: ({ row }) => (
                  <button type="button" className="btn-secondary" onClick={() => toggle.mutate(row.original)}>
                    {row.original.enabled ? "Disable" : "Enable"}
                  </button>
                ) },
            ]} />
        )}
      </QueryBoundary>
    </div>
  );
}
