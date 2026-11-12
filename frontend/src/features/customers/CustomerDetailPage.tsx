import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useParams } from "react-router";

import { QueryBoundary } from "../../components/States";
import { Tabs, type TabDef } from "../../components/Tabs";
import { Badge, Field, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { CAP, type Customer, type CustomerStatus } from "../../lib/types";
import { CustomerReports } from "../reports/CustomerReports";
import { AuditTable } from "./AuditTable";
import { MappingsPanel } from "./MappingsPanel";
import { MembersPanel } from "./MembersPanel";

const STATUSES: CustomerStatus[] = ["onboarding", "active", "suspended", "archived"];

function OverviewPanel({ customer }: { customer: Customer }) {
  const me = useMe();
  const queryClient = useQueryClient();
  const [name, setName] = useState(customer.name);
  const [status, setStatus] = useState<CustomerStatus>(customer.status);
  const [region, setRegion] = useState(customer.data_region);
  const [restricted, setRestricted] = useState(customer.restricted_data);
  const save = useMutation({
    mutationFn: () =>
      api.patch<Customer>(`/customers/${customer.id}/`, { name, status, data_region: region, restricted_data: restricted }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["customer", customer.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["customers"] });
    },
  });

  if (!me.is_super_admin) {
    return (
      <dl className="grid max-w-xl grid-cols-2 gap-y-1 text-sm">
        <dt className="text-slate-500">Status</dt>
        <dd>
          <Badge tone={statusTone[customer.status]}>{customer.status}</Badge>
        </dd>
        <dt className="text-slate-500">Data region</dt>
        <dd>{customer.data_region || "Not set"}</dd>
        <dt className="text-slate-500">Restricted data</dt>
        <dd>{customer.restricted_data ? "Yes" : "No"}</dd>
        <dt className="text-slate-500">Your capabilities</dt>
        <dd className="text-xs">{customer.my_capabilities.join(", ")}</dd>
      </dl>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form onSubmit={submit} aria-label="Edit customer" className="grid max-w-xl gap-3">
      <Field label="Name">{(id) => <input id={id} className="input" value={name} onChange={(e) => setName(e.target.value)} required />}</Field>
      <Field label="Status" hint="Archived and suspended customers are hidden from customer members.">
        {(id, hint) => (
          <select id={id} aria-describedby={hint} className="input" value={status} onChange={(e) => setStatus(e.target.value as CustomerStatus)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Data region">{(id) => <input id={id} className="input" value={region} onChange={(e) => setRegion(e.target.value)} />}</Field>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={restricted} onChange={(e) => setRestricted(e.target.checked)} />
        Restricted data (requires a separately approved deployment before any ingestion)
      </label>
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          Save changes
        </button>
        {save.isSuccess ? <span role="status" className="text-sm text-emerald-700">Saved.</span> : null}
        {save.isError ? (
          <span role="alert" className="text-sm text-red-700">
            {describeError(save.error)}
          </span>
        ) : null}
      </div>
    </form>
  );
}

export function CustomerDetailPage() {
  const { customerId = "" } = useParams();
  const [tab, setTab] = useState("overview");
  const query = useQuery({
    queryKey: ["customer", customerId],
    queryFn: ({ signal }) => api.get<Customer>(`/customers/${customerId}/`, undefined, signal),
  });

  return (
    <QueryBoundary query={query}>
      {(customer) => {
        const caps = new Set(customer.my_capabilities);
        const tabs: TabDef[] = [{ id: "overview", label: "Overview", content: <OverviewPanel customer={customer} /> }];
        if (caps.has(CAP.manageMembers)) tabs.push({ id: "members", label: "Members", content: <MembersPanel customer={customer} /> });
        if (caps.has(CAP.proposeMappings)) tabs.push({ id: "mappings", label: "Source mappings", content: <MappingsPanel customer={customer} /> });
        if (caps.has(CAP.auditRead))
          tabs.push({ id: "audit", label: "Audit", content: <AuditTable path={`/customers/${customer.id}/audit-events/`} caption={`${customer.code} audit events`} /> });
        if (caps.has(CAP.export)) tabs.push({ id: "reports", label: "Reports", content: <CustomerReports customer={customer} /> });
        return (
          <>
            <PageHeader
              title={`${customer.code} — ${customer.name}`}
              subtitle={<Badge tone={statusTone[customer.status]}>{customer.status}</Badge>}
            />
            <Tabs label="Customer sections" tabs={tabs} active={tab} onChange={setTab} />
          </>
        );
      }}
    </QueryBoundary>
  );
}
