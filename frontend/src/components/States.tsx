import type { ReactNode } from "react";

import { describeError } from "../lib/api";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <span aria-hidden="true" className="h-3 w-3 animate-pulse rounded-full bg-slate-400" />
      {label}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded border border-dashed border-slate-300 bg-white p-6 text-sm">
      <p className="font-medium text-slate-700">{title}</p>
      {children ? <div className="mt-1 text-slate-500">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <p className="font-medium">Could not load data</p>
      <p className="mt-1">{describeError(error)}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="mt-2 underline underline-offset-2">
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Renders loading / error / empty / content for a query consistently across screens. */
export function QueryBoundary<T>({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: { isPending: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown };
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState />;
  if (query.isError || query.data === undefined) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="Nothing to show yet." />}</>;
  return <>{children(query.data)}</>;
}
