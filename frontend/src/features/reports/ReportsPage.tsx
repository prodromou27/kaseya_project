import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, Field, Notice, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  type Customer,
  type Paginated,
  type ReportDefinitionRow,
  type ReportRun,
  type ReportScheduleRow,
  type ReportTemplate,
} from "../../lib/types";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function useTemplates() {
  return useQuery({ queryKey: ["report-templates"], queryFn: () => api.get<ReportTemplate[]>("/report-templates/"), staleTime: 300_000 });
}

function allowedTemplates(templates: ReportTemplate[], customer: Customer) {
  return templates.filter((t) => t.required_capabilities.every((c) => customer.my_capabilities.includes(c)));
}

/** Renders inputs for a template's code-defined, allowlisted filters. */
function FilterInputs({ template, value, onChange }: { template: ReportTemplate; value: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  const entries = Object.entries(template.filters);
  if (entries.length === 0) return <p className="text-xs text-slate-500">This report has no filters.</p>;
  return (
    <div className="flex flex-wrap gap-3">
      {entries.map(([name, f]) => (
        <Field key={name} label={name.replace(/_/g, " ")}>
          {(id) => f.choices ? (
            <select id={id} className="input" value={value[name] ?? ""} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
              <option value="">Any</option>
              {f.choices.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          ) : f.type === "BooleanField" ? (
            <select id={id} className="input" value={value[name] ?? ""} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
              <option value="">Default</option><option value="true">Yes</option><option value="false">No</option>
            </select>
          ) : (
            <input id={id} className="input w-44" maxLength={100} value={value[name] ?? ""}
                   inputMode={f.type === "IntegerField" ? "numeric" : undefined}
                   onChange={(e) => onChange({ ...value, [name]: e.target.value })} />
          )}
        </Field>
      ))}
    </div>
  );
}

function clean(filters: Record<string, string>): Record<string, string | boolean | number> {
  const out: Record<string, string | boolean | number> = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v === "") continue;
    out[k] = v === "true" ? true : v === "false" ? false : /^\d+$/.test(v) && k.endsWith("_days") ? Number(v) : v;
  }
  return out;
}

function NewReport({ customer, templates }: { customer: Customer; templates: ReportTemplate[] }) {
  const queryClient = useQueryClient();
  const [key, setKey] = useState(templates[0]?.key ?? "");
  const [format, setFormat] = useState("csv");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const template = templates.find((t) => t.key === key);
  const request = useMutation({
    mutationFn: () => api.post<ReportRun>(`/customers/${customer.id}/reports/`, { report_type: key, format, filters: clean(filters) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["reports", customer.id] }),
  });
  const save = useMutation({
    mutationFn: (name: string) => api.post(`/customers/${customer.id}/report-definitions/`, { name, report_type: key, format, filters: clean(filters) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["report-definitions", customer.id] }),
  });
  if (!template) return <EmptyState title="No report templates are available to you for this customer." />;
  const submit = (e: FormEvent) => { e.preventDefault(); request.mutate(); };
  return (
    <form onSubmit={submit} aria-label="New report" className="space-y-3 rounded border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Report">{(id) => (
          <select id={id} className="input w-72" value={key} onChange={(e) => { setKey(e.target.value); setFilters({}); }}>
            {templates.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
          </select>)}</Field>
        <Field label="Format">{(id) => (
          <select id={id} className="input" value={format} onChange={(e) => setFormat(e.target.value)}>
            {template.formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
          </select>)}</Field>
      </div>
      <p className="text-xs text-slate-600">{template.description} {template.limitations ? <em>Limitations: {template.limitations}</em> : null}</p>
      <FilterInputs template={template} value={filters} onChange={setFilters} />
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" className="btn-primary" disabled={request.isPending}>Generate</button>
        <button type="button" className="btn-secondary" disabled={save.isPending}
                onClick={() => { const name = window.prompt("Name for this saved report definition?"); if (name) save.mutate(name); }}>
          Save as definition
        </button>
        {request.isError ? <span role="alert" className="text-sm text-red-700">{describeError(request.error)}</span> : null}
        {save.isError ? <span role="alert" className="text-sm text-red-700">{describeError(save.error)}</span> : null}
        {save.isSuccess ? <span role="status" className="text-sm text-emerald-700">Definition saved.</span> : null}
      </div>
    </form>
  );
}

function RunHistory({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const key = ["reports", customer.id];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api.get<Paginated<ReportRun>>(`/customers/${customer.id}/reports/`, undefined, signal),
    refetchInterval: (q) => (q.state.data?.results.some((r) => r.state === "queued" || r.state === "running") ? 2000 : false),
  });
  const regenerate = useMutation({
    mutationFn: (id: string) => api.post<ReportRun>(`/reports/${id}/regenerate/`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key }),
  });
  const columns: ColumnDef<ReportRun, unknown>[] = [
    { header: "Requested", cell: ({ row }) => formatUtc(row.original.created_at) },
    { header: "Report", cell: ({ row }) => <span>{row.original.title ?? row.original.report_type}{row.original.regenerated_from ? <span className="ml-1"><Badge tone="info">regenerated</Badge></span> : null}</span> },
    { header: "Format", cell: ({ row }) => row.original.format.toUpperCase() },
    { header: "By", accessorKey: "requested_by" },
    { header: "State", cell: ({ row }) => <span><Badge tone={statusTone[row.original.state]}>{row.original.state}</Badge>{row.original.error_code ? <span className="ml-1 text-xs text-red-700">{row.original.error_code}</span> : null}</span> },
    { header: "Rows", cell: ({ row }) => row.original.row_count ?? "—" },
    { header: "Data basis", cell: ({ row }) => <Badge tone="neutral">{row.original.data_basis}</Badge> },
    { header: "File", cell: ({ row }) => (
      <span className="flex gap-2">
        {row.original.download_available
          ? <a className="text-sky-800 underline" href={`/api/v1/reports/${row.original.id}/download/`}>Download</a>
          : <span className="text-xs text-slate-400">{row.original.state === "completed" ? "Expired" : "—"}</span>}
        {row.original.state === "completed" && row.original.report_type !== "customer_audit_log" ? (
          <button type="button" className="text-xs text-sky-800 underline" onClick={() => regenerate.mutate(row.original.id)}
                  title="Re-create from the same pinned data snapshot">Regenerate</button>
        ) : null}
      </span>) },
  ];
  return (
    <>
      {regenerate.isError ? <p role="alert" className="text-sm text-red-700">{describeError(regenerate.error)}</p> : null}
      <QueryBoundary query={query}>
        {(data) => <DataTable caption={`${customer.code} reports`} columns={columns} rows={data.results} total={data.count} getRowId={(r) => r.id} emptyTitle="No reports generated yet." />}
      </QueryBoundary>
    </>
  );
}

