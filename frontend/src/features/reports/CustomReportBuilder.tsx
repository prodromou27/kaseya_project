import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { QueryBoundary } from "../../components/States";
import { Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Customer, ReportRun } from "../../lib/types";
import { LatestRun, RepeatReport } from "./ReportFollowUp";

type FieldType = "text" | "number" | "enum" | "bool" | "date";
type SourceField = { key: string; label: string; type: FieldType; values: string[]; operators: string[] };
type Source = { key: string; label: string; description: string; note: string; default_columns: string[]; fields: SourceField[] };
type Condition = { field: string; op: string; value: string | number | string[] | null };
type Spec = { source: string; columns: string[]; conditions: Condition[]; match: "all" | "any"; sort: string; descending: boolean; title: string };
type Preview = { columns: { key: string; label: string }[]; count: number; rows: (string | number)[][]; note: string };

const OP_LABEL: Record<string, string> = {
  contains: "contains", not_contains: "does not contain", equals: "is", not_equals: "is not", starts_with: "starts with",
  is_empty: "is empty", not_empty: "is not empty", eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤",
  in: "is any of", not_in: "is none of", is_true: "is yes", is_false: "is no", before: "before", after: "after",
  within_days: "within the last (days)", older_than_days: "older than (days)",
};
const NO_VALUE = new Set(["is_empty", "not_empty", "is_true", "is_false"]);
const words = (v: string) => v.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function defaultValue(f: SourceField, op: string): Condition["value"] {
  if (NO_VALUE.has(op)) return null;
  if (f.type === "enum") return [];
  if (f.type === "number" || op === "within_days" || op === "older_than_days") return 0;
  return "";
}

