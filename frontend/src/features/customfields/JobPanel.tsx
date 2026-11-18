import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { QueryBoundary } from "../../components/States";
import { Badge, Notice, type Tone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { formatUtc } from "../../lib/format";
import { CAP, type CfItem, type CfJob, type Customer, type Paginated } from "../../lib/types";

const BUSY = new Set(["previewing", "queued", "running"]);
const DONE = new Set(["completed", "cancelled", "failed", "rejected"]);
const RETRYABLE = new Set(["failed", "unknown", "verification_failed", "verification_pending", "skipped", "cancelled"]);

export const ACTION_TONE: Record<string, Tone> = { assign: "info", update: "warn", skip: "good", blocked: "bad", review: "warn" };
export const RESULT_TONE: Record<string, Tone> = {
  verified: "good", already_correct: "good", failed: "bad", unknown: "bad", verification_failed: "bad",
  verification_pending: "warn", skipped: "neutral", cancelled: "neutral", not_run: "neutral", pending: "neutral", sending: "info",
};
const MATCH_TONE: Record<string, Tone> = { matched: "good", multiple: "warn", not_found: "bad", invalid: "bad", duplicate: "neutral", other_customer: "bad", unsupported: "neutral" };

function base(customer: Customer, jobId: string) {
  return `/customers/${customer.id}/custom-field-jobs/${jobId}`;
}

export function useJob(customer: Customer, jobId: string) {
  return useQuery({
    queryKey: ["cf-job", customer.id, jobId],
    queryFn: ({ signal }) => api.get<CfJob>(`${base(customer, jobId)}/`, undefined, signal),
    refetchInterval: (q) => (q.state.data && BUSY.has(q.state.data.state) ? 2000 : false),
  });
}

function Count({ label, value, tone = "neutral" }: { label: string; value: number | undefined; tone?: Tone }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold tabular-nums"><Badge tone={value ? tone : "neutral"}>{value ?? 0}</Badge></div>
    </div>
  );
}

function current(i: CfItem) {
  if (i.current_source === "unknown") return <span className="text-amber-900">Unknown</span>;
  if (i.current_source === "none") return <span className="text-slate-500">Unassigned</span>;
  if (i.current_value === null) return <span className="text-slate-400">—</span>;
  return <span>{i.current_value || <em className="text-slate-500">(empty)</em>}{i.current_source === "inherited" ? <span className="block text-xs text-slate-500">inherited</span> : null}</span>;
}

