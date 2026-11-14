import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { LoadingState } from "../components/States";
import { api, describeError } from "../lib/api";
import { useMe } from "../lib/auth";
import { useCustomers } from "../lib/customerContext";

type NavItem = { to: string; label: string; adminOnly?: boolean };
export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  { label: "Overview", items: [{ to: "/", label: "Dashboard" }] },
  { label: "VSA operations", items: [
    { to: "/assets", label: "Devices" }, { to: "/groups", label: "Groups & network" },
    { to: "/device-health", label: "Device health" }, { to: "/notifications", label: "Notifications" },
    { to: "/changes", label: "Inventory changes" },
  ] },
  { label: "Software & patching", items: [
    { to: "/software", label: "Software" }, { to: "/windows-updates", label: "Windows updates" },
    { to: "/patch-policies", label: "Patch policies" }, { to: "/lifecycle", label: "Lifecycle" },
  ] },
  { label: "Inventory reconciliation", items: [{ to: "/onboarding", label: "Onboarding check" }] },
  { label: "Reporting", items: [{ to: "/reports", label: "Reports" }] },
  { label: "Administration", items: [
    { to: "/customers", label: "Customers" }, { to: "/group-moves", label: "Group move approvals" }, { to: "/admin", label: "Settings", adminOnly: true },
  ] },
];
export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

function CustomerSelector() {
  const { customers, selected, select, isLoading, isError } = useCustomers();
  return (
    <div className="flex min-w-0 flex-col gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
      <label htmlFor="customer-selector">Customer</label>
      <select id="customer-selector" className="input max-w-full font-medium normal-case tracking-normal text-slate-900 sm:w-72"
        value={selected?.id ?? ""} onChange={(e) => select(e.target.value || null)}
        disabled={isLoading || isError || customers.length === 0}>
        <option value="">{isLoading ? "Loading…" : customers.length === 0 ? "No assigned customers" : "Select a customer…"}</option>
        {customers.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
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
    onSuccess: () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });
  return (
    <div className="flex min-w-0 items-center gap-3 text-sm">
      <span className="hidden text-right leading-tight lg:block">
        <span className="block font-medium text-slate-800">{me.display_name || me.email}</span>
        <span className="text-xs text-slate-500">{me.is_super_admin ? "Super admin" : "Engineer portal"} · {me.auth_source === "oidc" ? "SSO" : "Local account"}</span>
      </span>
      <button type="button" className="btn-secondary whitespace-nowrap" disabled={logout.isPending} onClick={() => logout.mutate()}>Sign out</button>
      {logout.isError ? <span role="alert" className="max-w-52 text-xs text-red-700">Sign out failed. {describeError(logout.error)}</span> : null}
    </div>
  );
}

function MainNav({ onNavigate }: { onNavigate: () => void }) {
  const me = useMe();
  const [search, setSearch] = useState("");
  const visible = NAV_GROUPS.map((group) => ({ ...group, items: group.items.filter((item) =>
    (!item.adminOnly || me.is_super_admin) && `${group.label} ${item.label}`.toLowerCase().includes(search.trim().toLowerCase()),
  ) })).filter((group) => group.items.length);
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-4 px-3 py-5">
      <div className="px-2">
        <span className="text-lg font-semibold tracking-tight text-white">ODYSSEY<span className="ml-1 text-sky-400">/</span></span>
        <p className="mt-0.5 text-[11px] text-slate-400">Operations & analytics</p>
      </div>
      <label className="sr-only" htmlFor="nav-search">Find a page</label>
      <input id="nav-search" type="search" placeholder="Find a page…" maxLength={80} className="mx-1 min-w-0 rounded-md border border-slate-700 bg-slate-800 px-2.5 py-2 text-xs text-white placeholder:text-slate-400" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="space-y-4">
        {visible.map((group) => (
          <section key={group.label} aria-label={group.label}>
            <h2 className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">{group.label}</h2>
            <ul className="space-y-0.5">
              {group.items.map((item) => <li key={item.to}>
                <NavLink to={item.to} end={item.to === "/"} onClick={onNavigate} className={({ isActive }) =>
                  `nav-item flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[13px] ${isActive ? "bg-sky-400/15 font-semibold text-sky-200 ring-1 ring-inset ring-sky-400/20" : "text-slate-300 hover:bg-slate-800 hover:text-white"}`}>
                  <span aria-hidden="true" className="h-1 w-1 rounded-full bg-current opacity-60" />{item.label}
                </NavLink>
              </li>)}
            </ul>
          </section>
        ))}
        {!visible.length ? <p className="px-3 text-xs text-slate-400">No matching pages.</p> : null}
      </div>
      <p className="mt-auto border-t border-slate-800 px-3 pt-3 text-[10px] leading-relaxed text-slate-400">VSA source access is read-only.<br />Customer permissions apply to every view.</p>
    </nav>
  );
}

