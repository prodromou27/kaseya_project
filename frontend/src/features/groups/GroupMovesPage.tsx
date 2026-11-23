import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { Customer, Paginated } from "../../lib/types";
import { useUrlFilters } from "../../lib/useUrlFilters";
import { SelectCustomer } from "../../components/SelectCustomer";
import { SuggestionEvidence, type GroupSuggestion } from "./GroupSuggestions";

type Proposal = {
  id: string; asset: string; device_name: string; source_group_name: string;
  target_group_name: string; target_group_external_id: string; reason: string; policy_impact: string;
  state: "pending" | "approved" | "rejected"; requested_by: string; reviewed_by: string | null;
  review_reason: string; created_at: string; expires_at: string; expired: boolean;
  execution_enabled: boolean; execution_available: boolean; execution_unavailable_reason?: string; self_approval_allowed?: boolean; execution_blocked_reason: string; execution: Execution | null;
};
type ExecutionState = "sending" | "succeeded" | "unverified" | "unknown" | "failed";
type Execution = {
  state: ExecutionState; executed_by: string; started_at: string; finished_at: string | null;
  http_status: number | null; error_code: string; observed_group_id: string; verified_at: string | null;
};

const EXECUTION_TEXT: Record<ExecutionState, { label: string; tone: "good" | "warn" | "bad" | "neutral"; help: string }> = {
  sending: { label: "Sending", tone: "neutral", help: "The move is being sent to VSA X." },
  succeeded: { label: "Moved in VSA X", tone: "good", help: "VSA X accepted the move and reading the device back confirmed the new group." },
  unverified: { label: "Not confirmed yet", tone: "warn", help: "VSA X accepted the move but the device still reported its old group. Verify again in a few minutes." },
  unknown: { label: "Outcome unknown", tone: "warn", help: "VSA X did not answer clearly. The move is never sent twice; use Verify to read the device back." },
  failed: { label: "Not moved", tone: "bad", help: "The device was not moved. Submit a new proposal if it is still needed." },
};
/** Plain-language reason for an execution's error code (PERF/OPS 2026-11-23). */
const EXECUTION_REASON: Record<string, string> = {
  still_in_source_group: "Reading the device back showed it is still in its old group, so you can send the move again.",
  timeout_or_connection: "VSA X did not answer in time or the connection dropped.",
  unreadable_response: "VSA X accepted the request but its answer could not be read.",
  internal_error: "The portal hit an error while sending.",
};
function executionReason(ex: Execution): string {
  const known = EXECUTION_REASON[ex.error_code];
  if (known) return known;
  if (/^http_\d+$/.test(ex.error_code)) return `VSA X answered with HTTP ${ex.error_code.slice(5)}.`;
  if (/^rejected_http_\d+$/.test(ex.error_code)) return `VSA X refused the move (HTTP ${ex.error_code.slice(14)}).`;
  return "";
}
type MoveOptions = {
  source_group: string; policy_impact: string; execution_enabled: boolean;
  source_is_onboarding: boolean; suggestion_note: string; suggestions_ambiguous: boolean;
  suggestions: GroupSuggestion[];
  groups: { id: string; name: string; external_id: string; site: string }[];
};

