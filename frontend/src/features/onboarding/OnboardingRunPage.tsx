import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Notice, PageHeader, type Tone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  type Classification,
  type Customer,
  type Paginated,
  type ReconciliationResult,
  type ReconciliationRun,
} from "../../lib/types";

export const CLASS_LABEL: Record<Classification, string> = {
  MATCHED_CORRECT: "Matched, correct",
  MATCHED_WRONG_GROUP: "Wrong group",
  MATCHED_WRONG_SITE: "Wrong site",
  REVIEW_WRONG_ORGANIZATION: "Organisation differs (review)",
  NOT_FOUND_IN_COMPLETE_SNAPSHOT: "Not found in snapshot",
  AMBIGUOUS: "Ambiguous (review)",
  DUPLICATE_INPUT: "Duplicate row",
  INVALID_INPUT: "Invalid row",
};
const CLASS_TONE: Record<Classification, Tone> = {
  MATCHED_CORRECT: "good",
  MATCHED_WRONG_GROUP: "warn",
  MATCHED_WRONG_SITE: "warn",
  REVIEW_WRONG_ORGANIZATION: "bad",
  NOT_FOUND_IN_COMPLETE_SNAPSHOT: "bad",
  AMBIGUOUS: "warn",
  DUPLICATE_INPUT: "neutral",
  INVALID_INPUT: "neutral",
};
const FILTERS: { id: string; label: string; classification?: string; kind?: string; review?: string }[] = [
  { id: "all", label: "All expected" },
  { id: "correct", label: "Matched correct", classification: "MATCHED_CORRECT" },
  { id: "group", label: "Wrong group", classification: "MATCHED_WRONG_GROUP" },
  { id: "site", label: "Wrong site / org", classification: "MATCHED_WRONG_SITE,REVIEW_WRONG_ORGANIZATION" },
  { id: "notfound", label: "Not found", classification: "NOT_FOUND_IN_COMPLETE_SNAPSHOT" },
  { id: "ambiguous", label: "Ambiguous", classification: "AMBIGUOUS" },
  { id: "invalid", label: "Duplicate / invalid", classification: "DUPLICATE_INPUT,INVALID_INPUT" },
  { id: "review", label: "Needs review", review: "pending" },
  { id: "unexpected", label: "Unexpected in VSA", kind: "unexpected" },
];

function ClassBadge({ value }: { value: Classification | "" }) {
  return value ? <Badge tone={CLASS_TONE[value]}>{CLASS_LABEL[value]}</Badge> : null;
}

function placement(p: ReconciliationResult["actual"]) {
  if (!p.hostname && !p.source_id) return <span className="text-slate-400">—</span>;
  return (
    <span className="text-xs">
      <strong>{p.hostname}</strong> · {p.organization || p.organization_id} / {p.site || p.site_id || "?"} / {p.group || p.group_id || "no group"}
    </span>
  );
}

function ReviewControls({ customer, run, item }: { customer: Customer; run: ReconciliationRun; item: ReconciliationResult }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (body: { decision: string; asset?: string }) =>
      api.post<ReconciliationResult>(`/customers/${customer.id}/onboarding/runs/${run.id}/results/${item.id}/review/`, { ...body, note }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["onboarding-results", run.id] }),
  });
  return (
    <div className="space-y-1 text-xs">
      {item.candidates.map((c) => (
        <div key={c.asset_id} className="flex items-center gap-2">
          <span><strong>{c.hostname}</strong> · {c.site || c.site_id} / {c.group || c.group_id || "no group"}</span>
          <button type="button" className="btn-secondary py-0.5 text-xs" disabled={decide.isPending}
            onClick={() => decide.mutate(item.classification === "AMBIGUOUS" ? { decision: "match", asset: c.asset_id } : { decision: "confirm" })}>
            Confirm {c.hostname}
          </button>
        </div>
      ))}
      {item.classification === "REVIEW_WRONG_ORGANIZATION" ? (
        <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => decide.mutate({ decision: "confirm" })}>Confirm match</button>
      ) : null}
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor={`note-${item.id}`}>Review note for row {item.row_number}</label>
        <input id={`note-${item.id}`} className="input py-0.5 text-xs" placeholder="note (optional)" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        <button type="button" className="btn-secondary py-0.5 text-xs" disabled={decide.isPending} onClick={() => decide.mutate({ decision: "no_match" })}>
          Not this device
        </button>
      </div>
      {decide.isError ? <p role="alert" className="text-red-700">{describeError(decide.error)}</p> : null}
    </div>
  );
}

function Results({ customer, run }: { customer: Customer; run: ReconciliationRun }) {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const f = FILTERS.find((x) => x.id === filter) ?? { id: "all", label: "All expected" };
  const canReview = customer.my_capabilities.includes(CAP.sync);
  const query = useQuery({
    queryKey: ["onboarding-results", run.id, filter, page],
    queryFn: ({ signal }) =>
      api.get<Paginated<ReconciliationResult>>(
        `/customers/${customer.id}/onboarding/runs/${run.id}/results/`,
        { kind: f.kind ?? "expected", classification: f.classification, review_state: f.review, page },
        signal,
      ),
  });
  return (
    <>
      <div role="group" aria-label="Result filter" className="mb-2 flex flex-wrap gap-1">
        {FILTERS.map((x) => (
          <button key={x.id} type="button" aria-pressed={filter === x.id}
            className={filter === x.id ? "btn-primary py-1 text-xs" : "btn-secondary py-1 text-xs"}
            onClick={() => { setFilter(x.id); setPage(1); }}>
            {x.label}
          </button>
        ))}
      </div>
      <QueryBoundary query={query}>
        {(data) =>
          f.kind === "unexpected" ? (
            <DataTable caption="Unexpected VSA devices" rows={data.results} total={data.count} page={page} onPageChange={setPage}
              getRowId={(r) => r.id} emptyTitle="Every VSA device in the snapshot is represented in the expected list."
              columns={[
                { header: "Device", cell: ({ row }) => row.original.asset ? <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset}`}>{row.original.actual.hostname}</Link> : row.original.actual.hostname },
                { header: "Placement", cell: ({ row }) => placement(row.original.actual) },
                { header: "Last seen", cell: ({ row }) => formatUtc(row.original.actual.last_seen_online || null) },
                { header: "Note", cell: ({ row }) => row.original.pending_review_row ? <Badge tone="info">candidate of row {row.original.pending_review_row} (pending review)</Badge> : null },
              ]} />
          ) : (
            <DataTable caption="Expected rows" rows={data.results} total={data.count} page={page} onPageChange={setPage}
              getRowId={(r) => r.id} emptyTitle="No rows in this category."
              columns={[
                { header: "Row", accessorKey: "row_number" },
                { header: "Input", cell: ({ row }) => (
                  <span className="text-xs">{["hostname", "fqdn", "serial_number", "mac", "ip_address", "source_device_id", "asset_tag"]
                    .filter((k) => row.original.input[k]).map((k) => `${k.replace(/_/g, " ")}: ${row.original.input[k]}`).join(" · ") || "— no identifier —"}</span>
                ) },
                { header: "Expected", cell: ({ row }) => <span className="text-xs">{[row.original.input.expected_organization, row.original.input.expected_site, row.original.input.expected_group].filter(Boolean).join(" / ") || "—"}</span> },
                { header: "Result", cell: ({ row }) => (
                  <span className="flex flex-col gap-1">
                    <ClassBadge value={row.original.classification} />
                    {row.original.reviewed_classification ? <span className="text-xs">reviewed → <ClassBadge value={row.original.reviewed_classification} /> by {row.original.reviewed_by}</span> : null}
                    {row.original.flags.map((fl) => <Badge key={fl} tone="neutral">{fl}</Badge>)}
                  </span>
                ) },
                { header: "VSA device", cell: ({ row }) => placement(row.original.actual) },
                { header: "Evidence / review", cell: ({ row }) =>
                    row.original.review_state === "pending" && canReview ? <ReviewControls customer={customer} run={run} item={row.original} />
                      : <details className="text-xs"><summary>evidence</summary><pre className="whitespace-pre-wrap">{JSON.stringify(row.original.evidence, null, 1)}</pre></details> },
              ]} />
          )
        }
      </QueryBoundary>
    </>
  );
}

function View({ customer, runId }: { customer: Customer; runId: string }) {
  const query = useQuery({
    queryKey: ["onboarding-run", runId],
    queryFn: ({ signal }) => api.get<ReconciliationRun>(`/customers/${customer.id}/onboarding/runs/${runId}/`, undefined, signal),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.state) ? 1500 : false),
  });
  const canExport = customer.my_capabilities.includes(CAP.export);
  const exportBase = `/api/v1/customers/${customer.id}/onboarding/runs/${runId}/export/`;
  return (
    <QueryBoundary query={query}>
      {(run) => {
        const s = run.summary;
        const c = s.classifications ?? {};
        return (
          <>
            <PageHeader title={`Onboarding check — ${run.upload_name}`}
              subtitle={<span>sheet {run.sheet} · started {formatUtc(run.created_at)} by {run.requested_by} · snapshot {run.generation.slice(0, 8)} published {formatUtc(s.generation?.published_at || null)} · data basis {run.data_basis} · {run.logic_version}</span>}
              actions={run.state === "completed" && canExport ? (
                <>
                  <a className="btn-primary" href={`${exportBase}?output=xlsx`}>Download workbook (XLSX)</a>
                  <a className="btn-secondary" href={`${exportBase}?output=csv&part=expected`}>CSV</a>
                  <a className="btn-secondary" href={`${exportBase}?output=csv&part=unexpected`}>Unexpected CSV</a>
                </>
              ) : undefined} />
            {run.state === "failed" ? <Notice tone="bad">The comparison failed ({run.error_code}).</Notice> : null}
            {["queued", "running"].includes(run.state) ? <Notice tone="info">Comparing…</Notice> : null}
            {run.state === "completed" ? (
              <>
                <div className="mb-3 grid grid-cols-2 gap-2 text-sm md:grid-cols-4 lg:grid-cols-8">
                  {[
                    ["Expected rows", s.expected_rows],
                    ["Matched correct", c.MATCHED_CORRECT ?? 0],
                    ["Wrong group", c.MATCHED_WRONG_GROUP ?? 0],
                    ["Wrong site / org", (c.MATCHED_WRONG_SITE ?? 0) + (c.REVIEW_WRONG_ORGANIZATION ?? 0)],
                    ["Not found", c.NOT_FOUND_IN_COMPLETE_SNAPSHOT ?? 0],
                    ["Ambiguous", c.AMBIGUOUS ?? 0],
                    ["Duplicate / invalid", (c.DUPLICATE_INPUT ?? 0) + (c.INVALID_INPUT ?? 0)],
                    ["Unexpected in VSA", s.unexpected_vsa_assets ?? 0],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="rounded border border-slate-200 bg-white px-3 py-2">
                      <div className="text-xs text-slate-500">{label}</div>
                      <div className="text-lg font-semibold">{value}</div>
                    </div>
                  ))}
                </div>
                <Notice tone="info">
                  <ul className="list-disc pl-4">
                    {(s.notes ?? []).map((n) => <li key={n}>{n}</li>)}
                    <li>Device moves are not performed by this portal (VSA X stays read-only).</li>
                    {Object.entries(s.parameters?.flags_not_evaluated ?? {}).map(([k, v]) => <li key={k}>{k} not evaluated: {v}.</li>)}
                    {s.unexpected_pending_review ? <li>{s.unexpected_pending_review} VSA device(s) are candidates of rows awaiting review.</li> : null}
                  </ul>
                </Notice>
                {run.stale_source_acknowledged ? <Notice tone="warn">Compared against a stale snapshot (acknowledged).</Notice> : null}
                <div className="mt-4"><Results customer={customer} run={run} /></div>
              </>
            ) : null}
          </>
        );
      }}
    </QueryBoundary>
  );
}

export function OnboardingRunPage() {
  const { runId = "" } = useParams();
  const { selected } = useCustomers();
  return (
    <>
      <p className="mb-1 text-sm"><Link to="/onboarding" className="text-sky-800 hover:underline">← Onboarding check</Link></p>
      {!selected ? <EmptyState title="Select a customer" /> : <View customer={selected} runId={runId} />}
    </>
  );
}
