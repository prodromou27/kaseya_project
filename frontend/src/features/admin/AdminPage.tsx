import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";

import { DataTable } from "../../components/DataTable";
import { EmptyState, QueryBoundary } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { Badge, Field, Notice, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { formatUtc } from "../../lib/format";
import { PROVIDER_LABEL, type Integration, type Paginated, type PortalUser, type Provider, type SourceMapping } from "../../lib/types";
import { AuditTable } from "../customers/AuditTable";
import { mappingColumns } from "../customers/MappingsPanel";

function UsersPanel() {
  const me = useMe();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["users"], queryFn: ({ signal }) => api.get<Paginated<PortalUser>>("/users/", { page_size: 200 }, signal) });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<PortalUser> }) => api.patch<PortalUser>(`/users/${id}/`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["users"] }),
  });
  const columns: ColumnDef<PortalUser, unknown>[] = [
    { header: "Email", accessorKey: "email" },
    { header: "Name", accessorKey: "display_name", cell: ({ getValue }) => String(getValue() || "—") },
    { header: "Sign-in", cell: ({ row }) => (row.original.auth_source === "oidc" ? "SSO" : "Local") },
    { header: "Global role", accessorKey: "global_role", cell: ({ getValue }) => (getValue() ? <Badge tone="warn">{String(getValue())}</Badge> : "—") },
    { header: "Status", cell: ({ row }) => <Badge tone={row.original.is_active ? "good" : "neutral"}>{row.original.is_active ? "active" : "disabled"}</Badge> },
    { header: "Last login", accessorKey: "last_login", cell: ({ getValue }) => formatUtc(getValue() as string | null) },
    {
      header: "Actions",
      cell: ({ row }) =>
        row.original.id === me.id ? (
          <span className="text-xs text-slate-400">You</span>
        ) : (
          <button
            type="button"
            className={row.original.is_active ? "btn-danger" : "btn-secondary"}
            onClick={() => update.mutate({ id: row.original.id, body: { is_active: !row.original.is_active } })}
          >
            {row.original.is_active ? "Disable" : "Enable"}
          </button>
        ),
    },
  ];
  return (
    <div className="space-y-3">
      <Notice tone="info">
        Users are normally provisioned through Entra ID SSO with no grants; grant customer access from each customer's
        Members tab. Users are disabled, never deleted, to preserve audit history.
      </Notice>
      {update.isError ? <p role="alert" className="text-sm text-red-700">{describeError(update.error)}</p> : null}
      <QueryBoundary query={query}>
        {(data) => <DataTable caption="Portal users" columns={columns} rows={data.results} total={data.count} getRowId={(u) => u.id} />}
      </QueryBoundary>
    </div>
  );
}

function IntegrationsPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["integrations"], queryFn: ({ signal }) => api.get<Paginated<Integration>>("/integrations/", undefined, signal) });
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<Provider>("vsa_x");
  const [baseUrl, setBaseUrl] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [isFixture, setIsFixture] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      api.post<Integration>("/integrations/", { name, provider, base_url: baseUrl, credential_ref: isFixture ? "" : credentialRef, is_fixture: isFixture }),
    onSuccess: () => {
      setName("");
      setBaseUrl("");
      setCredentialRef("");
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
  const columns: ColumnDef<Integration, unknown>[] = [
    { header: "Name", cell: ({ row }) => <span>{row.original.name} {row.original.is_fixture ? <Badge tone="info">fixture</Badge> : <Badge tone="warn">live</Badge>}</span> },
    { header: "Provider", cell: ({ row }) => PROVIDER_LABEL[row.original.provider] },
    { header: "Base URL", accessorKey: "base_url", cell: ({ getValue }) => <code className="text-xs">{String(getValue())}</code> },
    { header: "Credential", cell: ({ row }) => (row.original.credential_configured ? "Reference set" : "None") },
    { header: "TLS verify", cell: ({ row }) => (row.original.verify_tls ? "On (enforced)" : "OFF") },
    { header: "Enabled", cell: ({ row }) => (row.original.enabled ? "Yes" : "No") },
    { header: "Status", accessorKey: "status", cell: ({ getValue }) => <Badge tone={statusTone[String(getValue())]}>{String(getValue())}</Badge> },
  ];
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <div className="space-y-3">
      <Notice tone="warn">
        Connectors are read-only. Hosts must be on the deployment allowlist; TLS verification cannot be disabled. Store
        only a <em>reference</em> to the secret (e.g. <code>vault:kv/portal/vsa</code>), never the secret itself. No
        connector performs collection until P1.
      </Notice>
      <form onSubmit={submit} aria-label="Add integration" className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
        <Field label="Name">{(id) => <input id={id} className="input w-48" required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Provider">
          {(id) => (
            <select id={id} className="input" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>
              {(Object.keys(PROVIDER_LABEL) as Provider[]).map((p) => (
                <option key={p} value={p}>
                  {PROVIDER_LABEL[p]}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Base URL" hint={isFixture ? "Fixture URLs must end in .invalid" : "https only, allowlisted host"}>
          {(id, hint) => <input id={id} aria-describedby={hint} className="input w-64" required value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://" />}
        </Field>
        {!isFixture ? (
          <Field label="Credential reference">
            {(id) => <input id={id} className="input w-56" value={credentialRef} onChange={(e) => setCredentialRef(e.target.value)} autoComplete="off" />}
          </Field>
        ) : null}
        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input type="checkbox" checked={isFixture} onChange={(e) => setIsFixture(e.target.checked)} />
          Fixture (demo) instance
        </label>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          Add
        </button>
        {create.isError ? <p role="alert" className="w-full text-sm text-red-700">{describeError(create.error)}</p> : null}
      </form>
      <QueryBoundary query={query}>
        {(data) => <DataTable caption="Integration instances" columns={columns} rows={data.results} total={data.count} getRowId={(i) => i.id} emptyTitle="No integrations configured." />}
      </QueryBoundary>
    </div>
  );
}

function MappingReviewPanel() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("proposed");
  const query = useQuery({
    queryKey: ["mapping-review", status],
    queryFn: ({ signal }) => api.get<Paginated<SourceMapping>>("/mappings/", { status }, signal),
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" | "revoke" }) => api.post<SourceMapping>(`/mappings/${id}/${action}/`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["mapping-review"] }),
  });
  const columns: ColumnDef<SourceMapping, unknown>[] = [
    { header: "Customer", cell: ({ row }) => `${row.original.customer.code} — ${row.original.customer.name}` },
    ...mappingColumns,
    {
      header: "Review",
      cell: ({ row }) => {
        const m = row.original;
        if (m.mapping_status === "proposed")
          return (
            <span className="flex gap-1">
              <button type="button" className="btn-secondary" onClick={() => window.confirm(`Approve ${m.external_org_id} → ${m.customer.code}? Verify the organisation ID in the vendor console first.`) && act.mutate({ id: m.id, action: "approve" })}>
                Approve
              </button>
              <button type="button" className="btn-danger" onClick={() => act.mutate({ id: m.id, action: "reject" })}>
                Reject
              </button>
            </span>
          );
        if (m.mapping_status === "approved")
          return (
            <button type="button" className="btn-danger" onClick={() => window.confirm("Revoke this mapping? Collected data will stop routing to the customer.") && act.mutate({ id: m.id, action: "revoke" })}>
              Revoke
            </button>
          );
        return <span className="text-xs text-slate-400">—</span>;
      },
    },
  ];
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm">
        Status
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["proposed", "approved", "rejected", "revoked"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      {act.isError ? <p role="alert" className="text-sm text-red-700">{describeError(act.error)}</p> : null}
      <QueryBoundary query={query}>
        {(data) => <DataTable caption="Source mapping review queue" columns={columns} rows={data.results} total={data.count} getRowId={(m) => m.id} emptyTitle={`No ${status} mappings.`} />}
      </QueryBoundary>
    </div>
  );
}

export function AdminPage() {
  const me = useMe();
  const [tab, setTab] = useState("mappings");
  if (!me.is_super_admin) {
    return (
      <>
        <PageHeader title="Administration" />
        <EmptyState title="Administration requires the super administrator role." />
      </>
    );
  }
  return (
    <>
      <PageHeader title="Administration" subtitle="System configuration · all changes are audited" />
      <Tabs
        label="Administration sections"
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "mappings", label: "Mapping review", content: <MappingReviewPanel /> },
          { id: "integrations", label: "Integrations", content: <IntegrationsPanel /> },
          { id: "users", label: "Users", content: <UsersPanel /> },
          { id: "audit", label: "Audit log", content: <AuditTable path="/audit-events/" caption="System audit events" /> },
        ]}
      />
    </>
  );
}
