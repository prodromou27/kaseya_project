import { Link } from "react-router";

import { SelectCustomer } from "../../components/SelectCustomer";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { Badge, PageHeader, statusTone } from "../../components/ui";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";
import type { Customer, Me } from "../../lib/types";
import { KpiTiles } from "./KpiTiles";
import { SetupChecklist } from "./SetupChecklist";
import { SystemStatusBanner } from "../admin/SystemStatusPanel";
import { Trends } from "./Trends";
import { DataSources } from "../inventory/DataSources";
import { AllCustomersPage } from "../customers/AllCustomersPage";
import { AttentionPanels, RecentReports, ScorecardButton } from "../customers/CustomerWorkspace";

const ROLE_LABEL: Record<string, string> = { admin: "Customer admin", engineer: "Engineer", viewer: "Viewer" };

function roleFor(me: Me, customer: Customer): string {
  if (me.is_super_admin) return "Super admin (all customers)";
  const m = me.memberships.find((x) => x.customer.id === customer.id);
  return m ? (ROLE_LABEL[m.role] ?? m.role) : "—";
}

/** Who and what you are looking at, in one line under the title. */
function CustomerLine({ me, customer }: { me: Me; customer: Customer }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-medium text-slate-700">{customer.code} — {customer.name}</span>
      {customer.status !== "active" ? <Badge tone={statusTone[customer.status]}>{customer.status}</Badge> : null}
      <span aria-hidden="true">·</span>
      <span className="sr-only">Your role:</span><span>{roleFor(me, customer)}</span>
      <span aria-hidden="true">·</span>
      <Link to={`/customers/${customer.id}`} className="text-sky-800 hover:underline">Customer details</Link>
    </span>
  );
}

/**
 * One customer at a glance (UX-10): data freshness, six key figures, four equal panels, then history and reports.
 * Each number is shown once and links to the page that explains it.
 */
export function DashboardPage() {
  const me = useMe();
  const { customers, selected, isLoading, isError } = useCustomers();

  return (
    <>
      <PageHeader title="Dashboard"
        subtitle={selected ? <CustomerLine me={me} customer={selected} /> : customers.length > 1 ? "All your customers" : "No customer selected"}
        actions={selected ? <ScorecardButton customer={selected} /> : undefined} />
      {me.is_super_admin ? <><SystemStatusBanner /><SetupChecklist /></> : null}

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
        <div className="space-y-4">
          <div className="[&>section]:mb-0"><DataSources key={`sources-${selected.id}`} customer={selected} compact /></div>
          <KpiTiles key={selected.id} customer={selected} />
          <AttentionPanels key={`panels-${selected.id}`} customer={selected} />
          <div className="flex flex-col gap-3 xl:flex-row">
            <div className="min-w-0 xl:flex-[2]"><Trends customer={selected} /></div>
            <div className="min-w-0 empty:hidden xl:flex-1"><RecentReports key={`reports-${selected.id}`} customer={selected} /></div>
          </div>
        </div>
      ) : customers.length > 1 ? (
        <AllCustomersPage embedded />
      ) : customers.length > 0 ? (
        <SelectCustomer>Choose the customer you want to look at. You can switch at any time in the header.</SelectCustomer>
      ) : null}
    </>
  );
}
