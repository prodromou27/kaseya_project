import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, Notice, type Tone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { LifecycleCatalogEntry, Paginated } from "../../lib/types";

type Product = { id: string; vendor: string; product: string; edition: string; channel: string };
const STATE_TONE: Record<LifecycleCatalogEntry["state"], Tone> = { proposed: "warn", approved: "good", rejected: "bad", retired: "neutral" };
const SOURCE_TYPES = [
  ["vendor_lifecycle_page", "Vendor lifecycle page"],
  ["vendor_announcement", "Vendor announcement"],
  ["manual_verification", "Manual verification"],
] as const;

const EMPTY = {
  kind: "os" as "os" | "software",
  os_family: "",
  product: "",
  release_label: "",
  version_prefix: "",
  end_of_support: "",
  extended_until: "",
  source_url: "",
  source_type: "vendor_lifecycle_page",
  source_checked_at: new Date().toISOString().slice(0, 10),
  confidence: "official" as "official" | "secondary",
  note: "",
};

/** Super admin: propose lifecycle entries; a different super admin approves them. Approved entries are immutable. */
export function LifecycleCatalogPanel() {
  const qc = useQueryClient();
  const [state, setState] = useState("");
  const [form, setForm] = useState(EMPTY);
  const entries = useQuery({
    queryKey: ["lifecycle-catalog", state],
    queryFn: ({ signal }) => api.get<Paginated<LifecycleCatalogEntry>>("/catalog/lifecycle/", state ? { state } : undefined, signal),
  });
  const products = useQuery({
    queryKey: ["catalog-products", "all"],
    queryFn: ({ signal }) => api.get<Paginated<Product>>("/catalog/products/", { page_size: 200 }, signal),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["lifecycle-catalog"] });
  const propose = useMutation({
    mutationFn: () =>
      api.post<LifecycleCatalogEntry>("/catalog/lifecycle/", {
        ...form,
        os_family: form.kind === "os" ? form.os_family : "",
        product: form.kind === "software" ? form.product || null : null,
        extended_until: form.extended_until || null,
      }),
    onSuccess: () => {
      setForm(EMPTY);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: "approve" | "reject" | "retire" }) => api.post<LifecycleCatalogEntry>(`/catalog/lifecycle/${id}/${verb}/`, {}),
    onSuccess: refresh,
  });
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    propose.mutate();
  };
  const columns: ColumnDef<LifecycleCatalogEntry, unknown>[] = [
    { header: "State", cell: ({ row }) => <Badge tone={STATE_TONE[row.original.state]}>{row.original.state}</Badge> },
    {
      header: "Target",
      cell: ({ row }) => (
        <span>
          {row.original.kind === "os" ? row.original.os_family : row.original.product_label} <strong>{row.original.release_label}</strong>
          {row.original.version_prefix ? <span className="block text-xs text-slate-500">version {row.original.version_prefix}.*</span> : null}
        </span>
      ),
    },
    { header: "End of support", accessorKey: "end_of_support" },
    { header: "Extended until", cell: ({ row }) => row.original.extended_until ?? "—" },
    {
      header: "Source",
      cell: ({ row }) => (
        <span className="text-xs">
          <a href={row.original.source_url} target="_blank" rel="noreferrer noopener" className="text-sky-800 underline">{row.original.source_type.replace(/_/g, " ")}</a>
          <span className="block text-slate-500">checked {row.original.source_checked_at} · {row.original.confidence}</span>
        </span>
      ),
    },
    { header: "Proposed / reviewed", cell: ({ row }) => <span className="text-xs">{row.original.created_by}<span className="block text-slate-500">{row.original.reviewed_by ?? "not reviewed"}</span></span> },
    {
      header: "Review",
      cell: ({ row }) => (
        <span className="flex gap-1">
          {row.original.state === "proposed" ? (
            <>
              <button type="button" className="btn-secondary" disabled={act.isPending} onClick={() => act.mutate({ id: row.original.id, verb: "approve" })}>Approve</button>
              <button type="button" className="btn-secondary text-red-700" disabled={act.isPending} onClick={() => act.mutate({ id: row.original.id, verb: "reject" })}>Reject</button>
            </>
          ) : null}
          {row.original.state === "approved" ? (
            <button type="button" className="btn-secondary" disabled={act.isPending}
                    onClick={() => { if (window.confirm("Retire this entry? Devices it covers become unknown until a new entry is approved.")) act.mutate({ id: row.original.id, verb: "retire" }); }}>
              Retire
            </button>
          ) : null}
        </span>
      ),
    },
  ];
  return (
    <div className="space-y-3">
      <Notice tone="info">
        Lifecycle entries drive the end-of-support views and report R17. Cite the vendor's official lifecycle page. A
        different super admin must approve each entry; approved entries cannot be edited, only retired and replaced.
        Entries with a <em>secondary</em> source are kept for reference but never classify a device (shown as unknown).
      </Notice>
      <form onSubmit={submit} aria-label="Propose lifecycle entry" className="space-y-2 rounded border border-slate-200 bg-white p-3">
        <h3 className="font-semibold">Propose an entry</h3>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Type">
            {(id) => (
              <select id={id} className="input" value={form.kind} onChange={set("kind")}>
                <option value="os">Operating system</option>
                <option value="software">Software</option>
              </select>
            )}
          </Field>
          {form.kind === "os" ? (
            <Field label="OS family (as reported)" hint="e.g. Windows 11, Windows Server 2019">
              {(id, hint) => <input id={id} aria-describedby={hint} className="input w-56" required value={form.os_family} onChange={set("os_family")} />}
            </Field>
          ) : (
            <Field label="Catalog product">
              {(id) => (
                <select id={id} className="input w-64" required value={form.product} onChange={set("product")}>
                  <option value="">Choose…</option>
                  {(products.data?.results ?? []).map((p) => (
                    <option key={p.id} value={p.id}>{p.vendor} {p.product}{p.edition ? ` ${p.edition}` : ""} ({p.channel})</option>
                  ))}
                </select>
              )}
            </Field>
          )}
          <Field label="Release">{(id) => <input id={id} className="input w-32" required value={form.release_label} onChange={set("release_label")} placeholder="e.g. 23H2" />}</Field>
          <Field label="Version prefix" hint="Dotted, e.g. 10.0.22631 (blank = whole family)">
            {(id, hint) => <input id={id} aria-describedby={hint} className="input w-36" value={form.version_prefix} onChange={set("version_prefix")} />}
          </Field>
          <Field label="End of support">{(id) => <input id={id} className="input" type="date" required value={form.end_of_support} onChange={set("end_of_support")} />}</Field>
          <Field label="Extended support until">{(id) => <input id={id} className="input" type="date" value={form.extended_until} onChange={set("extended_until")} />}</Field>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Source URL (https)">{(id) => <input id={id} className="input w-80" type="url" required value={form.source_url} onChange={set("source_url")} placeholder="https://" />}</Field>
          <Field label="Source type">
            {(id) => (
              <select id={id} className="input" value={form.source_type} onChange={set("source_type")}>
                {SOURCE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            )}
          </Field>
          <Field label="Source checked on">{(id) => <input id={id} className="input" type="date" required value={form.source_checked_at} onChange={set("source_checked_at")} />}</Field>
          <Field label="Confidence">
            {(id) => (
              <select id={id} className="input" value={form.confidence} onChange={set("confidence")}>
                <option value="official">Official vendor source</option>
                <option value="secondary">Secondary source (not used to classify)</option>
              </select>
            )}
          </Field>
          <button type="submit" className="btn-primary" disabled={propose.isPending}>Propose</button>
        </div>
        {propose.isError ? <p role="alert" className="text-sm text-red-700">{describeError(propose.error)}</p> : null}
      </form>
      <div className="flex items-end gap-2">
        <Field label="Show">
          {(id) => (
            <select id={id} className="input" value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">All</option>
              <option value="proposed">Proposed</option>
              <option value="approved">Approved</option>
              <option value="retired">Retired</option>
              <option value="rejected">Rejected</option>
            </select>
          )}
        </Field>
      </div>
      {act.isError ? <p role="alert" className="text-sm text-red-700">{describeError(act.error)}</p> : null}
      <QueryBoundary query={entries}>
        {(data) => <DataTable caption="Lifecycle catalog" columns={columns} rows={data.results} total={data.count} getRowId={(r) => r.id} emptyTitle="No lifecycle entries yet." />}
      </QueryBoundary>
    </div>
  );
}
