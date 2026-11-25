import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { Customer, CustomFieldAllow } from "../../lib/types";

export type CfCondition = { custom_field: string; custom_field_state: string; custom_field_value: string };
export const NO_CONDITION: CfCondition = { custom_field: "", custom_field_state: "", custom_field_value: "" };

/** CFA-10: the conditions the device filter understands (backend ``CUSTOM_FIELD_STATES``). */
export const CONDITIONS: { id: string; label: string; needsValue?: boolean }[] = [
  { id: "missing", label: "is empty" },
  { id: "missing_or_equals", label: "is empty or…", needsValue: true },
  { id: "equals", label: "is…", needsValue: true },
  { id: "not_equals", label: "has a value other than…", needsValue: true },
  { id: "set", label: "has any value" },
  { id: "not_read", label: "was not read in the last sync" },
];

/** Approved device custom field names: only their values are collected, so only they can be filtered on. */
export function useCollectedFields(customer: Customer) {
  return useQuery({
    queryKey: ["custom-field-allowlist", customer.id],
    queryFn: ({ signal }) => api.get<CustomFieldAllow[]>(`/customers/${customer.id}/custom-field-allowlist/`, undefined, signal),
    select: (rows) => rows.filter((r) => r.state === "approved").map((r) => r.name).sort((a, b) => a.localeCompare(b)),
  });
}

/** "Custom field [name] [condition] [value]": filters devices by the value the latest sync collected. */
export function CustomFieldCondition({ customer, value, onChange }: { customer: Customer; value: CfCondition; onChange: (next: CfCondition) => void }) {
  const names = useCollectedFields(customer);
  const state = value.custom_field_state || "missing";
  const needsValue = CONDITIONS.find((c) => c.id === state)?.needsValue;
  if (names.data && !names.data.length) {
    return <p className="text-xs text-slate-500">No device custom field values are collected for this customer. A customer administrator approves field names under Customer → Custom fields.</p>;
  }
  return (
    <fieldset className="flex flex-wrap items-end gap-2">
      <legend className="sr-only">Custom field condition</legend>
      <label className="list-label">Filter by custom field
        <select className="input max-w-56" value={value.custom_field}
          onChange={(e) => onChange(e.target.value ? { ...value, custom_field: e.target.value, custom_field_state: value.custom_field_state || "missing" } : NO_CONDITION)}>
          <option value="">Any</option>
          {(names.data ?? []).map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      {value.custom_field ? (
        <label className="list-label">Condition
          <select className="input" value={state} onChange={(e) => onChange({ ...value, custom_field_state: e.target.value })}>
            {CONDITIONS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </label>
      ) : null}
      {value.custom_field && needsValue ? (
        <label className="list-label">Compare with
          <input className="input w-36" maxLength={255} value={value.custom_field_value} placeholder="TBD"
            onChange={(e) => onChange({ ...value, custom_field_value: e.target.value })} />
        </label>
      ) : null}
    </fieldset>
  );
}

/** Only the parts the API needs: no field → nothing; a value only for conditions that compare with one. */
export function conditionParams(c: CfCondition): Partial<CfCondition> {
  if (!c.custom_field) return {};
  const state = c.custom_field_state || "missing";
  const needsValue = CONDITIONS.find((x) => x.id === state)?.needsValue;
  if (needsValue && !c.custom_field_value.trim()) return {};
  return { custom_field: c.custom_field, custom_field_state: state, ...(needsValue ? { custom_field_value: c.custom_field_value.trim() } : {}) };
}
