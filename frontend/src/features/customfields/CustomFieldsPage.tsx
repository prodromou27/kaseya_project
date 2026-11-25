import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { SelectCustomer } from "../../components/SelectCustomer";
import { QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, Notice, PageHeader } from "../../components/ui";
import { api, apiUpload, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import { CAP, type AssetRow, type CfJob, type Customer, type CustomFieldDef, type Paginated } from "../../lib/types";
import { conditionParams, CustomFieldCondition, NO_CONDITION, type CfCondition } from "./CustomFieldCondition";
import { JobPanel } from "./JobPanel";

const PAGE = 50;
const ROLE_LABELS: Record<string, string> = {
  device_id: "VSA device ID", serial: "Serial number", fqdn: "FQDN", hostname: "Hostname", asset_tag: "Asset tag (not collected)",
  expected_org: "Expected organisation ID", expected_site: "Expected site", expected_group: "Expected group", value: "Value per device",
};

export function useEditableFields(customer: Customer) {
  return useQuery({
    queryKey: ["cf-fields", customer.id, "editable"],
    queryFn: ({ signal }) => api.get<CustomFieldDef[]>(`/customers/${customer.id}/custom-fields/`, { editable: "true" }, signal),
  });
}

/** Field selector plus a value input that matches the field type. */
export function FieldValue({ fields, fieldId, value, onField, onValue, allowEmpty = false }: {
  fields: CustomFieldDef[]; fieldId: string; value: string; onField: (id: string) => void; onValue: (v: string) => void; allowEmpty?: boolean;
}) {
  const field = fields.find((f) => f.id === fieldId);
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="list-label">Custom field
        <select className="input w-64" value={fieldId} onChange={(e) => { onField(e.target.value); onValue(""); }}>
          <option value="">Choose a field…</option>
          {fields.filter((f) => f.editable).map((f) => <option key={f.id} value={f.id}>{f.name} ({f.type})</option>)}
        </select>
      </label>
      {field ? (
        <label className="list-label">Value{allowEmpty ? " (or from the file)" : ""}
          {field.type === "Boolean" ? (
            <select className="input w-40" value={value} onChange={(e) => onValue(e.target.value)}>
              <option value="">{allowEmpty ? "From the file" : "Choose…"}</option><option value="true">True</option><option value="false">False</option>
            </select>
          ) : (
            <input className="input w-56" value={value} maxLength={255}
                   type={field.type === "Date" ? "date" : field.type === "Number" ? "number" : "text"}
                   step={field.type === "Number" ? "any" : undefined}
                   placeholder={field.default_value ? `Default: ${field.default_value}` : ""}
                   onChange={(e) => onValue(e.target.value)} />
          )}
        </label>
      ) : null}
      {field?.description ? <p className="w-full text-xs text-slate-500">{field.description}</p> : null}
    </div>
  );
}

function NoFields({ customer }: { customer: Customer }) {
  return (
    <Notice tone="info">
      No custom field is editable for {customer.code} yet. A super administrator chooses editable fields under <strong>Field overview</strong>.
    </Notice>
  );
}

