import { useSearchParams } from "react-router";

/** URLs describe a view, never authorization. The API validates every filter and customer. */
export function useUrlFilters<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, params.get(key) ?? value])) as T;
  const requestedPage = Number(params.get("page") ?? "1");
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const update = (values: Partial<T>, replace = false) => {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(values)) {
        if (value !== undefined && value !== defaults[key]) next.set(key, value);
        else next.delete(key);
      }
      next.delete("page");
      return next;
    }, { replace });
  };
  const setPage = (value: number) => setParams((previous) => {
    const next = new URLSearchParams(previous);
    if (value > 1) next.set("page", String(value));
    else next.delete("page");
    return next;
  });
  const reset = () => setParams((previous) => {
    const next = new URLSearchParams(previous);
    for (const key of [...Object.keys(defaults), "page"]) next.delete(key);
    return next;
  });
  return { filters, update, reset, page, setPage };
}
