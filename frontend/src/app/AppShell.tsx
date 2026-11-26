import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { LoadingState } from "../components/States";
import { api, describeError } from "../lib/api";
import { useMe } from "../lib/auth";
import { useCustomers } from "../lib/customerContext";
import { AlertBell } from "../features/alerts/AlertsPage";
import { isHere, NAV_GROUPS, type NavItem } from "./nav";

export { NAV_GROUPS, NAV_ITEMS } from "./nav";

function CustomerSelector() {
  const { customers, selected, select, isLoading, isError } = useCustomers();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <label htmlFor="customer-selector" className="hidden text-xs font-medium text-slate-500 sm:block">Customer</label>
      <select id="customer-selector" className="input max-w-full bg-slate-50 font-medium text-slate-900 sm:w-72"
        value={selected?.id ?? ""} onChange={(e) => select(e.target.value || null)}
        disabled={isLoading || isError || customers.length === 0}>
        <option value="">{isLoading ? "Loading…" : customers.length === 0 ? "No assigned customers" : "Select a customer…"}</option>
        {customers.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
      </select>
    </div>
  );
}

function initials(name: string) {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
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
    <div className="flex min-w-0 items-center gap-2 text-sm">
      <AlertBell />
      <span className="ml-1 hidden items-center gap-2 border-l border-slate-200 pl-3 lg:flex">
        <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-xs font-semibold text-sky-800">{initials(me.display_name || me.email)}</span>
        <span className="leading-tight">
          <span className="block max-w-40 truncate text-[13px] font-medium text-slate-800">{me.display_name || me.email}</span>
          <span className="text-[11px] text-slate-500">{me.is_super_admin ? "Super admin" : "Engineer"} · {me.auth_source === "oidc" ? "SSO" : "Local account"}</span>
        </span>
      </span>
      <button type="button" aria-label="Sign out" title="Sign out" className="btn-secondary h-9 w-9 px-0" disabled={logout.isPending} onClick={() => logout.mutate()}>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
      </button>
      {logout.isError ? <span role="alert" className="max-w-52 text-xs text-red-700">Sign out failed. {describeError(logout.error)}</span> : null}
    </div>
  );
}

const FOLD_KEY = "okp.navOpen";

