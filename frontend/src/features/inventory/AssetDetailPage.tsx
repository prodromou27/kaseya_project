import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, Notice, PageHeader, statusTone } from "../../components/ui";
import { ThirdPartyPatchNotice } from "../../components/ThirdPartyPatchNotice";
import { api } from "../../lib/api";
import { AdapterList } from "../groups/GroupNetworkPage";
import { formatUtc } from "../../lib/format";
import { PATCH_STATE_LABEL, STATE_LABEL, UPDATE_STATUS_LABEL, type AssetDetail, type SoftwareRow } from "../../lib/types";
import { PolicyDefinitionView } from "../policies/PolicyDefinitionView";

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
    ["Group", `${a.group_name}${a.group_external_id ? ` (ID ${a.group_external_id})` : " (group ID not reported)"}`],
    ["Site", `${a.site_name || "?"} (ID ${a.site_external_id || "?"})`], ["Organization ID", a.organization_external_id],
    ["Agent installed", detail.details?.is_agent_installed === null || detail.details === null ? "not reported"
      : detail.details.is_agent_installed ? "yes" : "no"],
    ["OS", [a.os_name, a.os_version].filter(Boolean).join(" ") || "not reported"],
    ["Manufacturer / model", [a.manufacturer, a.model].filter(Boolean).join(" ") || "not reported"],
    ["Serial number", a.serial_number || "not reported"], ["Domain", a.domain || "not reported"],
    ["Agent version", a.client_version], ["Last seen online", formatUtc(a.last_seen_online)],
    ["Source", `${a.source} (${a.data_basis})`], ["Dataset as of", formatUtc(a.as_of)],
  ];
  const h = detail.health;
  return (
    <div className="space-y-4">
      <dl className="grid max-w-3xl grid-cols-[12rem_1fr] gap-y-1 text-sm">
        {fields.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="break-all">{v || "—"}</dd>
          </div>
        ))}
      </dl>
      {h ? (
        <section aria-label="Device health" className="max-w-3xl rounded border border-slate-200 bg-white p-3 text-sm">
          <h3 className="mb-1 font-semibold">Health (snapshot {formatUtc(h.snapshot_at)}, {h.thresholds.source} thresholds)</h3>
          <p className="mb-2 text-xs text-slate-500">Derived from the inventory snapshot, not live monitoring. Unknown states are not healthy or unhealthy.</p>
          <dl className="grid grid-cols-[12rem_1fr] gap-y-1">
            {([
              ["Connectivity", h.connectivity + (h.days_since_seen !== null ? ` (${h.days_since_seen} days since seen)` : "")],
              ["Agent version", `${h.agent_version}${h.thresholds.minimum_agent_version ? ` (minimum ${h.thresholds.minimum_agent_version})` : ""}`],
              ["System disk", h.disk + (h.worst_disk_free_pct !== null ? ` (${h.worst_disk_free_pct}% free)` : "")],
              ["Antivirus", h.antivirus],
              ["Firewall", h.firewall],
              ["CPU", [h.hardware.cpu, h.hardware.cores && `${h.hardware.cores} cores`, h.hardware.logical_processors && `${h.hardware.logical_processors} logical`].filter(Boolean).join(" · ") || "not reported"],
              ["Memory (raw, units undocumented)", h.hardware.memory_total_raw || "not reported"],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-slate-500">{k}</dt><dd>{v.replace(/_/g, " ")}</dd></div>
            ))}
          </dl>
        </section>
      ) : null}
    </div>
  );
}

function Network({ detail }: { detail: AssetDetail }) {
  const d = detail.details;
  if (!d) return <Notice tone="warn">Not in the current dataset.</Notice>;
  if (d.network_status === "not_collected") {
    return <Notice tone="warn">The source returned no network sections for this device (not collected, not “no network”).</Notice>;
  }
  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-slate-500">
        Reported adapters from VSA X. Subnets are derived only from a reported IPv4 address with its reported mask.
        {d.public_ip ? ` Public IP reported: ${d.public_ip}.` : ""}
      </p>
      <AdapterList adapters={d.adapters} />
    </div>
  );
}

