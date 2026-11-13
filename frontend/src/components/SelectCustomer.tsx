import type { ReactNode } from "react";

import { useCustomers } from "../lib/customerContext";

/** Shown when a customer-scoped page has no customer selected: pick one right here (same as the header selector). */
export function SelectCustomer({ children }: { children?: ReactNode }) {
  const { customers, select, isLoading } = useCustomers();
  return (
    <div className="rounded border border-dashed border-slate-300 bg-white p-6">
      <p className="font-medium text-slate-800">Select a customer</p>
      <p className="mt-1 text-sm text-slate-600">{children ?? "Every view is scoped to exactly one customer."}</p>
      {isLoading ? <p className="mt-3 text-sm text-slate-500">Loading customers…</p> : null}
      {!isLoading && customers.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">You have no customer assignments yet.</p>
      ) : null}
      {customers.length > 0 ? (
        <ul aria-label="Customers" className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {customers.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => select(c.id)}
                className="w-full rounded border border-slate-200 px-3 py-2 text-left text-sm hover:border-sky-300 hover:bg-sky-50 focus:outline-none focus:ring-2 focus:ring-sky-500"
              >
                <span className="font-semibold text-sky-800">{c.code}</span>
                <span className="block truncate text-slate-600">{c.name}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