function ScheduleForm({ customer, definition }: { customer: Customer; definition: ReportDefinitionRow }) {
  const queryClient = useQueryClient();
  const [frequency, setFrequency] = useState("weekly");
  const [time, setTime] = useState("07:00");
  const [weekday, setWeekday] = useState("0");
  const [dom, setDom] = useState("1");
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [recipients, setRecipients] = useState("");
  const create = useMutation({
    mutationFn: () => api.post(`/customers/${customer.id}/report-schedules/`, {
      definition: definition.id, frequency, time_of_day: time, timezone: tz,
      weekday: frequency === "weekly" ? Number(weekday) : null, day_of_month: frequency === "monthly" ? Number(dom) : null,
      recipients: recipients.split(",").map((r) => r.trim()).filter(Boolean),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["report-schedules", customer.id] }),
  });
  return (
    <form aria-label={`Schedule ${definition.name}`} className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <Field label="Frequency">{(id) => <select id={id} className="input" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
        <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>}</Field>
      {frequency === "weekly" ? <Field label="Day">{(id) => <select id={id} className="input" value={weekday} onChange={(e) => setWeekday(e.target.value)}>
        {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>}</Field> : null}
      {frequency === "monthly" ? <Field label="Day of month">{(id) => <input id={id} className="input w-16" type="number" min={1} max={28} value={dom} onChange={(e) => setDom(e.target.value)} />}</Field> : null}
      <Field label="Time">{(id) => <input id={id} className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} />}</Field>
      <Field label="Timezone (IANA)">{(id) => <input id={id} className="input w-40" value={tz} onChange={(e) => setTz(e.target.value)} />}</Field>
      <Field label="Recipients (emails, in-portal)">{(id) => <input id={id} className="input w-64" value={recipients} onChange={(e) => setRecipients(e.target.value)} />}</Field>
      <button type="submit" className="btn-secondary" disabled={create.isPending}>Add schedule</button>
      {create.isError ? <span role="alert" className="w-full text-sm text-red-700">{describeError(create.error)}</span> : null}
    </form>
  );
}

