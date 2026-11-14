import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";
import { CAP, type Customer, type ExpectedSubnet, type GroupNetwork } from "../../lib/types";

const FLAG_LABEL: Record<string, string> = {
  duplicate_ip: "Duplicate IP addresses",
  mac_reuse: "MAC addresses reused",
  outside_expected_subnet: "Addresses outside the expected subnets",
  address_changed_since_previous_snapshot: "Devices whose addresses changed since the previous snapshot",
  network_not_collected: "Devices without network data",
  address_without_derived_subnet: "Addresses without a derivable subnet",
};

/** VSA2-05 review flags + reviewed expected subnets for a group (and its site). Review observations only. */
export function NetworkReview({ customer, groupId, net }: { customer: Customer; groupId: string; net: GroupNetwork }) {
  const qc = useQueryClient();
  const siteId = net.group?.site_external_id ?? "";
  const base = `/customers/${customer.id}/expected-subnets/`;
  const canManage = customer.my_capabilities.includes(CAP.manageExceptions);
  const list = useQuery({
    queryKey: ["expected-subnets", customer.id],
    queryFn: ({ signal }) => api.get<ExpectedSubnet[]>(base, undefined, signal),
  });
  const [scopeType, setScopeType] = useState<"group" | "site">("group");
  const [cidr, setCidr] = useState("");
  const [reason, setReason] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["expected-subnets", customer.id] });
    void qc.invalidateQueries({ queryKey: ["group-network", customer.id, groupId] });
  };
  const propose = useMutation({
    mutationFn: () => api.post<ExpectedSubnet>(base, { scope_type: scopeType, scope_external_id: scopeType === "group" ? groupId : siteId, cidr, reason, integration_instance: net.instance_id }),
    onSuccess: () => { setCidr(""); setReason(""); refresh(); },
  });
  const act = useMutation({ mutationFn: ({ id, verb }: { id: string; verb: string }) => api.post<ExpectedSubnet>(`${base}${id}/${verb}/`), onSuccess: refresh });
  const changes = net.address_changes;

  return (
    <section aria-labelledby="review-h" className="space-y-3 rounded border border-slate-200 bg-white p-3 text-sm">
      <h2 id="review-h" className="font-semibold">Network review</h2>
      <ul aria-label="Review flags" className="grid gap-1 md:grid-cols-2">
        {(net.review_flags ?? []).map((f) => (
          <li key={f.flag} className="flex items-center gap-2">
            {f.evaluated === false ? <Badge tone="neutral">not evaluated</Badge> : <Badge tone={f.count ? "warn" : "good"}>{f.count}</Badge>}
            <span>{FLAG_LABEL[f.flag] ?? f.flag}</span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-slate-500">
        Expected subnets are reviewed customer expectations. An address outside them is a review observation, not proof of a wrong VLAN or misconfiguration.
        {net.addresses_not_evaluated_against_expectation ? ` ${net.addresses_not_evaluated_against_expectation} address(es) had no expectation of the same IP version and were not evaluated.` : ""}
      </p>
      {net.outside_expected_subnet?.length ? (
        <DataTable caption="Addresses outside expected subnets" rows={net.outside_expected_subnet} getRowId={(r) => `${r.asset_id}-${r.address}`}
          columns={[
            { header: "Device", cell: ({ row }) => <Link className="text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
            { header: "Address", cell: ({ row }) => <code>{row.original.address}</code> },
            { header: "Adapter", cell: ({ row }) => <span>{row.original.adapter}{row.original.mac_locally_administered ? <span className="ml-1"><Badge tone="info">virtual / locally administered</Badge></span> : null}</span> },
          ]} />
      ) : null}
      <div>
        <h3 className="text-xs font-semibold uppercase text-slate-500">Address changes since the previous complete snapshot</h3>
        {!changes || changes.previous_generation === null ? (
          <p className="text-xs text-slate-500">Not evaluated ({changes?.not_evaluated_reason ?? "no data"}).</p>
        ) : changes.devices.length === 0 ? (
          <p className="text-xs text-slate-500">No changes among {changes.compared_devices} device(s) compared (previous snapshot {formatUtc(changes.previous_generation.published_at)}).</p>
        ) : (
          <ul className="text-xs">
            {changes.devices.map((d) => (
              <li key={d.asset_id}><Link className="text-sky-800 hover:underline" to={`/assets/${d.asset_id}`}>{d.hostname}</Link>:{" "}
                {d.added.length ? <span>added <code>{d.added.join(", ")}</code></span> : null}{d.added.length && d.removed.length ? "; " : ""}
                {d.removed.length ? <span>removed <code>{d.removed.join(", ")}</code></span> : null}</li>
            ))}
          </ul>
        )}
      </div>
      <QueryBoundary query={list}>
        {(rows) => {
          const relevant = rows.filter((r) => (!r.integration_instance || r.integration_instance === net.instance_id) && ((r.scope_type === "group" && r.scope_external_id === groupId) || (r.scope_type === "site" && r.scope_external_id === siteId)));
          return (
            <DataTable caption="Expected subnets" rows={relevant} getRowId={(r) => r.id} emptyTitle="No expected subnets for this group or its site."
              columns={[
                { header: "Scope", cell: ({ row }) => `${row.original.scope_type} ${row.original.scope_external_id}` },
                { header: "Subnet", cell: ({ row }) => <code>{row.original.cidr}</code> },
                { header: "Reason", accessorKey: "reason" },
                { header: "State", cell: ({ row }) => <Badge tone={statusTone[row.original.state] ?? "neutral"}>{row.original.state}</Badge> },
                { header: "Proposed / reviewed", cell: ({ row }) => <span className="text-xs">{row.original.proposed_by}{row.original.reviewed_by ? ` / ${row.original.reviewed_by}` : ""}</span> },
                { header: "", id: "act", cell: ({ row }) => canManage ? (
                  <span className="flex gap-1">
                    {row.original.state === "proposed" ? <>
                      <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "approve" })}>Approve</button>
                      <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "reject" })}>Reject</button>
                    </> : null}
                    {row.original.state === "approved" ? <button type="button" className="btn-secondary py-0.5 text-xs" onClick={() => act.mutate({ id: row.original.id, verb: "retire" })}>Retire</button> : null}
                  </span>) : null },
              ]} />
          );
        }}
      </QueryBoundary>
      {act.isError ? <p role="alert" className="text-red-700">{describeError(act.error)}</p> : null}
      {canManage ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); propose.mutate(); }}>
          <Field label="Expected for">{(id) => (
            <select id={id} className="input" value={scopeType} onChange={(e) => setScopeType(e.target.value as "group" | "site")}>
              <option value="group">This group ({groupId})</option>
              {siteId ? <option value="site">Its site ({siteId})</option> : null}
            </select>)}</Field>
          <Field label="Subnet (CIDR)">{(id) => <input id={id} className="input w-44" placeholder="10.1.10.0/24" value={cidr} onChange={(e) => setCidr(e.target.value)} required />}</Field>
          <Field label="Reason">{(id) => <input id={id} className="input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} required />}</Field>
          <button type="submit" className="btn-primary" disabled={propose.isPending}>Propose subnet</button>
          <p className="w-full text-xs text-slate-500">A different administrator must approve before the subnet is used.</p>
          {propose.isError ? <p role="alert" className="w-full text-red-700">{describeError(propose.error)}</p> : null}
        </form>
      ) : null}
    </section>
  );
}
