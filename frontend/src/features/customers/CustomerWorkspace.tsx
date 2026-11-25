import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import { CAP, type Customer, type OsUpdateSummary, type Paginated, type ReportRun } from "../../lib/types";
import { KpiTiles } from "../dashboard/KpiTiles";
import { Go, Metric, Panel, ShareBar } from "../dashboard/parts";
import { DataSources } from "../inventory/DataSources";
import { LatestRun } from "../reports/ReportFollowUp";

type ComplianceOverview = { baselines: { id: string; name: string; score_pct: number | null; devices_in_scope: number; totals: Record<"pass" | "fail" | "unknown", number> }[] };
type ThirdParty = { totals: { outdated: number; outdated_not_covered: number; outdated_no_policy: number; outdated_covered: number } };
type ScopeFields = { scope_type: "organization" | "site" | "group"; scope_external_id: string; scope_name: string; fields: { name: string; value: string; type: string }[] }[];
type Subnets = { subnets: number; by_status: { unassigned: number }; mixed_groups: number; devices_outside_expected: number };
type ServerTotals = { servers: number; needs_attention: number; unassigned: number };

const BASELINES_SHOWN = 4;
const SCOPES_SHOWN = 6;

/** Produces the monthly scorecard PDF and offers the file in place when it is ready. */
export function ScorecardButton({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const scorecard = useMutation({
    mutationFn: () => api.post<ReportRun>(`/customers/${customer.id}/reports/`, { report_type: "customer_scorecard", format: "pdf", filters: {} }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports", customer.id] }),
  });
  if (!customer.my_capabilities.includes(CAP.export)) return null;
  return (
    <div className="flex flex-wrap items-center gap-3">
      {scorecard.data ? <LatestRun key={scorecard.data.id} runId={scorecard.data.id} /> : null}
      {scorecard.isError ? <span role="alert" className="text-sm text-red-700">{describeError(scorecard.error)}</span> : null}
      <button type="button" className="btn-primary" disabled={scorecard.isPending} onClick={() => scorecard.mutate()}>Monthly scorecard (PDF)</button>
    </div>
  );
}

/** Patching, compliance, servers and network: one row of equal panels, each number linked to its investigation. */
export function AttentionPanels({ customer }: { customer: Customer }) {
  const id = customer.id;
  const updates = useQuery({ queryKey: ["os-updates", id, "summary"], queryFn: ({ signal }) => api.get<OsUpdateSummary>(`/customers/${id}/os-updates/summary/`, undefined, signal) });
  const compliance = useQuery({ queryKey: ["compliance", id, "overview"], queryFn: ({ signal }) => api.get<ComplianceOverview>(`/customers/${id}/compliance-baselines/overview/`, undefined, signal) });
  const thirdParty = useQuery({ queryKey: ["software", id, "third-party", "", true], queryFn: ({ signal }) => api.get<ThirdParty>(`/customers/${id}/software/third-party/`, { outdated: "true" }, signal) });
  const subnets = useQuery({ queryKey: ["subnets", id, "", false, false, ""], queryFn: ({ signal }) => api.get<Subnets>(`/customers/${id}/subnets/`, undefined, signal) });
  const servers = useQuery({ queryKey: ["servers", id, "summary"], queryFn: ({ signal }) => api.get<{ totals: ServerTotals }>(`/customers/${id}/servers/`, undefined, signal) });

  const u = updates.data;
  const available = u && u.devices_reporting_updates > 0 ? u.devices_by_severity.Critical ?? 0 : null;
  const tp = thirdParty.data?.totals;
  const noRule = tp ? tp.outdated_not_covered + tp.outdated_no_policy : null;
  const sn = subnets.data;
  const st = servers.data?.totals;
  const baselines = compliance.data?.baselines ?? [];
  const open = (to: string, text = "Open") => <Go customer={customer} to={to}>{text} →</Go>;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <Panel title="Patching" action={open("/software?view=third-party")}>
        <Metric pending={updates.isPending} customer={customer} label="Devices with Critical OS updates" value={available} attention={(available ?? 0) > 0} to="/windows-updates?state=available&severity=Critical" />
        <Metric pending={thirdParty.isPending} customer={customer} label="Outdated third-party installs" value={tp?.outdated ?? null} attention={(tp?.outdated ?? 0) > 0} to="/software?view=third-party" />
        <Metric pending={thirdParty.isPending} customer={customer} label="…with no rule in patch policy" value={noRule} attention={(noRule ?? 0) > 0} to="/software?view=third-party" />
      </Panel>
      <Panel title="Compliance" action={open("/compliance")}>
        {baselines.length ? baselines.slice(0, BASELINES_SHOWN).map((b) => (
          <div key={b.id} className="space-y-0.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate" title={b.name}><Go customer={customer} to={`/compliance/${b.id}`}>{b.name}</Go></span>
              <span className="shrink-0 tabular-nums font-semibold text-slate-900">{b.score_pct === null ? "—" : `${b.score_pct}%`}</span>
            </div>
            <ShareBar value={b.score_pct} of={100} tone={(b.score_pct ?? 0) >= 80 ? "good" : "warn"} percent={false} />
            <p className="text-[11px] text-slate-500">{b.totals.fail} not compliant of {b.devices_in_scope}</p>
          </div>
        )) : <p className="text-slate-500">{compliance.isPending ? "Loading…" : "No baselines yet."}</p>}
        {baselines.length > BASELINES_SHOWN ? <p className="text-xs">{open("/compliance", `${baselines.length - BASELINES_SHOWN} more baselines`)}</p> : null}
      </Panel>
      <Panel title="Servers" action={open("/servers")}>
        <Metric pending={servers.isPending} customer={customer} label="Servers" value={st?.servers ?? null} to="/servers" />
        <Metric pending={servers.isPending} customer={customer} label="Need patching or an upgrade" value={st?.needs_attention ?? null} attention={(st?.needs_attention ?? 0) > 0} to="/servers?attention=true" />
        <Metric pending={servers.isPending} customer={customer} label="Without an owner" value={st?.unassigned ?? null} attention={(st?.unassigned ?? 0) > 0} to="/servers?owner=none" />
      </Panel>
      <Panel title="Network" action={open("/groups?view=subnets")}>
        <Metric pending={subnets.isPending} customer={customer} label="Subnets observed" value={sn?.subnets ?? null} to="/groups?view=subnets" />
        <Metric pending={subnets.isPending} customer={customer} label="Not in an approved subnet" value={sn?.by_status.unassigned ?? null} attention={(sn?.by_status.unassigned ?? 0) > 0} to="/groups?view=subnets" />
        <Metric pending={subnets.isPending} customer={customer} label="Devices outside approved scope" value={sn?.devices_outside_expected ?? null} attention={(sn?.devices_outside_expected ?? 0) > 0} to="/groups?view=subnets" />
      </Panel>
    </div>
  );
}

/** The five latest reports, with links to build one or see them all. Hidden without the export capability. */
export function RecentReports({ customer }: { customer: Customer }) {
  const canExport = customer.my_capabilities.includes(CAP.export);
  const reports = useQuery({ queryKey: ["reports", customer.id, 1], queryFn: ({ signal }) => api.get<Paginated<ReportRun>>(`/customers/${customer.id}/reports/`, { page: 1 }, signal), enabled: canExport,
    refetchInterval: (q) => (q.state.data?.results.some((r) => r.state === "queued" || r.state === "running") ? 2000 : false) });
  if (!canExport) return null;
  return (
    <Panel title="Recent reports" action={<span className="flex gap-3"><Go customer={customer} to="/reports?tab=custom">New report →</Go><Go customer={customer} to="/reports?tab=history">All →</Go></span>}>
      {reports.data?.results.length ? reports.data.results.slice(0, 5).map((r) => (
        <div key={r.id} className="flex items-baseline justify-between gap-3">
          {r.state === "completed" ? <a className="min-w-0 truncate text-sky-800 hover:underline" href={`/api/v1/reports/${r.id}/download/`}>{r.title ?? r.report_type}</a> : <span className="min-w-0 truncate">{r.title ?? r.report_type}</span>}
          <span className="shrink-0 text-xs text-slate-500">{formatUtc(r.created_at)}{r.state === "completed" ? "" : ` · ${r.state}`}</span>
        </div>
      )) : <p className="text-slate-500">{reports.isPending ? "Loading…" : "No reports yet."}</p>}
    </Panel>
  );
}

/** Approved VSA custom fields of the organisation, sites and groups, in columns; long lists fold. */
export function ScopeDetails({ customer }: { customer: Customer }) {
  const [all, setAll] = useState(false);
  const scopeFields = useQuery({ queryKey: ["scope-custom-fields", customer.id], queryFn: ({ signal }) => api.get<ScopeFields>(`/customers/${customer.id}/scope-custom-fields/`, undefined, signal) });
  const scopes = scopeFields.data ?? [];
  if (!scopes.length) return null;
  const shown = all ? scopes : scopes.slice(0, SCOPES_SHOWN);
  return (
    <Panel title="Details from VSA" action={<span className="text-slate-500">Approved custom fields</span>}>
      <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((scope) => (
          <div key={`${scope.scope_type}-${scope.scope_external_id}`} className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{scope.scope_type === "organization" ? "Organisation" : scope.scope_type === "site" ? `Site ${scope.scope_name}` : `Group ${scope.scope_name}`}</p>
            {scope.fields.map((f) => <div key={f.name} className="flex items-baseline justify-between gap-3"><span className="min-w-0 truncate text-slate-600">{f.name}</span><span className="min-w-0 truncate font-medium text-slate-900" title={f.value}>{f.value || "—"}</span></div>)}
          </div>
        ))}
      </div>
      {scopes.length > SCOPES_SHOWN ? (
        <button type="button" className="text-xs text-sky-800 hover:underline" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${scopes.length} sites and groups`}
        </button>
      ) : null}
    </Panel>
  );
}

/** Everything about one customer at a glance (the customer's Summary tab): same blocks as the dashboard. */
export function CustomerWorkspace({ customer }: { customer: Customer }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 [&>section]:mb-0"><DataSources customer={customer} compact /></div>
        <ScorecardButton customer={customer} />
      </div>
      <KpiTiles customer={customer} />
      <AttentionPanels customer={customer} />
      <div className="flex flex-col gap-3 xl:flex-row">
        <div className="min-w-0 empty:hidden xl:flex-[2]"><ScopeDetails customer={customer} /></div>
        <div className="min-w-0 empty:hidden xl:flex-1"><RecentReports customer={customer} /></div>
      </div>
    </div>
  );
}