function tri(v: boolean | null, yes: string, no: string) {
  return v === null ? <Badge tone="neutral">not reported</Badge> : <Badge tone={v ? "good" : "warn"}>{v ? yes : no}</Badge>;
}

function HardwareSecurity({ detail }: { detail: AssetDetail }) {
  const d = detail.details;
  if (!d) return <Notice tone="warn">Not in the current dataset.</Notice>;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section aria-labelledby="disk-h">
        <h3 id="disk-h" className="mb-1 text-sm font-semibold">Disks</h3>
        {d.disks_status === "not_collected" ? <Notice tone="warn">Disk section not collected.</Notice> : (
          <DataTable caption="Disks" rows={d.disks} getRowId={(r) => r.name} emptyTitle="Source reported no disks."
            columns={[
              { header: "Volume", accessorKey: "name" },
              { header: "System", cell: ({ row }) => (row.original.is_system === null ? "—" : row.original.is_system ? "yes" : "no") },
              { header: "Free", cell: ({ row }) => row.original.free_percentage === null ? "not reported"
                  : <span>{Number(row.original.free_percentage)}% {Number(row.original.free_percentage) < 10 ? <Badge tone="warn">low</Badge> : null}</span> },
              { header: "Total (as reported)", cell: ({ row }) => row.original.total_value_raw || "—" },
            ]} />
        )}
        <p className="mt-1 text-[11px] text-slate-500">{d.units_note} Inventory snapshot, not live telemetry.</p>
      </section>
      <section aria-labelledby="sec-h">
        <h3 id="sec-h" className="mb-1 text-sm font-semibold">Reported security observations</h3>
        {d.security_status === "not_collected" ? <Notice tone="warn">Security section not collected.</Notice> : (
          <DataTable caption="Security observations" rows={d.security} getRowId={(r) => `${r.type}-${r.name}`} emptyTitle="Source reported no security items."
            columns={[
              { header: "Type", accessorKey: "type" },
              { header: "Name", accessorKey: "name" },
              { header: "Enabled", cell: ({ row }) => tri(row.original.enabled, "enabled", "disabled") },
              { header: "Up to date", cell: ({ row }) => tri(row.original.up_to_date, "up to date", "not up to date") },
            ]} />
        )}
        <p className="mt-1 text-[11px] text-slate-500">Observations reported by the agent; not a security assessment. “Not reported” is neither secure nor insecure.</p>
      </section>
    </div>
  );
}

function Policies({ detail }: { detail: AssetDetail }) {
  const p = detail.policies;
  if (!p) return <Notice tone="warn">No policy record for this device in the current dataset.</Notice>;
  const tone = p.patch_state === "assigned" ? "good" : p.patch_state === "explicit_none" ? "warn" : "neutral";
  return (
    <div className="space-y-3">
      <Notice tone="info">{p.note}</Notice>
      <dl className="grid max-w-3xl grid-cols-[14rem_1fr] gap-y-1 text-sm">
        <dt className="text-slate-500">Patch Management</dt>
        <dd><Badge tone={tone}>{PATCH_STATE_LABEL[p.patch_state]}</Badge>{p.patch_policy_name ? ` · ${p.patch_policy_name}` : ""}{p.patch_policy_id ? ` (ID ${p.patch_policy_id})` : ""}</dd>
        <dt className="text-slate-500">Collection</dt>
        <dd>{p.collection_status.replace(/_/g, " ")}{p.collected_at ? ` · response from ${formatUtc(p.collected_at)}` : ""}</dd>
      </dl>
      <DataTable caption="Applied policies" rows={p.applied} getRowId={(r) => `${r.type}-${r.id}`} emptyTitle="No applied policies reported."
        columns={[
          { header: "Type", accessorKey: "type" },
          { header: "Policy", cell: ({ row }) => row.original.id ? `${row.original.name} (ID ${row.original.id})` : <span>{row.original.name} <Badge tone="warn">explicit</Badge></span> },
          { header: "Profiles", cell: ({ row }) => row.original.profiles.map((x) => `${x.name} (${x.category})`).join(", ") || "—" },
        ]} />
      {p.definition ? <PolicyDefinitionView definition={p.definition} /> : null}
    </div>
  );
}

