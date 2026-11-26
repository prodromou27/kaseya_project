import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import type { Customer } from "../../lib/types";
import { conditionParams, CustomFieldCondition, type CfCondition } from "../customfields/CustomFieldCondition";

/**
 * FLT-01: extra device filters shared by the Devices list and the Custom fields device picker. Every key is a backend
 * ``AssetFilters`` parameter, so the same values work for the list, "all matching" jobs, exports and saved views.
 */
export const ADVANCED_KEYS = [
  "manufacturer", "model", "os_version", "agent_version", "domain", "tag", "role",
  "software", "software_presence", "software_outdated", "missing_updates", "patch_policy",
] as const;
export const CF_SUFFIXES = ["", "_2", "_3"] as const;
export const CF_KEYS = CF_SUFFIXES.flatMap((s) => [`custom_field${s}`, `custom_field_state${s}`, `custom_field_value${s}`]);
export const EMPTY_ADVANCED: Record<string, string> = Object.fromEntries([...ADVANCED_KEYS, ...CF_KEYS].map((k) => [k, ""]));

export const NO_POLICY = "__none__";
export const UNKNOWN_POLICY = "__unknown__";

/** Short labels and values for the "active filter" chips. */
export const FILTER_LABELS: Record<string, string> = {
  manufacturer: "Manufacturer", model: "Model", os_version: "OS version", agent_version: "Agent", domain: "Domain", tag: "Tag",
  role: "Role", software: "Program", software_presence: "Program is", software_outdated: "Outdated software",
  missing_updates: "Missing updates", patch_policy: "Patch policy",
  custom_field: "Custom field", custom_field_2: "Custom field 2", custom_field_3: "Custom field 3",
};
export function describeFilter(key: string, value: string): string {
  if (key === "patch_policy") return value === NO_POLICY ? "none / not reported" : value === UNKNOWN_POLICY ? "not collected" : value;
  if (key === "software_outdated") return value === "true" ? "yes" : "none";
  if (key === "missing_updates") return value === "none" ? "none missing" : value;
  return value.replace(/_/g, " ");
}

type Facets = {
  manufacturer?: string[]; model?: string[]; os_version?: string[]; agent_version?: string[]; domain?: string[]; tag?: string[]; patch_policy?: string[];
};

/** The request parameters: empty values dropped, custom field rules only when complete. */
export function advancedParams(values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const key of ADVANCED_KEYS) if (values[key]?.trim()) out[key] = values[key].trim();
  if (!out.software) delete out.software_presence;
  CF_SUFFIXES.forEach((sfx) => {
    const c = conditionParams({
      custom_field: values[`custom_field${sfx}`] ?? "", custom_field_state: values[`custom_field_state${sfx}`] ?? "", custom_field_value: values[`custom_field_value${sfx}`] ?? "",
    });
    if (c.custom_field) {
      out[`custom_field${sfx}`] = c.custom_field;
      if (c.custom_field_state) out[`custom_field_state${sfx}`] = c.custom_field_state;
      if (c.custom_field_value) out[`custom_field_value${sfx}`] = c.custom_field_value;
    }
  });
  return out;
}

/** A text box that reports its value after a short pause, so typing does not send a request per key. */
function TypedFilter({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text === value) return;
    const t = setTimeout(() => onChange(text), 400);
    return () => clearTimeout(t);
  }, [text, value, onChange]);
  return <label className="list-label">{label}<input className="input" maxLength={255} value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} /></label>;
}

function Choice({ label, value, options, onChange, any = "Any" }: { label: string; value: string; options: (string | [string, string])[]; onChange: (v: string) => void; any?: string }) {
  return (
    <label className="list-label">{label}
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{any}</option>
        {options.map((o) => { const [v, t] = Array.isArray(o) ? o : [o, o]; return <option key={v} value={v}>{t}</option>; })}
      </select>
    </label>
  );
}