function ConditionRow({ source, c, onChange, onRemove }: { source: Source; c: Condition; onChange: (c: Condition) => void; onRemove: () => void }) {
  const f = source.fields.find((x) => x.key === c.field) ?? source.fields[0];
  if (!f) return null;
  const numeric = f.type === "number" || c.op === "within_days" || c.op === "older_than_days";
  return (
    <li className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 bg-slate-50/60 p-2">
      <Field label="Field">{(id) => (
        <select id={id} className="input w-52" value={c.field} onChange={(e) => {
          const nf = source.fields.find((x) => x.key === e.target.value) ?? f;
          const op = nf.operators[0] ?? "";
          onChange({ field: nf.key, op, value: defaultValue(nf, op) });
        }}>{source.fields.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</select>)}</Field>
      <Field label="Condition">{(id) => (
        <select id={id} className="input w-44" value={c.op} onChange={(e) => onChange({ ...c, op: e.target.value, value: defaultValue(f, e.target.value) })}>
          {f.operators.map((o) => <option key={o} value={o}>{OP_LABEL[o] ?? o}</option>)}
        </select>)}</Field>
      {NO_VALUE.has(c.op) ? null : f.type === "enum" ? (
        <fieldset className="flex max-w-xl flex-wrap gap-x-3 gap-y-1 pb-1.5 text-xs">
          <legend className="sr-only">Values</legend>
          {f.values.map((v) => {
            const list = Array.isArray(c.value) ? c.value : [];
            return <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={list.includes(v)}
              onChange={(e) => onChange({ ...c, value: e.target.checked ? [...list, v] : list.filter((x) => x !== v) })} />{words(v)}</label>;
          })}
        </fieldset>
      ) : (
        <Field label="Value">{(id) => (
          <input id={id} className="input w-48" type={numeric ? "number" : f.type === "date" ? "date" : "text"}
            value={c.value === null || Array.isArray(c.value) ? "" : c.value}
            onChange={(e) => onChange({ ...c, value: numeric ? Number(e.target.value) : e.target.value })} />
        )}</Field>
      )}
      <button type="button" className="btn-secondary" onClick={onRemove}>Remove</button>
    </li>
  );
}

function PreviewTable({ preview }: { preview: Preview }) {
  return (
    <section aria-label="Preview" className="space-y-2">
      <p className="text-sm text-slate-700"><span className="font-semibold">{preview.count}</span> row(s){preview.count > preview.rows.length ? ` · showing the first ${preview.rows.length}` : ""}{preview.note ? <span className="text-slate-500"> · {preview.note}</span> : null}</p>
      {/* A named scroll region needs keyboard focus so wide previews can be scrolled without a mouse. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className="max-h-[50vh] overflow-auto rounded-xl border border-slate-200 bg-white" role="region" aria-label="Preview table" tabIndex={0}>
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">Custom report preview</caption>
          <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600"><tr>{preview.columns.map((c) => <th key={c.key} scope="col" className="px-3 py-2 font-semibold">{c.label}</th>)}</tr></thead>
          <tbody className="divide-y divide-slate-100">
            {preview.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="px-3 py-1.5 align-top">{String(v)}</td>)}</tr>)}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Builder({ customer, sources }: { customer: Customer; sources: Source[] }) {
  const qc = useQueryClient();
  const first = sources[0];
  const [spec, setSpec] = useState<Spec>({ source: first?.key ?? "", columns: first?.default_columns ?? [], conditions: [], match: "all", sort: "", descending: false, title: "" });
  const [format, setFormat] = useState("xlsx");
  const source = sources.find((s) => s.key === spec.source) ?? first;
  const body = () => ({ ...spec, sort: spec.sort || spec.columns[0] || "" });
  const preview = useMutation({ mutationFn: () => api.post<Preview>(`/customers/${customer.id}/custom-reports/preview/`, body()) });
  const generate = useMutation({
    mutationFn: () => api.post<ReportRun>(`/customers/${customer.id}/reports/`, { report_type: "custom", format, filters: body() }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports", customer.id] }),
  });
  if (!source) return null;
  const pickSource = (key: string) => {
    const s = sources.find((x) => x.key === key);
    if (s) { setSpec({ ...spec, source: key, columns: s.default_columns, conditions: [], sort: "" }); preview.reset(); }
  };
  const toggleColumn = (key: string, on: boolean) => setSpec({ ...spec, columns: on ? [...spec.columns, key] : spec.columns.filter((c) => c !== key) });
  const addCondition = () => {
    const f = source.fields[0];
    if (f) setSpec({ ...spec, conditions: [...spec.conditions, { field: f.key, op: f.operators[0] ?? "", value: defaultValue(f, f.operators[0] ?? "") }] });
  };
  const errors = [preview, generate].filter((m) => m.isError);
  return (
    <div className="space-y-4">
      <section aria-labelledby="cr-src" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 id="cr-src" className="mb-2 text-sm font-semibold text-slate-900">1. Data</h2>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" role="radiogroup" aria-label="Data source">
          {sources.map((s) => (
            <button key={s.key} type="button" role="radio" aria-checked={s.key === spec.source} onClick={() => pickSource(s.key)}
              className={`rounded-lg border p-3 text-left text-sm hover:border-sky-400 ${s.key === spec.source ? "border-sky-400 bg-sky-50 ring-1 ring-sky-300" : "border-slate-200"}`}>
              <span className="block font-medium text-slate-900">{s.label}</span>
              <span className="mt-0.5 block text-xs text-slate-600">{s.description}</span>
            </button>
          ))}
        </div>
      </section>

      <section aria-labelledby="cr-cols" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 id="cr-cols" className="mb-2 text-sm font-semibold text-slate-900">2. Columns <span className="font-normal text-slate-500">({spec.columns.length} selected, in this order)</span></h2>
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm" role="group" aria-label="Columns">
          {source.fields.map((f) => (
            <label key={f.key} className="flex items-center gap-1.5"><input type="checkbox" checked={spec.columns.includes(f.key)} onChange={(e) => toggleColumn(f.key, e.target.checked)} />{f.label}</label>
          ))}
        </div>
      </section>

      <section aria-labelledby="cr-filters" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h2 id="cr-filters" className="text-sm font-semibold text-slate-900">3. Filters</h2>
          {spec.conditions.length > 1 ? (
            <label className="flex items-center gap-2 text-sm">Match
              <select className="input py-1" value={spec.match} onChange={(e) => setSpec({ ...spec, match: e.target.value as "all" | "any" })}>
                <option value="all">all conditions</option><option value="any">any condition</option>
              </select>
            </label>
          ) : null}
        </div>
        <ul className="space-y-2">
          {spec.conditions.map((c, i) => <ConditionRow key={i} source={source} c={c}
            onChange={(n) => setSpec({ ...spec, conditions: spec.conditions.map((x, j) => (j === i ? n : x)) })}
            onRemove={() => setSpec({ ...spec, conditions: spec.conditions.filter((_, j) => j !== i) })} />)}
        </ul>
        <button type="button" className="btn-secondary mt-2" onClick={addCondition} disabled={spec.conditions.length >= 20}>Add filter</button>
        {spec.conditions.length === 0 ? <p className="mt-1 text-xs text-slate-500">No filters: every row of this data is included.</p> : null}
      </section>

      <section aria-labelledby="cr-out" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 id="cr-out" className="mb-2 text-sm font-semibold text-slate-900">4. Sort and output</h2>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Sort by">{(id) => (
            <select id={id} className="input w-52" value={spec.sort || spec.columns[0] || ""} onChange={(e) => setSpec({ ...spec, sort: e.target.value })}>
              {source.fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>)}</Field>
          <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={spec.descending} onChange={(e) => setSpec({ ...spec, descending: e.target.checked })} />Descending</label>
          <Field label="Report title (optional)">{(id) => <input id={id} className="input w-64" maxLength={120} value={spec.title} onChange={(e) => setSpec({ ...spec, title: e.target.value })} placeholder={`Custom report: ${source.label}`} />}</Field>
          <Field label="Format">{(id) => (
            <select id={id} className="input" value={format} onChange={(e) => setFormat(e.target.value)}>
              <option value="xlsx">Excel</option><option value="csv">CSV</option><option value="pdf">PDF</option>
            </select>)}</Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className="btn-secondary" disabled={!spec.columns.length || preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? "Loading…" : "Preview"}</button>
          <button type="button" className="btn-primary" disabled={!spec.columns.length || generate.isPending} onClick={() => generate.mutate()}>Generate report</button>
        </div>
        {generate.data ? <div className="mt-2"><LatestRun key={generate.data.id} runId={generate.data.id} /></div> : null}
        {spec.columns.length ? (
          <div className="mt-3">
            <RepeatReport customer={customer} body={{ report_type: "custom", format, filters: body() }} defaultName={spec.title || `Custom report: ${source.label}`} />
          </div>
        ) : null}
        {errors.map((m, i) => <p key={i} role="alert" className="mt-2 text-sm text-red-700">{describeError(m.error)}</p>)}
      </section>

      {preview.data ? <PreviewTable preview={preview.data} /> : null}
    </div>
  );
}

/** Custom report builder: data source, columns, filters, sort; preview, generate, save and schedule. */
export function CustomReportBuilder({ customer }: { customer: Customer }) {
  const sources = useQuery({ queryKey: ["report-sources"], queryFn: ({ signal }) => api.get<Source[]>("/report-sources/", undefined, signal), staleTime: 300_000 });
  return <QueryBoundary query={sources}>{(s) => <Builder key={customer.id} customer={customer} sources={s} />}</QueryBoundary>;
}
