import { Link } from "react-router";

import { SelectCustomer } from "../../components/SelectCustomer";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { Badge, PageHeader, statusTone } from "../../components/ui";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";
import type { Customer, Me } from "../../lib/types";
import { KpiTiles } from "./KpiTiles";
import { SetupChecklist } from "./SetupChecklist";
import { Trends } from "./Trends";
import { DataSources } from "../inventory/DataSources";

const ROLE_LABEL: Record<string, string> = { admin: "Customer admin", engineer: "Engineer", viewer: "Viewer" };

function roleFor(me: Me, customer: Customer): string {
  if (me.is_super_admin) return "Super admin (all customers)";
  const m = me.memberships.find((x) => x.customer.id === customer.id);
  return m ? (ROLE_LABEL[m.role] ?? m.role) : "—";
}

function CustomerCard({ me, customer }: { me: Me; customer: Customer }) {
  return (
    <section aria-labelledby="sel-heading" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="sel-heading" className="text-sm font-semibold text-slate-900">Customer</h2>
        <Link to={`/customers/${customer.id}`} className="text-sm font-medium text-sky-800 hover:underline">
          Open customer
        </Link>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        <dt className="text-slate-500">Code</dt>
        <dd className="font-medium text-slate-900">{customer.code}</dd>
        <dt className="text-slate-500">Status</dt>
        <dd><Badge tone={statusTone[customer.status]}>{customer.status}</Badge></dd>
        <dt className="text-slate-500">Data region</dt>
        <dd className="text-slate-800">{customer.data_region || "Not set"}</dd>
        <dt className="text-slate-500">Your role</dt>
        <dd className="text-slate-800">{roleFor(me, customer)}</dd>
      </dl>
    </section>
  );
}

export function DashboardPage() {
  const me = useMe();
  const { customers, selected, isLoading, isError } = useCustomers();

  return (
    <>
      <PageHeader title="Dashboard" subtitle={selected ? `${selected.code} — ${selected.name}` : "No customer selected"} />
      {me.is_super_admin ? <SetupChecklist /> : null}

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
        <>
          <KpiTiles key={selected.id} customer={selected} />
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="min-w-0 lg:col-span-2">
              <Trends customer={selected} />
            </div>
            <aside className="min-w-0 space-y-4" aria-label="Sources and customer">
              <div className="[&>section]:mb-0"><DataSources key={`sources-${selected.id}`} customer={selected} /></div>
              <CustomerCard me={me} customer={selected} />
            </aside>
          </div>
        </>
      ) : customers.length > 0 ? (
        <SelectCustomer>Choose the customer you want to look at. You can switch at any time in the header.</SelectCustomer>
      ) : null}
    </>
  );
}
