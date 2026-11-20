import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { QueryBoundary } from "../../components/States";
import { Badge, Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Customer } from "../../lib/types";

type PlanDevice = { asset_id: string; hostname: string; basis?: string; evidence?: string[]; candidates?: string[] };
type Destination = { id: string; external_id: string; name: string; site_external_id: string; site_name: string; devices: PlanDevice[] };
export type Plan = {
  is_onboarding: boolean; destinations: Destination[]; ambiguous: PlanDevice[]; unmatched: PlanDevice[];
  devices: number; truncated: boolean; suggestion_note: string;
};

const BASIS: Record<string, string> = { approved_subnet: "Approved subnet", observed_subnet: "Observed subnet", naming: "Name" };

function csvCell(v: string) {
  const safe = /^[=+\-@]/.test(v) ? `'${v}` : v; // never let a spreadsheet evaluate a hostname
  return `"${safe.replace(/"/g, '""')}"`;
}

function downloadCsv(plan: Plan, groupLabel: string) {
  const lines = [["destination_site", "destination_group", "destination_group_id", "device", "evidence"].join(",")];
  for (const d of plan.destinations) {
    for (const dev of d.devices) lines.push([d.site_name || d.site_external_id, d.name, d.external_id, dev.hostname, (dev.evidence ?? []).join(" | ")].map(csvCell).join(","));
  }
  for (const dev of plan.ambiguous) lines.push(["", "NEEDS DECISION", "", dev.hostname, (dev.candidates ?? []).join(" or ")].map(csvCell).join(","));
  const blob = new Blob([`\uFEFF${lines.join("\r\n")}\r\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `move-list-${groupLabel}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Propose every ticked device of one destination for approval (one normal proposal per device). */
function ProposeAll({ customer, destination }: { customer: Customer; destination: Destination }) {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(destination.devices.map((d) => d.asset_id)));
  const [reason, setReason] = useState(`Onboarding: move to ${destination.name} (subnet/name evidence)`);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: number; problems: string[] } | null>(null);
  const toggle = (id: string) => setChosen((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const run = async () => {
    setBusy(true);
    let ok = 0;
    const problems: string[] = [];
    for (const dev of destination.devices.filter((d) => chosen.has(d.asset_id))) {
      try {
        await api.post(`/customers/${customer.id}/group-moves/`, { asset: dev.asset_id, target_group: destination.id, reason });
        ok += 1;
      } catch (error) {
        problems.push(`${dev.hostname}: ${describeError(error)}`);
      }
      setResult({ ok, problems: [...problems] });
    }
    setBusy(false);
    void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] });
  };
  return (
    <div className="mt-2 space-y-2 border-t border-slate-100 pt-2">
      <ul className="max-h-72 space-y-1 overflow-auto text-sm">
        {destination.devices.map((dev) => (
          <li key={dev.asset_id} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-slate-100 pt-1">
            <label className="flex items-center gap-1">
              <input type="checkbox" aria-label={`Include ${dev.hostname}`} checked={chosen.has(dev.asset_id)} onChange={() => toggle(dev.asset_id)} />
              <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${dev.asset_id}?tab=operations`}>{dev.hostname}</Link>
            </label>
            <span className="flex items-center gap-1 text-xs text-slate-600">
              <Badge tone={dev.basis === "naming" ? "neutral" : "info"}>{BASIS[dev.basis ?? ""] ?? dev.basis}</Badge>
              <span className="max-w-xs truncate" title={(dev.evidence ?? []).join("\n")}>{dev.evidence?.[0]}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Reason" hint="At least 10 characters; another administrator approves.">
          {(id, h) => <input id={id} aria-describedby={h} className="input w-72" minLength={10} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <button type="button" className="btn-primary" disabled={busy || !chosen.size || reason.trim().length < 10} onClick={() => void run()}>
          {busy ? "Proposing…" : `Propose moving ${chosen.size} device${chosen.size === 1 ? "" : "s"}`}
        </button>
      </div>
      {result ? (
        <div role="status" className="text-sm">
          {result.ok ? <p className="text-emerald-800">{result.ok} proposal(s) sent for approval. <Link className="text-sky-800 underline" to="/group-moves">Open approvals</Link></p> : null}
          {result.problems.length ? <ul className="text-xs text-red-700">{result.problems.map((m) => <li key={m}>{m}</li>)}</ul> : null}
        </div>
      ) : null}
    </div>
  );
}

/** Onboarding devices grouped by their clearly best destination: "move these N devices to group X at site Y". */
export function DestinationPlan({ customer, groupId, instance }: { customer: Customer; groupId: string; instance: string }) {
  const query = useQuery({
    queryKey: ["group-destination-plan", customer.id, instance, groupId],
    queryFn: ({ signal }) => api.get<Plan>(`/customers/${customer.id}/groups/${groupId}/suggestions/plan/`, { instance }, signal),
  });
  const canPropose = customer.my_capabilities.includes("customer.group_move.propose");
  return (
    <QueryBoundary query={query}>
      {(plan) => (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-700">
              <strong>{plan.devices}</strong> device(s) in this onboarding group: {plan.destinations.reduce((n, d) => n + d.devices.length, 0)} with a clear destination,
              {" "}{plan.ambiguous.length} needing a decision, {plan.unmatched.length} without evidence.
            </p>
            {plan.destinations.length || plan.ambiguous.length ? (
              <button type="button" className="btn-secondary" onClick={() => downloadCsv(plan, groupId)}>Download move list (CSV)</button>
            ) : null}
          </div>
          {plan.truncated ? <p className="text-xs text-amber-800">Only the first 2,000 devices are planned; use the per-device view to search the rest.</p> : null}
          <div className="grid gap-3 lg:grid-cols-2">
            {plan.destinations.map((d) => (
              <section key={d.external_id} aria-label={`Move to ${d.name}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-slate-900">
                  Move {d.devices.length} device(s) to <span className="text-sky-800">{d.name}</span>
                </h3>
                <p className="mb-2 text-xs text-slate-500">Site {d.site_name || d.site_external_id || "not reported"} · group ID {d.external_id}</p>
                {canPropose && d.id ? <ProposeAll customer={customer} destination={d} /> : (
                <ul className="max-h-72 space-y-1 overflow-auto text-sm">
                  {d.devices.map((dev) => (
                    <li key={dev.asset_id} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-slate-100 pt-1">
                      <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${dev.asset_id}?tab=operations`}>{dev.hostname}</Link>
                      <span className="flex items-center gap-1 text-xs text-slate-600">
                        <Badge tone={dev.basis === "naming" ? "neutral" : "info"}>{BASIS[dev.basis ?? ""] ?? dev.basis}</Badge>
                        <span className="max-w-xs truncate" title={(dev.evidence ?? []).join("\n")}>{dev.evidence?.[0]}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                )}
              </section>
            ))}
          </div>
          {plan.ambiguous.length ? (
            <section aria-label="Needs a decision" className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
              <h3 className="mb-2 text-sm font-semibold text-amber-900">Needs a decision ({plan.ambiguous.length})</h3>
              <ul className="space-y-1 text-sm">
                {plan.ambiguous.map((dev) => <li key={dev.asset_id}><Link className="font-medium text-sky-800 hover:underline" to={`/assets/${dev.asset_id}?tab=operations`}>{dev.hostname}</Link> <span className="text-xs text-slate-600">could go to {(dev.candidates ?? []).join(" or ")}</span></li>)}
              </ul>
            </section>
          ) : null}
          {plan.unmatched.length ? (
            <details className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
              <summary className="cursor-pointer font-semibold text-slate-900">No evidence yet ({plan.unmatched.length})</summary>
              <p className="mt-1 text-xs text-slate-500">No approved or observed subnet and no matching name start. Approve subnets for destination groups to improve this.</p>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">{plan.unmatched.map((dev) => <li key={dev.asset_id}><Link className="text-sky-800 hover:underline" to={`/assets/${dev.asset_id}?tab=operations`}>{dev.hostname}</Link></li>)}</ul>
            </details>
          ) : null}
          <p className="text-xs text-slate-500">{plan.suggestion_note}</p>
        </div>
      )}
    </QueryBoundary>
  );
}
