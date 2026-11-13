import { useMutation, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router";

import { api } from "../lib/api";
import { useMe } from "../lib/auth";
import { useCustomers } from "../lib/customerContext";

type NavItem = { to: string; label: string; phase?: string; adminOnly?: boolean };

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard" },
  { to: "/customers", label: "Customers" },
  { to: "/groups", label: "Groups & network" },
  { to: "/onboarding", label: "Onboarding check" },
  { to: "/assets", label: "Assets" },
  { to: "/device-health", label: "Device health" },
  { to: "/changes", label: "Inventory changes" },
  { to: "/notifications", label: "Notifications" },
  { to: "/software", label: "Software versions" },
  { to: "/windows-updates", label: "Windows updates" },
  { to: "/patch-policies", label: "Patch policies" },
  { to: "/itglue", label: "IT Glue", phase: "P3" },
  { to: "/autotask", label: "Autotask PSA", phase: "P4" },
  { to: "/reports", label: "Reports" },
  { to: "/admin", label: "Administration", adminOnly: true },
];

function CustomerSelector() {
  const { customers, selected, select, isLoading, isError } = useCustomers();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="customer-selector" className="text-xs font-medium text-slate-300">
        Customer
      </label>
      <select
        id="customer-selector"
        className="max-w-64 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-white"
        value={selected?.id ?? ""}
        onChange={(e) => select(e.target.value || null)}
        disabled={isLoading || isError || customers.length === 0}
      >
        <option value="">{isLoading ? "Loading…" : customers.length === 0 ? "No assigned customers" : "Select a customer…"}</option>
        {customers.map((c) => (
          <option key={c.id} value={c.id}>
            {c.code} — {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}

function AccountStatus() {
  const me = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: () => api.post<undefined>("/auth/logout/"),
    onSettled: () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });
  const role = me.is_super_admin ? "Super admin" : me.memberships.length ? `${me.memberships.length} customer grant(s)` : "No grants";
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-right leading-tight">
        <span className="block text-white">{me.display_name || me.email}</span>
        <span className="block text-xs text-slate-400">
          {role} · {me.auth_source === "oidc" ? "SSO" : "Local account"}
        </span>
      </span>
      <button type="button" className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" onClick={() => logout.mutate()}>
        Sign out
      </button>
    </div>
  );
}

export function AppShell() {
  const me = useMe();
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:bg-white focus:p-2">
        Skip to content
      </a>
      <header className="flex flex-wrap items-center justify-between gap-3 bg-slate-900 px-4 py-2">
        <div className="flex items-center gap-6">
          <span className="text-sm font-semibold tracking-wide text-white">Odyssey · Kaseya Analytics</span>
          <CustomerSelector />
        </div>
        <AccountStatus />
      </header>
      <div className="flex flex-1">
        <nav aria-label="Main" className="w-52 shrink-0 border-r border-slate-200 bg-white px-2 py-3">
          <ul className="space-y-0.5">
            {NAV_ITEMS.filter((item) => !item.adminOnly || me.is_super_admin).map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center justify-between rounded px-2 py-1.5 text-sm ${
                      isActive ? "bg-sky-50 font-medium text-sky-800" : "text-slate-700 hover:bg-slate-100"
                    }`
                  }
                >
                  {item.label}
                  {item.phase ? <span className="text-[10px] uppercase text-slate-400">{item.phase}</span> : null}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main" className="min-w-0 flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
