import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { Tabs } from "../../components/Tabs";
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
import { MoveList } from "./MoveList";

export type Proposal = {
  id: string; asset: string; device_name: string; source_group_name: string;
  target_group: string; target_group_name: string; target_group_external_id: string; reason: string; policy_impact: string;
  state: "pending" | "approved" | "rejected"; requested_by: string; reviewed_by: string | null;
  review_reason: string; created_at: string; expires_at: string; expired: boolean;
  execution_enabled: boolean; execution_available: boolean; execution_unavailable_reason?: string; self_approval_allowed?: boolean; execution_blocked_reason: string; execution: Execution | null;
};
type ExecutionState = "sending" | "succeeded" | "unverified" | "unknown" | "failed";
type Execution = {
  state: ExecutionState; executed_by: string; started_at: string; finished_at: string | null;
  http_status: number | null; error_code: string; observed_group_id: string; verified_at: string | null;
  /** Only for "answered OK but not applied": the shape of VSA X's answer (never its body). */
  answer?: { documented_answer?: boolean; content_type?: string; content_length?: number } | null;
};

export const EXECUTION_TEXT: Record<ExecutionState, { label: string; tone: "good" | "warn" | "bad" | "neutral"; help: string }> = {
  sending: { label: "Sending", tone: "neutral", help: "The move is being sent to VSA X." },
  succeeded: { label: "Moved in VSA X", tone: "good", help: "VSA X accepted the move and reading the device back confirmed the new group." },
  unverified: { label: "Not confirmed yet", tone: "warn", help: "VSA X accepted the move but the device still reported its old group. Verify again in a few minutes." },
  unknown: { label: "Outcome unknown", tone: "warn", help: "VSA X did not answer clearly. The move is never sent twice; use Verify to read the device back." },
  failed: { label: "Not moved", tone: "bad", help: "The device was not moved. Submit a new proposal if it is still needed." },
};
/** Plain-language reason for an execution's error code (PERF/OPS 2026-11-23). */
export const EXECUTION_REASON: Record<string, string> = {
  still_in_source_group: "Reading the device back showed it is still in its old group, so you can send the move again.",
  accepted_not_applied: "VSA X answered OK but did not apply the move: the device is still in its old group. Usually the API token is not allowed to move devices, or a proxy/firewall in front of VSA X answers instead of the API. Fix that first, then send the move again.",
  timeout_or_connection: "VSA X did not answer in time or the connection dropped.",
  unreadable_response: "VSA X accepted the request but its answer could not be read.",
  internal_error: "The portal hit an error while sending.",
};
/** One-step move for administrators (2026-11-24): record, approve, send and read back in one call. */
export function moveNow(customerId: string, asset: string, targetGroup: string, reason = "") {
  return api.post<Proposal>(`/customers/${customerId}/group-moves/move-now/`, { asset, target_group: targetGroup, reason });
}

/** Short result text for a finished one-step move; ``stop`` when VSA X answers OK but does not apply moves. */
export function moveOutcome(after: Proposal): { ok: boolean; text: string; stop: boolean } {
  const ex = after.execution;
  if (!ex) return { ok: false, text: "Not sent.", stop: false };
  const reason = executionReason(ex);
  return { ok: ex.state === "succeeded", text: `${EXECUTION_TEXT[ex.state].label}${reason ? `. ${reason}` : ""}`, stop: ex.error_code === "accepted_not_applied" };
}

