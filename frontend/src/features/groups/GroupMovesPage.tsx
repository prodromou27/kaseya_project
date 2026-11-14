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

type Proposal = {
  id: string; asset: string; device_name: string; source_group_name: string;
  target_group_name: string; target_group_external_id: string; reason: string; policy_impact: string;
  state: "pending" | "approved" | "rejected"; requested_by: string; reviewed_by: string | null;
  review_reason: string; created_at: string; expires_at: string; expired: boolean; execution_enabled: false;
};
type MoveOptions = {
  source_group: string; policy_impact: string; execution_enabled: false;
  source_is_onboarding: boolean; suggestion_note: string; suggestions_ambiguous: boolean;
  suggestions: { id: string; name: string; matches: { cidr: string; addresses: string[] }[] }[];
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
          <strong>{suggestion.name}</strong>: {suggestion.matches.map((match) => `${match.addresses.join(", ")} in ${match.cidr}`).join("; ")}
          {customer.my_capabilities.includes("customer.group_move.propose") ? <button type="button" className="btn-secondary ml-2" onClick={() => setTarget(suggestion.id)}>Use {suggestion.name}</button> : null}
        </li>)}</ul> : <p>No approved group subnet matches the reported addresses. Placement is not classified as incorrect.</p>}
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
    mutationFn: (value: "approved" | "rejected") => api.post<Proposal>(`/customers/${customer.id}/group-moves/${proposal.id}/review/`, { decision: value, reason }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] }),
  });
  return <div className="space-y-3">
    <p className="text-sm"><strong>Reason:</strong> {proposal.reason}</p>
    <p className="text-sm text-amber-900">{proposal.policy_impact}</p>
    <p className="text-xs text-slate-500">Requested {formatUtc(proposal.created_at)} · expires {formatUtc(proposal.expires_at)} · {proposal.requested_by}</p>
    {proposal.reviewed_by ? <p className="text-sm">Reviewed by {proposal.reviewed_by}: {proposal.review_reason}</p> : null}
    {proposal.state === "pending" && customer.my_capabilities.includes("customer.group_move.approve") && me.email !== proposal.requested_by ? (
      <form className="flex flex-wrap items-end gap-2" aria-label="Independent move review" onSubmit={(event) => { event.preventDefault(); decision.mutate("approved"); }}>
        <Field label="Review reason">{(id) => <input id={id} className="input w-80" required minLength={10} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} />}</Field>
        <button type="submit" className="btn-primary" disabled={decision.isPending || proposal.expired}>Approve proposal only</button>
        <button type="button" className="btn-danger" disabled={decision.isPending || reason.trim().length < 10} onClick={() => decision.mutate("rejected")}>Reject proposal</button>
      </form>
    ) : proposal.state === "pending" ? <p className="text-xs text-slate-500">A different authorized administrator must review this proposal.</p> : null}
    {decision.isError ? <p role="alert" className="text-sm text-red-700">{describeError(decision.error)}</p> : null}
  </div>;
}

function Requests({ customer }: { customer: Customer }) {
  const { page, setPage } = useUrlFilters({});
  const [open, setOpen] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["group-moves", customer.id, page], queryFn: ({ signal }) => api.get<Paginated<Proposal>>(`/customers/${customer.id}/group-moves/`, { page }, signal) });
  const selected = query.data?.results.find((proposal) => proposal.id === open);
  return <QueryBoundary query={query}>{(data) => <div className="space-y-4">
    <DataTable caption="Group move proposals" rows={data.results} total={data.count} page={page} onPageChange={setPage} getRowId={(row) => row.id}
      emptyTitle="No group changes have been proposed." emptyHint="Open a device's Operations tab to propose a change. Execution remains disabled."
      columns={[
        { header: "Device", cell: ({ row }) => <Link className="font-medium text-sky-800 underline" to={`/assets/${row.original.asset}`}>{row.original.device_name}</Link> },
        { header: "From", accessorKey: "source_group_name" }, { header: "To", accessorKey: "target_group_name" },
        { header: "Proposed by", accessorKey: "requested_by" },
        { header: "State", cell: ({ row }) => <Badge tone={row.original.expired && row.original.state === "pending" ? "warn" : "neutral"}>{row.original.expired && row.original.state === "pending" ? "expired" : row.original.state}</Badge> },
        { header: "Review", cell: ({ row }) => <button type="button" className="btn-secondary" aria-expanded={open === row.original.id} onClick={() => setOpen(open === row.original.id ? null : row.original.id)}>Review proposal</button> },
      ]} />
    {selected ? <section className="investigation-card" aria-label="Selected group move proposal"><Review key={selected.id} proposal={selected} customer={customer} /></section> : null}
  </div>}</QueryBoundary>;
}

export function GroupMovesPage() {
  const { selected } = useCustomers();
  return <>
    <PageHeader title="Group move proposals" subtitle="Customer-scoped requests and independent approvals. Vendor execution is disabled." />
    {!selected ? <SelectCustomer /> : <Requests key={selected.id} customer={selected} />}
  </>;
}