function Items({ customer, job, phase }: { customer: Customer; job: CfJob; phase: "match" | "preview" | "result" }) {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const key = phase === "match" ? "match" : phase === "preview" ? "action" : "result";
  const items = useQuery({
    queryKey: ["cf-items", job.id, phase, filter, page, job.state],
    queryFn: ({ signal }) => api.get<Paginated<CfItem>>(`${base(customer, job.id)}/items/`, { page, ...(filter ? { [key]: filter } : {}) }, signal),
    refetchInterval: BUSY.has(job.state) ? 2000 : false,
  });
  const resolve = useMutation({
    mutationFn: (v: { item: string; asset: string | null }) => api.post<CfItem>(`${base(customer, job.id)}/resolve/`, v),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["cf-items", job.id] }); void qc.invalidateQueries({ queryKey: ["cf-job", customer.id, job.id] }); },
  });
  const options = phase === "match"
    ? [["matched", "Matched"], ["multiple", "Multiple matches"], ["not_found", "Not found"], ["duplicate", "Duplicate"], ["invalid", "Invalid"], ["other_customer", "Other customer"], ["unsupported", "Unsupported"]]
    : phase === "preview"
      ? [["assign", "Assign"], ["update", "Update"], ["skip", "Already correct"], ["review", "Requires review"], ["blocked", "Blocked"]]
      : [["verified", "Verified"], ["already_correct", "Already correct"], ["failed", "Failed"], ["unknown", "Unknown outcome"], ["verification_failed", "Verification failed"], ["verification_pending", "Verification pending"], ["skipped", "Skipped"], ["cancelled", "Cancelled"], ["not_run", "Not run"]];
  return (
    <div className="space-y-2">
      <label className="list-label">Show
        <select className="input w-56" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }}>
          <option value="">All lines</option>
          {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <QueryBoundary query={items}>
        {(data) => (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" aria-label={phase === "match" ? "Matched devices" : phase === "preview" ? "Preview of changes" : "Results"}>
              <thead><tr className="text-left text-xs text-slate-500">
                <th className="py-1 pr-3">Input</th><th className="pr-3">Device</th><th className="pr-3">Site / group</th>
                {phase === "match" ? <th className="pr-3">Match</th> : <><th className="pr-3">Current value</th><th className="pr-3">New value</th><th className="pr-3">Action</th></>}
                {phase === "result" ? <><th className="pr-3">Result</th><th className="pr-3">VSA value now</th></> : null}
                <th>Details</th>
              </tr></thead>
              <tbody>
                {data.results.map((i) => (
                  <tr key={i.id} className="border-t border-slate-100 align-top">
                    <td className="py-1 pr-3">{i.input_identifier}{i.input_row ? <span className="block text-xs text-slate-500">row {i.input_row}</span> : null}</td>
                    <td className="pr-3">{i.hostname || "—"}</td>
                    <td className="pr-3 text-xs">{i.site}{i.group ? ` · ${i.group}` : ""}</td>
                    {phase === "match" ? (
                      <td className="pr-3"><Badge tone={MATCH_TONE[i.match_status] ?? "neutral"}>{i.match_label}</Badge>
                        {i.match_status === "multiple" && job.state === "draft" ? (
                          <fieldset className="mt-1 space-y-0.5 text-xs">
                            <legend className="sr-only">Choose the device for {i.input_identifier}</legend>
                            {i.candidates.map((c) => (
                              <label key={c.asset_id} className="flex items-center gap-1">
                                <input type="radio" name={`pick-${i.id}`} onChange={() => resolve.mutate({ item: i.id, asset: c.asset_id })} />
                                {c.hostname} · {c.site} · {c.group}
                              </label>
                            ))}
                          </fieldset>
                        ) : null}
                      </td>
                    ) : (
                      <>
                        <td className="pr-3">{i.match_status === "matched" ? current(i) : "—"}</td>
                        <td className="pr-3">{i.requested_value || job.value}</td>
                        <td className="pr-3">{i.action ? <Badge tone={ACTION_TONE[i.action] ?? "neutral"}>{i.action_label}</Badge> : <span className="text-xs text-slate-500">{i.match_label}</span>}</td>
                      </>
                    )}
                    {phase === "result" ? (
                      <><td className="pr-3"><Badge tone={RESULT_TONE[i.result] ?? "neutral"}>{i.result_label}</Badge></td>
                        <td className="pr-3">{i.final_value ?? "—"}</td></>
                    ) : null}
                    <td className="text-xs text-slate-600">{[i.match_note, i.action_note, i.error_code].filter(Boolean).join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.count > 100 ? (
              <div className="mt-2 flex items-center gap-2 text-sm">
                <button type="button" className="btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <span>Page {page} of {Math.ceil(data.count / 100)}</span>
                <button type="button" className="btn-secondary" disabled={!data.next} onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            ) : null}
          </div>
        )}
      </QueryBoundary>
      {resolve.isError ? <p role="alert" className="text-sm text-red-700">{describeError(resolve.error)}</p> : null}
    </div>
  );
}

/** One job, from match review to verified results. Used by every entry point (selection, list, import, device page). */
export function JobPanel({ customer, jobId, onClose, onRetry }: { customer: Customer; jobId: string; onClose?: () => void; onRetry?: (id: string) => void }) {
  const qc = useQueryClient();
  const me = useMe();
  const job = useJob(customer, jobId);
  const [ack, setAck] = useState(false);
  const [sure, setSure] = useState(false);
  const caps = customer.my_capabilities;
  // Engineers prepare and preview; only administrators (customer.custom_field.approve) apply or retry.
  const canApply = caps.includes(CAP.cfApprove);
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post<CfJob>(`${base(customer, jobId)}/${path}/`, body),
    onSuccess: (data, v) => {
      if (v.path === "retry" && onRetry) { onRetry(data.id); return; }
      void qc.invalidateQueries({ queryKey: ["cf-job", customer.id, jobId] });
      void qc.invalidateQueries({ queryKey: ["cf-items", jobId] });
      void qc.invalidateQueries({ queryKey: ["cf-jobs", customer.id] });
    },
  });
  return (
    <QueryBoundary query={job}>
      {(j) => {
        const c = j.counts;
        const done = DONE.has(j.state);
        const retryable = Object.entries(c.result ?? {}).some(([k, n]) => RETRYABLE.has(k) && n > 0);
        const ownJob = me.email === j.created_by || me.email === j.confirmed_by;
        return (
          <section aria-label="Custom field job" className="space-y-3 rounded border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-semibold">
                Set <span className="font-mono">{j.field_name}</span> = <span className="font-mono">{j.per_device_values ? "(per device)" : j.value}</span>
                <span className="ml-2"><Badge tone={j.state === "completed" ? "good" : j.state === "failed" || j.state === "rejected" ? "bad" : "info"}>{j.state_label}</Badge></span>
              </h3>
              <span className="text-xs text-slate-500">{j.source_label}{j.source_filename ? ` (${j.source_filename})` : ""} · {j.created_by} · {formatUtc(j.created_at)}{onClose ? <> · <button type="button" className="text-sky-800 underline" onClick={onClose}>Close</button></> : null}</span>
            </div>

            {j.state === "draft" ? (
              <>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
                  <Count label="Matched" value={c.match?.matched} tone="good" />
                  <Count label="Multiple matches" value={c.match?.multiple} tone="warn" />
                  <Count label="Not found" value={c.match?.not_found} tone="bad" />
                  <Count label="Duplicate" value={c.match?.duplicate} />
                  <Count label="Invalid / other customer" value={(c.match?.invalid ?? 0) + (c.match?.other_customer ?? 0)} tone="bad" />
                  <Count label="Unsupported (not a workstation)" value={c.match?.unsupported} />
                </div>
                <p className="text-sm text-slate-600">Only matched workstations are changed. Lines with several matching devices are left out until you choose one.</p>
                <Items customer={customer} job={j} phase="match" />
                <button type="button" className="btn-primary" disabled={act.isPending || !caps.includes(CAP.cfAssign)} onClick={() => act.mutate({ path: "preview" })}>Preview changes</button>
              </>
            ) : null}

            {j.state === "previewing" ? <p role="status" className="text-sm">Reading the current values from VSA X…</p> : null}

            {j.state === "previewed" ? (
              <>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                  <Count label="Ready to assign" value={c.action?.assign} tone="info" />
                  <Count label="Ready to update" value={c.action?.update} tone="warn" />
                  <Count label="Already correct" value={c.action?.skip} tone="good" />
                  <Count label="Requires review" value={c.action?.review} tone="warn" />
                  <Count label="Blocked" value={c.action?.blocked} tone="bad" />
                </div>
                <Items customer={customer} job={j} phase="preview" />
                {!j.writes.available ? <Notice tone="warn">Cannot apply yet: {j.writes.reason}</Notice> : null}
                {!canApply ? (
                  <Notice tone="info" title="An administrator applies these changes">
                    You can prepare and preview this job. A customer administrator opens it under Assignment history,
                    checks the preview and applies it.
                  </Notice>
                ) : null}
                {canApply && c.updates ? (
                  <label className="flex items-start gap-2 text-sm">
                    <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                    <span><strong>{c.updates}</strong> device{c.updates === 1 ? " has" : "s have"} a different value set on the device. Overwrite {c.updates === 1 ? "it" : "them"}.</span>
                  </label>
                ) : null}
                {canApply ? (
                  <label className="flex items-start gap-2 text-sm">
                    <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
                    <span>I confirm setting <strong>{j.field_name}</strong> on <strong>{c.to_change ?? 0}</strong> workstation{c.to_change === 1 ? "" : "s"} in VSA X.</span>
                  </label>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {canApply ? (
                    <button type="button" className="btn-primary" disabled={!sure || (Boolean(c.updates) && !ack) || !c.to_change || !j.writes.available || act.isPending}
                            onClick={() => act.mutate({ path: "confirm", body: { confirm: true, acknowledge_overwrite: ack } })}>Apply changes</button>
                  ) : null}
                  <button type="button" className="btn-secondary" disabled={act.isPending} onClick={() => act.mutate({ path: "preview" })}>Preview again</button>
                  <button type="button" className="btn-secondary" disabled={act.isPending} onClick={() => act.mutate({ path: "cancel" })}>Discard</button>
                </div>
              </>
            ) : null}

            {j.state === "awaiting_approval" ? (
              <Notice tone="info">
                Waiting for a different administrator to approve ({c.to_change} devices{j.approval_required ? "" : ""}).
                {caps.includes(CAP.cfApprove) && !ownJob ? (
                  <span className="mt-2 flex gap-2">
                    <button type="button" className="btn-primary" onClick={() => act.mutate({ path: "approve" })}>Approve and run</button>
                    <button type="button" className="btn-danger" onClick={() => act.mutate({ path: "reject" })}>Reject</button>
                  </span>
                ) : null}
              </Notice>
            ) : null}

            {j.state === "queued" || j.state === "running" ? (() => {
              const total = c.to_change ?? 0;
              const left = (c.result?.pending ?? 0) + (c.result?.sending ?? 0);
              const processed = Math.max(0, total - left);
              return (
                <div className="space-y-2">
                  <p role="status" className="text-sm">{j.cancel_requested ? "Stopping after the current device…" : `Applying: ${processed} of ${total} devices processed.`}</p>
                  <div className="h-2 w-full rounded bg-slate-100" aria-hidden="true"><div className="h-2 rounded bg-sky-600" style={{ width: `${total ? (100 * processed) / total : 0}%` }} /></div>
                  {!j.cancel_requested ? <button type="button" className="btn-secondary" onClick={() => act.mutate({ path: "cancel" })}>Cancel remaining devices</button> : null}
                </div>
              );
            })() : null}

            {done ? (
              <>
                {j.error_code ? <Notice tone="warn">Stopped: {j.error_code.replace(/_/g, " ")}.</Notice> : null}
                <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
                  <Count label="Verified" value={c.result?.verified} tone="good" />
                  <Count label="Already correct" value={c.result?.already_correct} tone="good" />
                  <Count label="Failed" value={c.result?.failed} tone="bad" />
                  <Count label="Unknown / not verified" value={(c.result?.unknown ?? 0) + (c.result?.verification_failed ?? 0) + (c.result?.verification_pending ?? 0)} tone="bad" />
                  <Count label="Skipped" value={c.result?.skipped} />
                  <Count label="Cancelled / not run" value={(c.result?.cancelled ?? 0) + (c.result?.not_run ?? 0)} />
                </div>
                <p className="text-xs text-slate-500">"Verified" means the value was read back from VSA X after the change.</p>
                <Items customer={customer} job={j} phase="result" />
                <div className="flex flex-wrap gap-2">
                  {caps.includes(CAP.export) ? <>
                    <a className="btn-secondary" href={`/api/v1${base(customer, j.id)}/report/?type=xlsx`}>Download results (Excel)</a>
                    <a className="btn-secondary" href={`/api/v1${base(customer, j.id)}/report/?type=csv`}>Download results (CSV)</a>
                  </> : null}
                  {retryable && canApply ? <button type="button" className="btn-secondary" onClick={() => act.mutate({ path: "retry" })}>Prepare a new job for the failed devices</button> : null}
                </div>
              </>
            ) : null}
            {act.isError ? <p role="alert" className="text-sm text-red-700">{describeError(act.error)}</p> : null}
          </section>
        );
      }}
    </QueryBoundary>
  );
}