function Definitions({ customer }: { customer: Customer }) {
  const queryClient = useQueryClient();
  const defs = useQuery({ queryKey: ["report-definitions", customer.id], queryFn: () => api.get<Paginated<ReportDefinitionRow>>(`/customers/${customer.id}/report-definitions/`) });
  const schedules = useQuery({ queryKey: ["report-schedules", customer.id], queryFn: () => api.get<Paginated<ReportScheduleRow>>(`/customers/${customer.id}/report-schedules/`) });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/customers/${customer.id}/report-schedules/${id}/`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["report-schedules", customer.id] }),
  });
  return (
    <div className="space-y-4">
      <Notice tone="info">
        Scheduled reports are generated by the portal and delivered <strong>in-portal only</strong> (no e-mail until
        approved, DEC-09). Owner and recipients are re-authorised at every run; anyone who has lost access is dropped.
      </Notice>
      <QueryBoundary query={defs} isEmpty={(d) => d.results.length === 0}
        empty={<EmptyState title="No saved report definitions.">Use “Save as definition” on the New report tab.</EmptyState>}>
        {(d) => (
          <ul className="space-y-3">
            {d.results.map((def) => (
              <li key={def.id} className="rounded border border-slate-200 bg-white p-3">
                <div className="mb-2 text-sm"><strong>{def.name}</strong> · {def.report_type} · {def.format.toUpperCase()}
                  {Object.keys(def.filters).length ? <code className="ml-2 text-xs">{JSON.stringify(def.filters)}</code> : null}</div>
                <ul className="mb-2 space-y-1 text-xs">
                  {(schedules.data?.results ?? []).filter((s) => s.definition === def.id).map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center gap-2">
                      <Badge tone={s.enabled ? "good" : "neutral"}>{s.enabled ? "enabled" : "disabled"}</Badge>
                      {s.frequency} at {s.time_of_day.slice(0, 5)} {s.timezone}
                      {s.weekday !== null ? ` on ${WEEKDAYS[s.weekday]}` : ""}{s.day_of_month ? ` on day ${s.day_of_month}` : ""}
                      · next {formatUtc(s.next_run_at)} · recipients: {s.recipient_emails.join(", ") || "owner only"}
                      {s.enabled ? <button type="button" className="text-red-700 underline" onClick={() => remove.mutate(s.id)}>Remove</button> : null}
                    </li>
                  ))}
                </ul>
                <ScheduleForm customer={customer} definition={def} />
              </li>
            ))}
          </ul>
        )}
      </QueryBoundary>
    </div>
  );
}

function Inbox() {
  const query = useQuery({ queryKey: ["report-inbox"], queryFn: () => api.get<ReportRun[]>("/reports/inbox/") });
  return (
    <QueryBoundary query={query}>
      {(runs) => <DataTable caption="Scheduled reports delivered to me" rows={runs} getRowId={(r) => r.id}
        emptyTitle="No scheduled reports have been delivered to you."
        columns={[
          { header: "Generated", cell: ({ row }) => formatUtc(row.original.completed_at ?? row.original.created_at) },
          { header: "Customer", accessorKey: "customer_code" },
          { header: "Report", cell: ({ row }) => row.original.title ?? row.original.report_type },
          { header: "Format", cell: ({ row }) => row.original.format.toUpperCase() },
          { header: "File", cell: ({ row }) => row.original.download_available
              ? <a className="text-sky-800 underline" href={`/api/v1/reports/${row.original.id}/download/`}>Download</a>
              : <span className="text-xs text-slate-400">{row.original.state}</span> },
        ]} />}
    </QueryBoundary>
  );
}

export function ReportsPage() {
  const { selected } = useCustomers();
  const templates = useTemplates();
  const [tab, setTab] = useState("new");
  const canExport = selected?.my_capabilities.includes(CAP.export) ?? false;
  return (
    <>
      <PageHeader title="Reports" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      <Tabs label="Report sections" active={tab} onChange={setTab} tabs={[
        { id: "new", label: "New report", content: !selected ? <EmptyState title="Select a customer">Reports are generated for exactly one customer.</EmptyState>
            : !canExport ? <EmptyState title="You do not have export permission for this customer." />
            : <QueryBoundary query={templates}>{(t) => <NewReport customer={selected} templates={allowedTemplates(t, selected)} />}</QueryBoundary> },
        { id: "history", label: "History", content: selected && canExport ? <RunHistory customer={selected} /> : <EmptyState title="Select a customer you can export for." /> },
        { id: "scheduled", label: "Definitions & schedules", content: selected && canExport ? <Definitions customer={selected} /> : <EmptyState title="Select a customer you can export for." /> },
        { id: "inbox", label: "Delivered to me", content: <Inbox /> },
      ]} />
    </>
  );
}
