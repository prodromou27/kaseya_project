import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link, useLocation } from "react-router";
import { useUrlFilters } from "../../lib/useUrlFilters";
import { Fragment, useState, type FormEvent } from "react";

import { Tabs } from "../../components/Tabs";
import { InvestigationDeviceLink } from "../../components/InvestigationDeviceLink";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Badge, Field, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
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
import { ThirdPartyPatching } from "./ThirdPartyPatching";
import { AddToCatalog } from "./AddToCatalog";
import { ExportButton } from "../reports/ExportButton";
import { SelectCustomer } from "../../components/SelectCustomer";

const STATES: ComplianceState[] = ["outdated", "current", "newer", "unknown", "excluded", "unsupported"];

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-slate-500">{hint}</div>
    </div>
  );
}

type InstalledProgram = { name: string; publisher: string; devices: number; version_count: number; versions: { version: string; devices: number }[] };

/** What the source reported as installed, grouped by name/publisher. Needs no catalog. */
function InstalledPrograms({ customer }: { customer: Customer }) {
  const me = useMe();
  const [adding, setAdding] = useState<InstalledProgram | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const term = useDebouncedValue(search, 300);
  const query = useQuery({
    queryKey: ["software", customer.id, "installed", term, page],
    queryFn: ({ signal }) => api.get<Paginated<InstalledProgram>>(`/customers/${customer.id}/software/installed/`, { search: term, page }, signal),
  });
  const columns: ColumnDef<InstalledProgram, unknown>[] = [
    { header: "Program", cell: ({ row }) => <span className="font-medium text-slate-900">{row.original.name}</span> },
    { header: "Publisher", cell: ({ row }) => row.original.publisher || <span className="text-slate-500">Not reported</span> },
    { header: "Devices", cell: ({ row }) => <span className="tabular-nums">{row.original.devices}</span> },
    { header: "Versions", cell: ({ row }) => (
      <span className="flex flex-wrap gap-1">
        {row.original.versions.map((v) => <span key={v.version} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700"><span className="nowrap">{v.version || "no version"}</span> · {v.devices}</span>)}
        {row.original.version_count > row.original.versions.length ? <span className="text-xs text-slate-500">+{row.original.version_count - row.original.versions.length} more</span> : null}
      </span>
    ) },
    ...(me.is_super_admin ? [{ header: "", id: "catalog", cell: ({ row }: { row: { original: InstalledProgram } }) => (
      <button type="button" className="btn-secondary" onClick={() => setAdding(row.original)}>Add to catalog</button>
    ) } as ColumnDef<InstalledProgram, unknown>] : []),
  ];
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">Everything the source reported as installed. No catalog needed; versions are shown as reported, without judging them.</p>
      <label className="list-label">Find a program<input className="input max-w-md" type="search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Name or publisher" /></label>
      {adding ? <AddToCatalog key={`${adding.name}|${adding.publisher}`} program={adding} onClose={() => setAdding(null)} /> : null}
      <QueryBoundary query={query}>
        {(data) => <DataTable caption="Installed programs" columns={columns} rows={data.results} total={data.count} page={page} pageSize={50} onPageChange={setPage}
          getRowId={(r) => `${r.name}|${r.publisher}`} emptyTitle={term ? "No programs match your search." : "No installed software reported in the current inventory."} />}
      </QueryBoundary>
    </div>
  );
}

function NoCatalog({ onShowInstalled }: { onShowInstalled: () => void }) {
  const me = useMe();
  return (
    <EmptyState title="No catalogued products yet, so versions are not compared.">
      <span className="block">Installed software is still collected. <button type="button" className="font-medium text-sky-800 underline" onClick={onShowInstalled}>See installed programs</button>.</span>
      {me.is_super_admin ? <span className="mt-1 block">To flag outdated versions, open <button type="button" className="font-medium text-sky-800 underline" onClick={onShowInstalled}>Installed programs</button> and use <strong>Add to catalog</strong> on the programs you care about (or import many under <Link className="font-medium text-sky-800 underline" to="/admin?tab=catalog">Settings → Software catalog</Link>).</span> : null}
    </EmptyState>
  );
}

function Summary({ s, onDrill, onShowInstalled }: { s: SoftwareSummary; onDrill: (state: ComplianceState | "", product: string) => void; onShowInstalled: () => void }) {
  const [productSearch, setProductSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const visibleProducts = s.products.filter((product) => `${product.label} ${product.channel}`.toLowerCase().includes(productSearch.toLowerCase()));
  const pct = (v: number | null) => (v === null ? "n/a" : `${v}%`);
  return (
    <>
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
      <label className="list-label mb-3">Find a product<input className="input max-w-md" type="search" value={productSearch} onChange={(event) => setProductSearch(event.target.value)} placeholder="Product or channel" /></label>
      {s.products.length === 0 ? <NoCatalog onShowInstalled={onShowInstalled} /> : visibleProducts.length === 0 ? <EmptyState title="No products match your search."><button type="button" className="underline text-sky-800" onClick={() => setProductSearch("")}>Clear product search</button></EmptyState> : (
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
              {visibleProducts.map((p: ProductSummary) => (
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

function Drilldown({ customer, products }: { customer: Customer; products: ProductSummary[] }) {
  const { filters, update, page, setPage } = useUrlFilters({ search: "", state: "outdated", product: "", page_size: "50" });
  const { state, product } = filters;
  const search = useDebouncedValue(filters.search);
  const pageSize = [25, 50, 100, 200].includes(Number(filters.page_size)) ? Number(filters.page_size) : 50;
  const query = useQuery({
    queryKey: ["software", customer.id, "rows", state, product, search, page, pageSize],
    queryFn: ({ signal }) => api.get<Paginated<SoftwareRow>>(`/customers/${customer.id}/software/`, { state, product, search, page, page_size: pageSize }, signal),
    placeholderData: (prev) => prev,
  });
  const columns: ColumnDef<SoftwareRow, unknown>[] = [
    { header: "Device", cell: ({ row }) => <InvestigationDeviceLink assetId={row.original.asset_id} name={row.original.hostname ?? row.original.asset_id.slice(0, 8)} tab="software" /> }, ...softwareColumns,
  ];
  return <section aria-label="Installation investigation" className="space-y-3">
    <div className="list-workspace flex flex-wrap items-end gap-3">
      <Field label="Search">{(id) => <input id={id} className="input w-72" type="search" maxLength={100} value={filters.search} placeholder="Software, publisher, version or device" onChange={(event) => update({ search: event.target.value }, true)} />}</Field>
      <Field label="Classification">{(id) => <select id={id} className="input" value={state} onChange={(event) => update({ state: event.target.value })}><option value="">All classifications</option>{STATES.map((item) => <option key={item} value={item}>{STATE_LABEL[item]}</option>)}</select>}</Field>
      <Field label="Product">{(id) => <select id={id} className="input max-w-64" value={product} onChange={(event) => update({ product: event.target.value })}><option value="">All products</option>{products.map((item) => <option key={item.product_id} value={item.product_id}>{item.label} ({item.channel})</option>)}</select>}</Field>
      <button type="button" className="btn-secondary" onClick={() => update({ state: "", product: "", search: "" })}>Clear filters</button>
      {customer.my_capabilities.includes(CAP.export) ? <ExportButton customer={customer} reportType="software_compliance" label="Export installations" filters={{ state, product, search: filters.search }} /> : null}
    </div>
    <p className="text-xs text-slate-500">Installation records, not unique devices. {state ? `Classification: ${STATE_LABEL[state as ComplianceState] ?? state}.` : "All classifications."}</p>
    {query.isError && page > 1 ? <button type="button" className="btn-secondary" onClick={() => setPage(1)}>Return to first page</button> : null}
    <QueryBoundary query={query}>{(data) => <DataTable columnChooser caption="Software installations" columns={columns} rows={data.results} total={data.count} loading={query.isFetching || filters.search !== search}
      page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={(size) => update({ page_size: String(size) })} getRowId={(row) => row.id} emptyTitle="No installations match." />}</QueryBoundary>
  </section>;
}

function Exceptions({ customer, products }: { customer: Customer; products: ProductSummary[] }) {
  const queryClient = useQueryClient();
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const url = `/customers/${customer.id}/software-exceptions/`;
  const { page, setPage } = useUrlFilters({});
  const list = useQuery({ queryKey: ["exceptions", customer.id, page], queryFn: () => api.get<Paginated<SoftwareExceptionRow>>(url, { page }) });
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
      {list.isError && page > 1 ? <button type="button" className="btn-secondary" onClick={() => setPage(1)}>Return to first page</button> : null}
      <QueryBoundary query={list}>
        {(data) => <DataTable caption="Software exceptions" rows={data.results} total={data.count} page={page} onPageChange={setPage} getRowId={(r) => r.id} emptyTitle="No exceptions."
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
  const { filters, update } = useUrlFilters({ view: "", state: "outdated", product: "", search: "" });
  const location = useLocation();
  const active = filters.view || (filters.product || filters.search || new URLSearchParams(location.search).has("state") ? "installations" : "overview");
  const summary = useQuery({ queryKey: ["software", customer.id, "summary"], queryFn: ({ signal }) => api.get<SoftwareSummary>(`/customers/${customer.id}/software/summary/`, undefined, signal) });
  return <>
    <DataSources customer={customer} compact />
    <p className="mb-2 text-xs text-slate-500">Version comparison against a reviewed catalog. Not evidence of missing third-party patches or vulnerabilities.</p>
    <ThirdPartyPatchNotice status={summary.data?.third_party_patch_status} />
    <div className="mt-4"><Tabs label="Software workspace" active={active} onChange={(view) => update({ view })} tabs={[
      { id: "overview", label: "Overview", content: <QueryBoundary query={summary} isEmpty={(s) => s.eligible_installations === 0} empty={<EmptyState title="No installed-software inventory in the current dataset.">Run a sync once a source mapping is approved.</EmptyState>}>{(s) => <Summary s={s} onDrill={(state, product) => update({ state, product, view: "installations" })} onShowInstalled={() => update({ view: "programs" })} />}</QueryBoundary> },
      { id: "programs", label: "Installed programs", content: <InstalledPrograms customer={customer} /> },
      { id: "third-party", label: "Third-party patching", content: <ThirdPartyPatching customer={customer} /> },
      { id: "installations", label: "Installations", content: <Drilldown customer={customer} products={summary.data?.products ?? []} /> },
      { id: "exceptions", label: "Exceptions", content: <Exceptions customer={customer} products={summary.data?.products ?? []} /> },
    ]} /></div>
  </>;
}

export function SoftwarePage() {
  const { selected } = useCustomers();
  return (
    <>
      <PageHeader title="Software versions" subtitle={selected ? `${selected.code} — ${selected.name}` : undefined} />
      {!selected ? <SelectCustomer /> : <SoftwareView key={selected.id} customer={selected} />}
    </>
  );
}