function readOpen(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(FOLD_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function MainNav({ onNavigate }: { onNavigate: () => void }) {
  const me = useMe();
  const { pathname } = useLocation();
  const [search, setSearch] = useState("");
  const [opened, setOpened] = useState<string[]>(readOpen);
  const toggle = (label: string, open: boolean) => setOpened((prev) => {
    const next = open ? [...new Set([...prev, label])] : prev.filter((x) => x !== label);
    try { window.localStorage.setItem(FOLD_KEY, JSON.stringify(next)); } catch { /* per-browser convenience only */ }
    return next;
  });
  const here = (item: NavItem) => isHere(item, pathname);
  const visible = NAV_GROUPS.map((group) => ({ ...group, items: group.items.filter((item) =>
    (!item.adminOnly || me.is_super_admin) && `${group.label} ${item.label}`.toLowerCase().includes(search.trim().toLowerCase()),
  ) })).filter((group) => group.items.length);
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-4 px-3 py-4">
      <div className="flex items-center gap-2.5 px-2">
        <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500 text-sm font-bold text-white">O</span>
        <span className="leading-tight">
          <span className="block text-[15px] font-semibold tracking-tight text-white">Odyssey</span>
          <span className="block text-[11px] text-slate-400">Kaseya analytics</span>
        </span>
      </div>
      <label className="sr-only" htmlFor="nav-search">Find a page</label>
      <input id="nav-search" type="search" placeholder="Find a page…" maxLength={80} className="mx-1 min-w-0 rounded-md border border-slate-700/80 bg-slate-800/70 px-2.5 py-1.5 text-xs text-white placeholder:text-slate-400" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="space-y-3">
        {visible.map((group) => {
          const links = (
            <ul className="space-y-0.5">
              {group.items.map((item) => <li key={item.to}>
                <NavLink to={item.to} end={item.to === "/"} onClick={onNavigate} className={({ isActive }) =>
                  `nav-item relative flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[13px] ${isActive ? "bg-white/10 font-medium text-white before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sky-400" : "text-slate-300 hover:bg-white/5 hover:text-white"}`}>
                  <span className={here(item) ? "text-sky-300" : "text-slate-400"}>{item.icon}</span>{item.label}
                </NavLink>
              </li>)}
            </ul>
          );
          if (!group.folded) {
            return (
              <section key={group.label} aria-label={group.label}>
                <h2 className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">{group.label}</h2>
                {links}
              </section>
            );
          }
          const open = Boolean(search.trim()) || group.items.some(here) || opened.includes(group.label);
          return (
            <details key={group.label} aria-label={group.label} open={open} className="group/fold"
              onToggle={(e) => { const now = (e.currentTarget as HTMLDetailsElement).open; if (now !== open) toggle(group.label, now); }}>
              <summary className="mb-1 flex cursor-pointer list-none items-center justify-between rounded-md px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
                {group.label}<span aria-hidden="true" className="transition-transform group-open/fold:rotate-90">›</span>
              </summary>
              {links}
            </details>
          );
        })}
        {!visible.length ? <p className="px-3 text-xs text-slate-400">No matching pages.</p> : null}
      </div>
      <p className="mt-auto border-t border-slate-800 px-3 pt-3 text-[10px] leading-relaxed text-slate-400">VSA source access is read-only.<br />Customer permissions apply to every view.</p>
    </nav>
  );
}

type DeviceHit = {
  asset_id: string; hostname: string; customer_id: string; customer_code: string; customer_name: string;
  site: string; group: string; os: string; last_seen_online: string | null;
};

/** Type a hostname, serial or device ID: matches from every customer you may read; pick one to open the device. */
function DeviceSearch() {
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const { select } = useCustomers();
  useEffect(() => {
    const t = setTimeout(() => setTerm(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);
  const hits = useQuery({
    queryKey: ["device-lookup", term],
    queryFn: ({ signal }) => api.get<{ results: DeviceHit[] }>("/assets/lookup/", { q: term }, signal),
    enabled: term.length >= 2,
    staleTime: 30_000,
  });
  const results = term.length >= 2 ? hits.data?.results ?? [] : [];
  const go = (hit: DeviceHit) => {
    select(hit.customer_id);
    setOpen(false);
    setSearch("");
    navigate(`/assets/${hit.asset_id}`);
  };
  return (
    <form role="search" aria-label="Device search" className="relative order-last flex w-full min-w-0 items-center gap-2 md:order-none md:w-auto md:flex-1 md:justify-end"
      onSubmit={(e) => {
        e.preventDefault();
        const hit = results[active] ?? (results.length === 1 ? results[0] : undefined);
        if (hit) go(hit);
      }}>
      <label className="sr-only" htmlFor="global-device-search">Find a device in any of your customers</label>
      <input id="global-device-search" className="input w-full md:w-64" type="search" placeholder="Find a device (name, serial, ID)…" maxLength={100}
        role="combobox" aria-expanded={open && results.length > 0} aria-controls="device-search-results" aria-autocomplete="list"
        aria-activedescendant={open && results[active] ? `device-hit-${results[active].asset_id}` : undefined}
        value={search} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => { setSearch(e.target.value); setActive(0); setOpen(true); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, Math.max(results.length - 1, 0))); }
          if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
          if (e.key === "Escape") setOpen(false);
        }} />
      {open && term.length >= 2 ? (
        <ul id="device-search-results" role="listbox" aria-label="Matching devices"
          className="absolute right-0 top-full z-40 mt-1 max-h-96 w-full overflow-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg md:w-96">
          {hits.isFetching && !results.length ? <li className="px-3 py-2 text-slate-500">Searching…</li> : null}
          {!hits.isFetching && hits.isSuccess && !results.length ? <li className="px-3 py-2 text-slate-500">No device matches “{term}”.</li> : null}
          {hits.isError ? <li className="px-3 py-2 text-red-700">{describeError(hits.error)}</li> : null}
          {results.map((hit, i) => (
            <li key={hit.asset_id} id={`device-hit-${hit.asset_id}`} role="option" aria-selected={i === active}
              className={`cursor-pointer px-3 py-1.5 ${i === active ? "bg-sky-50" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); go(hit); }} onMouseEnter={() => setActive(i)}>
              <span className="font-medium text-slate-900">{hit.hostname}</span>
              <span className="ml-2 rounded bg-slate-100 px-1.5 text-xs text-slate-700">{hit.customer_code}</span>
              <span className="block truncate text-xs text-slate-500">{[hit.site, hit.group, hit.os].filter(Boolean).join(" · ")}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); menuButton.current?.focus(); }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [menuOpen]);
  return (
    <div className="min-h-screen bg-canvas text-slate-800">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:p-2">Skip to content</a>
      <aside id="main-nav" className={`${menuOpen ? "block" : "hidden"} fixed inset-y-0 left-0 z-30 w-60 overflow-y-auto bg-slate-900 shadow-xl md:block md:shadow-none`}>
        <MainNav onNavigate={() => setMenuOpen(false)} />
      </aside>
      <div className="min-w-0 md:ml-60">
        <header className="sticky top-0 z-20 flex min-h-14 flex-wrap items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur lg:px-6">
          <button ref={menuButton} type="button" className="btn-secondary z-40 md:hidden" aria-expanded={menuOpen} aria-controls="main-nav" onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? "Close menu" : "Menu"}</button>
          <CustomerSelector />
          <DeviceSearch />
          <AccountStatus />
        </header>
        {menuOpen ? <button type="button" aria-label="Close navigation" className="fixed inset-0 z-20 bg-slate-900/40 md:hidden" onClick={() => { setMenuOpen(false); menuButton.current?.focus(); }} /> : null}
        <main id="main" tabIndex={-1} className="mx-auto min-w-0 max-w-[1600px] p-4 lg:px-6 lg:py-5"><Suspense fallback={<LoadingState label="Loading workspace..." />}><Outlet /></Suspense></main>
      </div>
    </div>
  );
}
