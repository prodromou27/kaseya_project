import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { api } from "../lib/api";
import { useMe } from "../lib/auth";
import { useCustomers } from "../lib/customerContext";

type NavItem = { to: string; label: string; adminOnly?: boolean };

/** The everyday pages: always visible. */
export const MAIN_NAV: NavItem[] = [
  { to: "/", label: "Dashboard" },
  { to: "/assets", label: "Devices" },
  { to: "/device-health", label: "Device health" },
  { to: "/windows-updates", label: "Windows updates" },
  { to: "/software", label: "Software" },
  { to: "/reports", label: "Reports" },
];

/** Specialist views: folded under "More" (opened automatically when one of them is the current page). */
export const MORE_NAV: NavItem[] = [
  { to: "/customers", label: "Customers" },
  { to: "/lifecycle", label: "Lifecycle" },
  { to: "/patch-policies", label: "Patch policies" },
  { to: "/changes", label: "Inventory changes" },
  { to: "/notifications", label: "Notifications" },
  { to: "/groups", label: "Groups & network" },
  { to: "/onboarding", label: "Onboarding check" },
];

export const SETTINGS_NAV: NavItem = { to: "/admin", label: "Settings", adminOnly: true };

/** Flat list (kept for callers/tests that iterate all destinations). */
export const NAV_ITEMS: NavItem[] = [...MAIN_NAV, ...MORE_NAV, SETTINGS_NAV];

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

function NavItemLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.to === "/"}
        onClick={onNavigate}
        className={({ isActive }) =>
          `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-sky-50 font-medium text-sky-800" : "text-slate-700 hover:bg-slate-100"}`
        }
      >
        {item.label}
      </NavLink>
    </li>
  );
}

function MainNav({ onNavigate }: { onNavigate?: () => void }) {
  const me = useMe();
  const { pathname } = useLocation();
  const inMore = MORE_NAV.some((i) => pathname === i.to || pathname.startsWith(`${i.to}/`));
  const [moreOpen, setMoreOpen] = useState(inMore);
  const open = moreOpen || inMore;
  return (
    <nav aria-label="Main" className="flex h-full flex-col px-2 py-4">
      <ul className="space-y-0.5">
        {MAIN_NAV.map((item) => <NavItemLink key={item.to} item={item} onNavigate={onNavigate} />)}
      </ul>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="nav-more"
        onClick={() => setMoreOpen((v) => !v)}
        className="mt-3 flex items-center justify-between rounded-md px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-700"
      >
        More <span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open ? (
        <ul id="nav-more" className="space-y-0.5">
          {MORE_NAV.map((item) => <NavItemLink key={item.to} item={item} onNavigate={onNavigate} />)}
        </ul>
      ) : null}
      {me.is_super_admin ? (
        <ul className="mt-auto border-t border-slate-100 pt-3">
          <NavItemLink item={SETTINGS_NAV} onNavigate={onNavigate} />
        </ul>
      ) : null}
    </nav>
  );
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:bg-white focus:p-2">
        Skip to content
      </a>
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 bg-slate-900 px-4 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
          <button
            type="button"
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 md:hidden"
            aria-expanded={menuOpen}
            aria-controls="main-nav"
            onClick={() => setMenuOpen((v) => !v)}
          >
            Menu
          </button>
          <span className="text-sm font-semibold tracking-wide text-white">Odyssey · Kaseya Analytics</span>
          <CustomerSelector />
        </div>
        <AccountStatus />
      </header>
      <div className="flex flex-1">
        <div id="main-nav" className={`${menuOpen ? "block" : "hidden"} fixed inset-x-0 top-auto z-20 max-h-[80vh] overflow-y-auto border-b border-slate-200 bg-white shadow md:static md:block md:max-h-none md:w-56 md:shrink-0 md:border-b-0 md:border-r md:shadow-none`}>
          <MainNav onNavigate={() => setMenuOpen(false)} />
        </div>
        <main id="main" className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
