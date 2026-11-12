import { EmptyState } from "../../components/States";
import { PageHeader } from "../../components/ui";
import { useCustomers } from "../../lib/customerContext";
import { CAP } from "../../lib/types";
import { CustomerReports } from "./CustomerReports";

export function ReportsPage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Reports" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? (
        <EmptyState title="Select a customer">Reports are always generated for exactly one customer.</EmptyState>
      ) : !selected.my_capabilities.includes(CAP.export) ? (
        <EmptyState title="You do not have export permission for this customer." />
      ) : (
        <CustomerReports customer={selected} />
      )}
    </>
  );
}
