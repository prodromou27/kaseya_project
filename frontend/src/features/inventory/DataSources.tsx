import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

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

/** Plain-language explanation of the commonest sync outcomes (codes come from the backend). */
const SYNC_ERRORS: Record<string, string> = {
  auth_failed: "VSA X rejected the API credentials. Re-enter them under Settings → Integrations.",
  credential_unavailable: "No usable API credentials. Enter them under Settings → Integrations.",
  egress_blocked: "The VSA host is not allowed or resolves to a private address. Check Allowed API hosts.",
  vendor_unavailable: "VSA X did not respond. The server may be unable to reach it (DNS, firewall or proxy).",
  rate_limited: "VSA X rate limit reached. The sync continues automatically later.",
  retry_budget_exhausted: "VSA X kept failing; the sync gave up. Try again later.",
  row_count_drop_guard: "Far fewer devices than last time, so the previous data was kept. Check the VSA organisation.",
  internal_error: "Unexpected error on the server. An administrator should check the worker logs.",
};
const STUCK_AFTER_MS = 2 * 60 * 1000;

/** Source freshness and sync state. Stale/never-synced data is always shown explicitly, never hidden. */
export function DataSources({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const datasets = useDatasets(customer.id);
  const previousGeneration = useRef<string | null>(null);
  const generationKey = datasets.data?.map((dataset) => `${dataset.mapping_id}:${dataset.generation_id}`).sort().join("|") ?? null;
  useEffect(() => {
    if (generationKey === null) return;
    if (previousGeneration.current !== null && previousGeneration.current !== generationKey) {
      for (const key of ["assets", "software", "os-updates", "device-health", "trends", "lifecycle", "hierarchy"]) {
        void queryClient.invalidateQueries({ queryKey: [key, customer.id] });
      }
    }
    previousGeneration.current = generationKey;
  }, [generationKey, queryClient, customer.id]);
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
      {syncNow.isSuccess ? <p role="status" className="mb-2 text-sm text-slate-600">Sync requested. Status updates below.</p> : null}
      {datasets.data.some((d) => d.last_run?.state === "queued" && Date.now() - Date.parse(d.last_run.created_at) > STUCK_AFTER_MS) ? (
        <p role="alert" className="mb-2 rounded bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-inset ring-amber-200">
          A sync has been waiting for more than two minutes, so the background worker is probably not running. An
          administrator can check it on the server with <code>python manage.py sync_status</code>.
        </p>
      ) : null}
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
                {d.last_run.error_code && SYNC_ERRORS[d.last_run.error_code] ? (
                  <span className={`block ${d.last_run.state === "partial" ? "text-amber-800" : "text-red-700"}`}>
                    {d.last_run.state === "partial" ? "Paused: " : ""}
                    {SYNC_ERRORS[d.last_run.error_code]}
                    {d.last_run.state === "partial" ? " It resumes automatically from where it stopped; the previous data stays visible meanwhile." : ""}
                  </span>
                ) : null}
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
