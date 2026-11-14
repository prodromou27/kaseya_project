import { useId, type ReactNode } from "react";

const BADGE_TONES = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  good: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warn: "bg-amber-50 text-amber-900 ring-amber-200",
  bad: "bg-red-50 text-red-800 ring-red-200",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
} as const;

export type Tone = keyof typeof BADGE_TONES;

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h1 className="break-words text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex gap-2">{actions}</div> : null}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="flex min-w-0 max-w-full flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-700">
        {label}
      </label>
      {children(id, hintId)}
      {hint ? (
        <p id={hintId} className="text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Warnings and errors are always shown in full. Informational notes (tone "info", the default) are explanations
 * most users do not need every time: they fold into a single "About this view" line that expands on click.
 */
export function Notice({ tone = "info", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  if (tone === "info") {
    return (
      <details className="group text-sm text-slate-600">
        <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-slate-500 hover:text-slate-800">
          <span aria-hidden="true" className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-300 text-[10px] font-semibold">i</span>
          {title ?? "About this view"}
        </summary>
        <div className="mt-1.5 rounded bg-slate-50 px-3 py-2 ring-1 ring-inset ring-slate-200">{children}</div>
      </details>
    );
  }
  return <div className={`rounded px-3 py-2 text-sm ring-1 ring-inset ${BADGE_TONES[tone]}`}>{children}</div>;
}

export const statusTone: Record<string, Tone> = {
  active: "good",
  approved: "good",
  completed: "good",
  success: "good",
  onboarding: "info",
  proposed: "warn",
  queued: "info",
  running: "info",
  suspended: "warn",
  denied: "bad",
  failed: "bad",
  failure: "bad",
  rejected: "bad",
  revoked: "neutral",
  archived: "neutral",
  current: "good",
  outdated: "bad",
  newer: "info",
  unknown: "warn",
  unsupported: "neutral",
  excluded: "neutral",
  fresh: "good",
  stale: "warn",
  never_synced: "neutral",
  partial: "warn",
  fixture: "info",
  live: "warn",
  collected: "good",
  not_collected: "warn",
  not_supported: "neutral",
  not_requested: "neutral",
  carried_forward: "info",
};
