import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { QueryBoundary } from "../../components/States";
import { Notice } from "../../components/ui";
import { TrendChart } from "../../components/TrendChart";
import { api } from "../../lib/api";
import type { Customer, TrendResponse } from "../../lib/types";

export function Trends({ customer }: { customer: Customer }) {
  const [days, setDays] = useState(90);
  const query = useQuery({
    queryKey: ["trends", customer.id, days],
    queryFn: ({ signal }) => api.get<TrendResponse>(`/customers/${customer.id}/trends/`, { days }, signal),
  });
  return (
    <section aria-labelledby="trend-h" className="h-full rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="trend-h" className="text-sm font-semibold text-slate-900">History</h2>
        <label className="flex items-center gap-2 text-xs text-slate-600">
          Range
          <select className="input py-1" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>1 year</option>
          </select>
        </label>
      </div>
      <QueryBoundary query={query} isEmpty={(d) => d.points.length === 0}
        empty={<p className="py-4 text-center text-sm text-slate-500">No history in this range yet. It builds up with each sync.</p>}>
        {(d) => (
          <>
            <TrendChart
              title="Devices over time"
              unit="devices, latest published dataset per day"
              xLabels={d.points.map((p) => d.points.some((other) => other.source !== p.source) ? `${p.day} / ${p.source}` : p.day)}
              series={[
                { key: "devices", label: "In inventory", values: d.points.map((p) => p.devices) },
                { key: "outdated", label: "With outdated software", values: d.points.map((p) => p.software?.devices_with_outdated ?? null) },
                { key: "critical", label: "With Critical OS updates", values: d.points.map((p) => p.os_updates.devices_with_critical) },
              ]}
            />
            <div className="mt-2"><Notice title="How these figures are counted">
              {d.method} Software figures use each day's reviewed catalog revision; OS update figures count only devices that
              reported update data ({d.points.at(-1)?.os_updates.devices_not_reporting ?? 0} devices without update data on the latest day).
            </Notice></div>
          </>
        )}
      </QueryBoundary>
    </section>
  );
}
