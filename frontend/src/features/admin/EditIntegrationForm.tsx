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
  const urlChanged = baseUrl.trim().replace(/\/$/, "") !== integration.base_url;
  const save = useMutation({
    mutationFn: () =>
      api.patch<Integration>(`/integrations/${integration.id}/`, {
        name,
        base_url: baseUrl.trim(),
        max_rps: maxRps,
        ...Object.fromEntries(Object.entries(budgets).map(([k, v]) => [k, Number(v)])),
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
      {save.isError ? <p role="alert" className="text-sm text-red-700">{describeError(save.error)}</p> : null}
    </form>
  );
}
