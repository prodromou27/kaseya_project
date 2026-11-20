import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Customer, ReportDefinitionRow, ReportRun } from "../../lib/types";

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** The report just requested: waits for the file and offers the download right here (no trip to History). */
export function LatestRun({ runId }: { runId: string }) {
  const run = useQuery({
    queryKey: ["report-run", runId],
    queryFn: ({ signal }) => api.get<ReportRun>(`/reports/${runId}/`, undefined, signal),
    refetchInterval: (q) => (!q.state.data || ["queued", "running"].includes(q.state.data.state) ? 1500 : false),
  });
  const r = run.data;
  if (!r) return <p role="status" className="text-sm text-slate-600">Preparing the report…</p>;
  if (r.state === "queued" || r.state === "running") return <p role="status" className="text-sm text-slate-600">Preparing the report…</p>;
  if (r.state === "completed" && r.download_available) {
    return (
      <p role="status" className="flex flex-wrap items-center gap-2 text-sm text-emerald-800">
        Ready{r.row_count !== null && r.row_count !== undefined ? ` (${r.row_count} rows)` : ""}.
        <a className="btn-primary" href={`/api/v1/reports/${r.id}/download/`}>Download {r.format.toUpperCase()}</a>
      </p>
    );
  }
  return <p role="alert" className="text-sm text-red-700">The report could not be created{r.error_code ? `: ${r.error_code}` : ""}.</p>;
}

/** Save the current report and schedule it in one step (definition + schedule, both via the normal APIs). */
export function RepeatReport({ customer, body, defaultName }: { customer: Customer; body: Record<string, unknown>; defaultName: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(defaultName);
  const [frequency, setFrequency] = useState("weekly");
  const [weekday, setWeekday] = useState("0");
  const [dom, setDom] = useState("1");
  const [time, setTime] = useState("07:00");
  const [recipients, setRecipients] = useState("");
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const save = useMutation({
    mutationFn: async (withSchedule: boolean) => {
      const def = await api.post<ReportDefinitionRow>(`/customers/${customer.id}/report-definitions/`, { name, ...body });
      if (!withSchedule) return;
      await api.post(`/customers/${customer.id}/report-schedules/`, {
        definition: def.id, frequency, time_of_day: time, timezone: tz,
        weekday: frequency === "weekly" ? Number(weekday) : null, day_of_month: frequency === "monthly" ? Number(dom) : null,
        recipients: recipients.split(/[,;\s]+/).map((r) => r.trim()).filter(Boolean),
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["report-definitions", customer.id] });
      void queryClient.invalidateQueries({ queryKey: ["report-schedules", customer.id] });
    },
  });
  return (
    <details className="rounded border border-slate-200 bg-slate-50 p-3 text-sm">
      <summary className="cursor-pointer font-semibold">Send this report regularly</summary>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <Field label="Name">{(id) => <input id={id} className="input w-56" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Frequency">{(id) => <select id={id} className="input" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
          <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>}</Field>
        {frequency === "weekly" ? <Field label="Day">{(id) => <select id={id} className="input" value={weekday} onChange={(e) => setWeekday(e.target.value)}>
          {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>}</Field> : null}
        {frequency === "monthly" ? <Field label="Day of month">{(id) => <input id={id} className="input w-16" type="number" min={1} max={28} value={dom} onChange={(e) => setDom(e.target.value)} />}</Field> : null}
        <Field label="Time" hint={tz}>{(id, h) => <input id={id} aria-describedby={h} className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} />}</Field>
        <Field label="Recipients" hint="Portal users' emails; empty = only you. Delivered in the portal.">
          {(id, h) => <input id={id} aria-describedby={h} className="input w-64" value={recipients} onChange={(e) => setRecipients(e.target.value)} />}
        </Field>
        <button type="button" className="btn-primary" disabled={save.isPending || !name.trim()} onClick={() => save.mutate(true)}>Save and schedule</button>
        <button type="button" className="btn-secondary" disabled={save.isPending || !name.trim()} onClick={() => save.mutate(false)}>Save without schedule</button>
      </div>
      {save.isError ? <p role="alert" className="mt-1 text-red-700">{describeError(save.error)}</p> : null}
      {save.isSuccess ? <p role="status" className="mt-1 text-emerald-700">Saved. Manage it under Definitions &amp; schedules.</p> : null}
    </details>
  );
}
