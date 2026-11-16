import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { EmptyState, QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Field, PageHeader } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import { useUrlFilters } from "../../lib/useUrlFilters";
import type { Paginated } from "../../lib/types";

type AlertRow = { id: string; customer: string; customer_code: string; kind: string; title: string; body: string; link: string; created_at: string; read_at: string | null };
type Watch = { id: string; customer: string; customer_code: string; kind: string; params: Record<string, string | number>; enabled: boolean; label: string };

const KINDS: { kind: string; label: string; param?: { key: string; label: string; type: "number" | "text"; placeholder: string } }[] = [
  { kind: "new_device", label: "New device appears" },
  { kind: "offline", label: "Device not seen for more than N days", param: { key: "days", label: "Days", type: "number", placeholder: "14" } },
  { kind: "disk_critical", label: "System disk becomes critical" },
  { kind: "forbidden_software", label: "Program appears on a device", param: { key: "name", label: "Program name contains", type: "text", placeholder: "e.g. TeamViewer" } },
  { kind: "compliance_below", label: "Compliance score falls below", param: { key: "percent", label: "Percent", type: "number", placeholder: "80" } },
  { kind: "workflow_failed", label: "An automation workflow fails on a device" },
];

export function useUnreadAlerts() {
  return useQuery({
    queryKey: ["alerts", "unread-count"],
    queryFn: ({ signal }) => api.get<{ unread: number }>("/alerts/unread-count/", undefined, signal),
    refetchInterval: 60_000,
  });
}

/** Header bell: unread alert count, links to the Alerts page. */
export function AlertBell() {
  const unread = useUnreadAlerts().data?.unread ?? 0;
  return (
    <Link to="/alerts" aria-label={unread ? `Alerts, ${unread} unread` : "Alerts"} className="relative inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50">
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      {unread ? <span aria-hidden="true" className="absolute -right-1.5 -top-1.5 min-w-5 rounded-full bg-red-600 px-1 text-center text-[11px] font-semibold leading-5 text-white">{unread > 99 ? "99+" : unread}</span> : null}
    </Link>
  );
}

function AlertList() {
  const qc = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const query = useQuery({
    queryKey: ["alerts", "list", unreadOnly],
    queryFn: ({ signal }) => api.get<Paginated<AlertRow>>("/alerts/", { unread: unreadOnly ? "true" : "" }, signal),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["alerts"] });
  const read = useMutation({ mutationFn: (id: string) => api.post(`/alerts/${id}/read/`), onSuccess: refresh });
  const readAll = useMutation({ mutationFn: () => api.post("/alerts/read-all/"), onSuccess: refresh });
  const { select } = useCustomers();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />Unread only</label>
        <button type="button" className="btn-secondary" disabled={readAll.isPending} onClick={() => readAll.mutate()}>Mark all as read</button>
      </div>
      <QueryBoundary query={query} isEmpty={(d) => d.results.length === 0}
        empty={<EmptyState title={unreadOnly ? "No unread alerts." : "No alerts yet."}>Add watches under <strong>My watches</strong>; alerts appear after the next sync that changes something.</EmptyState>}>
        {(d) => (
          <ul aria-label="Alerts" className="space-y-2">
            {d.results.map((a) => (
              <li key={a.id} className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border p-3 ${a.read_at ? "border-slate-200 bg-white" : "border-sky-200 bg-sky-50/60"}`}>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">{a.read_at ? null : <span className="sr-only">Unread: </span>}{a.title}</p>
                  {a.body ? <p className="mt-0.5 text-sm text-slate-700">{a.body}</p> : null}
                  <p className="mt-1 text-xs text-slate-500">{formatUtc(a.created_at)}</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  {a.link ? <Link className="btn-secondary" to={a.link} onClick={() => { select(a.customer); if (!a.read_at) read.mutate(a.id); }}>Open</Link> : null}
                  {a.read_at ? null : <button type="button" className="btn-secondary" onClick={() => read.mutate(a.id)}>Mark read</button>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </QueryBoundary>
    </div>
  );
}

function Watches() {
  const qc = useQueryClient();
  const { customers, selected } = useCustomers();
  const [customer, setCustomer] = useState(selected?.id ?? customers[0]?.id ?? "");
  const [kind, setKind] = useState("new_device");
  const [value, setValue] = useState("");
  const query = useQuery({ queryKey: ["alert-subscriptions"], queryFn: ({ signal }) => api.get<Watch[]>("/alert-subscriptions/", undefined, signal) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["alert-subscriptions"] });
  const spec = KINDS.find((k) => k.kind === kind);
  const add = useMutation({
    mutationFn: () => api.post("/alert-subscriptions/", {
      customer, kind, params: spec?.param ? { [spec.param.key]: spec.param.type === "number" ? Number(value) : value } : {},
    }),
    onSuccess: () => { setValue(""); refresh(); },
  });
  const toggle = useMutation({ mutationFn: (w: Watch) => api.patch(`/alert-subscriptions/${w.id}/`, { enabled: !w.enabled }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/alert-subscriptions/${id}/`), onSuccess: refresh });
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate(); };
  return (
    <div className="space-y-4">
      <form onSubmit={submit} aria-label="Add watch" className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <Field label="Customer">{(id) => (
          <select id={id} className="input" value={customer} onChange={(e) => setCustomer(e.target.value)} required>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
          </select>)}</Field>
        <Field label="Alert me when">{(id) => (
          <select id={id} className="input w-72" value={kind} onChange={(e) => { setKind(e.target.value); setValue(""); }}>
            {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select>)}</Field>
        {spec?.param ? <Field label={spec.param.label}>{(id) => <input id={id} className="input w-40" type={spec.param?.type} required value={value} placeholder={spec.param?.placeholder} onChange={(e) => setValue(e.target.value)} />}</Field> : null}
        <button type="submit" className="btn-primary" disabled={add.isPending || !customer}>Add watch</button>
        {add.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(add.error)}</p> : null}
      </form>
      <QueryBoundary query={query} isEmpty={(w) => w.length === 0} empty={<EmptyState title="You are not watching anything yet." />}>
        {(rows) => (
          <ul aria-label="My watches" className="space-y-2">
            {rows.map((w) => (
              <li key={w.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm">
                <span><span className="font-medium text-slate-900">{w.customer_code}</span> · {w.label}{w.enabled ? null : <span className="ml-2 text-xs text-slate-500">(paused)</span>}</span>
                <span className="flex gap-2">
                  <button type="button" className="btn-secondary" onClick={() => toggle.mutate(w)}>{w.enabled ? "Pause" : "Resume"}</button>
                  <button type="button" className="btn-danger" onClick={() => remove.mutate(w.id)}>Remove</button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </QueryBoundary>
      <p className="text-xs text-slate-500">Watches are checked after every successful sync. You are alerted only about what is new since the previous check, so adding a watch never floods you with existing items. Alerts appear in the portal; email delivery is not enabled.</p>
    </div>
  );
}

export function AlertsPage() {
  const { filters, update } = useUrlFilters({ tab: "alerts" });
  return (
    <>
      <PageHeader title="Alerts" subtitle="Changes you asked to be told about, across your customers." />
      <Tabs label="Alerts sections" active={filters.tab} onChange={(tab) => update({ tab })} tabs={[
        { id: "alerts", label: "Alerts", content: <AlertList /> },
        { id: "watches", label: "My watches", content: <Watches /> },
      ]} />
    </>
  );
}