export function executionReason(ex: Execution): string {
  const known = EXECUTION_REASON[ex.error_code];
  if (known && ex.error_code === "accepted_not_applied" && ex.answer) {
    const a = ex.answer;
    const shape = [ex.http_status ? `HTTP ${ex.http_status}` : "", a.content_type || "no content type", `${a.content_length ?? 0} bytes`].filter(Boolean).join(", ");
    return `${known} VSA X's answer: ${shape}${a.documented_answer === false ? " - not the documented API answer" : ""}${/html/i.test(a.content_type ?? "") ? " (an HTML page usually means a proxy, firewall or login page answered)" : ""}.`;
  }
  if (known) return known;
  if (/^http_\d+$/.test(ex.error_code)) return `VSA X answered with HTTP ${ex.error_code.slice(5)}.`;
  if (/^rejected_http_\d+$/.test(ex.error_code)) return `VSA X refused the move (HTTP ${ex.error_code.slice(14)}).`;
  return "";
}
type MoveOptions = {
  source_group: string; policy_impact: string; execution_enabled: boolean;
  move_now_allowed?: boolean; execution_unavailable_reason?: string;
  source_is_onboarding: boolean; suggestion_note: string; suggestions_ambiguous: boolean;
  suggestions: GroupSuggestion[];
  groups: { id: string; name: string; external_id: string; site: string }[];
};

export function ProposeGroupMove({ customer, assetId }: { customer: Customer; assetId: string }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const options = useQuery({
    queryKey: ["group-move-options", customer.id, assetId],
    queryFn: ({ signal }) => api.get<MoveOptions>(`/customers/${customer.id}/group-moves/options/`, { asset: assetId }, signal),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] });
    void qc.invalidateQueries({ queryKey: ["asset", assetId] });
  };
  const propose = useMutation({
    mutationFn: () => api.post<Proposal>(`/customers/${customer.id}/group-moves/`, { asset: assetId, target_group: target, reason }),
    onSuccess: () => { setReason(""); refresh(); },
  });
  const move = useMutation({ mutationFn: () => moveNow(customer.id, assetId, target, reason), onSettled: () => { setConfirming(false); refresh(); } });
  const canSuggest = customer.my_capabilities.includes("customer.group_move.propose");
  const isAdmin = customer.my_capabilities.includes("customer.group_move.approve");
  return <QueryBoundary query={options}>{(data) => {
    const direct = Boolean(data.move_now_allowed);
    const chosen = data.groups.find((g) => g.id === target);
    const outcome = move.data ? moveOutcome(move.data) : null;
    return (
      <section className="investigation-card space-y-3" aria-label="Move to another group">
        <h2 className="text-sm font-semibold">Move to another group</h2>
        <p className="text-xs text-slate-500">Now in <strong>{data.source_group}</strong>. Only active groups of the same customer, VSA source and organization are offered. The new group&apos;s policies apply to the device.</p>
        <section aria-label="CIDR group suggestions" className="space-y-1 text-sm">
          <h3 className="font-semibold">Suggested</h3>
          {data.source_is_onboarding ? <p className="text-xs text-slate-500">This is an onboarding group, a valid temporary installation destination. Move devices out when you are ready.</p> : null}
          {data.suggestions_ambiguous ? <Notice tone="warn">Several groups match. Check the evidence before choosing.</Notice> : null}
          {data.suggestions?.length ? <ul>{data.suggestions.map((suggestion) => <li key={suggestion.id} className="mb-1">
            <button type="button" className="btn-secondary mr-2" onClick={() => { setTarget(suggestion.id); setConfirming(false); }}>
              Use {suggestion.name}{suggestion.external_id ? ` · ID ${suggestion.external_id}` : ""}
            </button>
            <SuggestionEvidence suggestion={suggestion} />
          </li>)}</ul> : <p className="text-xs text-slate-500">No matching subnet or naming evidence. Placement is not classified as incorrect. Add approved subnets on destination groups to improve suggestions.</p>}
        </section>
        {direct || canSuggest ? (
          <form className="flex flex-wrap items-end gap-3" aria-label="Group move" onSubmit={(event) => { event.preventDefault(); if (direct) setConfirming(true); else propose.mutate(); }}>
            <Field label="Destination group">{(id) => <select id={id} className="input" required value={target} onChange={(event) => { setTarget(event.target.value); setConfirming(false); }}>
              <option value="">Select an active group…</option>
              {data.groups.map((group) => <option key={group.id} value={group.id}>{group.name} · site {group.site} · ID {group.external_id}</option>)}
            </select>}</Field>
            <Field label={direct ? "Note (optional)" : "Reason"} hint={direct ? "Kept in the audit log." : "At least 10 characters; an administrator applies it."}>
              {(id, h) => <input id={id} aria-describedby={h} className="input w-72" required={!direct} minLength={direct ? undefined : 10} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} />}
            </Field>
            <button type="submit" className="btn-primary" disabled={!target || propose.isPending || move.isPending}>{direct ? "Move in VSA X…" : "Suggest move"}</button>
          </form>
        ) : <p className="text-sm text-slate-600">Your role cannot move devices.</p>}
        {!direct && isAdmin && data.execution_unavailable_reason
          ? <p className="text-xs text-amber-900">Moving directly is not available: {data.execution_unavailable_reason}</p> : null}
        {confirming && chosen ? (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" role="group" aria-label="Confirm move">
            <p>Move this device from <strong>{data.source_group}</strong> to <strong>{chosen.name}</strong> (ID {chosen.external_id}) in VSA X now? The new group&apos;s policies apply.</p>
            <div className="flex gap-2">
              <button type="button" className="btn-danger" disabled={move.isPending} onClick={() => move.mutate()}>{move.isPending ? "Moving…" : "Move now"}</button>
              <button type="button" className="btn-secondary" disabled={move.isPending} onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        ) : null}
        {outcome ? <p role="status" className={outcome.ok ? "text-sm text-emerald-800" : "text-sm text-amber-900"}>{outcome.text}</p> : null}
        {move.isError ? <p role="alert" className="text-sm text-red-700">{describeError(move.error)}</p> : null}
        {propose.isError ? <p role="alert" className="text-sm text-red-700">{describeError(propose.error)}</p> : null}
        {propose.isSuccess ? <p role="status" className="text-sm text-emerald-800">Suggestion sent. An administrator applies it under <Link className="underline" to="/group-moves">Group moves</Link>.</p> : null}
      </section>
    );
  }}</QueryBoundary>;
}

