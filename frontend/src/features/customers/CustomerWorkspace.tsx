import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Badge } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import { CAP, type Customer, type DatasetStatus, type HealthSummary, type OsUpdateSummary, type Paginated, type ReportRun } from "../../lib/types";

type ComplianceOverview = { baselines: { id: string; name: string; score_pct: number | null; devices_in_scope: number; totals: Record<"pass" | "fail" | "unknown", number> }[] };
type ThirdParty = { totals: { outdated: number; outdated_not_covered: number; outdated_no_policy: number; outdated_covered: number } };
type Subnets = { subnets: number; by_status: { unassigned: number }; mixed_groups: number; devices_outside_expected: number };

const sum = (r: Record<string, number> | undefined, keys: string[]) => (r ? keys.reduce((n, k) => n + (r[k] ?? 0), 0) : null);

/** A link that first makes this customer the selected one, so the target page opens on the right data. */
function Go({ customer, to, children }: { customer: Customer; to: string; children: ReactNode }) {
  const { select } = useCustomers();
  return <Link to={to} onClick={() => select(customer.id)} className="text-sky-800 hover:underline">{children}</Link>;
}

function Card({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">{title}</h2>
      <div className="flex-1 space-y-2 text-sm">{children}</div>
      {footer ? <div className="mt-3 border-t border-slate-100 pt-2 text-xs">{footer}</div> : null}
    </section>
  );
}

function Line({ label, value, attention, customer, to, pending }: { label: string; value: number | string | null; attention?: boolean; customer: Customer; to?: string; pending?: boolean }) {
  const shown = value === null ? (pending ? "…" : "—") : value;
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-slate-600">{label}</span>
      <span className={`tabular-nums font-semibold ${attention ? "text-amber-800" : "text-slate-900"}`}>
        {to && value !== null ? <Go customer={customer} to={to}>{shown}</Go> : shown}
      </span>
    </div>
  );
}

