import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Field, Notice } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Integration, ProviderSpec } from "../../lib/types";

export function useProviders() {
  return useQuery({
    queryKey: ["integration-providers"],
    queryFn: ({ signal }) => api.get<ProviderSpec[]>("/integrations/providers/", undefined, signal),
    staleTime: Infinity,
  });
}

/**
 * Super admin enters the provider's credentials (fields come from the server's provider catalog). Sent once over
 * HTTPS, stored encrypted on the server and never shown again: inputs are cleared after saving and the API only
 * reports *that* credentials are set.
 */
export function CredentialForm({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const queryClient = useQueryClient();
  const providers = useProviders();
  const spec = providers.data?.find((p) => p.key === integration.provider);
  const [values, setValues] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => api.post<Integration>(`/integrations/${integration.id}/credential/`, { fields: values }),
    onSuccess: () => {
      setValues({});
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
    },
    // Never keep secrets in the form after a failed attempt.
    onError: () => setValues((v) => Object.fromEntries(Object.entries(v).filter(([k]) => !spec?.fields.find((f) => f.name === k)?.secret))),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form onSubmit={submit} aria-label={`Credentials: ${integration.name}`} className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <h3 className="font-semibold">Credentials: {integration.name}</h3>
      <Notice tone="info">
        Use <strong>read-only</strong> credentials. Everything entered here is stored encrypted on this server and can
        never be viewed again; you can only replace or remove it. Changing the integration's base URL removes it. Run{" "}
        <em>Test connection</em> after saving.
      </Notice>
      {integration.credential_source === "portal" ? <p className="text-xs text-slate-600">Saving replaces the current credentials.</p> : null}
      {providers.isPending ? <p className="text-sm text-slate-500">Loading…</p> : null}
      {providers.isError ? <p role="alert" className="text-sm text-red-700">{describeError(providers.error)}</p> : null}
      {spec ? (
        <div className="flex flex-wrap items-end gap-3">
          {spec.fields.map((f) => (
            <Field key={f.name} label={f.label} hint={f.help || undefined}>
              {(id, hint) => (
                <input id={id} aria-describedby={hint} className="input w-64" required maxLength={f.max_length}
                       type={f.secret ? "password" : "text"} autoComplete={f.secret ? "new-password" : "off"} spellCheck={false}
                       value={values[f.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
              )}
            </Field>
          ))}
          <button type="submit" className="btn-primary" disabled={save.isPending}>Save credentials</button>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      ) : null}
      {save.isError ? <p role="alert" className="text-sm text-red-700">{describeError(save.error)}</p> : null}
    </form>
  );
}

export function credentialLabel(i: Integration): string {
  if (i.is_fixture) return "Not used (fixture)";
  if (i.credential_source === "portal") return "Set in portal (encrypted)";
  if (i.credential_source === "server") return "Server reference";
  return "None";
}
