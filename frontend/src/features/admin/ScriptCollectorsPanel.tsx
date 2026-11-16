import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";

type Script = { integration_instance: string; id: string; name: string; category: string; platforms: string[]; folder: string };
type Collector = { id: string; integration_instance: string; script_external_id: string; script_name: string; label: string; allowed_variables: string[]; enabled: boolean };

/** Super admin: choose VSA scripts whose latest successful run per device is read (allowlisted variables only). */
export function ScriptCollectorsPanel() {
  const qc = useQueryClient();
  const scripts = useQuery({ queryKey: ["automation", "scripts"], queryFn: ({ signal }) => api.get<Script[]>("/automation/scripts/", undefined, signal) });
  const collectors = useQuery({ queryKey: ["script-collectors"], queryFn: ({ signal }) => api.get<Collector[]>("/script-collectors/", undefined, signal) });
  const [script, setScript] = useState("");
  const [label, setLabel] = useState("");
  const [variables, setVariables] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["script-collectors"] });
  const picked = scripts.data?.find((s) => `${s.integration_instance}|${s.id}` === script);
  const add = useMutation({
    mutationFn: () => api.post("/script-collectors/", {
      integration_instance: picked?.integration_instance, script_external_id: picked?.id, label: label || picked?.name,
      allowed_variables: variables.split(",").map((v) => v.trim()).filter(Boolean),
    }),
    onSuccess: () => { setScript(""); setLabel(""); setVariables(""); refresh(); },
  });
  const toggle = useMutation({ mutationFn: (c: Collector) => api.patch(`/script-collectors/${c.id}/`, { enabled: !c.enabled }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/script-collectors/${id}/`), onSuccess: refresh });
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate(); };
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Pick VSA scripts that report something useful (for example BitLocker state, local administrators or uptime) as
        <strong> output variables</strong>. After each sync the portal reads each device's latest successful run and keeps only the
        variables you list. Free-text script output is never stored, and names that look like credentials are refused.
      </p>
      <form onSubmit={submit} aria-label="Add script collector" className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <QueryBoundary query={scripts} isEmpty={(s) => s.length === 0} empty={<p className="text-sm text-slate-500">The script catalog appears after the next successful sync (needs automation permission on the API token).</p>}>
          {(rows) => (
            <Field label="Script">{(id) => (
              <select id={id} className="input w-80" required value={script} onChange={(e) => setScript(e.target.value)}>
                <option value="">Choose a script…</option>
                {rows.map((s) => <option key={`${s.integration_instance}|${s.id}`} value={`${s.integration_instance}|${s.id}`}>{s.name}{s.category ? ` (${s.category})` : ""}</option>)}
              </select>)}</Field>
          )}
        </QueryBoundary>
        <Field label="Label">{(id) => <input id={id} className="input w-48" maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={picked?.name ?? "e.g. BitLocker"} />}</Field>
        <Field label="Output variables to keep" hint="Comma separated, exactly as named in the script">{(id, hint) => <input id={id} aria-describedby={hint} className="input w-72" required value={variables} onChange={(e) => setVariables(e.target.value)} placeholder="BitLockerProtection, LastBoot" />}</Field>
        <button type="submit" className="btn-primary" disabled={add.isPending || !picked}>Add collector</button>
        {add.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(add.error)}</p> : null}
      </form>
      <QueryBoundary query={collectors} isEmpty={(c) => c.length === 0} empty={<EmptyState title="No script collectors yet." />}>
        {(rows) => (
          <ul aria-label="Script collectors" className="space-y-2">
            {rows.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm">
                <span>
                  <span className="font-medium text-slate-900">{c.label}</span> <span className="text-slate-500">· {c.script_name || c.script_external_id}</span>
                  <span className="mt-1 flex flex-wrap gap-1">{c.allowed_variables.map((v) => <Badge key={v} tone="neutral">{v}</Badge>)}{c.enabled ? null : <Badge tone="warn">paused</Badge>}</span>
                </span>
                <span className="flex gap-2">
                  <button type="button" className="btn-secondary" onClick={() => toggle.mutate(c)}>{c.enabled ? "Pause" : "Resume"}</button>
                  <button type="button" className="btn-danger" onClick={() => { if (window.confirm(`Remove collector “${c.label}” and its collected values?`)) remove.mutate(c.id); }}>Remove</button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </QueryBoundary>
    </div>
  );
}