/** Administrators move or reject a suggestion in one step; without moving switched on they approve or reject. */
function canMoveDirectly(proposal: Proposal, customer: Customer): boolean {
  return customer.my_capabilities.includes("customer.group_move.approve") && Boolean(proposal.self_approval_allowed) && proposal.execution_available;
}

function Review({ proposal, customer }: { proposal: Proposal; customer: Customer }) {
  const me = useMe();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] });
  const decision = useMutation({
    mutationFn: (value: "approved" | "rejected") => api.post<Proposal>(`/customers/${customer.id}/group-moves/${proposal.id}/review/`, { decision: value, reason: note }),
    onSettled: refresh,
  });
  const move = useMutation({ mutationFn: () => moveNow(customer.id, proposal.asset, proposal.target_group, note), onSettled: () => { setConfirming(false); refresh(); } });
  const mayDecide = customer.my_capabilities.includes("customer.group_move.approve") && (proposal.self_approval_allowed || me.email !== proposal.requested_by);
  const direct = canMoveDirectly(proposal, customer);
  const busy = decision.isPending || move.isPending;
  const outcome = move.data ? moveOutcome(move.data) : null;
  return <div className="space-y-3">
    <p className="text-sm"><strong>Reason:</strong> {proposal.reason}</p>
    <p className="text-xs text-slate-500">Suggested {formatUtc(proposal.created_at)} by {proposal.requested_by} · expires {formatUtc(proposal.expires_at)}</p>
    {proposal.reviewed_by ? <p className="text-sm">Decided by {proposal.reviewed_by}: {proposal.review_reason}</p> : null}
    {proposal.state === "pending" && mayDecide ? (
      <div className="space-y-2" role="group" aria-label="Decide">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Note (optional)" hint="Kept in the audit log.">{(id, h) => <input id={id} aria-describedby={h} className="input w-72" maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} />}</Field>
          {direct
            ? <button type="button" className="btn-primary" disabled={busy || proposal.expired} onClick={() => setConfirming(true)}>Move in VSA X…</button>
            : <button type="button" className="btn-primary" disabled={busy || proposal.expired} onClick={() => decision.mutate("approved")}>Approve</button>}
          <button type="button" className="btn-danger" disabled={busy} onClick={() => decision.mutate("rejected")}>Reject</button>
        </div>
        {!direct && proposal.execution_unavailable_reason ? <p className="text-xs text-amber-900">Approving only records the decision: {proposal.execution_unavailable_reason}</p> : null}
        {confirming ? (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" role="group" aria-label="Confirm move">
            <p>Move <strong>{proposal.device_name}</strong> from <strong>{proposal.source_group_name}</strong> to <strong>{proposal.target_group_name}</strong> (ID {proposal.target_group_external_id}) in VSA X now? The new group&apos;s policies apply.</p>
            <div className="flex gap-2">
              <button type="button" className="btn-danger" disabled={busy} onClick={() => move.mutate()}>{move.isPending ? "Moving…" : "Move now"}</button>
              <button type="button" className="btn-secondary" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        ) : null}
      </div>
    ) : proposal.state === "pending" ? <p className="text-xs text-slate-500">A different administrator must decide this suggestion.</p> : null}
    {outcome ? <p role="status" className={outcome.ok ? "text-sm text-emerald-800" : "text-sm text-amber-900"}>{outcome.text}</p> : null}
    {decision.isError ? <p role="alert" className="text-sm text-red-700">{describeError(decision.error)}</p> : null}
    {move.isError ? <p role="alert" className="text-sm text-red-700">{describeError(move.error)}</p> : null}
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
        <p className="text-xs text-slate-600">{["still_in_source_group", "accepted_not_applied"].includes(ex.error_code) ? "" : EXECUTION_TEXT[ex.state].help} {executionReason(ex)}</p>
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

