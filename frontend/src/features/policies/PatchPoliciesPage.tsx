import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader, statusTone, type Tone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  PATCH_STATE_LABEL,
  type Customer,
  type DriftState,
  type Paginated,
  type PatchBaseline,
  type PatchPolicyState,
  type PolicyDeviceRow,
  type PolicySummary,
} from "../../lib/types";
import { PolicyDefinitionView } from "./PolicyDefinitionView";
import { SelectCustomer } from "../../components/SelectCustomer";

const DRIFT_TONE: Record<DriftState, Tone> = {
  no_baseline: "neutral",
  unknown: "neutral",
  matches: "good",
  different_policy: "warn",
  missing_policy: "bad",
  unexpected_policy: "warn",
};

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      {hint ? <div className="text-[11px] text-slate-500">{hint}</div> : null}
    </div>
  );
}

function Baselines({ customer, summary }: { customer: Customer; summary: PolicySummary }) {
  const qc = useQueryClient();
  const base = `/customers/${customer.id}/patch-policy-baselines/`;
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const query = useQuery({ queryKey: ["patch-baselines", customer.id], queryFn: ({ signal }) => api.get<PatchBaseline[]>(base, undefined, signal) });
  const [scopeType, setScopeType] = useState<"organization" | "site" | "group">("group");
  const [scopeId, setScopeId] = useState("");
  const [policy, setPolicy] = useState("");
  const [reason, setReason] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["patch-baselines", customer.id] });
    void qc.invalidateQueries({ queryKey: ["patch-policies", customer.id] });
  };
  const propose = useMutation({
    mutationFn: () =>
      api.post<PatchBaseline>(base, {
        scope_type: scopeType,
        scope_external_id: scopeId,
        expect_no_policy: policy === "none",
        expected_policy_id: policy === "none" ? "" : policy,
        reason,
      }),
    onSuccess: () => { setReason(""); refresh(); },
  });
  const act = useMutation({ mutationFn: ({ id, verb }: { id: string; verb: string }) => api.post<PatchBaseline>(`${base}${id}/${verb}/`), onSuccess: refresh });
  const scopes =
    scopeType === "group"
      ? Object.entries(summary.scopes.groups).map(([id, g]) => [id, `${g.name} (site ${summary.scopes.sites[g.site] ?? g.site})`])
      : Object.entries(scopeType === "site" ? summary.scopes.sites : summary.scopes.organizations);
  const scopeLabel = (b: PatchBaseline) =>
    b.scope_type === "group" ? summary.scopes.groups[b.scope_external_id]?.name : b.scope_type === "site" ? summary.scopes.sites[b.scope_external_id] : summary.scopes.organizations[b.scope_external_id];

  return (
    <section aria-labelledby="baseline-h" className="rounded border border-slate-200 bg-white p-4">
      <h2 id="baseline-h" className="mb-1 font-semibold">Expected policies (reviewed baseline)</h2>
      <p className="mb-2 text-xs text-slate-500">Drift is measured only against approved expectations. The most specific scope wins (group, then site, then organisation). A different administrator must approve each proposal.</p>
      <QueryBoundary query={query}>
        {(rows) => (
          <DataTable caption="Expected policies" rows={rows} getRowId={(r) => r.id} emptyTitle="No expectations yet: every device shows 'no baseline'."
            columns={[
              { header: "Scope", cell: ({ row }) => `${row.original.scope_type} ${scopeLabel(row.original) ?? ""} (${row.original.scope_external_id})` },
              { header: "Expected", cell: ({ row }) => row.original.expect_no_policy ? "No policy" : `${row.original.expected_policy_name} (ID ${row.original.expected_policy_id})` },
              { header: "Reason", accessorKey: "reason" },
              { header: "State", cell: ({ row }) => <Badge tone={statusTone[row.original.state] ?? "neutral"}>{row.original.state}</Badge> },
              { header: "Proposed / reviewed", cell: ({ row }) => <span className="text-xs">{row.original.proposed_by}{row.original.reviewed_by ? ` / ${row.original.reviewed_by}` : ""}</span> },
              { header: "", id: "actions", cell: ({ row }) => canManage ? (
                <span className="flex gap-1">
                  {row.original.state === "proposed" ? <>
                    <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "approve" })}>Approve</button>
                    <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "reject" })}>Reject</button>
                  </> : null}
                  {row.original.state === "approved" ? <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "retire" })}>Retire</button> : null}
                </span>) : null },
            ]} />
        )}
      </QueryBoundary>
      {act.isError ? <p role="alert" className="mt-2 text-sm text-red-700">{describeError(act.error)}</p> : null}
      {canManage ? (
        <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); propose.mutate(); }}>
          <Field label="Scope type">{(id) => (
            <select id={id} className="input" value={scopeType} onChange={(e) => { setScopeType(e.target.value as typeof scopeType); setScopeId(""); }}>
              <option value="group">Group</option><option value="site">Site</option><option value="organization">Organisation</option>
            </select>)}</Field>
          <Field label="Scope">{(id) => (
            <select id={id} className="input" value={scopeId} onChange={(e) => setScopeId(e.target.value)} required>
              <option value="">Choose…</option>
              {scopes.map(([sid, name]) => <option key={sid} value={sid}>{name} ({sid})</option>)}
            </select>)}</Field>
          <Field label="Expected policy">{(id) => (
            <select id={id} className="input" value={policy} onChange={(e) => setPolicy(e.target.value)} required>
              <option value="">Choose…</option>
              <option value="none">No policy (explicit)</option>
              {summary.definitions.filter((d) => d.status === "collected").map((d) => <option key={d.policy_id} value={d.policy_id}>{d.name} (ID {d.policy_id})</option>)}
            </select>)}</Field>
          <Field label="Reason">{(id) => <input id={id} className="input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} required />}</Field>
          <button type="submit" className="btn-primary" disabled={propose.isPending}>Propose expectation</button>
          {propose.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(propose.error)}</p> : null}
        </form>
      ) : null}
    </section>
  );
}