function Reconciliation({ detail }: { detail: AssetDetail }) {
  const rows = detail.reconciliation ?? [];
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500">Onboarding checks in which this device was matched, offered as a candidate, or listed as unexpected (newest first).</p>
      <DataTable caption="Onboarding results for this device" rows={rows} getRowId={(r) => `${r.run_id}-${r.kind}-${r.row_number ?? ""}`}
        emptyTitle="This device has not appeared in any onboarding check."
        columns={[
          { header: "Check", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/onboarding/${row.original.run_id}`}>{formatUtc(row.original.run_created_at)} · {row.original.upload_name}</Link> },
          { header: "Role", cell: ({ row }) => row.original.kind === "unexpected" ? "unexpected in VSA" : `${row.original.role.replace(/_/g, " ")} (row ${row.original.row_number})` },
          { header: "Result", cell: ({ row }) => <span>{row.original.classification || "—"}{row.original.reviewed_classification ? ` → reviewed ${row.original.reviewed_classification}` : ""}</span> },
          { header: "Flags", cell: ({ row }) => row.original.flags.join(", ") || "—" },
        ]} />
    </div>
  );
}

function OsUpdates({ detail }: { detail: AssetDetail }) {
  const o = detail.os_updates;
  if (!o) return <Notice tone="warn">No OS update record for this device in the current dataset.</Notice>;
  const s = o.status;
  return (
    <div className="space-y-3">
      <dl className="grid max-w-3xl grid-cols-[14rem_1fr] gap-y-1 text-sm">
        <dt className="text-slate-500">Available updates section</dt>
        <dd>
          <Badge tone={statusTone[s.available_status]}>{UPDATE_STATUS_LABEL[s.available_status]}</Badge>
          {s.available_count !== null ? ` · ${s.available_count} available` : ""}
        </dd>
        <dt className="text-slate-500">Source severity counts</dt>
        <dd>{s.update_counts ? Object.entries(s.update_counts).map(([k, v]) => `${k}: ${v}`).join(" · ") : "not reported"}</dd>
        <dt className="text-slate-500">Installed updates</dt>
        <dd>
          <Badge tone={statusTone[s.installed_status]}>{UPDATE_STATUS_LABEL[s.installed_status]}</Badge>
          {s.installed_count !== null ? ` · ${s.installed_count} installed` : ""}
          {s.installed_collected_at ? ` · collected ${formatUtc(s.installed_collected_at)}` : ""}
        </dd>
      </dl>
      <p className="text-xs text-slate-500">
        The VSA X API documents no update-scan time; InstalledAt values are shown as reported (no timezone).
      </p>
      <DataTable caption="OS updates for this device" rows={o.updates} getRowId={(r) => r.id} emptyTitle="No update records."
        columns={[
          { header: "State", cell: ({ row }) => <Badge tone={row.original.state === "available" ? "warn" : "good"}>{row.original.state}</Badge> },
          { header: "KB", cell: ({ row }) => (row.original.kb_article ? `KB${row.original.kb_article}` : "—") },
          { header: "Title", accessorKey: "title" },
          { header: "Severity", accessorKey: "severity" },
          { header: "Installed at (as reported)", cell: ({ row }) => row.original.installed_at_raw || "—" },
        ]} />
    </div>
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
                : <><ThirdPartyPatchNotice status={detail.third_party_patch_status} /><DataTable caption="Installed software" columns={softwareColumns} rows={detail.software} getRowId={(r) => r.id}
                             emptyTitle="The source reported no installed software for this device." /></>
            ) },
            { id: "os-updates", label: "OS updates", content: <OsUpdates detail={detail} /> },
            { id: "policies", label: "Policies", content: <Policies detail={detail} /> },
            { id: "network", label: "Network", content: <Network detail={detail} /> },
            { id: "onboarding", label: "Onboarding", content: <Reconciliation detail={detail} /> },
            { id: "hardware", label: "Hardware & security", content: <HardwareSecurity detail={detail} /> },
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
