import { useEffect, useRef, useState } from "react";
import { useNavigationType, useSearchParams } from "react-router";

/** URLs describe a view, never authorization. The API validates every filter and customer. */
export function useUrlFilters<T extends Record<string, string>>(defaults: T) {
  const [committed, setParams] = useSearchParams();
  const navigationType = useNavigationType();
  const [params, setDraft] = useState(committed);
  const pending = useRef(new Set<string>());
  const latestRequested = useRef("");
  const committedKey = committed.toString();
  useEffect(() => {
    // Input updates are immediate; router transitions may commit later or skip intermediate keystrokes.
    if (navigationType !== "POP" && pending.current.delete(committedKey)) {
      if (committedKey === latestRequested.current) pending.current.clear();
      return;
    }
    pending.current.clear();
    setDraft(committed);
  }, [committed, committedKey, navigationType]);
  const navigate = (next: URLSearchParams, replace = false) => {
    latestRequested.current = next.toString();
    pending.current.add(latestRequested.current);
    setDraft(next);
    setParams(next, { replace });
  };
  const filters = Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, params.get(key) ?? value])) as T;
  const requestedPage = Number(params.get("page") ?? "1");
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const update = (values: Partial<T>, replace = false, resetPage = true) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value !== undefined && value !== defaults[key]) next.set(key, value);
      else next.delete(key);
    }
    if (resetPage) next.delete("page");
    navigate(next, replace);
  };
  const setPage = (value: number) => {
    const next = new URLSearchParams(params);
    if (value > 1) next.set("page", String(value));
    else next.delete("page");
    navigate(next);
  };
  const reset = () => {
    const next = new URLSearchParams(params);
    for (const key of [...Object.keys(defaults), "page"]) next.delete(key);
    navigate(next);
  };
  return { filters, update, reset, page, setPage };
}
