import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Fragment, useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useCustomers } from "../../lib/customerContext";
import { formatUtc } from "../../lib/format";
import {
  CAP,
  STATE_LABEL,
  type ComplianceState,
  type Customer,
  type Paginated,
  type ProductSummary,
  type SoftwareExceptionRow,
  type SoftwareRow,
  type SoftwareSummary,
} from "../../lib/types";
import { softwareColumns } from "../inventory/AssetDetailPage";
import { ThirdPartyPatchNotice } from "../../components/ThirdPartyPatchNotice";
import { DataSources } from "../inventory/DataSources";
import { ExportButton } from "../reports/ExportButton";
import { SelectCustomer } from "../../components/SelectCustomer";

const STATES: ComplianceState[] = ["outdated", "current", "newer", "unknown", "excluded", "unsupported"];
const PAGE_SIZE = 50;

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-slate-500">{hint}</div>
    </div>
  );
}

function Summary({ s, onDrill }: { s: SoftwareSummary; onDrill: (state: ComplianceState | "", product: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const pct = (v: number | null) => (v === null ? "n/a" : `${v}%`);
  return (
    <>
      <Notice tone="info">{s.disclaimer}</Notice>
      <div className="mt-2"><ThirdPartyPatchNotice status={s.third_party_patch_status} /></div>
      <div className="my-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Metric label="Version compliance" value={pct(s.version_compliance_pct)}
                hint={`current / (current + outdated) = ${s.totals.current} / ${s.totals.current + s.totals.outdated}`} />
        <Metric label="Comparable coverage" value={pct(s.comparable_coverage_pct)}
                hint={`${s.comparable_installations} of ${s.eligible_installations} installations comparable`} />
        <Metric label="Devices with outdated software" value={String(s.unique_assets_with_outdated)}
                hint={`of ${s.unique_assets_evaluated} devices with collected inventory (each counted once)`} />
        <Metric label="Outdated installations" value={String(s.totals.outdated)} hint="installation records, not devices" />
      </div>
      <div className="mb-3 flex flex-wrap gap-2 text-sm" aria-label="Classification totals">
        {STATES.map((st) => (
          <button key={st} type="button" className="btn-secondary" onClick={() => onDrill(st, "")}>
            <Badge tone={statusTone[st]}>{STATE_LABEL[st]}</Badge> {s.totals[st]}
          </button>
        ))}
      </div>
      <p className="mb-3 text-xs text-slate-500">
        As of {s.as_of.map(formatUtc).join(", ") || "—"} · catalog revisions applied: {s.catalog_revision_ids.length} ·
        comparator v{s.algorithm_version} · data basis {s.data_basis.join(", ") || "none"}
      </p>
      {s.products.length === 0 ? (
        <EmptyState title="No catalogued products found in this inventory.">
          Installed software that is not in the reviewed catalog is reported as “Not catalogued”.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <caption className="sr-only">Catalogued products</caption>
            <thead className="bg-slate-100 text-xs uppercase text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-2 text-left">Product</th>
                {STATES.slice(0, 5).map((st) => <th key={st} scope="col" className="px-2 py-2 text-right">{STATE_LABEL[st]}</th>)}
                <th scope="col" className="px-2 py-2 text-right">Devices</th>
                <th scope="col" className="px-2 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {s.products.map((p: ProductSummary) => (
                <Fragment key={p.product_id}>
                  <tr>
                    <th scope="row" className="px-3 py-1.5 text-left font-medium">
                      {p.label} <span className="text-xs text-slate-500">({p.channel})</span>
                    </th>
                    {STATES.slice(0, 5).map((st) => (
                      <td key={st} className="px-2 py-1.5 text-right">
                        {p.states[st] ? (
                          <button type="button" className="text-sky-800 hover:underline" onClick={() => onDrill(st, p.product_id)}>
                            {p.states[st]}
                          </button>
                        ) : <span className="text-slate-300">0</span>}
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-right">{p.unique_assets}</td>
                    <td className="px-2 py-1.5 text-right">
                      <button type="button" className="text-xs text-sky-800 underline" aria-expanded={open === p.product_id}
                              onClick={() => setOpen(open === p.product_id ? null : p.product_id)}>
                        versions
                      </button>
                    </td>
                  </tr>
                  {open === p.product_id ? (
                    <tr>
                      <td colSpan={8} className="bg-slate-50 px-6 py-2">
                        <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                          {p.versions.map((v) => (
                            <li key={`${v.version}-${v.state}`}>
                              <code>{v.version || "(blank)"}</code> <Badge tone={statusTone[v.state]}>{STATE_LABEL[v.state]}</Badge>{" "}
                              {v.installations} installs on {v.unique_assets} devices
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Drilldown({ customer, state, product, onReset }: { customer: Customer; state: string; product: string; onReset: () => void }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["software", customer.id, "rows", state, product, search, page],
    queryFn: ({ signal }) => api.get<Paginated<SoftwareRow>>(`/customers/${customer.id}/software/`,
      { state, product, search, page, page_size: PAGE_SIZE }, signal),
    placeholderData: (prev) => prev,
  });
  const columns: ColumnDef<SoftwareRow, unknown>[] = [
    { header: "Device", cell: ({ row }) => row.original.hostname ?? row.original.asset_id.slice(0, 8) },
    ...softwareColumns,
  ];
  return (
    <section aria-labelledby="drill-heading" className="mt-6">
      <div className="mb-2 flex flex-wrap items-end gap-3">
        <h2 id="drill-heading" className="text-sm font-semibold">
          Installations {state ? `· ${STATE_LABEL[state as ComplianceState]}` : ""} {product ? "· selected product" : ""}
        </h2>
        <label className="flex items-center gap-1 text-xs">
          Search
          <input className="input w-48" type="search" maxLength={100} value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        </label>
        {state || product ? <button type="button" className="btn-secondary" onClick={onReset}>Clear filters</button> : null}
        {customer.my_capabilities.includes(CAP.export) ? (
          <ExportButton customer={customer} reportType="software_compliance" label="Export CSV" filters={{ state, product, search }} />
        ) : null}
      </div>
      <QueryBoundary query={query}>
        {(data) => <DataTable caption="Software installations" columns={columns} rows={data.results} total={data.count}
                              page={page} pageSize={PAGE_SIZE} onPageChange={setPage} getRowId={(r) => r.id}
                              emptyTitle="No installations match." />}
      </QueryBoundary>
    </section>
  );
}

function Exceptions({ customer, products }: { customer: Customer; products: ProductSummary[] }) {
  const queryClient = useQueryClient();
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const url = `/customers/${customer.id}/software-exceptions/`;
  const list = useQuery({ queryKey: ["exceptions", customer.id], queryFn: () => api.get<Paginated<SoftwareExceptionRow>>(url) });
  const [product, setProduct] = useState("");
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["exceptions", customer.id] });
    void queryClient.invalidateQueries({ queryKey: ["software", customer.id] });
  };
  const create = useMutation({
    mutationFn: () => api.post(url, { product, reason, expires_at: new Date(expires).toISOString() }),
    onSuccess: () => { setReason(""); refresh(); },
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.del(`${url}${id}/`), onSuccess: refresh });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <section aria-labelledby="exc-heading" className="mt-6">
      <h2 id="exc-heading" className="mb-2 text-sm font-semibold">Approved exceptions</h2>
      {canManage ? (
        <form onSubmit={submit} aria-label="Add exception" className="mb-3 flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
          <Field label="Product">{(id) => (
            <select id={id} className="input w-64" required value={product} onChange={(e) => setProduct(e.target.value)}>
              <option value="">Select…</option>
              {products.map((p) => <option key={p.product_id} value={p.product_id}>{p.label} ({p.channel})</option>)}
            </select>)}</Field>
          <Field label="Justification">{(id) => <input id={id} className="input w-72" required minLength={10} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <Field label="Expires (max 12 months)">{(id) => <input id={id} className="input" type="date" required value={expires} onChange={(e) => setExpires(e.target.value)} />}</Field>
          <button type="submit" className="btn-primary" disabled={create.isPending}>Approve exception</button>
          {create.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(create.error)}</p> : null}
        </form>
      ) : null}
      <QueryBoundary query={list}>
        {(data) => <DataTable caption="Software exceptions" rows={data.results} getRowId={(r) => r.id} emptyTitle="No exceptions."
          columns={[
            { header: "Product", accessorKey: "product_label" },
            { header: "Scope", cell: ({ row }) => (row.original.asset ? "single device" : "all devices") },
            { header: "Reason", accessorKey: "reason" },
            { header: "Approved", cell: ({ row }) => `${row.original.approved_by}, ${formatUtc(row.original.approved_at)}` },
            { header: "Expires", cell: ({ row }) => formatUtc(row.original.expires_at) },
            { header: "Status", cell: ({ row }) => <Badge tone={row.original.status === "active" ? "info" : "neutral"}>{row.original.status}</Badge> },
            { header: "", id: "act", cell: ({ row }) => canManage && row.original.status === "active"
                ? <button type="button" className="btn-danger" onClick={() => revoke.mutate(row.original.id)}>Revoke</button> : null },
          ]} />}
      </QueryBoundary>
    </section>
  );
}

function SoftwareView({ customer }: { customer: Customer }) {
  const [drill, setDrill] = useState<{ state: string; product: string }>({ state: "outdated", product: "" });
  const summary = useQuery({
    queryKey: ["software", customer.id, "summary"],
    queryFn: ({ signal }) => api.get<SoftwareSummary>(`/customers/${customer.id}/software/summary/`, undefined, signal),
  });
  return (
    <>
      <DataSources customer={customer} />
      <QueryBoundary query={summary} isEmpty={(s) => s.eligible_installations === 0}
        empty={<EmptyState title="No installed-software inventory in the current dataset.">Run a sync once a source mapping is approved.</EmptyState>}>
        {(s) => (
          <>
            <Summary s={s} onDrill={(state, product) => setDrill({ state, product })} />
            <Drilldown customer={customer} state={drill.state} product={drill.product} onReset={() => setDrill({ state: "", product: "" })} />
            <Exceptions customer={customer} products={s.products} />
          </>
        )}
      </QueryBoundary>
    </>
  );
}

export function SoftwarePage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Software versions" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? <SelectCustomer /> : <SoftwareView customer={selected} />}
    </>
  );
}
