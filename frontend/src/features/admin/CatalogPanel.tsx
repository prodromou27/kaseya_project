import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Notice, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { formatUtc } from "../../lib/format";
import type { CatalogAlias, CatalogImport, CatalogProduct, Paginated } from "../../lib/types";

const EXAMPLE = JSON.stringify(
  [
    {
      vendor: "Google",
      product: "Chrome",
      channel: "stable",
      architecture: "any",
      reference_version: "131.0.6778.86",
      vendor_url: "https://chromereleases.googleblog.com/",
      source_type: "vendor_release_notes",
      source_checked_at: new Date().toISOString(),
      aliases: [{ name_pattern: "Google Chrome", publisher_pattern: "Google LLC", match_type: "exact" }],
    },
  ],
  null,
  2,
);

type Preview = { valid: boolean; rows: CatalogImport["preview"] };

function PreviewTable({ rows }: { rows: CatalogImport["preview"] }) {
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((r) => (
        <li key={r.index} className="rounded bg-slate-50 px-2 py-1">
          Row {r.index + 1}: {r.status === "ok" ? (
            <>
              <strong>{r.product}</strong> · {r.change?.replace("_", " ")} · {r.current_reference ?? "—"} → <code>{r.new_reference}</code>
              {r.warnings?.map((w) => <span key={w} className="block text-amber-800">⚠ {w}</span>)}
            </>
          ) : <span className="text-red-700">{JSON.stringify(r.errors)}</span>}
        </li>
      ))}
    </ul>
  );
}

function ImportForm() {
  const queryClient = useQueryClient();
  const [text, setText] = useState(EXAMPLE);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const parse = (): unknown[] | null => {
    try {
      const value: unknown = JSON.parse(text);
      setParseError(null);
      return Array.isArray(value) ? value : null;
    } catch {
      setParseError("Not valid JSON.");
      return null;
    }
  };
  const doPreview = useMutation({ mutationFn: (rows: unknown[]) => api.post<Preview>("/catalog/imports/preview/", { rows }), onSuccess: setPreview });
  const submit = useMutation({
    mutationFn: (rows: unknown[]) => api.post<CatalogImport>("/catalog/imports/", { rows }),
    onSuccess: () => { setPreview(null); void queryClient.invalidateQueries({ queryKey: ["catalog"] }); },
  });
  return (
    <div className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <label htmlFor="catalog-json" className="text-sm font-medium">Reference versions to import (JSON array)</label>
      <textarea id="catalog-json" className="input h-48 w-full font-mono text-xs" value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
      <div className="flex gap-2">
        <button type="button" className="btn-secondary" onClick={() => { const r = parse(); if (r) doPreview.mutate(r); }}>Preview (dry run)</button>
        <button type="button" className="btn-primary" disabled={!preview?.valid || submit.isPending}
                onClick={() => { const r = parse(); if (r) submit.mutate(r); }}>Submit for review</button>
      </div>
      {parseError ? <p role="alert" className="text-sm text-red-700">{parseError}</p> : null}
      {doPreview.isError ? <p role="alert" className="text-sm text-red-700">{describeError(doPreview.error)}</p> : null}
      {submit.isError ? <p role="alert" className="text-sm text-red-700">{describeError(submit.error)}</p> : null}
      {submit.isSuccess ? <p role="status" className="text-sm text-emerald-700">Submitted. A different administrator must approve it.</p> : null}
      {preview ? <PreviewTable rows={preview.rows} /> : null}
    </div>
  );
}

