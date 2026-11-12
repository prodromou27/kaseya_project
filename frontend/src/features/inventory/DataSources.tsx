import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState, LoadingState } from "../../components/States";
import { Badge, Notice, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import { CAP, PROVIDER_LABEL, type Customer, type DatasetStatus } from "../../lib/types";

export function useDatasets(customerId: string) {
  return useQuery({
    queryKey: ["datasets", customerId],
    queryFn: ({ signal }) => api.get<DatasetStatus[]>(`/customers/${customerId}/datasets/`, undefined, signal),
    refetchInterval: (q) =>
      q.state.data?.some((d) => d.last_run && ["queued", "running"].includes(d.last_run.state)) ? 2000 : false,
  });
}

/** Source freshness and sync state. Stale/never-synced data is always shown explicitly, never hidden. */
export function DataSources({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const datasets = useDatasets(customer.id);
  const canSync = customer.my_capabilities.includes(CAP.sync);
  const syncNow = useMutation({
    mutationFn: () => api.post<unknown>(`/customers/${customer.id}/sync-runs/`),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["datasets", customer.id] });
      void queryClient.invalidateQueries({ queryKey: ["assets", customer.id] });
      void queryClient.invalidateQueries({ queryKey: ["software", customer.id] });
    },
  });

  if (datasets.isPending) return <LoadingState label="Checking data sources…" />;
  if (datasets.isError) return <ErrorState error={datasets.error} onRetry={() => void datasets.refetch()} />;
  if (datasets.data.length === 0) {
    return (
      <Notice tone="warn">
        No approved source mapping for this customer, so no inventory can be collected. A customer administrator can
        propose a mapping; a super administrator must approve it.
      </Notice>
    );
  }
  return (
    <section aria-labelledby="sources-heading" className="mb-4 rounded border border-slate-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 id="sources-heading" className="text-sm font-semibold text-slate-700">
          Data sources
        </h2>
        {canSync ? (
          <button type="button" className="btn-secondary" disabled={syncNow.isPending} onClick={() => syncNow.mutate()}>
            {syncNow.isPending ? "Requesting…" : "Sync now (read-only)"}
          </button>
        ) : null}
      </div>
      {syncNow.isError ? (
        <p role="alert" className="mb-2 text-sm text-red-700">
          {describeError(syncNow.error)}
        </p>
      ) : null}
      <ul className="space-y-1 text-sm">
        {datasets.data.map((d) => (
          <li key={d.mapping_id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{d.integration.name}</span>
            <span className="text-xs text-slate-500">
              {PROVIDER_LABEL[d.integration.provider]} · org {d.external_org_id}
            </span>
            <Badge tone={statusTone[d.status]}>{d.status.replace("_", " ")}</Badge>
            {d.data_basis ? <Badge tone={statusTone[d.data_basis]}>{d.data_basis}</Badge> : null}
            <span className="text-xs text-slate-600">
              {d.as_of ? `as of ${formatUtc(d.as_of)} · ${d.row_count} devices` : "no published dataset"}
            </span>
            {d.last_run ? (
              <span className="text-xs text-slate-500">
                last run: <Badge tone={statusTone[d.last_run.state]}>{d.last_run.state}</Badge>
                {d.last_run.error_code ? ` (${d.last_run.error_code})` : ""}
                {d.last_run.quarantined ? ` · ${d.last_run.quarantined} quarantined` : ""}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {datasets.data.some((d) => d.data_basis === "fixture") ? (
        <p className="mt-2 text-xs text-sky-800">
          Fixture data: synthetic demo records from an offline fixture source — not a live VSA X tenant.
        </p>
      ) : null}
    </section>
  );
}
