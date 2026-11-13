import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";

import { ErrorState } from "../components/States";
import { ApiError, UNAUTHENTICATED_EVENT, api } from "./api";
import type { Me } from "./types";

const MeContext = createContext<Me | null>(null);

export const ME_QUERY_KEY = ["me"] as const;

export function useMeQuery() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Me>("/auth/me/", undefined, signal),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 60_000,
  });
}

/** Returns the authenticated user. Only valid beneath <RequireAuth>. */
export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe used outside RequireAuth");
  return me;
}

export function RequireAuth({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const me = useMeQuery();

  useEffect(() => {
    const onUnauthenticated = () => {
      queryClient.clear();
      navigate("/login", { replace: true, state: { from: location.pathname } });
    };
    window.addEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
  }, [navigate, location.pathname, queryClient]);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) {
      navigate("/login", { replace: true, state: { from: location.pathname } });
    }
  }, [me.error, navigate, location.pathname]);

  if (me.isPending) return <>{fallback}</>;
  if (me.isError && !(me.error instanceof ApiError && me.error.status === 401)) {
    // Not "signed out": the API is unreachable or refused the request (e.g. 400 for an unknown host name, 502 when
    // the backend is down). Show it instead of an endless "Checking your session…".
    return (
      <div className="mx-auto mt-16 max-w-lg p-4">
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
        <p className="mt-3 text-sm text-slate-600">
          Open the portal with the host name it was installed for. If the problem persists, ask the administrator to
          check the server (<code>docker compose ps</code> and the backend logs).
        </p>
      </div>
    );
  }
  if (!me.data) return <>{fallback}</>;
  return <MeContext.Provider value={me.data}>{children}</MeContext.Provider>;
}

export function hasGlobal(me: Me, capability: string): boolean {
  return me.global_capabilities.includes(capability);
}
