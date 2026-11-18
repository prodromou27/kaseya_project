import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Field, Notice } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import type { Integration } from "../../lib/types";

function when(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleString() : "";
}

/**
 * OPTIONAL separate VSA X write token (super admin). Without one, writes use the integration's API token. Sent once
 * over HTTPS, stored encrypted, never shown again; used only for approved group moves and custom field assignments.
 */
export function WriteTokenForm({ integration }: { integration: Integration }) {
  const queryClient = useQueryClient();
  const [tokenId, setTokenId] = useState("");
  const [secret, setSecret] = useState("");
  const done = () => {
    setTokenId("");
    setSecret("");
    void queryClient.invalidateQueries({ queryKey: ["integrations"] });
  };
  const save = useMutation({
    mutationFn: () => api.post<Integration>(`/integrations/${integration.id}/write-credential/`, { token_id: tokenId, token_secret: secret }),
    onSuccess: done,
    onError: () => setSecret(""), // never keep the secret in the form after a failed attempt
  });
  const remove = useMutation({
    mutationFn: () => api.del<Integration>(`/integrations/${integration.id}/write-credential/`),
    onSuccess: done,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const source = integration.write_credential_source ?? (integration.write_credential_configured ? "server" : "none");
  return (
    <form onSubmit={submit} aria-label="VSA X write token" className="space-y-2 rounded border border-amber-200 bg-amber-50/50 p-3">
      <h4 className="text-sm font-semibold">Separate write token (optional)</h4>
      <p className="text-xs text-slate-600">
        Not required: without it, changes are made with this integration's API token (entered under Credentials). Enter a
        second VSA X API token here only if you want changes made with a different token. Stored encrypted; it can be
        replaced or removed but never viewed again.
      </p>
      <p className="text-sm" aria-live="polite">
        Status:{" "}
        <strong>
          {source === "portal"
            ? `entered in the portal${integration.write_credential_set_by ? ` by ${integration.write_credential_set_by}` : ""}${integration.write_credential_set_at ? `, ${when(integration.write_credential_set_at)}` : ""}`
            : source === "server" ? "server secret reference" : "not set (the integration's API token is used)"}
        </strong>
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Write token ID">
          {(id) => <input id={id} className="input w-56" required maxLength={200} autoComplete="off" spellCheck={false} value={tokenId} onChange={(e) => setTokenId(e.target.value)} />}
        </Field>
        <Field label="Write token secret">
          {(id) => <input id={id} className="input w-56" required maxLength={500} type="password" autoComplete="new-password" spellCheck={false} value={secret} onChange={(e) => setSecret(e.target.value)} />}
        </Field>
        <button type="submit" className="btn-primary" disabled={save.isPending}>{source === "portal" ? "Replace write token" : "Save write token"}</button>
        {source === "portal" ? (
          <button type="button" className="btn-secondary" disabled={remove.isPending}
                  onClick={() => { if (window.confirm("Remove the separate write token? Changes will then be made with the integration's API token.")) remove.mutate(); }}>
            Remove write token
          </button>
        ) : null}
      </div>
      {save.isError ? <p role="alert" className="text-sm text-red-700">{describeError(save.error)}</p> : null}
      {remove.isError ? <p role="alert" className="text-sm text-red-700">{describeError(remove.error)}</p> : null}
    </form>
  );
}

type ValidationResult = { result: { route: string; field: string; field_id: string; device: string; value: string; observed: string | null } };

/** Write ONE test value to ONE authorised test workstation, read it back and record the working route (super admin). */
export function RouteValidationForm({ integration }: { integration: Integration }) {
  const queryClient = useQueryClient();
  const [device, setDevice] = useState("");
  const [fieldId, setFieldId] = useState("");
  const [value, setValue] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const run = useMutation({
    mutationFn: () =>
      api.post<ValidationResult>(`/integrations/${integration.id}/validate-custom-field-route/`, {
        device: device.trim(), field_id: fieldId.trim(), value, confirm_test_device: confirmed,
      }),
    onSuccess: () => {
      setConfirmed(false);
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run.mutate();
  };
  const validated = integration.custom_field_write_route;
  return (
    <form onSubmit={submit} aria-label="Validate on a test workstation" className="space-y-2 rounded border border-amber-200 bg-amber-50/50 p-3">
      <h4 className="text-sm font-semibold">Validate on a test workstation</h4>
      <p className="text-xs text-slate-600">
        Before custom field changes can be applied, the portal writes one value to one test workstation, reads it back
        and remembers which documented VSA X route works. Use a device you are allowed to change. Field IDs are listed
        under Custom fields → Field overview after <em>Read fields from VSA X</em>.
      </p>
      <p className="text-sm">
        Status:{" "}
        <strong>
          {integration.is_fixture ? "not needed for fixture integrations"
            : validated ? `validated (/api/v3/${validated}/…)${integration.custom_field_route_validated_at ? `, ${when(integration.custom_field_route_validated_at)}` : ""}`
              : "not validated yet"}
        </strong>
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Test workstation" hint="Hostname or VSA X device ID">
          {(id, h) => <input id={id} aria-describedby={h} className="input w-56" required maxLength={255} value={device} onChange={(e) => setDevice(e.target.value)} />}
        </Field>
        <Field label="Custom field ID">
          {(id) => <input id={id} className="input w-28" required inputMode="numeric" pattern="[0-9]{1,18}" value={fieldId} onChange={(e) => setFieldId(e.target.value)} />}
        </Field>
        <Field label="Test value">
          {(id) => <input id={id} className="input w-48" maxLength={255} value={value} onChange={(e) => setValue(e.target.value)} />}
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        This is an authorised test workstation and may be changed
      </label>
      <button type="submit" className="btn-primary" disabled={!confirmed || run.isPending}>
        {run.isPending ? "Writing and reading back…" : "Write test value and verify"}
      </button>
      {run.isSuccess ? (
        <Notice tone="good">
          Confirmed: {run.data.result.field} = “{run.data.result.value}” was written to {run.data.result.device} and read back.
          Route <code>/api/v3/{run.data.result.route}/…</code> recorded.
        </Notice>
      ) : null}
      {run.isError ? <p role="alert" className="text-sm text-red-700">{describeError(run.error)}</p> : null}
    </form>
  );
}