export function ProposeGroupMove({ customer, assetId }: { customer: Customer; assetId: string }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const options = useQuery({
    queryKey: ["group-move-options", customer.id, assetId],
    queryFn: ({ signal }) => api.get<MoveOptions>(`/customers/${customer.id}/group-moves/options/`, { asset: assetId }, signal),
  });
  const propose = useMutation({
    mutationFn: () => api.post<Proposal>(`/customers/${customer.id}/group-moves/`, { asset: assetId, target_group: target, reason }),
    onSuccess: () => { setReason(""); void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] }); },
  });
  return <QueryBoundary query={options}>{(data) => (
    <section className="investigation-card space-y-3" aria-label="Propose group move">
      <h2 className="text-sm font-semibold">Request a group assignment change</h2>
      <Notice tone="warn">{data.policy_impact}</Notice>
      <p className="text-xs text-slate-500">Source group: {data.source_group}. Destinations are restricted to active groups in the same customer, VSA instance and organization.</p>
      <section aria-label="CIDR group suggestions" className="space-y-2 text-sm">
        <h3 className="font-semibold">Suggested destination groups</h3>
        {data.source_is_onboarding ? <p>This is an onboarding group, a valid temporary installation destination. Transfer is manual when an administrator is ready.</p> : null}
        <p className="text-xs text-slate-500">{data.suggestion_note}</p>
        {data.suggestions_ambiguous ? <Notice tone="warn">Several groups match. Review overlapping subnets and adapter evidence before choosing.</Notice> : null}
        {data.suggestions?.length ? <ul>{data.suggestions.map((suggestion) => <li key={suggestion.id} className="mb-2">
          <strong>{suggestion.name}</strong><SuggestionEvidence suggestion={suggestion} />
          {customer.my_capabilities.includes("customer.group_move.propose") ? <button type="button" className="btn-secondary ml-2" onClick={() => setTarget(suggestion.id)}>Use {suggestion.name}{suggestion.external_id ? ` · ID ${suggestion.external_id}` : ""}</button> : null}
        </li>)}</ul> : <p>No matching subnet or naming evidence. Placement is not classified as incorrect. Add approved subnets on destination groups to improve suggestions.</p>}
      </section>
      {customer.my_capabilities.includes("customer.group_move.propose") ? (
        <form className="flex flex-wrap items-end gap-3" aria-label="Group move proposal" onSubmit={(event) => { event.preventDefault(); propose.mutate(); }}>
          <Field label="Target group">{(id) => <select id={id} className="input" required value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="">Select an active group…</option>
            {data.groups.map((group) => <option key={group.id} value={group.id}>{group.name} · site {group.site} · ID {group.external_id}</option>)}
          </select>}</Field>
          <Field label="Change reason" hint="At least 10 characters. An independent administrator must review.">{(id) => <input id={id} className="input w-80" required minLength={10} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} />}</Field>
          <button type="submit" className="btn-primary" disabled={propose.isPending || !target}>Submit proposal</button>
        </form>
      ) : <p className="text-sm text-slate-600">Your role cannot propose group moves.</p>}
      {propose.isError ? <p role="alert" className="text-sm text-red-700">{describeError(propose.error)}</p> : null}
      {propose.isSuccess ? <p role="status" className="text-sm text-emerald-800">Proposal submitted for independent review. No VSA change was executed.</p> : null}
      <Link className="text-sm text-sky-800 underline" to="/group-moves">Review group move proposals</Link>
    </section>
  )}</QueryBoundary>;
}