function DeviceSearch() {
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const { selected } = useCustomers();
  return (
    <form role="search" aria-label="Device search" className="hidden min-w-0 flex-1 items-center justify-end gap-2 xl:flex" onSubmit={(e) => {
      e.preventDefault();
      if (selected && search.trim()) navigate(`/assets?search=${encodeURIComponent(search.trim())}`);
    }}>
      <label className="sr-only" htmlFor="global-device-search">Search devices</label>
      <input id="global-device-search" className="input w-52" type="search" placeholder="Find a device…" maxLength={100}
        value={search} onChange={(e) => setSearch(e.target.value)} disabled={!selected} />
      <button type="submit" className="btn-secondary" disabled={!selected || !search.trim()}>Search</button>
    </form>
  );
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const { selected } = useCustomers();
  const { pathname } = useLocation();
  const matches = (item: NavItem) => item.to === "/" ? pathname === "/" : pathname === item.to || pathname.startsWith(`${item.to}/`);
  const current = NAV_GROUPS.find((group) => group.items.some(matches));
  const destination = current?.items.find(matches);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); menuButton.current?.focus(); }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [menuOpen]);
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:p-2">Skip to content</a>
      <aside id="main-nav" className={`${menuOpen ? "block" : "hidden"} fixed inset-y-0 left-0 z-30 w-60 overflow-y-auto bg-slate-900 shadow-xl md:block md:shadow-none`}>
        <MainNav onNavigate={() => setMenuOpen(false)} />
      </aside>
      <div className="min-w-0 md:ml-60">
        <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 lg:px-6">
          <button ref={menuButton} type="button" className="btn-secondary z-40 md:hidden" aria-expanded={menuOpen} aria-controls="main-nav" onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? "Close menu" : "Menu"}</button>
          <CustomerSelector />
          <DeviceSearch />
          <AccountStatus />
        </header>
        {menuOpen ? <button type="button" aria-label="Close navigation" className="fixed inset-0 z-20 bg-slate-900/40 md:hidden" onClick={() => { setMenuOpen(false); menuButton.current?.focus(); }} /> : null}
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-200 bg-white/70 px-4 py-2 text-[11px] text-slate-500 lg:px-6">
          <nav aria-label="Breadcrumb" className="flex items-center gap-2">
            <Link to="/" className="hover:text-sky-700">Portal</Link><span aria-hidden="true">/</span><span>{current?.label ?? "Workspace"}</span>
            {destination ? <><span aria-hidden="true">/</span><span className="font-medium text-slate-700">{destination.label}</span></> : null}
          </nav>
          <span aria-label="Active scope">{selected ? `Scope: ${selected.code} · ${selected.name}` : "Select an authorized customer to begin"}</span>
        </div>
        <main id="main" tabIndex={-1} className="min-w-0 p-4 lg:p-6"><Suspense fallback={<LoadingState label="Loading workspace..." />}><Outlet /></Suspense></main>
      </div>
    </div>
  );
}