function SelectDevices({ customer, onJob }: { customer: Customer; onJob: (id: string) => void }) {
  const fields = useEditableFields(customer);
  const [search, setSearch] = useState("");
  const [site, setSite] = useState("");
  const [group, setGroup] = useState("");
  const [os, setOs] = useState("");
  const [page, setPage] = useState(1);
  const [chosen, setChosen] = useState<Map<string, string>>(new Map());
  const [allMatching, setAllMatching] = useState(false);
  const [fieldId, setFieldId] = useState("");
  const [value, setValue] = useState("");
  const [condition, setCondition] = useState<CfCondition>(NO_CONDITION);
  const filters = { search, site, group, os, device_type: "", ...conditionParams(condition) };
  const assets = useQuery({
    queryKey: ["cf-assets", customer.id, search, site, group, os, conditionParams(condition), page],
    queryFn: ({ signal }) => api.get<Paginated<AssetRow>>(`/customers/${customer.id}/assets/`, { ...filters, page, page_size: PAGE, ordering: "hostname" }, signal),
  });
  const create = useMutation({
    mutationFn: () => api.post<CfJob>(`/customers/${customer.id}/custom-field-jobs/`, {
      field: fieldId, value, source: "selection",
      ...(allMatching ? { filters: Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) } : { assets: [...chosen.keys()] }),
    }),
    onSuccess: (job) => onJob(job.id),
  });
  const toggle = (row: AssetRow) => setChosen((m) => { const n = new Map(m); if (n.has(row.id)) n.delete(row.id); else n.set(row.id, row.hostname); return n; });
  const rows = assets.data?.results ?? [];
  const pageAll = rows.length > 0 && rows.every((r) => chosen.has(r.id));
  const count = allMatching ? assets.data?.count ?? 0 : chosen.size;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="list-label">Search<input className="input w-56" type="search" value={search} placeholder="Hostname, serial or device ID" onChange={(e) => { setSearch(e.target.value); setPage(1); setAllMatching(false); }} /></label>
        <label className="list-label">Site<input className="input w-40" value={site} onChange={(e) => { setSite(e.target.value); setPage(1); setAllMatching(false); }} /></label>
        <label className="list-label">Group<input className="input w-40" value={group} onChange={(e) => { setGroup(e.target.value); setPage(1); setAllMatching(false); }} /></label>
        <label className="list-label">Operating system<input className="input w-40" value={os} onChange={(e) => { setOs(e.target.value); setPage(1); setAllMatching(false); }} /></label>
        <CustomFieldCondition customer={customer} value={condition} onChange={(c) => { setCondition(c); setPage(1); setAllMatching(false); }} />
      </div>
      <QueryBoundary query={assets}>
        {(data) => (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" aria-label="Devices to choose from">
              <thead><tr className="text-left text-xs text-slate-500">
                <th className="py-1 pr-2"><input type="checkbox" aria-label="Select all on this page" checked={pageAll} disabled={allMatching}
                  onChange={() => setChosen((m) => { const n = new Map(m); for (const r of rows) { if (pageAll) n.delete(r.id); else n.set(r.id, r.hostname); } return n; })} /></th>
                <th className="pr-3">Hostname</th><th className="pr-3">Site</th><th className="pr-3">Group</th><th className="pr-3">Operating system</th><th>Serial</th>
              </tr></thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td className="py-1 pr-2"><input type="checkbox" aria-label={`Select ${r.hostname}`} disabled={allMatching} checked={allMatching || chosen.has(r.id)} onChange={() => toggle(r)} /></td>
                    <td className="pr-3">{r.hostname}</td><td className="pr-3">{r.site_name || r.site_external_id}</td><td className="pr-3">{r.group_name}</td>
                    <td className="pr-3">{r.os_name}</td><td className="font-mono text-xs">{r.serial_number}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <button type="button" className="btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
              <span>Page {page} of {Math.max(1, Math.ceil(data.count / PAGE))} · {data.count} devices</span>
              <button type="button" className="btn-secondary" disabled={!data.next} onClick={() => setPage((p) => p + 1)}>Next</button>
              <label className="ml-4 flex items-center gap-1"><input type="checkbox" checked={allMatching} onChange={(e) => setAllMatching(e.target.checked)} />
                Use all {data.count} devices matching these filters</label>
            </div>
          </div>
        )}
      </QueryBoundary>
      <p role="status" className="text-sm font-medium">{count} device{count === 1 ? "" : "s"} selected{allMatching ? " (fixed when you continue)" : ""}
        {!allMatching && chosen.size ? <button type="button" className="ml-2 text-xs text-sky-800 underline" onClick={() => setChosen(new Map())}>Clear</button> : null}</p>
      <QueryBoundary query={fields}>
        {(list) => list.some((f) => f.editable) ? (
          <div className="space-y-2">
            <FieldValue fields={list} fieldId={fieldId} value={value} onField={setFieldId} onValue={setValue} />
            <button type="button" className="btn-primary" disabled={!fieldId || !value || !count || create.isPending} onClick={() => create.mutate()}>Review devices</button>
            {create.isError ? <p role="alert" className="text-sm text-red-700">{describeError(create.error)}</p> : null}
          </div>
        ) : <NoFields customer={customer} />}
      </QueryBoundary>
    </div>
  );
}

/**
 * CFA-10: put a placeholder (default "TBD") on every workstation that has no value yet, so the field exists on all
 * devices before the final values are known. Devices that already show any value, set on the device or inherited, are
 * left unchanged. The usual preview and confirmation apply.
 */
function FillEmpty({ customer, onJob }: { customer: Customer; onJob: (id: string) => void }) {
  const fields = useEditableFields(customer);
  const [fieldId, setFieldId] = useState("");
  const [value, setValue] = useState("TBD");
  const [site, setSite] = useState("");
  const [group, setGroup] = useState("");
  const facets = useQuery({
    queryKey: ["assets", customer.id, "facets"],
    queryFn: ({ signal }) => api.get<{ sites?: { site_external_id: string; site_name: string }[]; groups?: { group_external_id: string; group_name: string; site_name: string }[] }>(`/customers/${customer.id}/assets/facets/`, undefined, signal),
  });
  const scope = Object.fromEntries(Object.entries({ site, group_id: group }).filter(([, v]) => v));
  const devices = useQuery({
    queryKey: ["cf-assets", customer.id, "fill-empty", scope],
    queryFn: ({ signal }) => api.get<Paginated<AssetRow>>(`/customers/${customer.id}/assets/`, { ...scope, page: 1, page_size: 1 }, signal),
  });
  const create = useMutation({
    mutationFn: () => api.post<CfJob>(`/customers/${customer.id}/custom-field-jobs/`, { field: fieldId, value, source: "selection", filters: scope, only_if_empty: true }),
    onSuccess: (job) => onJob(job.id),
  });
  return (
    <div className="space-y-3">
      <Notice tone="info" title="How the placeholder works">
        Every workstation of {customer.code} (or of the site or group you choose) without a value for the field gets the
        placeholder. A device that already has any value, on the device or from its organisation, site or group, is
        left unchanged, and so is a device whose value is set by someone else before the change is applied. Servers are
        never changed. You see the full preview before anything is written. Later, filter the devices whose field is
        still the placeholder (Device assignments, or Devices → More filters) and set the final values.
      </Notice>
      <QueryBoundary query={fields}>
        {(list) => list.some((f) => f.editable && f.type === "Text") ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="list-label">Field
                <select className="input w-64" value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
                  <option value="">Choose a text field…</option>
                  {list.filter((f) => f.editable && f.type === "Text").map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </label>
              <label className="list-label">Placeholder value<input className="input w-40" maxLength={255} value={value} onChange={(e) => setValue(e.target.value)} /></label>
              <label className="list-label">Site
                <select className="input max-w-56" value={site} onChange={(e) => { setSite(e.target.value); setGroup(""); }}>
                  <option value="">All sites</option>
                  {(facets.data?.sites ?? []).map((x) => <option key={x.site_external_id} value={x.site_external_id}>{x.site_name || x.site_external_id}</option>)}
                </select>
              </label>
              <label className="list-label">Group
                <select className="input max-w-64" value={group} onChange={(e) => setGroup(e.target.value)}>
                  <option value="">All groups</option>
                  {(facets.data?.groups ?? []).filter((x) => !site || (facets.data?.sites ?? []).some((y) => y.site_external_id === site && y.site_name === x.site_name))
                    .map((x) => <option key={x.group_external_id} value={x.group_external_id}>{x.group_name || x.group_external_id} · {x.site_name}</option>)}
                </select>
              </label>
            </div>
            <p role="status" className="text-sm">
              {devices.data ? <><strong>{devices.data.count}</strong> device{devices.data.count === 1 ? "" : "s"} will be checked; only those without a value are changed.</> : "Counting devices…"}
            </p>
            <button type="button" className="btn-primary" disabled={!fieldId || !value.trim() || !devices.data?.count || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Preparing…" : "Review devices"}
            </button>
            {create.isError ? <p role="alert" className="text-sm text-red-700">{describeError(create.error)}</p> : null}
          </div>
        ) : <NoFields customer={customer} />}
      </QueryBoundary>
    </div>
  );
}

type Inspect = { columns: string[]; rows: number; sample: string[][]; mapping: Record<string, number>; roles: string[] };

function ImportList({ customer, onJob }: { customer: Customer; onJob: (id: string) => void }) {
  const fields = useEditableFields(customer);
  const [mode, setMode] = useState<"paste" | "file">("paste");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inspect, setInspect] = useState<Inspect | null>(null);
  const [mapping, setMapping] = useState<Record<string, number>>({});
  const [fieldId, setFieldId] = useState("");
  const [value, setValue] = useState("");
  const base = `/customers/${customer.id}/custom-field-jobs/`;
  const look = useMutation({
    mutationFn: (f: File) => apiUpload<Inspect>(`${base}inspect-file/`, f),
    onSuccess: (r) => { setInspect(r); setMapping(r.mapping); },
  });
  const create = useMutation({
    mutationFn: () => mode === "paste"
      ? api.post<CfJob>(base, { field: fieldId, value, source: "list", text })
      : apiUpload<CfJob>(base, file as File, "file", { field: fieldId, value, mapping: JSON.stringify(mapping) }),
    onSuccess: (job) => onJob(job.id),
  });
  const perDevice = mode === "file" && mapping.value !== undefined;
  return (
    <div className="space-y-3">
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-1"><input type="radio" checked={mode === "paste"} onChange={() => setMode("paste")} />Paste names</label>
        <label className="flex items-center gap-1"><input type="radio" checked={mode === "file"} onChange={() => setMode("file")} />Upload TXT, CSV or Excel</label>
      </div>
      {mode === "paste" ? (
        <label className="list-label">Workstations (one per line, or separated by commas or semicolons)
          <textarea className="input h-40 w-full max-w-xl font-mono text-sm" value={text} placeholder={"WS-FIN-001\nWS-FIN-002"} onChange={(e) => setText(e.target.value)} />
        </label>
      ) : (
        <div className="space-y-2">
          <label className="list-label">File
            <input type="file" accept=".txt,.csv,.xlsx" onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); setInspect(null); if (f) look.mutate(f); }} />
          </label>
          {look.isError ? <p role="alert" className="text-sm text-red-700">{describeError(look.error)}</p> : null}
          {inspect ? (
            <div className="space-y-2 rounded bg-slate-50 p-2 text-sm">
              <p>{inspect.rows} rows. Map the columns (at least one identifier):</p>
              <div className="flex flex-wrap gap-3">
                {inspect.roles.map((role) => (
                  <label key={role} className="list-label">{ROLE_LABELS[role] ?? role}
                    <select className="input w-44" value={mapping[role] ?? ""} onChange={(e) => setMapping((m) => (
                      e.target.value === ""
                        ? Object.fromEntries(Object.entries(m).filter(([k]) => k !== role))
                        : { ...m, [role]: Number(e.target.value) }
                    ))}>
                      <option value="">Not used</option>
                      {inspect.columns.map((c, i) => <option key={i} value={i}>{c || `Column ${i + 1}`}</option>)}
                    </select>
                  </label>
                ))}
              </div>
              <table className="text-xs" aria-label="First rows of the file"><tbody>
                {inspect.sample.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="border border-slate-200 px-1">{c}</td>)}</tr>)}
              </tbody></table>
            </div>
          ) : null}
        </div>
      )}
      <QueryBoundary query={fields}>
        {(list) => list.some((f) => f.editable) ? (
          <div className="space-y-2">
            <FieldValue fields={list} fieldId={fieldId} value={value} onField={setFieldId} onValue={setValue} allowEmpty={perDevice} />
            <button type="button" className="btn-primary" disabled={!fieldId || (!value && !perDevice) || (mode === "paste" ? !text.trim() : !inspect) || create.isPending}
                    onClick={() => create.mutate()}>Find devices</button>
            <p className="text-xs text-slate-500">Nothing is changed yet: you review the matches and a preview first.</p>
            {create.isError ? <p role="alert" className="text-sm text-red-700">{describeError(create.error)}</p> : null}
          </div>
        ) : <NoFields customer={customer} />}
      </QueryBoundary>
    </div>
  );
}

