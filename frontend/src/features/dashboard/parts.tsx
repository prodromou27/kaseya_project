import type { ReactNode } from "react";
import { Link } from "react-router";

import { useCustomers } from "../../lib/customerContext";
import type { Customer } from "../../lib/types";

/**
 * Dashboard building blocks (UX-10). Every summary panel has the same anatomy: a title row with one "Open" link, then
 * label/value rows. Panels in a row stretch to the same height; nothing grows with the data except lists, which are
 * capped by their callers.
 */

/** A link that first makes this customer the selected one, so the target page opens on the right data. */
export function Go({ customer, to, children, className = "text-sky-800 hover:underline" }: { customer: Customer; to: string; children: ReactNode; className?: string }) {
  const { select } = useCustomers();
  return <Link to={to} onClick={() => select(customer.id)} className={className}>{children}</Link>;
}

export function Panel({ title, action, children, className = "" }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`flex h-full min-w-0 flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {action ? <span className="shrink-0 text-xs">{action}</span> : null}
      </div>
      <div className="flex-1 space-y-1.5 text-sm">{children}</div>
    </section>
  );
}

/** Share of a whole as a thin bar; decorative, because the number next to it carries the meaning. */
export function ShareBar({ value, of, tone = "warn", percent = true }: { value: number | null; of: number | null; tone?: "warn" | "good" | "neutral"; percent?: boolean }) {
  const pct = value === null || !of ? null : Math.min(100, Math.round((100 * value) / of));
  const fill = tone === "good" ? "bg-emerald-500" : tone === "neutral" ? "bg-slate-400" : "bg-amber-500";
  return (
    <span className="flex items-center gap-2">
      <span aria-hidden="true" className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-100">
        {pct ? <span className={`block h-full rounded-full ${fill}`} style={{ width: `${Math.max(pct, 2)}%` }} /> : null}
      </span>
      {percent ? <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-slate-500">{pct === null ? "" : `${pct}%`}</span> : null}
    </span>
  );
}

/** One label/value row; the value links to the matching investigation when there is something to see. */
export function Metric({ label, value, attention, customer, to, pending, title }: {
  label: ReactNode; value: number | string | null; attention?: boolean; customer: Customer; to?: string; pending?: boolean; title?: string;
}) {
  const shown = value === null ? (pending ? "…" : "—") : value;
  return (
    <div className="flex items-baseline justify-between gap-3" title={title}>
      <span className="min-w-0 text-slate-600">{label}</span>
      <span className={`shrink-0 tabular-nums font-semibold ${attention ? "text-amber-800" : "text-slate-900"}`}>
        {to && value !== null ? <Go customer={customer} to={to}>{shown}</Go> : shown}
      </span>
    </div>
  );
}
