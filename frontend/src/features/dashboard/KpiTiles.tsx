import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { ErrorState, LoadingState } from "../../components/States";
import { api } from "../../lib/api";
import type { Customer, HealthSummary, OsUpdateSummary, SoftwareSummary } from "../../lib/types";

type Tile = { label: string; value: number | null; sub: string; to: string; attention?: boolean };

function TileCard({ tile }: { tile: Tile }) {
  return (
    <Link to={tile.to} className="group flex min-w-0 flex-col rounded-lg border border-slate-200 bg-white p-3 shadow-sm hover:border-sky-400 focus-visible:ring-2 focus-visible:ring-sky-500">
      <span className="flex items-start justify-between gap-2 text-xs font-medium text-slate-600">
        {tile.label}<span aria-hidden="true" className="text-slate-400 group-hover:text-sky-700">↗</span>
      </span>
      <span className={`mt-2 text-3xl font-semibold tabular-nums tracking-tight ${tile.attention ? "text-amber-700" : "text-slate-900"}`}>{tile.value ?? "—"}</span>
      <span className="mt-1 text-[11px] leading-relaxed text-slate-500">{tile.sub}</span>
    </Link>
  );
}

const sum = (record: Record<string, number> | undefined, keys: string[]) => record ? keys.reduce((n, key) => n + (record[key] ?? 0), 0) : null;

/** Use current customer-wide summaries. A historical trend point belongs to one source, not the whole customer. */
export function KpiTiles({ customer }: { customer: Customer }) {
  const health = useQuery({
    queryKey: ["device-health", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<HealthSummary>(`/customers/${customer.id}/device-health/summary/`, undefined, signal),
  });
  const software = useQuery({
    queryKey: ["software", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<SoftwareSummary>(`/customers/${customer.id}/software/summary/`, undefined, signal),
  });
  const patch = useQuery({
    queryKey: ["os-updates", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<OsUpdateSummary>(`/customers/${customer.id}/os-updates/summary/`, undefined, signal),
  });
  if (health.isPending) return <LoadingState label="Loading operational summary…" />;
  const h = health.data;
  const offline = sum(h?.dimensions.connectivity, ["offline", "stale", "never_seen"]);
  const disk = h?.dimensions.disk?.critical ?? null;
  const antivirus = sum(h?.dimensions.antivirus, ["disabled", "enabled_outdated"]);
  const os = patch.data;
  const sw = software.data;
  const tiles: Tile[] = [
    { label: "Devices", value: h?.devices ?? null, sub: "Current published inventory · all approved sources", to: "/assets" },
    { label: "Offline / stale", value: offline, sub: "Includes devices with no last-seen evidence", to: "/device-health?connectivity=offline,stale,never_seen", attention: (offline ?? 0) > 0 },
    { label: "Disk critical", value: disk, sub: `${h?.dimensions.disk?.warning ?? "—"} more at warning level`, to: "/device-health?disk=critical", attention: (disk ?? 0) > 0 },
    { label: "Antivirus issues", value: antivirus, sub: "Reported disabled or enabled but outdated", to: "/device-health?antivirus=disabled,enabled_outdated", attention: (antivirus ?? 0) > 0 },
    { label: "Missing critical updates", value: os && os.devices_reporting_updates > 0 ? os.devices_by_severity.Critical ?? 0 : null,
      sub: os ? `of ${os.devices_reporting_updates} devices reporting updates · ${os.devices_total - os.devices_reporting_updates} without data` : patch.isPending ? "Loading update evidence…" : "Update summary unavailable",
      to: "/windows-updates?state=available&severity=Critical", attention: (os?.devices_by_severity.Critical ?? 0) > 0 },
    { label: "Outdated software", value: sw && sw.eligible_installations > 0 ? sw.unique_assets_with_outdated : null,
      sub: sw ? `${sw.totals.outdated} outdated of ${sw.comparable_installations} comparable installs` : software.isPending ? "Loading software evidence…" : "Software summary unavailable",
      to: "/software?state=outdated", attention: (sw?.unique_assets_with_outdated ?? 0) > 0 },
  ];
  return (
    <section aria-label="Summary" className="mb-5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">Operational overview</h2>
        <span className="text-xs text-slate-500">Snapshot observations · select a metric to investigate</span>
      </div>
      {health.isError ? <ErrorState error={health.error} onRetry={() => void health.refetch()} /> : null}
      {software.isError ? <ErrorState error={software.error} onRetry={() => void software.refetch()} /> : null}
      {patch.isError ? <ErrorState error={patch.error} onRetry={() => void patch.refetch()} /> : null}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">{tiles.map((tile) => <TileCard key={tile.label} tile={tile} />)}</div>
      {h?.devices === 0 ? <p className="text-sm text-slate-600">No devices yet for this customer. Inventory appears after a successful sync of an approved source mapping.</p> : null}
    </section>
  );
}
