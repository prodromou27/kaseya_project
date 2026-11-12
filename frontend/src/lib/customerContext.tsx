import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { api } from "./api";
import type { Customer, Paginated } from "./types";

/**
 * Selected customer. Only the customer *ID* is remembered (sessionStorage, cleared with the tab). It is a UI
 * convenience — the server re-authorises the customer on every request.
 */
const STORAGE_KEY = "okp.selectedCustomer";

type CustomerContextValue = {
  customers: Customer[];
  isLoading: boolean;
  isError: boolean;
  selected: Customer | null;
  select: (id: string | null) => void;
};

const Ctx = createContext<CustomerContextValue | null>(null);

function readStored(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function CustomerProvider({ children }: { children: ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(readStored);
  const query = useQuery({
    queryKey: ["customers", "selector"],
    queryFn: ({ signal }) => api.get<Paginated<Customer>>("/customers/", { page_size: 200 }, signal),
  });

  const select = useCallback((id: string | null) => {
    setSelectedId(id);
    try {
      if (id) window.sessionStorage.setItem(STORAGE_KEY, id);
      else window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* storage unavailable: selection is per-render only */
    }
  }, []);

  const value = useMemo<CustomerContextValue>(() => {
    const customers = query.data?.results ?? [];
    // A stale/forged stored ID that is not in the server-authorised list is ignored.
    const selected = customers.find((c) => c.id === selectedId) ?? (customers.length === 1 ? (customers[0] ?? null) : null);
    return { customers, isLoading: query.isPending, isError: query.isError, selected, select };
  }, [query.data, query.isPending, query.isError, selectedId, select]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCustomers(): CustomerContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCustomers outside CustomerProvider");
  return ctx;
}
