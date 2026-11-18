import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Integration } from "../../lib/types";

/** Edit an integration's API settings. Provider and fixture/live designation cannot change after creation. */
export function EditIntegrationForm({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(integration.name);
  const [baseUrl, setBaseUrl] = useState(integration.base_url);
  const [maxRps, setMaxRps] = useState(integration.max_rps);
  const [budgets, setBudgets] = useState({
    installed_updates_budget: String(integration.installed_updates_budget),
    applied_policies_budget: String(integration.applied_policies_budget),
    notifications_budget: String(integration.notifications_budget),
    custom_fields_budget: String(integration.custom_fields_budget),
  });
  const [executeMoves, setExecuteMoves] = useState(Boolean(integration.group_move_execution_enabled));
  const [writeRef, setWriteRef] = useState("");
  const [cfWrites, setCfWrites] = useState(Boolean(integration.custom_field_writes_enabled));
  const [cfThreshold, setCfThreshold] = useState(String(integration.custom_field_approval_threshold ?? 0));
  const urlChanged = baseUrl.trim().replace(/\/$/, "") !== integration.base_url;
  const save = useMutation({
    mutationFn: () =>
      api.patch<Integration>(`/integrations/${integration.id}/`, {
        name,
        base_url: baseUrl.trim(),
        max_rps: maxRps,
        ...Object.fromEntries(Object.entries(budgets).map(([k, v]) => [k, Number(v)])),
        ...(integration.provider === "vsa_x"
          ? { group_move_execution_enabled: executeMoves, custom_field_writes_enabled: cfWrites, custom_field_approval_threshold: Number(cfThreshold) }
          : {}),
        ...(writeRef.trim() ? { write_credential_ref: writeRef.trim() } : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (urlChanged && integration.credential_source === "portal"
        && !window.confirm("Changing the base URL removes the stored API token. You will need to enter it again. Continue?")) return;
    save.mutate();
  };
  const budget = (key: keyof typeof budgets, label: string) => (
    <Field label={label} hint="0 = off">
      {(id, h) => (
        <input id={id} aria-describedby={h} className="input w-24" type="number" min={0} max={3000} value={budgets[key]}
               onChange={(e) => setBudgets((b) => ({ ...b, [key]: e.target.value }))} />
      )}
    </Field>
  );
  return (
    <form onSubmit={submit} aria-label={`Edit integration: ${integration.name}`} className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <h3 className="font-semibold">Edit integration: {integration.name}</h3>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Name">{(id) => <input id={id} className="input w-48" required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Base URL" hint={integration.is_fixture ? "Fixture URLs must end in .invalid" : "https://<allowed host>"}>
          {(id, h) => <input id={id} aria-describedby={h} className="input w-64" required value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />}
        </Field>
        <Field label="Max requests / second" hint="0.01–20">
          {(id, h) => <input id={id} aria-describedby={h} className="input w-24" type="number" min={0.01} max={20} step={0.01} value={maxRps} onChange={(e) => setMaxRps(e.target.value)} />}
        </Field>
        {budget("installed_updates_budget", "InstalledUpdates budget / sync")}
        {budget("applied_policies_budget", "Applied policies budget / sync")}
        {budget("notifications_budget", "Notifications budget / sync")}
        {budget("custom_fields_budget", "Custom fields budget / sync")}
        <button type="submit" className="btn-primary" disabled={save.isPending}>Save</button>
        <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
      </div>
      {integration.provider === "vsa_x" ? (
        <fieldset className="space-y-2 rounded border border-amber-200 bg-amber-50/50 p-3">
          <legend className="px-1 text-sm font-semibold">Execute approved group moves in VSA X</legend>
          <p className="text-xs text-slate-600">
            The only change the portal can make in VSA X. It needs three things: the server switch
            (<code>VSA_GROUP_MOVE_EXECUTION_ENABLED</code>, currently <strong>{integration.group_move_execution_server_enabled ? "on" : "off"}</strong>),
            this switch, and a separate VSA X API token kept as a server secret (<strong>{integration.write_credential_configured ? "configured" : "not configured"}</strong>).
            Every move still needs an independent approval and is sent once.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={executeMoves} onChange={(e) => setExecuteMoves(e.target.checked)} />
            Allow approved moves to be executed for this integration
          </label>
          {!integration.is_fixture ? (
            <Field label="Write token reference" hint="Server secret name, e.g. env:VSA_WRITE_PROD (TOKEN_ID:TOKEN_SECRET). Leave empty to keep the current one.">
              {(id, h) => <input id={id} aria-describedby={h} className="input w-64" pattern="env:VSA_WRITE_[A-Z0-9_]{1,50}" value={writeRef} onChange={(e) => setWriteRef(e.target.value)} />}
            </Field>
          ) : null}
        </fieldset>
      ) : null}
      {integration.provider === "vsa_x" ? (
        <fieldset className="space-y-2 rounded border border-amber-200 bg-amber-50/50 p-3">
          <legend className="px-1 text-sm font-semibold">Assign custom fields in VSA X</legend>
          <p className="text-xs text-slate-600">
            Lets engineers set editable custom fields on workstations (Custom fields page). It needs the server switch
            (<code>VSA_CUSTOM_FIELD_WRITES_ENABLED</code>, currently <strong>{integration.custom_field_writes_server_enabled ? "on" : "off"}</strong>),
            this switch, the separate write token above and, for a live server, a route confirmed on a test workstation
            (<strong>{integration.is_fixture ? "not needed for fixtures" : integration.custom_field_write_route
              ? `/api/v3/${integration.custom_field_write_route}/…` : "not validated yet: run manage.py vsa_custom_field_validate"}</strong>).
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cfWrites} onChange={(e) => setCfWrites(e.target.checked)} />
            Allow confirmed custom field assignments for this integration
          </label>
          <Field label="Second approval above (devices)" hint="Jobs changing more devices than this need another administrator. 0 = never.">
            {(id, h) => <input id={id} aria-describedby={h} className="input w-28" type="number" min={0} max={100000} value={cfThreshold} onChange={(e) => setCfThreshold(e.target.value)} />}
          </Field>
        </fieldset>
      ) : null}
      {save.isError ? <p role="alert" className="text-sm text-red-700">{describeError(save.error)}</p> : null}
    </form>
  );
}
