import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { DataTable } from "../../components/DataTable";
import { SelectCustomer } from "../../components/SelectCustomer";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { CAP, type Customer, type Paginated } from "../../lib/types";
import {
  RULE_PARAMS, STATE_LABEL, STATE_TONE,
  type Baseline, type BaselineResults, type BaselineRule, type DeviceResult, type Overview, type RuleKind, type RuleState, type Severity,
} from "./ComplianceApi";

const base = (c: Customer) => `/customers/${c.id}/compliance-baselines/`;
const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
const SEVERITY_TONE: Record<Severity, "bad" | "warn" | "neutral"> = { high: "bad", medium: "warn", low: "neutral" };

function ScoreBar({ totals }: { totals: Record<RuleState, number> }) {
  const all = totals.pass + totals.fail + totals.unknown;
  if (!all) return null;
  const w = (n: number) => `${(100 * n) / all}%`;
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
      <span className="bg-emerald-500" style={{ width: w(totals.pass) }} />
      <span className="bg-red-500" style={{ width: w(totals.fail) }} />
      <span className="bg-amber-400" style={{ width: w(totals.unknown) }} />
    </div>
  );
}

function Totals({ totals }: { totals: Record<RuleState, number> }) {
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600">
      <span><span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500" />{totals.pass} compliant</span>
      <span><span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />{totals.fail} not compliant</span>
      <span><span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />{totals.unknown} unknown</span>
    </span>
  );
}

// ------------------------------------------------------------------------------------------------ editor

const EMPTY: Omit<Baseline, "id" | "created_by" | "created_at" | "updated_at"> = {
  name: "", description: "", enabled: true, scope_device_type: "", scope_site_external_id: "", scope_group_external_id: "", rules: [],
};

type CollectorOption = { id: string; label: string; allowed_variables: string[] };

/** Script value rule: collector, variable, comparison and value (collectors come from the customer's sources). */
function ScriptValueParams({ rule, collectors, onChange }: { rule: BaselineRule; collectors: CollectorOption[]; onChange: (r: BaselineRule) => void }) {
  const set = (key: string, value: string) => onChange({ ...rule, params: { ...rule.params, [key]: value } });
  const picked = collectors.find((c) => c.id === rule.params.collector);
  if (!collectors.length) return <p className="pb-2 text-xs text-slate-500">No script collectors for this customer yet (Settings → Script collectors).</p>;
  return (
    <>
      <Field label="Collector">{(id) => (
        <select id={id} className="input w-48" required value={String(rule.params.collector ?? "")} onChange={(e) => onChange({ ...rule, params: { ...rule.params, collector: e.target.value, variable: "" } })}>
          <option value="">Choose…</option>{collectors.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>)}</Field>
      <Field label="Variable">{(id) => (
        <select id={id} className="input w-48" required value={String(rule.params.variable ?? "")} onChange={(e) => set("variable", e.target.value)}>
          <option value="">Choose…</option>{(picked?.allowed_variables ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
        </select>)}</Field>
      <Field label="Comparison">{(id) => (
        <select id={id} className="input" value={String(rule.params.op ?? "equals")} onChange={(e) => set("op", e.target.value)}>
          <option value="equals">is</option><option value="not_equals">is not</option><option value="contains">contains</option><option value="at_least">is at least</option>
        </select>)}</Field>
      <Field label="Value">{(id) => <input id={id} className="input w-40" required value={String(rule.params.value ?? "")} onChange={(e) => set("value", e.target.value)} />}</Field>
    </>
  );
}

function RuleEditor({ rule, kinds, collectors, onChange, onRemove }: {
  rule: BaselineRule; kinds: { kind: RuleKind; label: string }[]; collectors: CollectorOption[]; onChange: (r: BaselineRule) => void; onRemove: () => void;
}) {
  return (
    <li className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
      <Field label="Rule">{(id) => (
        <select id={id} className="input w-72" value={rule.kind} onChange={(e) => onChange({ ...rule, kind: e.target.value as RuleKind, params: e.target.value === "script_value" ? { op: "equals" } : {} })}>
          {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
        </select>)}</Field>
      {rule.kind === "script_value" ? <ScriptValueParams rule={rule} collectors={collectors} onChange={onChange} /> : null}
      {(RULE_PARAMS[rule.kind] ?? []).map((p) => (
        <Field key={p.key} label={p.label}>{(id) => (
          <input id={id} className="input w-48" type={p.type} required={!p.optional} placeholder={p.placeholder}
            value={rule.params[p.key] ?? ""}
            onChange={(e) => onChange({ ...rule, params: { ...rule.params, [p.key]: p.type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value } })} />
        )}</Field>
      ))}
      <Field label="Severity">{(id) => (
        <select id={id} className="input" value={rule.severity} onChange={(e) => onChange({ ...rule, severity: e.target.value as Severity })}>
          <option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
        </select>)}</Field>
      <button type="button" className="btn-secondary" onClick={onRemove}>Remove</button>
    </li>
  );
}

function BaselineForm({ customer, initial, kinds, onDone }: {
  customer: Customer; initial?: Baseline; kinds: { kind: RuleKind; label: string }[]; onDone: (id?: string) => void;
}) {
  const qc = useQueryClient();
  const collectors = useQuery({ queryKey: ["script-collectors", customer.id], queryFn: ({ signal }) => api.get<CollectorOption[]>(`/customers/${customer.id}/script-collectors/`, undefined, signal) });
  const [form, setForm] = useState(initial ? { ...initial } : { ...EMPTY, rules: [{ kind: "antivirus_healthy" as RuleKind, params: {}, severity: "high" as Severity }] });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, rules: form.rules.map(({ kind, params, severity }) => ({ kind, params, severity })) };
      return initial ? api.patch<Baseline>(`${base(customer)}${initial.id}/`, body) : api.post<Baseline>(base(customer), body);
    },
    onSuccess: (b) => { void qc.invalidateQueries({ queryKey: ["compliance", customer.id] }); onDone(b.id); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const setRule = (i: number, r: BaselineRule) => setForm({ ...form, rules: form.rules.map((x, j) => (j === i ? r : x)) });
  return (
    <form onSubmit={submit} aria-label={initial ? "Edit baseline" : "New baseline"} className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-base font-semibold text-slate-900">{initial ? `Edit “${initial.name}”` : "New baseline"}</h2>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name">{(id) => <input id={id} className="input w-full" required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Workstation standard" />}</Field>
        <Field label="Description (optional)">{(id) => <input id={id} className="input w-full" maxLength={500} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />}</Field>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium text-slate-700">Scope <span className="font-normal text-slate-500">(optional, all devices by default)</span></summary>
        <div className="mt-2 grid gap-3 md:grid-cols-3">
          <Field label="Device type" hint="As reported, e.g. windows">{(id, hint) => <input id={id} aria-describedby={hint} className="input w-full" value={form.scope_device_type} onChange={(e) => setForm({ ...form, scope_device_type: e.target.value })} />}</Field>
          <Field label="Site ID">{(id) => <input id={id} className="input w-full" value={form.scope_site_external_id} onChange={(e) => setForm({ ...form, scope_site_external_id: e.target.value })} />}</Field>
          <Field label="Group ID">{(id) => <input id={id} className="input w-full" value={form.scope_group_external_id} onChange={(e) => setForm({ ...form, scope_group_external_id: e.target.value })} />}</Field>
        </div>
      </details>
      <section aria-label="Rules" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-900">Rules</h3>
        <ul className="space-y-2">
          {form.rules.map((r, i) => <RuleEditor key={i} rule={r} kinds={kinds} collectors={collectors.data ?? []} onChange={(x) => setRule(i, x)} onRemove={() => setForm({ ...form, rules: form.rules.filter((_, j) => j !== i) })} />)}
        </ul>
        <button type="button" className="btn-secondary" onClick={() => setForm({ ...form, rules: [...form.rules, { kind: "required_software", params: {}, severity: "medium" }] })}>Add rule</button>
      </section>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />Enabled</label>
      {save.isError ? <p role="alert" className="text-sm text-red-700">{describeError(save.error)}</p> : null}
      <div className="flex gap-2">
        <button type="submit" className="btn-primary" disabled={save.isPending}>{initial ? "Save changes" : "Create baseline"}</button>
        <button type="button" className="btn-secondary" onClick={() => onDone()}>Cancel</button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------------------------------------ overview

function OverviewView({ customer }: { customer: Customer }) {
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const overview = useQuery({ queryKey: ["compliance", customer.id, "overview"], queryFn: ({ signal }) => api.get<Overview>(`${base(customer)}overview/`, undefined, signal) });
  const all = useQuery({ queryKey: ["compliance", customer.id, "list"], queryFn: ({ signal }) => api.get<Paginated<Baseline>>(base(customer), undefined, signal) });
  const disabled = (all.data?.results ?? []).filter((b) => !b.enabled);
  return (
    <div className="space-y-4">
      {canManage && !creating ? <div><button type="button" className="btn-primary" onClick={() => setCreating(true)}>New baseline</button></div> : null}
      {creating && overview.data ? <BaselineForm customer={customer} kinds={overview.data.rule_kinds} onDone={(id) => { setCreating(false); if (id) navigate(`/compliance/${id}`); }} /> : null}
      <QueryBoundary query={overview} isEmpty={(o) => o.baselines.length === 0}
        empty={<EmptyState title="No compliance baselines yet.">{canManage ? "Create one to check every device against your own rules: required or forbidden software, OS version, antivirus, firewall, disk space, patching and more." : "A customer administrator can create baselines."}</EmptyState>}>
        {(o) => (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {o.baselines.map((b) => (
              <Link key={b.id} to={`/compliance/${b.id}`} className="group flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-sky-400">
                <span className="flex items-start justify-between gap-2">
                  <span className="font-semibold text-slate-900 group-hover:text-sky-800">{b.name}</span>
                  <span className="text-2xl font-semibold tabular-nums text-slate-900">{pct(b.score_pct)}</span>
                </span>
                <ScoreBar totals={b.totals} />
                <Totals totals={b.totals} />
                <span className="text-xs text-slate-500">{b.devices_in_scope} devices · {b.rules.length} rules{b.groups[0]?.score_pct !== null && b.groups[0] ? ` · weakest group: ${b.groups[0].group_name || "no group"} (${pct(b.groups[0].score_pct)})` : ""}</span>
              </Link>
            ))}
          </div>
        )}
      </QueryBoundary>
      {disabled.length ? (
        <p className="text-sm text-slate-600">Disabled: {disabled.map((b, i) => <span key={b.id}>{i ? ", " : ""}<Link className="text-sky-800 underline" to={`/compliance/${b.id}`}>{b.name}</Link></span>)}</p>
      ) : null}
      <Notice title="How compliance is measured">
        Rules are checked against the latest VSA X snapshot each time you open a page; nothing is changed in VSA X. A rule whose
        data was not collected is <em>unknown</em>, never counted as a pass or a failure. Score = compliant ÷ (compliant + not compliant).
      </Notice>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ detail

function DetailView({ customer, id }: { customer: Customer; id: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<"" | RuleState>("");
  const [rule, setRule] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const term = useDebouncedValue(search, 300);
  const baseline = useQuery({ queryKey: ["compliance", customer.id, "baseline", id], queryFn: ({ signal }) => api.get<Baseline>(`${base(customer)}${id}/`, undefined, signal) });
  const kinds = useQuery({ queryKey: ["compliance", customer.id, "overview"], queryFn: ({ signal }) => api.get<Overview>(`${base(customer)}overview/`, undefined, signal), enabled: editing });
  const results = useQuery({
    queryKey: ["compliance", customer.id, "results", id, status, rule, term, page],
    queryFn: ({ signal }) => api.get<BaselineResults>(`${base(customer)}${id}/results/`, { status, rule, search: term, page }, signal),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`${base(customer)}${id}/`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["compliance", customer.id] }); navigate("/compliance"); },
  });
  const ruleLabel = Object.fromEntries((results.data?.rules ?? []).map((r) => [r.id, r.label]));
  const columns: ColumnDef<DeviceResult, unknown>[] = [
    { header: "Device", cell: ({ row }) => <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
    { header: "Site / group", cell: ({ row }) => <span>{row.original.site_name || row.original.site_external_id || "—"} / {row.original.group_name || "no group"}</span> },
    { header: "Status", cell: ({ row }) => <Badge tone={STATE_TONE[row.original.status]}>{STATE_LABEL[row.original.status]}</Badge> },
    { header: "Findings", cell: ({ row }) => {
      const shown = row.original.results.filter((r) => r.state !== "pass");
      return shown.length ? (
        <ul className="space-y-0.5 text-xs">
          {shown.map((r) => <li key={r.rule_id}><span className={r.state === "fail" ? "font-medium text-red-800" : "text-amber-800"}>{r.state === "fail" ? "✗" : "?"}</span> {ruleLabel[r.rule_id]}: <span className="text-slate-600">{r.reason}</span></li>)}
        </ul>
      ) : <span className="text-xs text-emerald-800">All rules pass</span>;
    } },
  ];
  if (editing && baseline.data && kinds.data) {
    return <BaselineForm customer={customer} initial={baseline.data} kinds={kinds.data.rule_kinds} onDone={() => setEditing(false)} />;
  }
  return (
    <div className="space-y-4">
      <Link to="/compliance" className="text-sm text-sky-800 hover:underline">All baselines</Link>
      <QueryBoundary query={baseline}>
        {(b) => (
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold text-slate-900">{b.name} {b.enabled ? null : <Badge tone="neutral">disabled</Badge>}</h2>
              {b.description ? <p className="text-sm text-slate-600">{b.description}</p> : null}
              <p className="text-xs text-slate-500">Scope: {[b.scope_device_type && `type ${b.scope_device_type}`, b.scope_site_external_id && `site ${b.scope_site_external_id}`, b.scope_group_external_id && `group ${b.scope_group_external_id}`].filter(Boolean).join(", ") || "all devices"}</p>
            </div>
            {canManage ? (
              <div className="flex gap-2">
                <button type="button" className="btn-secondary" onClick={() => setEditing(true)}>Edit</button>
                <button type="button" className="btn-danger" disabled={remove.isPending} onClick={() => { if (window.confirm(`Delete baseline “${b.name}”?`)) remove.mutate(); }}>Delete</button>
              </div>
            ) : null}
          </div>
        )}
      </QueryBoundary>
      {remove.isError ? <p role="alert" className="text-sm text-red-700">{describeError(remove.error)}</p> : null}
      <QueryBoundary query={results}>
        {(r) => (
          <>
            <section aria-label="Score" className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-sm font-medium text-slate-700">Compliance score</p>
                <p className="mt-1 text-4xl font-semibold tabular-nums text-slate-900">{pct(r.score_pct)}</p>
                <div className="mt-3 space-y-2"><ScoreBar totals={r.totals} /><Totals totals={r.totals} /></div>
                <p className="mt-2 text-xs text-slate-500">{r.devices_in_scope} devices in scope</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <p className="mb-2 text-sm font-medium text-slate-700">Rules <span className="font-normal text-slate-500">· select one to list its failing devices</span></p>
                <ul className="space-y-1.5">
                  {r.rules.map((x) => (
                    <li key={x.id}>
                      <button type="button" aria-pressed={rule === x.id} onClick={() => { setRule(rule === x.id ? "" : x.id); setPage(1); }}
                        className={`flex w-full flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm hover:border-sky-300 ${rule === x.id ? "border-sky-300 bg-sky-50" : "border-slate-200"}`}>
                        <span className="flex items-center gap-2"><Badge tone={SEVERITY_TONE[x.severity]}>{x.severity}</Badge>{x.label}</span>
                        <span className="text-xs text-slate-600"><span className="font-semibold text-red-800">{x.counts.fail} failing</span> · {x.counts.pass} pass · {x.counts.unknown} unknown</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
            <section aria-labelledby="cmp-dev-h" className="space-y-2">
              <h3 id="cmp-dev-h" className="text-sm font-semibold text-slate-900">Devices</h3>
              <div className="flex flex-wrap items-end gap-3">
                <label className="list-label">Search<input type="search" className="input w-64" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Device name" /></label>
                <label className="list-label">Status
                  <select className="input" value={status} onChange={(e) => { setStatus(e.target.value as "" | RuleState); setPage(1); }}>
                    <option value="">All</option><option value="fail">Not compliant</option><option value="unknown">Unknown</option><option value="pass">Compliant</option>
                  </select>
                </label>
                {rule ? <button type="button" className="filter-chip" onClick={() => setRule("")}>Rule: {ruleLabel[rule]} ✕</button> : null}
              </div>
              <DataTable caption="Compliance by device" columns={columns} rows={r.results} total={r.count} page={page} pageSize={r.page_size} onPageChange={setPage}
                getRowId={(d) => d.asset_id} emptyTitle="No devices match." />
            </section>
            {r.groups.length ? (
              <section aria-labelledby="cmp-grp-h" className="space-y-2">
                <h3 id="cmp-grp-h" className="text-sm font-semibold text-slate-900">By group <span className="font-normal text-slate-500">(weakest first)</span></h3>
                <DataTable caption="Compliance by group" rows={r.groups} getRowId={(g) => `${g.site}-${g.group_external_id}`} columns={[
                  { header: "Site", cell: ({ row }) => row.original.site || "—" },
                  { header: "Group", cell: ({ row }) => row.original.group_name || "no group" },
                  { header: "Score", cell: ({ row }) => <span className="font-semibold tabular-nums">{pct(row.original.score_pct)}</span> },
                  { header: "Compliant", accessorKey: "pass" }, { header: "Not compliant", accessorKey: "fail" }, { header: "Unknown", accessorKey: "unknown" },
                ]} />
              </section>
            ) : null}
          </>
        )}
      </QueryBoundary>
    </div>
  );
}

export function CompliancePage() {
  const { selected } = useCustomers();
  const { baselineId } = useParams();
  return (
    <>
      <PageHeader title="Compliance" subtitle={selected ? `${selected.code} — ${selected.name}` : "Check every device against your own standards."} />
      {!selected ? <SelectCustomer>Compliance is evaluated for one customer at a time.</SelectCustomer>
        : baselineId ? <DetailView key={`${selected.id}-${baselineId}`} customer={selected} id={baselineId} />
        : <OverviewView key={selected.id} customer={selected} />}
    </>
  );
}