/** Customer workspace: everything that needs attention for one customer, each number linked to its investigation. */
export function CustomerWorkspace({ customer }: { customer: Customer }) {
  const id = customer.id;
  const canExport = customer.my_capabilities.includes(CAP.export);
  const health = useQuery({ queryKey: ["device-health", id, "summary"], queryFn: ({ signal }) => api.get<HealthSummary>(`/customers/${id}/device-health/summary/`, undefined, signal) });
  const updates = useQuery({ queryKey: ["os-updates", id, "summary"], queryFn: ({ signal }) => api.get<OsUpdateSummary>(`/customers/${id}/os-updates/summary/`, undefined, signal) });
  const compliance = useQuery({ queryKey: ["compliance", id, "overview"], queryFn: ({ signal }) => api.get<ComplianceOverview>(`/customers/${id}/compliance-baselines/overview/`, undefined, signal) });
  const thirdParty = useQuery({ queryKey: ["software", id, "third-party", "", true], queryFn: ({ signal }) => api.get<ThirdParty>(`/customers/${id}/software/third-party/`, { outdated: "true" }, signal) });
  const subnets = useQuery({ queryKey: ["subnets", id, "", false, false, ""], queryFn: ({ signal }) => api.get<Subnets>(`/customers/${id}/subnets/`, undefined, signal) });
  const datasets = useQuery({ queryKey: ["datasets", id], queryFn: ({ signal }) => api.get<DatasetStatus[]>(`/customers/${id}/datasets/`, undefined, signal) });
  const qc = useQueryClient();
  const scorecard = useMutation({
    mutationFn: () => api.post<ReportRun>(`/customers/${id}/reports/`, { report_type: "customer_scorecard", format: "pdf", filters: {} }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports", id] }),
  });
  const reports = useQuery({ queryKey: ["reports", id, 1], queryFn: ({ signal }) => api.get<Paginated<ReportRun>>(`/customers/${id}/reports/`, { page: 1 }, signal), enabled: canExport,
    refetchInterval: (q) => (q.state.data?.results.some((r) => r.state === "queued" || r.state === "running") ? 2000 : false) });

  const h = health.data;
  const offline = sum(h?.dimensions.connectivity, ["offline", "stale", "never_seen"]);
  const disk = h?.dimensions.disk?.critical ?? null;
  const av = sum(h?.dimensions.antivirus, ["disabled", "enabled_outdated"]);
  const critical = updates.data && updates.data.devices_reporting_updates > 0 ? updates.data.devices_by_severity.Critical ?? 0 : null;
  const tp = thirdParty.data?.totals;
  const sn = subnets.data;
  return (
    <div className="space-y-4">
      {canExport ? (
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" disabled={scorecard.isPending} onClick={() => scorecard.mutate()}>Monthly scorecard (PDF)</button>
          {scorecard.isSuccess ? <span role="status" className="text-sm text-emerald-800">Scorecard requested; it appears under Recent reports when ready. Schedule it monthly under Reports → Definitions &amp; schedules.</span> : null}
          {scorecard.isError ? <span role="alert" className="text-sm text-red-700">{describeError(scorecard.error)}</span> : null}
        </div>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card title="Device health" footer={<Go customer={customer} to="/device-health">Open device health</Go>}>
          <Line pending={health.isPending} customer={customer} label="Devices" value={h?.devices ?? null} to="/assets" />
          <Line pending={health.isPending} customer={customer} label="Offline or not seen" value={offline} attention={(offline ?? 0) > 0} to="/device-health?connectivity=offline,stale,never_seen" />
          <Line pending={health.isPending} customer={customer} label="Disk critical" value={disk} attention={(disk ?? 0) > 0} to="/device-health?disk=critical" />
          <Line pending={health.isPending} customer={customer} label="Antivirus issues" value={av} attention={(av ?? 0) > 0} to="/device-health?antivirus=disabled,enabled_outdated" />
        </Card>
        <Card title="Compliance" footer={<Go customer={customer} to="/compliance">Open compliance</Go>}>
          {compliance.data?.baselines.length ? compliance.data.baselines.map((b) => (
            <div key={b.id} className="flex items-baseline justify-between gap-3">
              <Go customer={customer} to={`/compliance/${b.id}`}>{b.name}</Go>
              <span className="tabular-nums font-semibold text-slate-900">{b.score_pct === null ? "—" : `${b.score_pct}%`} <span className="text-xs font-normal text-slate-500">{b.totals.fail} not compliant</span></span>
            </div>
          )) : <p className="text-slate-500">{compliance.isPending ? "Loading…" : "No baselines yet."}</p>}
        </Card>
        <Card title="Patching" footer={<Go customer={customer} to="/software?view=third-party">Open third-party patching</Go>}>
          <Line pending={updates.isPending} customer={customer} label="Devices with Critical OS updates" value={critical} attention={(critical ?? 0) > 0} to="/windows-updates?state=available&severity=Critical" />
          <Line pending={thirdParty.isPending} customer={customer} label="Outdated third-party installs" value={tp?.outdated ?? null} attention={(tp?.outdated ?? 0) > 0} to="/software?view=third-party" />
          <Line pending={thirdParty.isPending} customer={customer} label="…with no rule in patch policy" value={tp ? tp.outdated_not_covered + tp.outdated_no_policy : null} attention={(tp?.outdated_not_covered ?? 0) + (tp?.outdated_no_policy ?? 0) > 0} to="/software?view=third-party" />
        </Card>
        <Card title="Network" footer={<Go customer={customer} to="/groups?view=subnets">Open subnets</Go>}>
          <Line pending={subnets.isPending} customer={customer} label="Subnets observed" value={sn?.subnets ?? null} to="/groups?view=subnets" />
          <Line pending={subnets.isPending} customer={customer} label="Not in an approved subnet" value={sn?.by_status.unassigned ?? null} attention={(sn?.by_status.unassigned ?? 0) > 0} to="/groups?view=subnets" />
          <Line pending={subnets.isPending} customer={customer} label="Devices outside approved scope" value={sn?.devices_outside_expected ?? null} attention={(sn?.devices_outside_expected ?? 0) > 0} to="/groups?view=subnets" />
        </Card>
        <Card title="Data sources">
          {datasets.data?.length ? datasets.data.map((d) => (
            <div key={d.mapping_id} className="flex flex-wrap items-center justify-between gap-2">
              <span>{d.integration.name} <span className="text-xs text-slate-500">org {d.external_org_id}</span></span>
              <span className="flex items-center gap-2"><Badge tone={d.status === "fresh" ? "good" : "warn"}>{d.status.replace("_", " ")}</Badge><span className="text-xs text-slate-500">{d.as_of ? formatUtc(d.as_of) : "never synced"}</span></span>
            </div>
          )) : <p className="text-slate-500">No approved source mapping.</p>}
        </Card>
        {canExport ? (
          <Card title="Recent reports" footer={<span className="flex gap-3"><Go customer={customer} to="/reports?tab=custom">Build a custom report</Go><Go customer={customer} to="/reports?tab=history">All reports</Go></span>}>
            {reports.data?.results.length ? reports.data.results.slice(0, 5).map((r) => (
              <div key={r.id} className="flex items-baseline justify-between gap-3">
                {r.state === "completed" ? <a className="truncate text-sky-800 hover:underline" href={`/api/v1/reports/${r.id}/download/`}>{r.title ?? r.report_type}</a> : <span className="truncate">{r.title ?? r.report_type}</span>}
                <span className="shrink-0 text-xs text-slate-500">{formatUtc(r.created_at)} · {r.state}</span>
              </div>
            )) : <p className="text-slate-500">No reports yet.</p>}
          </Card>
        ) : null}
      </div>
    </div>
  );
}