function Review({ proposal, customer }: { proposal: Proposal; customer: Customer }) {
  const me = useMe();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const decision = useMutation({
    mutationFn: async (value: "approved" | "rejected" | "move") => {
      const reviewed = await api.post<Proposal>(`/customers/${customer.id}/group-moves/${proposal.id}/review/`, { decision: value === "move" ? "approved" : value, reason });
      // The same administrator may execute what they approved (never the requester); the server re-checks everything.
      if (value === "move" && reviewed.execution_enabled) await api.post(`/customers/${customer.id}/group-moves/${proposal.id}/execute/`, {});
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] }),
  });
  return <div className="space-y-3">
    <p className="text-sm"><strong>Reason:</strong> {proposal.reason}</p>
    <p className="text-sm text-amber-900">{proposal.policy_impact}</p>
    <p className="text-xs text-slate-500">Requested {formatUtc(proposal.created_at)} · expires {formatUtc(proposal.expires_at)} · {proposal.requested_by}</p>
    {proposal.reviewed_by ? <p className="text-sm">Reviewed by {proposal.reviewed_by}: {proposal.review_reason}</p> : null}
    {proposal.state === "pending" && customer.my_capabilities.includes("customer.group_move.approve") && (proposal.self_approval_allowed || me.email !== proposal.requested_by) ? (
      <form className="flex flex-wrap items-end gap-2" aria-label="Independent move review" onSubmit={(event) => { event.preventDefault(); decision.mutate(proposal.execution_available ? "move" : "approved"); }}>
        <Field label="Review reason">{(id) => <input id={id} className="input w-80" required minLength={10} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} />}</Field>
        {proposal.execution_available ? (
          <button type="submit" className="btn-primary" disabled={decision.isPending || proposal.expired || reason.trim().length < 10}>
            {decision.isPending ? "Working…" : "Approve and move in VSA X"}
          </button>
        ) : null}
        <button type={proposal.execution_available ? "button" : "submit"} className={proposal.execution_available ? "btn-secondary" : "btn-primary"} disabled={decision.isPending || proposal.expired || reason.trim().length < 10}
                onClick={proposal.execution_available ? () => decision.mutate("approved") : undefined}>Approve only</button>
        <button type="button" className="btn-danger" disabled={decision.isPending || reason.trim().length < 10} onClick={() => decision.mutate("rejected")}>Reject proposal</button>
      </form>
    ) : proposal.state === "pending" ? <p className="text-xs text-slate-500">A different authorized administrator must review this proposal.</p> : null}
    {decision.isError ? <p role="alert" className="text-sm text-red-700">{describeError(decision.error)}</p> : null}
    {proposal.state === "approved" ? <ExecutionPanel proposal={proposal} customer={customer} /> : null}
  </div>;
}

function ExecutionPanel({ proposal, customer }: { proposal: Proposal; customer: Customer }) {
  const me = useMe();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const run = useMutation({
    mutationFn: (step: "execute" | "verify") => api.post<Proposal>(`/customers/${customer.id}/group-moves/${proposal.id}/${step}/`, {}),
    onSettled: () => { setConfirming(false); void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] }); },
  });
  const canApprove = customer.my_capabilities.includes("customer.group_move.approve");
  const ex = proposal.execution;
  return <section aria-label="Execute in VSA X" className="space-y-2 border-t border-slate-200 pt-3">
    <h3 className="text-sm font-semibold">Execute in VSA X</h3>
    {ex ? (
      <div className="space-y-1 text-sm">
        <p><Badge tone={EXECUTION_TEXT[ex.state].tone}>{EXECUTION_TEXT[ex.state].label}</Badge> <span className="text-xs text-slate-500">by {ex.executed_by} · {formatUtc(ex.started_at)}{ex.http_status ? ` · HTTP ${ex.http_status}` : ""}</span></p>
        <p className="text-xs text-slate-600">{ex.error_code === "still_in_source_group" ? "" : EXECUTION_TEXT[ex.state].help} {executionReason(ex)}</p>
        {ex.observed_group_id ? <p className="text-xs text-slate-500">Group reported by VSA X: ID {ex.observed_group_id}{ex.verified_at ? ` (read ${formatUtc(ex.verified_at)})` : ""}</p> : null}
        {["unknown", "unverified", "sending"].includes(ex.state) && canApprove ? <button type="button" className="btn-secondary" disabled={run.isPending} onClick={() => run.mutate("verify")}>Verify in VSA X</button> : null}
      </div>
    ) : null}
    {(!ex || proposal.execution_enabled) && (proposal.execution_enabled ? (
      canApprove && (proposal.self_approval_allowed || me.email !== proposal.requested_by) ? (
        confirming ? (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" role="group" aria-label="Confirm move">
            <p>Move <strong>{proposal.device_name}</strong> from <strong>{proposal.source_group_name}</strong> to <strong>{proposal.target_group_name}</strong> (ID {proposal.target_group_external_id}) in VSA X now? Policies inherited from the new group apply to the device. This is sent once and cannot be undone from the portal.</p>
            <div className="flex gap-2">
              <button type="button" className="btn-danger" disabled={run.isPending} onClick={() => run.mutate("execute")}>Move device in VSA X</button>
              <button type="button" className="btn-secondary" disabled={run.isPending} onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        ) : <button type="button" className="btn-primary" onClick={() => setConfirming(true)}>Execute move in VSA X…</button>
      ) : <p className="text-xs text-slate-500">An administrator other than the requester can execute this approved move.</p>
    ) : <p className="text-xs text-slate-500">{proposal.execution_blocked_reason || "Execution is not available."} The move can be made manually in VSA X.</p>)}
    {run.isError ? <p role="alert" className="text-sm text-red-700">{describeError(run.error)}</p> : null}
  </section>;
}