function History({ customer, onOpen }: { customer: Customer; onOpen: (id: string) => void }) {
  const [state, setState] = useState("");
  const jobs = useQuery({
    queryKey: ["cf-jobs", customer.id, state],
    queryFn: ({ signal }) => api.get<Paginated<CfJob>>(`/customers/${customer.id}/custom-field-jobs/`, state ? { state } : {}, signal),
    refetchInterval: 5000,
  });
  return (
    <div className="space-y-2">
      <label className="list-label">State
        <select className="input w-48" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All jobs</option><option value="completed">Completed</option><option value="running">Running</option>
          <option value="awaiting_approval">Waiting for approval</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option>
        </select>
      </label>
      <QueryBoundary query={jobs}>
        {(data) => data.results.length ? (
          <table className="min-w-full text-sm" aria-label="Assignment history">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1 pr-3">Requested</th><th className="pr-3">Field = value</th><th className="pr-3">Source</th><th className="pr-3">Devices</th><th className="pr-3">State</th><th>Results</th></tr></thead>
            <tbody>
              {data.results.map((j) => (
                <tr key={j.id} className="border-t border-slate-100 align-top">
                  <td className="py-1 pr-3">{formatUtc(j.created_at)}<span className="block text-xs text-slate-500">{j.created_by}</span></td>
                  <td className="pr-3"><button type="button" className="text-left text-sky-800 underline" onClick={() => onOpen(j.id)}>{j.field_name} = {j.per_device_values ? "(per device)" : j.value}</button></td>
                  <td className="pr-3">{j.source_label}</td>
                  <td className="pr-3 tabular-nums">{j.counts.items ?? 0}</td>
                  <td className="pr-3"><Badge tone={j.state === "completed" ? "good" : j.state === "failed" ? "bad" : "info"}>{j.state_label}</Badge></td>
                  <td className="text-xs">{Object.entries(j.counts.result ?? {}).filter(([k]) => k !== "not_run").map(([k, n]) => `${k.replace(/_/g, " ")}: ${n}`).join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-sm text-slate-500">No custom field jobs yet.</p>}
      </QueryBoundary>
    </div>
  );
}

function FieldOverview({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const me = useMe();
  const fields = useQuery({
    queryKey: ["cf-fields", customer.id, "all"],
    queryFn: ({ signal }) => api.get<CustomFieldDef[]>(`/customers/${customer.id}/custom-fields/`, undefined, signal),
  });
  const refresh = useMutation({
    mutationFn: () => api.post(`/customers/${customer.id}/custom-fields/refresh/`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["cf-fields", customer.id] }),
  });
  const setting = useMutation({
    mutationFn: (v: { id: string; body: Partial<CustomFieldDef> }) => api.patch(`/custom-field-definitions/${v.id}/`, v.body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["cf-fields", customer.id] }),
  });
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {customer.my_capabilities.includes(CAP.cfAssign) ? <button type="button" className="btn-secondary" disabled={refresh.isPending} onClick={() => refresh.mutate()}>{refresh.isPending ? "Reading…" : "Read fields from VSA X"}</button> : null}
        <span className="text-xs text-slate-500">Only device fields that are not read-only or expired can be made editable, and never credential-like ones.</span>
      </div>
      {refresh.isError ? <p role="alert" className="text-sm text-red-700">{describeError(refresh.error)}</p> : null}
      {setting.isError ? <p role="alert" className="text-sm text-red-700">{describeError(setting.error)}</p> : null}
      <QueryBoundary query={fields}>
        {(list) => list.length ? (
          <table className="min-w-full text-sm" aria-label="Custom fields in VSA X">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1 pr-3">Field</th><th className="pr-3">Type</th><th className="pr-3">Contexts</th><th className="pr-3">Default</th><th className="pr-3">Status</th>{me.is_super_admin ? <th>Portal setting</th> : null}</tr></thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.id} className="border-t border-slate-100 align-top">
                  <td className="py-1 pr-3"><span className="font-medium">{f.name}</span> <span className="text-xs text-slate-500">#{f.external_id} · {f.integration}</span>{f.description ? <span className="block text-xs text-slate-500">{f.description}</span> : null}</td>
                  <td className="pr-3">{f.type}</td>
                  <td className="pr-3 text-xs">{f.contexts.join(", ")}</td>
                  <td className="pr-3 text-xs">{f.default_value || "—"}</td>
                  <td className="pr-3">{f.editable ? <Badge tone="good">Editable</Badge> : <span className="text-xs text-slate-600">{f.reason}{f.expiration_date ? ` (${f.expiration_date.slice(0, 10)})` : ""}</span>}</td>
                  {me.is_super_admin ? (
                    <td className="text-xs">
                      <label className="flex items-center gap-1"><input type="checkbox" disabled={!f.device_capable || setting.isPending} checked={f.portal_writable}
                        onChange={(e) => setting.mutate({ id: f.id, body: { portal_writable: e.target.checked } })} />Editable in the portal</label>
                      <label className="flex items-center gap-1"><input type="checkbox" disabled={!f.portal_writable || setting.isPending} checked={f.requires_approval}
                        onChange={(e) => setting.mutate({ id: f.id, body: { requires_approval: e.target.checked } })} />Always needs approval</label>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-sm text-slate-500">No fields read yet. Choose "Read fields from VSA X".</p>}
      </QueryBoundary>
    </div>
  );
}

/** Administrators: jobs engineers have prepared (previewed) or that wait for a second approval, one click to open. */
function WaitingForYou({ customer, openId, onOpen }: { customer: Customer; openId: string | null; onOpen: (id: string) => void }) {
  const jobs = useQuery({
    queryKey: ["cf-jobs", customer.id, "waiting"],
    queryFn: ({ signal }) => api.get<Paginated<CfJob>>(`/customers/${customer.id}/custom-field-jobs/`, { state: "previewed,awaiting_approval" }, signal),
    refetchInterval: 15000,
  });
  const list = (jobs.data?.results ?? []).filter((j) => j.id !== openId);
  if (!list.length) return null;
  return (
    <section aria-label="Waiting for you to apply" className="rounded border border-sky-200 bg-sky-50/60 p-3">
      <h3 className="text-sm font-semibold">Waiting for you to apply ({list.length})</h3>
      <ul className="mt-1 divide-y divide-sky-100 text-sm">
        {list.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
            <span>
              <span className="font-mono">{j.field_name}</span> = <span className="font-mono">{j.per_device_values ? "(per device)" : j.value}</span>
              {" "}on {j.counts.to_change ?? j.counts.items ?? 0} device{(j.counts.to_change ?? j.counts.items) === 1 ? "" : "s"}
              <span className="block text-xs text-slate-500">{j.state === "awaiting_approval" ? "Needs a second approval" : "Prepared"} by {j.created_by} · {formatUtc(j.created_at)}</span>
            </span>
            <button type="button" className="btn-primary" onClick={() => onOpen(j.id)}>Review and apply</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Workspace({ customer }: { customer: Customer }) {
  const [tab, setTab] = useState("devices");
  const [jobId, setJobId] = useState<string | null>(null);
  const canAssign = customer.my_capabilities.includes(CAP.cfAssign);
  const canApply = customer.my_capabilities.includes(CAP.cfApprove);
  const open = (id: string) => {
    setJobId(id);
    requestAnimationFrame(() => document.querySelector("[aria-label=\"Custom field job\"]")?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };
  const tabs = [
    ...(canAssign ? [
      { id: "devices", label: "Device assignments", content: <SelectDevices customer={customer} onJob={open} /> },
      { id: "placeholder", label: "Placeholder for all devices", content: <FillEmpty customer={customer} onJob={open} /> },
      { id: "import", label: "Import list", content: <ImportList customer={customer} onJob={open} /> },
    ] : []),
    { id: "history", label: "Assignment history", content: <History customer={customer} onOpen={open} /> },
    { id: "fields", label: "Field overview", content: <FieldOverview customer={customer} /> },
  ];
  const active = tabs.some((t) => t.id === tab) ? tab : (tabs[0]?.id ?? "history");
  return (
    <div className="space-y-4">
      {canApply ? <WaitingForYou customer={customer} openId={jobId} onOpen={open} /> : null}
      {jobId ? <JobPanel key={jobId} customer={customer} jobId={jobId} onClose={() => setJobId(null)} onRetry={open} /> : null}
      <Tabs label="Custom fields" tabs={tabs} active={active} onChange={setTab} />
    </div>
  );
}

export function CustomFieldsPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Custom fields" subtitle="Assign or update existing VSA X custom fields on workstations: preview, confirm, and verified in VSA X." />
      {!selected ? <SelectCustomer /> : <Workspace key={selected.id} customer={selected} />}
    </>
  );
}
