import { useQuery } from "@tanstack/react-query";

import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge } from "../../components/ui";
import { api } from "../../lib/api";
import { formatUtc } from "../../lib/format";

type Row = { asset_id: string; collector: string; state: string; executed_at: string | null; fetched_at: string; values: Record<string, { value: string; type: string }> };

const STATE: Record<string, { label: string; tone: "good" | "warn" | "neutral" }> = {
  collected: { label: "collected", tone: "good" }, never_run: { label: "no successful run", tone: "neutral" }, failed: { label: "could not be read", tone: "warn" },
};

/** Values collected from VSA scripts for one device (only administrator-allowlisted output variables). */
export function DeviceScriptData({ customerId, assetId }: { customerId: string; assetId: string }) {
  const query = useQuery({
    queryKey: ["script-values", customerId, assetId],
    queryFn: ({ signal }) => api.get<{ results: Row[] }>(`/customers/${customerId}/script-values/`, { asset: assetId }, signal),
  });
  return (
    <QueryBoundary query={query} isEmpty={(d) => d.results.length === 0}
      empty={<EmptyState title="No script data for this device.">A super administrator chooses which VSA scripts are read under Settings → Script collectors.</EmptyState>}>
      {(d) => (
        <div className="grid gap-3 md:grid-cols-2">
          {d.results.map((r) => (
            <section key={r.collector} aria-label={r.collector} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-slate-900">{r.collector}</h3>
                <Badge tone={STATE[r.state]?.tone ?? "neutral"}>{STATE[r.state]?.label ?? r.state}</Badge>
              </div>
              {Object.keys(r.values).length ? (
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
                  {Object.entries(r.values).map(([k, v]) => <div key={k} className="contents"><dt className="text-slate-500">{k}</dt><dd className="font-medium text-slate-900">{v.value || "—"}</dd></div>)}
                </dl>
              ) : <p className="text-sm text-slate-500">No values.</p>}
              <p className="mt-2 text-xs text-slate-500">{r.executed_at ? `Script ran ${formatUtc(r.executed_at)} · ` : ""}read {formatUtc(r.fetched_at)}</p>
            </section>
          ))}
        </div>
      )}
    </QueryBoundary>
  );
}
