import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { QueryBoundary } from "../../components/States";
import { api } from "../../lib/api";
import { formatUtc } from "../../lib/format";

export type StatusFinding = { level: "ok" | "warn" | "error"; code: string; message: string };
export type SystemStatus = {
  generated_at: string;
  level: "ok" | "warn" | "error";
  worker: { checked: boolean; answering: number | null };
  queue: { queued_stuck: number; running_long: number; oldest_queued_minutes: number };
  syncs_24h: { by_state: Record<string, number>; errors: Record<string, number> };
  stale_sources: { customer: string; integration: string; as_of: string | null }[];
  exports_24h: number;
  failed_logins_24h: number;
  findings: StatusFinding[];
};

export function useSystemStatus(enabled = true) {
  return useQuery({
    queryKey: ["system-status"],
    queryFn: ({ signal }) => api.get<SystemStatus>("/system/status/", undefined, signal),
    enabled,
    refetchInterval: 60_000,
  });
}

const LEVEL = {
  ok: { label: "All good", dot: "bg-emerald-500", box: "border-emerald-200 bg-emerald-50 text-emerald-900" },
  warn: { label: "Needs attention", dot: "bg-amber-500", box: "border-amber-200 bg-amber-50 text-amber-900" },
  error: { label: "Problem", dot: "bg-red-500", box: "border-red-200 bg-red-50 text-red-900" },
} as const;

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-slate-600">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

/** Super admin: is the portal healthy? Worker, queue, sync outcomes, stale data, export and sign-in signals. */
export function SystemStatusPanel() {
  const query = useSystemStatus();
  return (
    <QueryBoundary query={query}>
      {(s) => {
        const runs = Object.values(s.syncs_24h.by_state).reduce((a, b) => a + b, 0);
        const failed = (s.syncs_24h.by_state.failed ?? 0) + (s.syncs_24h.by_state.partial ?? 0);
        return (
          <div className="space-y-4">
            <section aria-label="Overall status" className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 ${LEVEL[s.level].box}`}>
              <span className="inline-flex items-center gap-2 font-semibold">
                <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${LEVEL[s.level].dot}`} />{LEVEL[s.level].label}
              </span>
              <span className="text-xs opacity-80">Checked {formatUtc(s.generated_at)} · refreshes every minute</span>
            </section>
            {s.findings.length ? (
              <ul aria-label="Findings" className="space-y-2">
                {s.findings.map((f) => (
                  <li key={f.code} className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                    <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold ${f.level === "error" ? "bg-red-50 text-red-800 ring-1 ring-inset ring-red-200" : "bg-amber-50 text-amber-900 ring-1 ring-inset ring-amber-200"}`}>
                      {f.level === "error" ? "Problem" : "Check"}
                    </span>
                    <span className="text-slate-800">{f.message}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-slate-600">No problems found.</p>}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Background worker" value={!s.worker.checked ? "—" : s.worker.answering === null ? "Unreachable" : s.worker.answering ? "Running" : "Not answering"} hint={!s.worker.checked ? "Not checked (tasks run inline)" : s.worker.answering ? `${s.worker.answering} answering` : undefined} />
              <Stat label="Queue wait" value={s.queue.oldest_queued_minutes ? `${s.queue.oldest_queued_minutes} min` : "None"} hint="Oldest sync waiting to start" />
              <Stat label="Syncs (24 h)" value={runs} hint={`${failed} failed or paused`} />
              <Stat label="Exports (24 h)" value={s.exports_24h} hint={`${s.failed_logins_24h} failed sign-ins`} />
            </div>
            {s.stale_sources.length ? (
              <section aria-labelledby="stale-h" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <h3 id="stale-h" className="mb-2 text-sm font-semibold text-slate-900">Out-of-date data</h3>
                <ul className="space-y-1 text-sm">
                  {s.stale_sources.map((x) => (
                    <li key={`${x.customer}-${x.integration}`}>
                      <span className="font-medium">{x.customer}</span> <span className="text-slate-500">via {x.integration}</span>{" "}
                      · {x.as_of ? `last data ${formatUtc(x.as_of)}` : "never synced"}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-slate-500">Use Sync now on the customer's pages, or check <Link className="underline" to="/admin?tab=sync-schedules">Sync schedules</Link>.</p>
              </section>
            ) : null}
          </div>
        );
      }}
    </QueryBoundary>
  );
}

/** Dashboard banner for super admins: only shown when something is actually broken. */
export function SystemStatusBanner() {
  const query = useSystemStatus();
  const s = query.data;
  if (!s || s.level !== "error") return null;
  const first = s.findings.find((f) => f.level === "error");
  return (
    <section role="alert" aria-label="System problem" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
      <span><strong>System problem:</strong> {first?.message}</span>
      <Link to="/admin?tab=status" className="font-medium underline">Open system status</Link>
    </section>
  );
}
