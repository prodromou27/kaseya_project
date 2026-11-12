import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId } from "react";

import { api, describeError } from "../../lib/api";
import type { Customer, Paginated, SavedViewRow } from "../../lib/types";

/** Load / save named filter sets. Filters are validated (allowlisted, customer-checked) on the server. */
export function SavedViews({
  customer,
  viewType,
  current,
  onLoad,
}: {
  customer: Customer;
  viewType: "assets" | "software" | "os_updates";
  current: Record<string, string>;
  onLoad: (filters: Record<string, string>) => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const key = ["saved-views", customer.id, viewType];
  const views = useQuery({
    queryKey: key,
    queryFn: () => api.get<Paginated<SavedViewRow>>(`/customers/${customer.id}/saved-views/`, { view_type: viewType }),
  });
  const save = useMutation({
    mutationFn: ({ name, shared }: { name: string; shared: boolean }) =>
      api.post<SavedViewRow>(`/customers/${customer.id}/saved-views/`, {
        name, view_type: viewType, shared,
        filters: Object.fromEntries(Object.entries(current).filter(([, v]) => v !== "")),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key }),
  });
  return (
    <span className="flex items-end gap-2 text-xs">
      <label htmlFor={id} className="flex flex-col font-medium text-slate-700">
        Saved view
        <select id={id} className="input w-48" defaultValue="" onChange={(e) => {
          const v = views.data?.results.find((x) => x.id === e.target.value);
          if (v) onLoad(v.filters);
        }}>
          <option value="">—</option>
          {(views.data?.results ?? []).map((v) => (
            <option key={v.id} value={v.id}>{v.name}{v.shared ? " (shared)" : ""}</option>
          ))}
        </select>
      </label>
      <button type="button" className="btn-secondary" disabled={save.isPending} onClick={() => {
        const name = window.prompt("Name this view");
        if (name) save.mutate({ name, shared: window.confirm("Share with everyone who can read this customer?") });
      }}>
        Save view
      </button>
      {save.isError ? <span role="alert" className="text-red-700">{describeError(save.error)}</span> : null}
    </span>
  );
}
