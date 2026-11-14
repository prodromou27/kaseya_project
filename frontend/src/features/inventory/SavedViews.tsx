import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import type { Customer, ListLayout, Paginated, SavedViewRow } from "../../lib/types";

/** Named layouts reuse the existing customer/private-owner/shared-view permission contract. */
export function SavedViews({ customer, viewType, current, layout, selectedId = "", onLoad }: {
  customer: Customer; viewType: "assets" | "software" | "os_updates";
  current: Record<string, string>; layout?: ListLayout; selectedId?: string;
  onLoad: (filters: Record<string, string>, layout: ListLayout, id: string) => void;
}) {
  const me = useMe();
  const qc = useQueryClient();
  const key = ["saved-views", customer.id, viewType];
  const views = useQuery({ queryKey: key, queryFn: () => api.get<Paginated<SavedViewRow>>(`/customers/${customer.id}/saved-views/`, { view_type: viewType, page_size: 200 }) });
  const selected = useQuery({ queryKey: [...key, selectedId], queryFn: () => api.get<SavedViewRow>(`/customers/${customer.id}/saved-views/${selectedId}/`), enabled: Boolean(selectedId) });
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const loaded = useRef("");
  const apply = (view: SavedViewRow) => {
    loaded.current = view.id;
    onLoad(view.filters, view.layout ?? {}, view.id);
  };
  useEffect(() => {
    if (!selectedId) { loaded.current = ""; return; }
    if (selected.data && loaded.current !== selectedId) {
      loaded.current = selectedId;
      onLoad(selected.data.filters, selected.data.layout ?? {}, selectedId);
    }
  }, [selectedId, selected.data, onLoad]);
  const save = useMutation({
    mutationFn: (update: boolean) => {
      if (update && !selected.data) throw new Error("Load a saved view before updating it.");
      const data = { name: update ? selected.data?.name : name.trim(), view_type: viewType, shared: update ? selected.data?.shared : shared,
        filters: Object.fromEntries(Object.entries(current).filter(([, value]) => value !== "")), layout: layout ?? {} };
      return update ? api.patch<SavedViewRow>(`/customers/${customer.id}/saved-views/${selectedId}/`, data) : api.post<SavedViewRow>(`/customers/${customer.id}/saved-views/`, data);
    },
    onSuccess: (view) => { qc.setQueryData([...key, view.id], view); void qc.invalidateQueries({ queryKey: key }); apply(view); setName(""); },
  });
  const remove = useMutation({ mutationFn: () => api.del(`/customers/${customer.id}/saved-views/${selectedId}/`), onSuccess: () => {
    void qc.invalidateQueries({ queryKey: key }); setConfirmDelete(false); onLoad(current, layout ?? {}, "");
  } });
  const owned = selected.data?.owner === me.email;
  return <details className="list-disclosure">
    <summary>Saved views{selected.data ? ` / ${selected.data.name}` : ""}</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-slate-500">Save filters, visible columns, row density and page size. Private unless you choose to share.</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="list-label">Saved view<select className="input" value={selectedId} disabled={views.isPending} onChange={(event) => {
          const view = views.data?.results.find((row) => row.id === event.target.value);
          if (view) apply(view); else onLoad(current, layout ?? {}, "");
        }}><option value="">Current unsaved view</option>{(views.data?.results ?? []).map((view) => <option key={view.id} value={view.id}>{view.name}{view.shared ? " (shared)" : ""}</option>)}</select></label>
        {owned ? <><button type="button" className="btn-secondary" disabled={save.isPending} onClick={() => save.mutate(true)}>Update view</button><button type="button" className="btn-secondary" onClick={() => setConfirmDelete(true)}>Delete view</button></> : null}
      </div>
      <form className="flex flex-wrap items-end gap-3" aria-label="Save list view" onSubmit={(event) => { event.preventDefault(); save.mutate(false); }}>
        <label className="list-label">View name<input className="input" required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Offline HQ workstations" /></label>
        <label className="flex min-h-9 items-center gap-2 text-xs"><input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} />Share with this customer's readers</label>
        <button type="submit" className="btn-secondary" disabled={save.isPending || !name.trim()}>Save view</button>
      </form>
      {confirmDelete ? <div className="flex items-center gap-3 text-sm"><span>Delete your saved view?</span><button type="button" className="btn-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>Confirm delete</button><button type="button" className="btn-secondary" onClick={() => setConfirmDelete(false)}>Cancel</button></div> : null}
      {save.isSuccess ? <p role="status" className="text-xs text-emerald-800">View saved.</p> : null}
      {[views.error, selected.error, save.error, remove.error].filter(Boolean).map((error, index) => <p key={index} role="alert" className="text-xs text-red-700">{describeError(error)}</p>)}
    </div>
  </details>;
}