/** Hardware & identity, Software & patching, and up to three custom field rules (all must match). */
export function DeviceFilters({ customer, values, onChange }: { customer: Customer; values: Record<string, string>; onChange: (next: Record<string, string>) => void }) {
  const facets = useQuery({
    queryKey: ["assets", customer.id, "facets"],
    queryFn: ({ signal }) => api.get<Facets>(`/customers/${customer.id}/assets/facets/`, undefined, signal),
  });
  const f = facets.data ?? {};
  const v = (k: string) => values[k] ?? "";
  const set = (k: string) => (next: string) => onChange({ [k]: next });
  const rulesShown = Math.max(1, ...CF_SUFFIXES.map((s, i) => (v(`custom_field${s}`) ? i + 1 : 0)));
  const [rules, setRules] = useState(rulesShown);
  const shown = Math.max(rules, rulesShown);
  return (
    <div className="space-y-4">
      <fieldset>
        <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Hardware &amp; identity</legend>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Choice label="Role" value={v("role")} options={[["workstation", "Workstations"], ["server", "Servers"]]} onChange={set("role")} any="Workstations and servers" />
          <Choice label="Manufacturer" value={v("manufacturer")} options={f.manufacturer ?? []} onChange={set("manufacturer")} />
          <TypedFilter label="Model contains" value={v("model")} onChange={set("model")} placeholder="e.g. Latitude" />
          <Choice label="OS version" value={v("os_version")} options={f.os_version ?? []} onChange={set("os_version")} />
          <Choice label="Agent version" value={v("agent_version")} options={f.agent_version ?? []} onChange={set("agent_version")} />
          <Choice label="Domain" value={v("domain")} options={f.domain ?? []} onChange={set("domain")} />
          <Choice label="VSA tag" value={v("tag")} options={f.tag ?? []} onChange={set("tag")} />
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Software &amp; patching</legend>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TypedFilter label="Program name contains" value={v("software")} onChange={set("software")} placeholder="e.g. Chrome" />
          <label className="list-label">Program is
            <select className="input" value={v("software_presence") || "installed"} onChange={(e) => onChange({ software_presence: e.target.value })}>
              <option value="installed">installed</option>
              <option value="not_installed">not installed</option>
            </select>
          </label>
          <Choice label="Outdated software" value={v("software_outdated")} options={[["true", "Has outdated software"], ["false", "Nothing outdated"]]} onChange={set("software_outdated")} />
          <Choice label="Missing OS updates" value={v("missing_updates")}
            options={[["critical", "Critical missing"], ["important", "Important missing"], ["any", "Any update missing"], ["none", "None missing"]]} onChange={set("missing_updates")} />
          <Choice label="Patch policy" value={v("patch_policy")}
            options={[...(f.patch_policy ?? []), [NO_POLICY, "No policy / not reported"], [UNKNOWN_POLICY, "Not collected"]]} onChange={set("patch_policy")} />
        </div>
        <p className="mt-1 text-xs text-slate-500">Devices whose software or updates were not collected are never counted as &quot;not installed&quot;, &quot;nothing outdated&quot; or &quot;none missing&quot;.</p>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Custom fields (all rules must match)</legend>
        <div className="space-y-2">
          {CF_SUFFIXES.slice(0, shown).map((sfx, i) => (
            <div key={sfx} className="flex flex-wrap items-end gap-2" aria-label={`Custom field rule ${i + 1}`} role="group">
              <CustomFieldCondition customer={customer}
                value={{ custom_field: v(`custom_field${sfx}`), custom_field_state: v(`custom_field_state${sfx}`), custom_field_value: v(`custom_field_value${sfx}`) }}
                onChange={(c: CfCondition) => onChange({ [`custom_field${sfx}`]: c.custom_field, [`custom_field_state${sfx}`]: c.custom_field_state, [`custom_field_value${sfx}`]: c.custom_field_value })} />
            </div>
          ))}
          {shown < CF_SUFFIXES.length && v(`custom_field${CF_SUFFIXES[shown - 1]}`) ? (
            <button type="button" className="text-xs font-medium text-sky-800 underline" onClick={() => setRules(shown + 1)}>Add another custom field rule</button>
          ) : null}
        </div>
      </fieldset>
    </div>
  );
}