type Outcome = { device: string; ok: boolean; text: string };

/** Decide (and optionally execute) several selected proposals one after another; every call is the normal per-move API. */
function BulkDecision({ customer, rows }: { customer: Customer; rows: Proposal[] }) {
  const me = useMe();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Outcome[]>([]);
  // Own proposals are skipped only when a second approver is required (REQUIRE_SECOND_APPROVER).
  const mine = (p: Proposal) => p.requested_by === me.email && !p.self_approval_allowed;
  const pending = rows.filter((p) => p.state === "pending" && !p.expired && !mine(p));
  const approvedWaiting = rows.filter((p) => p.state === "approved" && p.execution_enabled && !mine(p));
  const movable = [...pending.filter((p) => p.execution_available), ...approvedWaiting];
  const skipped = rows.length - pending.length - approvedWaiting.length;
  const base = `/customers/${customer.id}/group-moves`;
  const run = async (mode: "move" | "approved" | "rejected") => {
    setBusy(true);
    setDone([]);
    const list = mode === "move" ? movable : pending;
    const results: Outcome[] = [];
    for (const p of list) {
      try {
        let current = p;
        if (p.state === "pending") current = await api.post<Proposal>(`${base}/${p.id}/review/`, { decision: mode === "move" ? "approved" : mode, reason });
        if (mode === "move") {
          const after = await api.post<Proposal>(`${base}/${p.id}/execute/`, {});
          const state = after.execution?.state ?? "sending";
          results.push({ device: p.device_name, ok: state === "succeeded", text: EXECUTION_TEXT[state].label });
        } else {
          results.push({ device: p.device_name, ok: true, text: current.state });
        }
      } catch (error) {
        results.push({ device: p.device_name, ok: false, text: describeError(error) });
      }
      setDone([...results]);
    }
    setBusy(false);
    setSure(false);
    void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] });
  };
  const needsReason = pending.length > 0;
  const reasonOk = !needsReason || reason.trim().length >= 10;
  return (
    <div className="flex w-full flex-col gap-2 text-sm" role="group" aria-label="Decide selected proposals">
      {skipped ? <p className="text-xs text-slate-600">{skipped} selected proposal(s) skipped: expired, already decided or already sent{rows.some((p) => p.requested_by === me.email && !p.self_approval_allowed) ? ", or your own (a second administrator must approve)" : ""}.</p> : null}
      {pending.length && !movable.length ? (
        <p className="text-xs text-amber-900">
          Approving only records the decision: {pending[0]?.execution_unavailable_reason || "moving in VSA X is not available for this integration."}
          {" "}A super admin switches moves on under Settings → Integrations → Edit.
        </p>
      ) : null}
      {pending.length || approvedWaiting.length ? (
        <div className="flex flex-wrap items-end gap-2">
          {needsReason ? (
            <Field label="Review reason (all selected)">{(id) => <input id={id} className="input w-72" minLength={10} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          ) : null}
          {movable.length ? (
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
              Move {movable.length} device{movable.length === 1 ? "" : "s"} in VSA X now (sent once; the new group&apos;s policies apply)
            </label>
          ) : null}
          {movable.length ? <button type="button" className="btn-primary" disabled={busy || !sure || !reasonOk} onClick={() => void run("move")}>Approve and move ({movable.length})</button> : null}
          {pending.length ? <button type="button" className="btn-secondary" disabled={busy || !reasonOk} onClick={() => void run("approved")}>Approve only ({pending.length})</button> : null}
          {pending.length ? <button type="button" className="btn-danger" disabled={busy || !reasonOk} onClick={() => void run("rejected")}>Reject ({pending.length})</button> : null}
        </div>
      ) : null}
      {done.length ? (
        <ul aria-label="Decision results" aria-live="polite" className="space-y-0.5 text-xs">
          {busy ? <li>Working… {done.length} done</li> : null}
          {done.map((o, i) => <li key={i}><Badge tone={o.ok ? "good" : "bad"}>{o.ok ? "Done" : "Problem"}</Badge> {o.device}: {o.text}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

function Requests({ customer }: { customer: Customer }) {
  const { filters, update, page, setPage } = useUrlFilters({ view: "waiting" });
  const [open, setOpen] = useState<string | null>(null);
  const view = filters.view;
  const query = useQuery({
    queryKey: ["group-moves", customer.id, view, page],
    queryFn: ({ signal }) => api.get<Paginated<Proposal>>(`/customers/${customer.id}/group-moves/`, { page, page_size: 200, ...(view ? { view } : {}) }, signal),
  });
  const selected = query.data?.results.find((proposal) => proposal.id === open);
  const VIEWS: [string, string][] = [["waiting", "Waiting for decision"], ["to_move", "Approved, not moved yet"], ["", "All proposals"]];
  return <div className="space-y-3">
    <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
      {VIEWS.map(([v, label]) => <button key={v || "all"} type="button" aria-pressed={view === v} className="list-preset" onClick={() => update({ view: v }, true)}>{label}</button>)}
    </div>
    <QueryBoundary query={query}>{(data) => <div className="space-y-4">
    {data.count && customer.my_capabilities.includes("customer.group_move.approve") ? <p className="text-xs text-slate-600">Tick the box in the table header to select all {Math.min(data.count, 200)} on this page, then choose Approve and move.</p> : null}
    <DataTable caption="Group move proposals" rows={data.results} total={data.count} page={page} pageSize={200} onPageChange={setPage} getRowId={(row) => row.id}
      selectable={customer.my_capabilities.includes("customer.group_move.approve")}
      selectionActions={(rows) => <BulkDecision customer={customer} rows={rows} />}
      emptyTitle="No group changes have been proposed." emptyHint="Open a device's Operations tab to propose a change."
      columns={[
        { header: "Device", cell: ({ row }) => <Link className="font-medium text-sky-800 underline" to={`/assets/${row.original.asset}`}>{row.original.device_name}</Link> },
        { header: "From", accessorKey: "source_group_name" }, { header: "To", accessorKey: "target_group_name" },
        { header: "Proposed by", accessorKey: "requested_by" },
        { header: "State", cell: ({ row }) => <Badge tone={row.original.expired && row.original.state === "pending" ? "warn" : "neutral"}>{row.original.expired && row.original.state === "pending" ? "expired" : row.original.state}</Badge> },
        { header: "In VSA X", cell: ({ row }) => row.original.execution ? <Badge tone={EXECUTION_TEXT[row.original.execution.state].tone}>{EXECUTION_TEXT[row.original.execution.state].label}</Badge> : <span className="text-xs text-slate-500">—</span> },
        { header: "Review", cell: ({ row }) => <button type="button" className="btn-secondary" aria-expanded={open === row.original.id} onClick={() => setOpen(open === row.original.id ? null : row.original.id)}>Review proposal</button> },
      ]} />
    {selected ? <section className="investigation-card" aria-label="Selected group move proposal"><Review key={selected.id} proposal={selected} customer={customer} /></section> : null}
  </div>}</QueryBoundary>
  </div>;
}

export function GroupMovesPage() {
  const { selected } = useCustomers();
  return <>
    <PageHeader title="Group move proposals" subtitle="Customer-scoped requests and independent approvals. Approved moves can be executed in VSA X only where an administrator enabled it." />
    {!selected ? <SelectCustomer /> : <Requests key={selected.id} customer={selected} />}
  </>;
}
