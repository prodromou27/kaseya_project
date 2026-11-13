import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { EmptyState } from "../../components/States";
import { Field, PageHeader } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import { useCustomers } from "../../lib/customerContext";
import type { ConnectionTestResult } from "../../lib/types";

type Org = { external_org_id: string; name: string; mapping: null | { status: string; customer: { code: string } } };
type ConnectResult = { integration_id: string; connection: ConnectionTestResult; organizations: Org[] };
type ImportResult = { imported: { external_org_id: string; customer: string; status: string; sync?: string }[]; syncs_started: number };

function Steps({ step }: { step: 1 | 2 | 3 }) {
  const labels = ["Connect", "Choose organisations", "Done"];
  return (
    <ol className="mb-6 flex gap-2 text-sm" aria-label="Progress">
      {labels.map((label, i) => (
        <li key={label} aria-current={step === i + 1 ? "step" : undefined}
            className={`flex items-center gap-2 rounded-full px-3 py-1 ${step === i + 1 ? "bg-sky-700 text-white" : step > i + 1 ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-500"}`}>
          <span className="font-semibold">{step > i + 1 ? "✓" : i + 1}</span> {label}
        </li>
      ))}
    </ol>
  );
}

/** Super admin: connect VSA X in two screens. Every underlying action is the same audited, read-only one. */
export function ConnectVsaPage() {
  const me = useMe();
  const qc = useQueryClient();
  const { customers } = useCustomers();
  const [url, setUrl] = useState("");
  const [tokenId, setTokenId] = useState("");
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState<ConnectResult | null>(null);
  const [picked, setPicked] = useState<Record<string, string>>({}); // org id -> "" (new customer) or customer id
  const [done, setDone] = useState<ImportResult | null>(null);

  const connect = useMutation({
    mutationFn: () => api.post<ConnectResult>("/integrations/connect/", { base_url: url, token_id: tokenId, token_secret: secret }),
    onSuccess: (r) => {
      setSecret("");
      setResult(r);
      setPicked(Object.fromEntries(r.organizations.filter((o) => !o.mapping).map((o) => [o.external_org_id, ""])));
      void qc.invalidateQueries({ queryKey: ["integrations"] });
    },
    onError: () => setSecret(""),
  });
  const importOrgs = useMutation({
    mutationFn: () =>
      api.post<ImportResult>(`/integrations/${result?.integration_id}/import-orgs/`, {
        organizations: (result?.organizations ?? [])
          .filter((o) => o.external_org_id in picked)
          .map((o) => ({ external_org_id: o.external_org_id, name: o.name, ...(picked[o.external_org_id] ? { customer_id: picked[o.external_org_id] } : {}) })),
      }),
    onSuccess: (r) => {
      setDone(r);
      void qc.invalidateQueries();
    },
  });

  if (!me.is_super_admin) {
    return (
      <>
        <PageHeader title="Connect VSA" />
        <EmptyState title="Only a super administrator can connect VSA." />
      </>
    );
  }

  const ok = result?.connection.outcome === "ok";
  const step: 1 | 2 | 3 = done ? 3 : ok ? 2 : 1;
  const submitConnect = (e: FormEvent) => {
    e.preventDefault();
    connect.mutate();
  };
  const toggle = (id: string) =>
    setPicked((p) => (id in p ? Object.fromEntries(Object.entries(p).filter(([k]) => k !== id)) : { ...p, [id]: "" }));

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Connect VSA" subtitle="Link your Kaseya VSA X server. Read-only: the portal never changes anything in VSA." />
      <Steps step={step} />

      {step === 1 ? (
        <form onSubmit={submitConnect} aria-label="Connect VSA" className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
          <Field label="VSA X address" hint="The address you open VSA X with, e.g. https://yourcompany.vsax.net">
            {(id, hint) => <input id={id} aria-describedby={hint} className="input w-full" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" autoComplete="url" />}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="API token ID">
              {(id) => <input id={id} className="input w-full" required value={tokenId} onChange={(e) => setTokenId(e.target.value)} autoComplete="off" spellCheck={false} />}
            </Field>
            <Field label="API token secret">
              {(id) => <input id={id} className="input w-full" type="password" required value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" spellCheck={false} />}
            </Field>
          </div>
          <p className="text-xs text-slate-500">
            Create a <strong>read-only</strong> API token in VSA X (Settings → API tokens). The secret is stored encrypted and never shown again.
          </p>
          {result && !ok ? <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">{result.connection.message}</p> : null}
          {connect.isError ? <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">{describeError(connect.error)}</p> : null}
          <button type="submit" className="btn-primary" disabled={connect.isPending}>{connect.isPending ? "Connecting…" : "Connect"}</button>
        </form>
      ) : null}

      {step === 2 && result ? (
        <section aria-label="Choose organisations" className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-700">
            Connected. Tick the VSA organisations to bring in. Each one becomes a customer in the portal (or joins an
            existing one) and syncs now and then every day.
          </p>
          {result.organizations.length === 0 ? <p className="text-sm text-slate-500">No organisations are visible to this token.</p> : null}
          <ul className="divide-y divide-slate-100" aria-label="VSA organisations">
            {result.organizations.map((o) => (
              <li key={o.external_org_id} className="flex flex-wrap items-center gap-3 py-2">
                {o.mapping ? (
                  <span className="text-sm text-slate-500">✓ {o.name} <span className="text-xs">already linked to {o.mapping.customer.code}</span></span>
                ) : (
                  <>
                    <label className="flex flex-1 items-center gap-2 text-sm">
                      <input type="checkbox" checked={o.external_org_id in picked} onChange={() => toggle(o.external_org_id)} />
                      {o.name} <span className="text-xs text-slate-400">#{o.external_org_id}</span>
                    </label>
                    {o.external_org_id in picked ? (
                      <select aria-label={`Customer for ${o.name}`} className="input text-sm" value={picked[o.external_org_id]}
                              onChange={(e) => setPicked((p) => ({ ...p, [o.external_org_id]: e.target.value }))}>
                        <option value="">New customer “{o.name}”</option>
                        {customers.map((c) => <option key={c.id} value={c.id}>Existing: {c.code} — {c.name}</option>)}
                      </select>
                    ) : null}
                  </>
                )}
              </li>
            ))}
          </ul>
          {importOrgs.isError ? <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">{describeError(importOrgs.error)}</p> : null}
          <div className="flex gap-2">
            <button type="button" className="btn-primary" disabled={importOrgs.isPending || Object.keys(picked).length === 0} onClick={() => importOrgs.mutate()}>
              {importOrgs.isPending ? "Importing…" : `Import ${Object.keys(picked).length} organisation(s)`}
            </button>
            <button type="button" className="btn-secondary" onClick={() => setResult(null)}>Back</button>
          </div>
        </section>
      ) : null}

      {step === 3 && done ? (
        <section aria-label="Done" className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-700">
            {done.syncs_started} sync(s) started. The first one can take a while for large organisations; data appears as soon as it completes.
          </p>
          <ul className="space-y-1 text-sm">
            {done.imported.map((i) => (
              <li key={i.external_org_id}>
                <span className="font-medium">{i.customer}</span> <span className="text-slate-500">— {i.status}{i.sync ? `, sync ${i.sync}` : ""}</span>
              </li>
            ))}
          </ul>
          <Link to="/" className="btn-primary inline-block">Go to the dashboard</Link>
        </section>
      ) : null}
    </div>
  );
}
