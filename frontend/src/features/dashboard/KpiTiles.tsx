import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Badge } from "../../components/ui";
import { api } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import type { Customer, HealthSummary, LifecycleSummary, TrendResponse } from "../../lib/types";

type Tile = { label: string; value: number | null; sub: string; to: string; attention?: boolean };

function TileCard({ tile }: { tile: Tile }) {
  return (
    <Link
      to={tile.to}
      className="block rounded border border-slate-200 bg-white p-3 hover:border-sky-300 focus:outline-none focus:ring-2 focus:ring-sky-500"
    >
      <span className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-slate-600">{tile.label}</span>
        {tile.attention ? <Badge tone="warn">attention</Badge> : null}
      </span>
      <span className="mt-1 block text-2xl font-semibold tabular-nums text-slate-900">{tile.value ?? "—"}</span>
      <span className="mt-0.5 block text-xs text-slate-500">{tile.sub}</span>
    </Link>
  );
}

const sum = (rec: Record<string, number> | undefined, keys: string[]) => keys.reduce((n, k) => n + (rec?.[k] ?? 0), 0);

/** Headline numbers for the selected customer, from the latest published snapshot. Every tile links to its page. */
export function KpiTiles({ customer }: { customer: Customer }) {
  const health = useQuery({
    queryKey: ["device-health", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<HealthSummary>(`/customers/${customer.id}/device-health/summary/`, undefined, signal),
  });
  const trends = useQuery({
    queryKey: ["trends", customer.id, 7],
    queryFn: ({ signal }) => api.get<TrendResponse>(`/customers/${customer.id}/trends/`, { days: 7 }, signal),
  });
  const lifecycle = useQuery({
    queryKey: ["lifecycle", customer.id],
    queryFn: ({ signal }) => api.get<LifecycleSummary>(`/customers/${customer.id}/lifecycle/`, undefined, signal),
  });
  if (health.isPending || trends.isPending) return <p className="mb-4 text-sm text-slate-500">Loading summary…</p>;
  if (health.isError) return null;
  const h = health.data;
  if (h.devices === 0) {
    return (
      <p className="mb-4 rounded border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-600">
        No devices yet for this customer. Data appears after the first successful sync of an approved mapping.
      </p>
    );
  }
  const latest = trends.data?.points.at(-1);
  const d = h.dimensions;
  const offline = sum(d.connectivity, ["offline", "stale", "never_seen"]);
  const diskCritical = d.disk?.critical ?? 0;
  const diskWarning = d.disk?.warning ?? 0;
  const av = sum(d.antivirus, ["disabled", "enabled_outdated"]);
  const fw = d.firewall?.disabled ?? 0;
  const os = latest?.os_updates;
  const sw = latest?.software;
  const tiles: Tile[] = [
    { label: "Devices", value: h.devices, sub: `latest snapshot${h.data_basis.includes("fixture") ? " · demo data" : ""}`, to: "/assets" },
    { label: "Offline / stale", value: offline, sub: `of ${h.devices} devices`, to: "/device-health", attention: offline > 0 },
    { label: "Disk critical", value: diskCritical, sub: `${diskWarning} more at warning level`, to: "/device-health", attention: diskCritical > 0 },
    { label: "Antivirus issues", value: av, sub: `off or outdated · firewall off on ${fw}`, to: "/device-health", attention: av + fw > 0 },
    {
      label: "Missing critical updates",
      value: os ? os.devices_with_critical : null,
      sub: os ? `of ${os.devices_reporting} devices reporting updates` : "no update data yet",
      to: "/windows-updates",
      attention: (os?.devices_with_critical ?? 0) > 0,
    },
    {
      label: "Outdated software",
      value: sw?.devices_with_outdated ?? null,
      sub: sw ? `${sw.outdated} outdated of ${sw.comparable} comparable installs` : "no reviewed catalog yet",
      to: "/software",
      attention: (sw?.devices_with_outdated ?? 0) > 0,
    },
    {
      label: "OS end of support",
      value: lifecycle.data ? lifecycle.data.os.totals.end_of_support : null,
      sub: lifecycle.data
        ? `${lifecycle.data.os.totals.ending_soon} ending soon · ${lifecycle.data.os.totals.unknown} unknown`
        : "lifecycle not available",
      to: "/lifecycle",
      attention: (lifecycle.data?.os.totals.end_of_support ?? 0) > 0,
    },
  ];
  const asOf = h.as_of.filter(Boolean).sort().at(-1);
  return (
    <section aria-label="Summary" className="mb-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
        {tiles.map((t) => (
          <TileCard key={t.label} tile={t} />
        ))}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {asOf ? `As of ${formatUtc(asOf)}. ` : ""}Figures come from the latest published read-only snapshot; software figures are
        version comparisons, not patch applicability.
      </p>
    </section>
  );
}
