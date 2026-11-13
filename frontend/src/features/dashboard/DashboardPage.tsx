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

const ROLE_LABEL: Record<string, string> = { admin: "Customer admin", engineer: "Engineer", viewer: "Viewer" };

function roleFor(me: Me, customer: Customer): string {
  if (me.is_super_admin) return "Super admin (all customers)";
  const m = me.memberships.find((x) => x.customer.id === customer.id);
  return m ? (ROLE_LABEL[m.role] ?? m.role) : "—";
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
          <KpiTiles customer={selected} />
          <section aria-labelledby="sel-heading" className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-1 rounded border border-slate-200 bg-white px-4 py-3 text-sm">
            <h2 id="sel-heading" className="sr-only">Selected customer</h2>
            <span><span className="text-slate-500">Customer</span> <span className="font-medium">{selected.code}</span></span>
            <span><span className="text-slate-500">Status</span> <Badge tone={statusTone[selected.status]}>{selected.status}</Badge></span>
            <span><span className="text-slate-500">Data region</span> {selected.data_region || "Not set"}</span>
            <span><span className="text-slate-500">Your role</span> {roleFor(me, selected)}</span>
            <Link to={`/customers/${selected.id}`} className="ml-auto text-sky-800 underline">
              Open customer
            </Link>
          </section>
          <Trends customer={selected} />
        </>
      ) : customers.length > 0 ? (
        <SelectCustomer>Choose the customer you want to look at. You can switch at any time in the header.</SelectCustomer>
      ) : null}
    </>
  );
}
