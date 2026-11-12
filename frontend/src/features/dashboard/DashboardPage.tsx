import { Link } from "react-router";

import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { Badge, Notice, PageHeader, statusTone } from "../../components/ui";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";

export function DashboardPage() {
  const me = useMe();
  const { customers, selected, isLoading, isError } = useCustomers();

  return (
    <>
      <PageHeader title="Dashboard" subtitle={selected ? `${selected.code} — ${selected.name}` : "No customer selected"} />
      <div className="mb-4">
        <Notice tone="info">
          Foundation release (P0). No vendor connector is live yet, so inventory, software and update figures are not
          available. Nothing on this portal currently reflects vendor data.
        </Notice>
      </div>

      {isLoading ? <LoadingState /> : null}
      {isError ? <ErrorState error={new Error("Customers could not be loaded.")} /> : null}

      {!isLoading && !isError && customers.length === 0 ? (
        <EmptyState title="You have no customer assignments.">
          {me.is_super_admin ? (
            <Link to="/customers" className="underline">
              Create a customer
            </Link>
          ) : (
            "Ask a portal administrator to grant you access to a customer."
          )}
        </EmptyState>
      ) : null}

      {selected ? (
        <section aria-labelledby="sel-heading" className="rounded border border-slate-200 bg-white p-4">
          <h2 id="sel-heading" className="mb-2 text-sm font-semibold text-slate-700">
            Selected customer
          </h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <dt className="text-slate-500">Code</dt>
            <dd>{selected.code}</dd>
            <dt className="text-slate-500">Status</dt>
            <dd>
              <Badge tone={statusTone[selected.status]}>{selected.status}</Badge>
            </dd>
            <dt className="text-slate-500">Data region</dt>
            <dd>{selected.data_region || "Not set"}</dd>
            <dt className="text-slate-500">Your capabilities</dt>
            <dd className="text-xs">{selected.my_capabilities.join(", ") || "—"}</dd>
          </dl>
          <Link to={`/customers/${selected.id}`} className="mt-3 inline-block text-sm text-sky-800 underline">
            Open customer
          </Link>
        </section>
      ) : customers.length > 0 ? (
        <EmptyState title="Select a customer">Use the customer selector in the header to scope the portal.</EmptyState>
      ) : null}
    </>
  );
}
