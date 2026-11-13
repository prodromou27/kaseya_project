import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader, type Tone } from "../../components/ui";
import { api } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import type { Customer, NotificationRow, NotificationSummary, Paginated } from "../../lib/types";

export const PRIORITY_TONE: Record<string, Tone> = { critical: "bad", high: "bad", elevated: "warn", normal: "neutral", low: "neutral" };

function View({ customer }: { customer: Customer }) {
  const [priority, setPriority] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const summary = useQuery({
    queryKey: ["notifications", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<NotificationSummary>(`/customers/${customer.id}/notifications/summary/`, undefined, signal),
  });
  const list = useQuery({
    queryKey: ["notifications", customer.id, priority, q, page],
    queryFn: ({ signal }) => api.get<Paginated<NotificationRow>>(`/customers/${customer.id}/notifications/`, { priority, q, page }, signal),
  });
  return (
    <QueryBoundary query={summary}>
      {(s) => {
        const notCollected = (s.collection_status.not_requested ?? 0) + (s.collection_status.failed ?? 0) + s.devices_without_fetch_row;
        return (
          <div className="space-y-4">
            <Notice tone="info">{s.note}</Notice>
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              {[
                ["Notifications (last " + s.window_days + " days)", s.notifications],
                ["Devices with notifications", s.devices_with_notifications],
                ["Devices collected", s.collection_status.collected ?? 0],
                ["Devices not collected", notCollected],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded border border-slate-200 bg-white px-3 py-2">
                  <div className="text-xs text-slate-500">{label}</div>
                  <div className="text-lg font-semibold">{value}</div>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500">
              Up to {s.per_device_limit} most recent per device per sync, of {s.devices} devices. By priority:{" "}
              {Object.entries(s.by_priority).map(([p, n]) => `${p} ${n}`).join(" · ") || "none"}.
            </p>
            {s.recurring.length ? (
              <DataTable caption="Recurring notifications" rows={s.recurring} getRowId={(r) => r.pattern}
                columns={[
                  { header: "Pattern", cell: ({ row }) => <span className="text-xs">{row.original.pattern}</span> },
                  { header: "Occurrences", accessorKey: "count" },
                  { header: "Devices", accessorKey: "devices" },
                ]} />
            ) : null}
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Priority">{(id) => (
                <select id={id} className="input" value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1); }}>
                  <option value="">All</option>
                  {Object.keys(s.by_priority).map((p) => <option key={p} value={p}>{p}</option>)}
                </select>)}</Field>
              <Field label="Message contains">{(id) => <input id={id} className="input" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />}</Field>
            </div>
            <QueryBoundary query={list}>
              {(d) => (
                <DataTable caption="Device notifications" rows={d.results} total={d.count} page={page} onPageChange={setPage} getRowId={(r) => r.id}
                  emptyTitle="No notifications match."
                  columns={[
                    { header: "When", cell: ({ row }) => row.original.occurred_at ? formatUtc(row.original.occurred_at) : (row.original.occurred_raw || "unknown") },
                    { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset}`}>{row.original.hostname}</Link> },
                    { header: "Priority", cell: ({ row }) => <Badge tone={PRIORITY_TONE[row.original.priority] ?? "neutral"}>{row.original.priority || "—"}</Badge> },
                    { header: "Message", cell: ({ row }) => (
                      <span className="text-xs">{row.original.message}{row.original.redactions ? <span className="ml-1"><Badge tone="info">{row.original.redactions} redacted</Badge></span> : null}</span>
                    ) },
                  ]} />
              )}
            </QueryBoundary>
          </div>
        );
      }}
    </QueryBoundary>
  );
}

export function NotificationsPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Notifications" subtitle="Recent VSA X device notifications and recurring patterns." />
      {!selected ? <EmptyState title="Select a customer" /> : <View customer={selected} />}
    </>
  );
}
