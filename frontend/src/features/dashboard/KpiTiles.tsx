import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { ErrorState, LoadingState } from "../../components/States";
import { api } from "../../lib/api";
import type { Customer, HealthSummary, OsUpdateSummary, SoftwareSummary } from "../../lib/types";

type Tile = { label: string; value: number | null; sub: string; to: string; icon: ReactNode; check?: boolean };

/** Decorative 20px stroke icons (aria-hidden): the label carries the meaning. */
const svg = (d: ReactNode) => (
  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
    {d}
  </svg>
);
const ICONS = {
  devices: svg(<><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>),
  offline: svg(<><path d="M2 8.8a15 15 0 0 1 4.2-2.6M22 8.8A15 15 0 0 0 10.7 5M5 12.6a10 10 0 0 1 3.5-2M19 12.6a10 10 0 0 0-4.2-2.3M8.5 16.3a5 5 0 0 1 7 0M12 20h.01M3 3l18 18" /></>),
  disk: svg(<><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>),
  shield: svg(<><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M12 8v4M12 16h.01" /></>),
  updates: svg(<><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5M12 8v4l3 2" /></>),
  software: svg(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><path d="M17.5 14v7M14 17.5h7" /></>),
};

function TileStatus({ tile, empty }: { tile: Tile; empty: boolean }) {
  if (!tile.check) return null;
  if (tile.value === null || empty) return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">No data</span>;
  return tile.value > 0 ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-amber-500" />Review
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-800 ring-1 ring-inset ring-emerald-200">
      <span aria-hidden="true">✓</span>OK
    </span>
  );
}

function TileCard({ tile, primary = false, empty = false }: { tile: Tile; primary?: boolean; empty?: boolean }) {
  const attention = tile.check && (tile.value ?? 0) > 0;
  const accent = primary ? "bg-sky-50 text-sky-700" : attention ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-500";
  return (
    <Link
      to={tile.to}
      className={`group relative flex min-h-32 min-w-0 flex-col rounded-xl border bg-white p-3 sm:min-h-36 sm:p-4 shadow-sm transition-colors duration-150 hover:border-sky-400 hover:shadow focus-visible:ring-2 focus-visible:ring-sky-500 ${attention ? "border-amber-200" : "border-slate-200"}`}
    >
      <span className="flex items-start justify-between gap-2 text-sm font-medium text-slate-700">
        {tile.label}
        <span className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${accent}`}>{tile.icon}</span>
      </span>
      <span className="mt-1 min-h-5"><TileStatus tile={tile} empty={empty} /></span>
      <span className={`mt-auto pt-2 text-2xl font-semibold tabular-nums sm:text-3xl tracking-tight ${attention ? "text-amber-800" : "text-slate-900"}`}>{tile.value ?? "—"}</span>
      <span className="mt-1 block text-xs leading-snug text-slate-500">{tile.sub}</span>
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
  const devices: Tile = { label: "Devices", value: h?.devices ?? null, sub: "In the current inventory", to: "/assets", icon: ICONS.devices };
  const checks: Tile[] = [
    { label: "Offline / stale", value: offline, sub: "Not seen recently, or never", to: "/device-health?connectivity=offline,stale,never_seen", icon: ICONS.offline, check: true },
    { label: "Disk critical", value: disk, sub: `${h?.dimensions.disk?.warning ?? "—"} more at warning level`, to: "/device-health?disk=critical", icon: ICONS.disk, check: true },
    { label: "Antivirus issues", value: antivirus, sub: "Disabled, or enabled but outdated", to: "/device-health?antivirus=disabled,enabled_outdated", icon: ICONS.shield, check: true },
    { label: "Missing critical updates", value: os && os.devices_reporting_updates > 0 ? os.devices_by_severity.Critical ?? 0 : null,
      sub: os ? `of ${os.devices_reporting_updates} devices reporting updates` : patch.isPending ? "Loading…" : "Update summary unavailable",
      to: "/windows-updates?state=available&severity=Critical", icon: ICONS.updates, check: true },
    { label: "Outdated software", value: sw && sw.eligible_installations > 0 ? sw.unique_assets_with_outdated : null,
      sub: sw ? `devices · ${sw.totals.outdated} outdated of ${sw.comparable_installations} comparable installs` : software.isPending ? "Loading…" : "Software summary unavailable",
      to: "/software?state=outdated", icon: ICONS.software, check: true },
  ];
  const needReview = checks.filter((t) => (t.value ?? 0) > 0).length;
  return (
    <section aria-label="Summary" className="mb-6 space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">Overview</h2>
        <p role="status" className="text-sm text-slate-600">
          {h?.devices ? (needReview === 0 ? "All checks look good." : `${needReview} of ${checks.length} checks need review.`) : null}
        </p>
      </div>
      {health.isError ? <ErrorState error={health.error} onRetry={() => void health.refetch()} /> : null}
      {software.isError ? <ErrorState error={software.error} onRetry={() => void software.refetch()} /> : null}
      {patch.isError ? <ErrorState error={patch.error} onRetry={() => void patch.refetch()} /> : null}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <TileCard tile={devices} primary />
        {checks.map((tile) => <TileCard key={tile.label} tile={tile} empty={h?.devices === 0} />)}
      </div>
      {h?.devices === 0 ? <p className="text-sm text-slate-600">No devices yet. They appear after the first successful sync.</p> : null}
    </section>
  );
}
