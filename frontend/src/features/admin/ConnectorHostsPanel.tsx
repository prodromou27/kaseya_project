import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { QueryBoundary } from "../../components/States";
import { Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";

type ConnectorHost = { id: string; provider: string; hostname: string; reason: string; added_by: string | null; created_at: string };
type HostList = { results: ConnectorHost[]; deployment: { provider: string; hostname: string }[] };

/** Super admin: VSA X API hostnames the connector may call. Every request re-checks this list. */
export function ConnectorHostsPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["connector-hosts"], queryFn: ({ signal }) => api.get<HostList>("/connector-hosts/", undefined, signal) });
  const [hostname, setHostname] = useState("");
  const [reason, setReason] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["connector-hosts"] });
  const add = useMutation({
    mutationFn: () => api.post<ConnectorHost>("/connector-hosts/", { provider: "vsa_x", hostname, reason }),
    onSuccess: () => {
      setHostname("");
      setReason("");
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/connector-hosts/${id}/`), onSuccess: refresh });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <section aria-label="Allowed API hosts" className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <h3 className="font-semibold">Allowed API hosts</h3>
      <p className="text-xs text-slate-600">
        The connector only calls these VSA X servers (HTTPS, read-only). Add the exact hostname of your VSA server, e.g.{" "}
        <code>yourcompany.vsax.net</code>. Private, internal and IP addresses are always refused.
      </p>
      <QueryBoundary query={query}>
        {(data) => (
          <ul className="divide-y divide-slate-100 text-sm" aria-label="Allowed hosts">
            {data.results.map((h) => (
              <li key={h.id} className="flex flex-wrap items-center gap-2 py-1">
                <code>{h.hostname}</code>
                <span className="text-xs text-slate-500">
                  added by {h.added_by ?? "deleted user"}, {formatUtc(h.created_at)}{h.reason ? ` — ${h.reason}` : ""}
                </span>
                <button type="button" className="btn-secondary ml-auto py-0.5 text-xs" disabled={remove.isPending}
                        onClick={() => { if (window.confirm(`Stop allowing ${h.hostname}?`)) remove.mutate(h.id); }}>
                  Remove
                </button>
              </li>
            ))}
            {data.deployment.filter((d) => d.provider === "vsa_x").map((d) => (
              <li key={`dep-${d.hostname}`} className="flex items-center gap-2 py-1">
                <code>{d.hostname}</code>
                <span className="text-xs text-slate-500">set in the server configuration</span>
              </li>
            ))}
            {!data.results.length && !data.deployment.some((d) => d.provider === "vsa_x") ? (
              <li className="py-1 text-slate-500">No VSA X host allowed yet.</li>
            ) : null}
          </ul>
        )}
      </QueryBoundary>
      <form onSubmit={submit} aria-label="Allow API host" className="flex flex-wrap items-end gap-3">
        <Field label="VSA X hostname">
          {(id) => <input id={id} className="input w-64" required value={hostname} onChange={(e) => setHostname(e.target.value)} placeholder="yourcompany.vsax.net" autoComplete="off" />}
        </Field>
        <Field label="Reason (optional)">
          {(id) => <input id={id} className="input w-64" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <button type="submit" className="btn-primary" disabled={add.isPending}>Allow host</button>
      </form>
      {add.isError ? <p role="alert" className="text-sm text-red-700">{describeError(add.error)}</p> : null}
      {remove.isError ? <p role="alert" className="text-sm text-red-700">{describeError(remove.error)}</p> : null}
    </section>
  );
}