function Devices({ customer, summary }: { customer: Customer; summary: PolicySummary }) {
  const [state, setState] = useState("");
  const [drift, setDrift] = useState("");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["patch-policies", customer.id, "devices", state, drift, page],
    queryFn: ({ signal }) => api.get<Paginated<PolicyDeviceRow>>(`/customers/${customer.id}/patch-policies/devices/`, { patch_state: state, drift, page }, signal),
  });
  return (
    <section aria-labelledby="devices-h">
      <h2 id="devices-h" className="mb-2 text-sm font-semibold">Devices</h2>
      <div className="mb-2 flex flex-wrap gap-2">
        <Field label="Assignment">{(id) => (
          <select id={id} className="input" value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>
            <option value="">All</option>
            {(Object.keys(PATCH_STATE_LABEL) as PatchPolicyState[]).map((s) => <option key={s} value={s}>{PATCH_STATE_LABEL[s]}</option>)}
          </select>)}</Field>
        <Field label="Drift">{(id) => (
          <select id={id} className="input" value={drift} onChange={(e) => { setDrift(e.target.value); setPage(1); }}>
            <option value="">All</option>
            {(Object.keys(summary.drift_labels) as DriftState[]).map((d) => <option key={d} value={d}>{summary.drift_labels[d]}</option>)}
          </select>)}</Field>
      </div>
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable caption="Patch policy by device" rows={data.results} total={data.count} page={page} onPageChange={setPage} getRowId={(r) => r.asset_id}
            emptyTitle="No devices match."
            columns={[
              { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
              { header: "Site / group", cell: ({ row }) => `${row.original.site_name || row.original.site_external_id} / ${row.original.group_name || row.original.group_external_id || "no group"}` },
              { header: "Patch Management", cell: ({ row }) => <span><Badge tone={row.original.patch_state === "assigned" ? "good" : row.original.patch_state === "explicit_none" ? "warn" : "neutral"}>{PATCH_STATE_LABEL[row.original.patch_state]}</Badge>{row.original.patch_policy_name ? <span className="block text-xs">{row.original.patch_policy_name}</span> : null}</span> },
              { header: "Collected", cell: ({ row }) => <span className="text-xs">{row.original.collection_status.replace(/_/g, " ")}{row.original.collected_at ? ` · ${formatUtc(row.original.collected_at)}` : ""}</span> },
              { header: "Expected", cell: ({ row }) => row.original.expected ? (row.original.expected.expect_no_policy ? "No policy" : row.original.expected.policy_name) : "—" },
              { header: "Drift", cell: ({ row }) => <Badge tone={DRIFT_TONE[row.original.drift]}>{summary.drift_labels[row.original.drift]}</Badge> },
            ]} />
        )}
      </QueryBoundary>
    </section>
  );
}

function View({ customer }: { customer: Customer }) {
  const query = useQuery({
    queryKey: ["patch-policies", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<PolicySummary>(`/customers/${customer.id}/patch-policies/summary/`, undefined, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(s) => (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">As of {s.as_of.map(formatUtc).join(", ") || "never"} · data basis {s.data_basis.join(", ") || "none"}</p>
          <Notice tone="info">{s.note}</Notice>
          {s.devices === 0 ? <EmptyState title="No devices in the current snapshot." /> : null}
          <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-5">
            <Tile label="Policy assigned" value={s.patch_states.assigned} />
            <Tile label="No Policy (explicit)" value={s.patch_states.explicit_none} />
            <Tile label="No Patch Management entry" value={s.patch_states.not_reported} hint="not the same as no policy" />
            <Tile label="Unknown (not collected)" value={s.patch_states.unknown} />
            <Tile label="Coverage" value={s.coverage.percent === null ? "n/a" : `${s.coverage.percent}%`}
              hint={`${s.coverage.assigned} of ${s.coverage.verified_denominator} verified; ${s.coverage.excluded_unknown} excluded`} />
          </div>
          <p className="text-xs text-slate-500">Coverage = {s.coverage.definition}. {s.carried_forward_note}</p>
          <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-6">
            {(Object.keys(s.drift) as DriftState[]).map((k) => <Tile key={k} label={s.drift_labels[k]} value={s.drift[k]} />)}
          </div>
          <section aria-labelledby="defs-h" className="rounded border border-slate-200 bg-white p-4">
            <h2 id="defs-h" className="mb-2 font-semibold">Patch policies in use</h2>
            {s.definitions.length === 0 ? <p className="text-sm text-slate-500">No patch policy definitions were collected.</p> : null}
            <div className="space-y-4">
              {s.definitions.map((d) => (
                <div key={d.policy_id}>
                  <p className="text-xs text-slate-500">ID {d.policy_id} · {s.by_policy.find((p) => p.policy_id === d.policy_id)?.devices ?? 0} device(s)</p>
                  <PolicyDefinitionView definition={d} />
                </div>
              ))}
            </div>
          </section>
          <Baselines customer={customer} summary={s} />
          <Devices customer={customer} summary={s} />
        </div>
      )}
    </QueryBoundary>
  );
}

export function PatchPoliciesPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Patch policies" subtitle="Assigned VSA X Patch Management policies, their configuration, and drift from the approved expectation." />
      {!selected ? <SelectCustomer /> : <View customer={selected} />}
    </>
  );
}