/** Act on several selected rows one after another; every call is the normal per-move API. */
function BulkDecision({ customer, rows }: { customer: Customer; rows: Proposal[] }) {
  const me = useMe();
  const qc = useQueryClient();
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Outcome[]>([]);
  // Own suggestions are skipped only when a second approver is required (REQUIRE_SECOND_APPROVER).
  const mine = (p: Proposal) => p.requested_by === me.email && !p.self_approval_allowed;
  const pending = rows.filter((p) => p.state === "pending" && !p.expired && !mine(p));
  const approvedWaiting = rows.filter((p) => p.state === "approved" && p.execution_enabled && !mine(p));
  const movable = [...pending, ...approvedWaiting].filter((p) => canMoveDirectly(p, customer) || p.state === "approved");
  const approvable = pending.filter((p) => !canMoveDirectly(p, customer));
  const unconfirmed = rows.filter((p) => p.execution && ["unknown", "unverified", "sending"].includes(p.execution.state));
  const skipped = rows.length - new Set([...pending, ...approvedWaiting, ...unconfirmed].map((p) => p.id)).size;
  const base = `/customers/${customer.id}/group-moves`;
  const finish = (results: Outcome[]) => {
    setDone([...results]);
  };
  const loop = async (list: Proposal[], step: (p: Proposal) => Promise<{ ok: boolean; text: string; stop?: boolean }>) => {
    setBusy(true);
    setDone([]);
    const results: Outcome[] = [];
    for (const p of list) {
      try {
        const r = await step(p);
        results.push({ device: p.device_name, ok: r.ok, text: r.stop ? `${r.text} Stopped: the remaining moves were not sent.` : r.text });
        finish(results);
        if (r.stop) break;
      } catch (error) {
        results.push({ device: p.device_name, ok: false, text: describeError(error) });
        finish(results);
      }
    }
    setBusy(false);
    setSure(false);
    void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] });
  };
  const moveAll = () => loop(movable, async (p) => moveOutcome(
    p.state === "approved"
      ? await api.post<Proposal>(`${base}/${p.id}/execute/`, {})
      : await moveNow(customer.id, p.asset, p.target_group),
  ));
  const decideAll = (value: "approved" | "rejected", list: Proposal[]) => loop(list, async (p) => {
    const after = await api.post<Proposal>(`${base}/${p.id}/review/`, { decision: value });
    return { ok: true, text: after.state === "approved" ? "Approved" : "Rejected" };
  });
  const verifyAll = () => loop(unconfirmed, async (p) => {
    const after = await api.post<Proposal>(`${base}/${p.id}/verify/`, {});
    const state = after.execution?.state ?? "unknown";
    return { ok: state === "succeeded", text: EXECUTION_TEXT[state].label };
  });
  return (
    <div className="flex w-full flex-col gap-2 text-sm" role="group" aria-label="Decide selected proposals">
      {skipped ? <p className="text-xs text-slate-600">{skipped} selected row(s) skipped: expired, already decided or already sent{rows.some((p) => p.requested_by === me.email && !p.self_approval_allowed) ? ", or your own (a second administrator must decide)" : ""}.</p> : null}
      {approvable.length && !movable.length ? (
        <p className="text-xs text-amber-900">
          Approving only records the decision: {approvable[0]?.execution_unavailable_reason || "moving in VSA X is not available for this integration."}
          {" "}A super admin switches moves on under Settings → Integrations → Edit.
        </p>
      ) : null}
      {movable.length || pending.length ? (
        <div className="flex flex-wrap items-center gap-2">
          {movable.length ? (
            <>
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
                Move {movable.length} device{movable.length === 1 ? "" : "s"} in VSA X now (the new group&apos;s policies apply)
              </label>
              <button type="button" className="btn-primary" disabled={busy || !sure} onClick={() => void moveAll()}>Move in VSA X ({movable.length})</button>
            </>
          ) : null}
          {approvable.length ? <button type="button" className="btn-secondary" disabled={busy} onClick={() => void decideAll("approved", approvable)}>Approve ({approvable.length})</button> : null}
          {pending.length ? <button type="button" className="btn-danger" disabled={busy} onClick={() => void decideAll("rejected", pending)}>Reject ({pending.length})</button> : null}
        </div>
      ) : null}
      {unconfirmed.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => void verifyAll()}>Verify in VSA X ({unconfirmed.length})</button>
          <span className="text-xs text-slate-600">Reads each device&apos;s group back from VSA X; nothing is sent again.</span>
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
  const VIEWS: [string, string][] = [["waiting", "Waiting for decision"], ["to_move", "Approved, not moved yet"], ["to_verify", "Sent, not confirmed"], ["", "All proposals"]];
  return <div className="space-y-3">
    <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
      {VIEWS.map(([v, label]) => <button key={v || "all"} type="button" aria-pressed={view === v} className="list-preset" onClick={() => update({ view: v }, true)}>{label}</button>)}
    </div>
    <QueryBoundary query={query}>{(data) => <div className="space-y-4">
    {data.count && customer.my_capabilities.includes("customer.group_move.approve") ? <p className="text-xs text-slate-600">Tick the box in the table header to select all {Math.min(data.count, 200)} on this page, then choose {view === "to_verify" ? "Verify in VSA X" : "Move in VSA X"}.</p> : null}
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

function Workspace({ customer }: { customer: Customer }) {
  const { filters, update } = useUrlFilters({ tab: "results" });
  const canList = customer.my_capabilities.includes("customer.group_move.propose");
  const tabs = [
    { id: "results", label: "Suggestions & results", content: <Requests customer={customer} /> },
    ...(canList ? [{ id: "list", label: "Move a list", content: <MoveList customer={customer} /> }] : []),
  ];
  return <Tabs label="Group moves" tabs={tabs} active={tabs.some((t) => t.id === filters.tab) ? filters.tab : "results"} onChange={(id) => update({ tab: id }, true)} />;
}

export function GroupMovesPage() {
  const { selected } = useCustomers();
  return <>
    <PageHeader title="Group moves" subtitle="Move a list of devices to a group, review suggestions from engineers and see the result of every move." />
    {!selected ? <SelectCustomer /> : <Workspace key={selected.id} customer={selected} />}
  </>;
}
