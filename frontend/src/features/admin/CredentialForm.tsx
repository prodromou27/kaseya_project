import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Field, Notice } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Integration } from "../../lib/types";

/**
 * Super admin enters the VSA X API token (ID + secret). Sent once over HTTPS, stored encrypted on the server and never
 * shown again: the inputs are cleared after saving and the API only reports *that* a token is set.
 */
export function CredentialForm({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [tokenId, setTokenId] = useState("");
  const [tokenSecret, setTokenSecret] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<Integration>(`/integrations/${integration.id}/credential/`, { token_id: tokenId, token_secret: tokenSecret }),
    onSuccess: () => {
      setTokenId("");
      setTokenSecret("");
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
    },
    onError: () => setTokenSecret(""),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form onSubmit={submit} aria-label={`API token: ${integration.name}`} className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <h3 className="font-semibold">API token: {integration.name}</h3>
      <Notice tone="info">
        Use a <strong>read-only</strong> VSA X API token. It is stored encrypted on this server and can never be viewed
        again; you can only replace or remove it. Changing the integration's base URL removes it. Run{" "}
        <em>Test connection</em> after saving.
      </Notice>
      {integration.credential_source === "portal" ? (
        <p className="text-xs text-slate-600">Saving replaces the current token.</p>
      ) : null}
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Token ID">
          {(id) => <input id={id} className="input w-56" required value={tokenId} onChange={(e) => setTokenId(e.target.value)} autoComplete="off" spellCheck={false} />}
        </Field>
        <Field label="Token secret">
          {(id) => (
            <input id={id} className="input w-72" type="password" required value={tokenSecret} onChange={(e) => setTokenSecret(e.target.value)}
                   autoComplete="new-password" spellCheck={false} />
          )}
        </Field>
        <button type="submit" className="btn-primary" disabled={save.isPending}>Save token</button>
        <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
      </div>
      {save.isError ? <p role="alert" className="text-sm text-red-700">{describeError(save.error)}</p> : null}
    </form>
  );
}

export function credentialLabel(i: Integration): string {
  if (i.is_fixture) return "Not used (fixture)";
  if (i.credential_source === "portal") return "Token set in portal";
  if (i.credential_source === "server") return "Server reference";
  return "None";
}
