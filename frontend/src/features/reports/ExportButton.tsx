import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, describeError } from "../../lib/api";
import type { Customer, ReportRun } from "../../lib/types";

/** Requests an async, customer-scoped report and offers the (re-authorised) download once it is ready. */
export function ExportButton({
  customer,
  reportType,
  label,
  filters,
  formats = ["csv", "xlsx", "pdf"],
}: {
  customer: Customer;
  reportType: string;
  label: string;
  filters: Record<string, string>;
  formats?: string[];
}) {
  const id = useId();
  const [format, setFormat] = useState(formats[0] ?? "csv");
  const [runId, setRunId] = useState<string | null>(null);
  const cleanFilters = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ""));
  const request = useMutation({
    mutationFn: () =>
      api.post<ReportRun>(`/customers/${customer.id}/reports/`, { report_type: reportType, format, filters: cleanFilters }),
    onSuccess: (run) => setRunId(run.id),
  });
  const run = useQuery({
    queryKey: ["report-run", runId],
    queryFn: () => api.get<ReportRun>(`/reports/${runId}/`),
    enabled: runId !== null,
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.state) ? 1500 : false),
  });

  return (
    <span className="flex items-center gap-2 text-sm">
      {formats.length > 1 ? (
        <>
          <label htmlFor={id} className="sr-only">{`${label} format`}</label>
          <select id={id} className="input py-1" value={format} onChange={(e) => setFormat(e.target.value)}>
            {formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
          </select>
        </>
      ) : null}
      <button type="button" className="btn-secondary" disabled={request.isPending} onClick={() => request.mutate()}>
        {label}
      </button>
      <span aria-live="polite">
        {request.isError ? <span className="text-red-700">{describeError(request.error)}</span> : null}
        {run.data?.state === "completed" && run.data.download_available ? (
          <a className="text-sky-800 underline" href={`/api/v1/reports/${run.data.id}/download/`}>
            Download {run.data.format.toUpperCase()} ({run.data.row_count} rows)
          </a>
        ) : null}
        {run.data && ["queued", "running"].includes(run.data.state) ? <span className="text-slate-500">Generating…</span> : null}
        {run.data?.state === "failed" ? <span className="text-red-700">Failed: {run.data.error_code}</span> : null}
      </span>
    </span>
  );
}
