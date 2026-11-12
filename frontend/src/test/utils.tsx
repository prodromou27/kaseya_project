import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { AppRoutes, makeQueryClient } from "../app/App";
import type { Customer, Me } from "../lib/types";

type Handler = { status?: number; body?: unknown; headers?: Record<string, string> };
export type Routes = Record<string, Handler | ((init: RequestInit | undefined, url: URL) => Handler)>;

/** Installs a fetch mock keyed by "METHOD /api/v1/path" (query string ignored). Records calls. */
export function mockFetch(routes: Routes) {
  const calls: { method: string; url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, url: url.pathname + url.search, init });
    const route = routes[`${method} ${url.pathname}`];
    if (!route) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: "Not found.", request_id: "req-test" } }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    const handler = typeof route === "function" ? route(init, url) : route;
    const status = handler.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(handler.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json", "X-Request-ID": "req-test", ...handler.headers },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function renderApp(path = "/") {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const customerA: Customer = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  code: "ACME",
  name: "Acme Ltd",
  status: "active",
  data_region: "EU",
  restricted_data: false,
  notes: "",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  my_capabilities: ["customer.read", "customer.export"],
};

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    id: "user-1",
    email: "eng@example.test",
    display_name: "Eng One",
    auth_source: "local",
    global_role: null,
    global_capabilities: [],
    is_super_admin: false,
    memberships: [{ customer: { id: customerA.id, code: "ACME", name: "Acme Ltd" }, role: "engineer", capabilities: customerA.my_capabilities }],
    ...overrides,
  };
}

export const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });
