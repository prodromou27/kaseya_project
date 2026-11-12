import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, Notice, PageHeader, statusTone } from "../../components/ui";
import { api } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import { STATE_LABEL, type AssetDetail, type SoftwareRow } from "../../lib/types";

export const softwareColumns: ColumnDef<SoftwareRow, unknown>[] = [
  { header: "Installed software", cell: ({ row }) => (
      <span>{row.original.name}<span className="block text-xs text-slate-500">{row.original.publisher}</span></span>) },
  { header: "Installed", accessorKey: "installed_version", cell: ({ getValue }) => <code className="text-xs">{String(getValue() || "—")}</code> },
  { header: "Reference", cell: ({ row }) => row.original.reference_version
      ? <code className="text-xs">{row.original.reference_version}</code> : <span className="text-slate-400">—</span> },
  { header: "Classification", cell: ({ row }) => (
      <span><Badge tone={statusTone[row.original.state]}>{STATE_LABEL[row.original.state]}</Badge>
        <span className="block text-[11px] text-slate-500">{row.original.reason_code}</span></span>) },
  { header: "Catalog product", cell: ({ row }) => row.original.product
      ? <span>{row.original.product}{row.original.catalog_source_url ? (
          <a className="ml-1 text-xs text-sky-800 underline" href={row.original.catalog_source_url} target="_blank" rel="noopener noreferrer">evidence</a>) : null}</span>
      : <span className="text-slate-400">not catalogued</span> },
];

function Overview({ detail }: { detail: AssetDetail }) {
  const a = detail.asset;
  if (!a) return <Notice tone="warn">This device is not in the current published dataset (it may have been removed at the source or its mapping revoked).</Notice>;
  const fields: [string, string][] = [
    ["Device ID (source)", detail.external_id], ["Hostname", a.hostname], ["Description", a.description],
    ["Group", a.group_name], ["Site ID", a.site_external_id], ["Organization ID", a.organization_external_id],
    ["OS", [a.os_name, a.os_version].filter(Boolean).join(" ") || "not reported"],
    ["Manufacturer / model", [a.manufacturer, a.model].filter(Boolean).join(" ") || "not reported"],
    ["Serial number", a.serial_number || "not reported"], ["Domain", a.domain || "not reported"],
    ["Agent version", a.client_version], ["Last seen online", formatUtc(a.last_seen_online)],
    ["Source", `${a.source} (${a.data_basis})`], ["Dataset as of", formatUtc(a.as_of)],
  ];
  return (
    <dl className="grid max-w-3xl grid-cols-[12rem_1fr] gap-y-1 text-sm">
      {fields.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="break-all">{v || "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function AssetDetailPage() {
  const { assetId = "" } = useParams();
  const [tab, setTab] = useState("overview");
  const query = useQuery({
    queryKey: ["asset", assetId],
    queryFn: ({ signal }) => api.get<AssetDetail>(`/assets/${assetId}/`, undefined, signal),
  });
  return (
    <QueryBoundary query={query}>
      {(detail) => (
        <>
          <p className="mb-1 text-sm"><Link to="/assets" className="text-sky-800 hover:underline">← Assets</Link></p>
          <PageHeader title={detail.asset?.hostname || detail.external_id}
                      subtitle={detail.active ? "Active in current inventory" : "Inactive (absent from latest complete inventory)"} />
          <Tabs label="Device sections" active={tab} onChange={setTab} tabs={[
            { id: "overview", label: "Overview", content: <Overview detail={detail} /> },
            { id: "software", label: `Installed software (${detail.software.length})`, content: (
              detail.asset?.software_status === "not_collected"
                ? <Notice tone="warn">The source did not return an InstalledSoftware section for this device. This is “not collected”, not “no software”.</Notice>
                : <DataTable caption="Installed software" columns={softwareColumns} rows={detail.software} getRowId={(r) => r.id}
                             emptyTitle="The source reported no installed software for this device." />
            ) },
            { id: "history", label: "Observation history", content: (
              <DataTable caption="Observation history" getRowId={(h) => h.generation_id} rows={detail.history} columns={[
                { header: "Dataset published", cell: ({ row }) => formatUtc(row.original.published_at) },
                { header: "Hostname", accessorKey: "hostname" },
                { header: "Last seen", cell: ({ row }) => formatUtc(row.original.last_seen_online) },
                { header: "Software items", cell: ({ row }) => row.original.software_count ?? "not collected" },
                { header: "", id: "cur", cell: ({ row }) => (row.original.current ? <Badge tone="good">current</Badge> : null) },
              ]} />
            ) },
          ]} />
        </>
      )}
    </QueryBoundary>
  );
}