export function CatalogPanel() {
  const me = useMe();
  const queryClient = useQueryClient();
  const imports = useQuery({ queryKey: ["catalog", "imports"], queryFn: () => api.get<Paginated<CatalogImport>>("/catalog/imports/") });
  const products = useQuery({ queryKey: ["catalog", "products"], queryFn: () => api.get<Paginated<CatalogProduct>>("/catalog/products/", { page_size: 200 }) });
  const aliases = useQuery({ queryKey: ["catalog", "aliases"], queryFn: () => api.get<Paginated<CatalogAlias>>("/catalog/aliases/", { review_status: "proposed" }) });
  const review = useMutation({
    mutationFn: ({ path }: { path: string }) => api.post(path),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["catalog"] }),
  });

  return (
    <div className="space-y-6">
      <Notice tone="warn">
        Reference versions drive “outdated” classifications. Each import is previewed, then approved by a <strong>different</strong>{" "}
        administrator. Published revisions are immutable; retire and re-import to change one. This is version comparison only —
        not patch applicability.
      </Notice>
      <ImportForm />
      {review.isError ? <p role="alert" className="text-sm text-red-700">{describeError(review.error)}</p> : null}
      <section aria-labelledby="imports-h">
        <h3 id="imports-h" className="mb-2 text-sm font-semibold">Imports</h3>
        <QueryBoundary query={imports}>
          {(data) => <DataTable caption="Catalog imports" rows={data.results} getRowId={(r) => r.id} emptyTitle="No imports yet." columns={[
            { header: "Submitted", cell: ({ row }) => `${row.original.created_by}, ${formatUtc(row.original.created_at)}` },
            { header: "Rows", cell: ({ row }) => row.original.rows.length },
            { header: "Preview", cell: ({ row }) => <PreviewTable rows={row.original.preview} /> },
            { header: "State", cell: ({ row }) => <Badge tone={row.original.state === "pending" ? "warn" : statusTone[row.original.state]}>{row.original.state}</Badge> },
            { header: "Review", cell: ({ row }) => row.original.state !== "pending" ? (row.original.reviewed_by ?? "—")
                : row.original.created_by === me.email ? <span className="text-xs text-slate-500">awaiting another reviewer</span>
                : <span className="flex gap-1">
                    <button type="button" className="btn-secondary" onClick={() => review.mutate({ path: `/catalog/imports/${row.original.id}/approve/` })}>Approve</button>
                    <button type="button" className="btn-danger" onClick={() => review.mutate({ path: `/catalog/imports/${row.original.id}/reject/` })}>Reject</button>
                  </span> },
          ]} />}
        </QueryBoundary>
      </section>
      <section aria-labelledby="aliases-h">
        <h3 id="aliases-h" className="mb-2 text-sm font-semibold">Proposed aliases</h3>
        <QueryBoundary query={aliases}>
          {(data) => <DataTable caption="Proposed aliases" rows={data.results} getRowId={(r) => r.id} emptyTitle="No aliases awaiting review." columns={[
            { header: "Pattern", cell: ({ row }) => <code className="text-xs">{row.original.match_type}: {row.original.name_pattern}</code> },
            { header: "Publisher", cell: ({ row }) => row.original.publisher_pattern || "any" },
            { header: "Proposed by", accessorKey: "created_by" },
            { header: "Review", cell: ({ row }) => row.original.created_by === me.email ? <span className="text-xs text-slate-500">awaiting another reviewer</span> : (
                <span className="flex gap-1">
                  <button type="button" className="btn-secondary" onClick={() => review.mutate({ path: `/catalog/aliases/${row.original.id}/approve/` })}>Approve</button>
                  <button type="button" className="btn-danger" onClick={() => review.mutate({ path: `/catalog/aliases/${row.original.id}/reject/` })}>Reject</button>
                </span>) },
          ]} />}
        </QueryBoundary>
      </section>
      <section aria-labelledby="products-h">
        <h3 id="products-h" className="mb-2 text-sm font-semibold">Catalogued products</h3>
        <QueryBoundary query={products}>
          {(data) => <DataTable caption="Catalogued products" rows={data.results} getRowId={(r) => r.id} total={data.count} emptyTitle="Catalog is empty." columns={[
            { header: "Product", cell: ({ row }) => `${row.original.vendor} ${row.original.product} ${row.original.edition}`.trim() },
            { header: "Channel", accessorKey: "channel" },
            { header: "Arch", accessorKey: "architecture" },
            { header: "Current reference", cell: ({ row }) => row.original.current_reference ? (
                <span><code className="text-xs">{row.original.current_reference.reference_version}</code>{" "}
                  <a className="text-xs text-sky-800 underline" href={row.original.current_reference.vendor_url} target="_blank" rel="noopener noreferrer">evidence</a></span>)
                : <span className="text-slate-400">none published</span> },
          ]} />}
        </QueryBoundary>
      </section>
    </div>
  );
}
