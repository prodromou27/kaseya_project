import type { ReactNode } from "react";

export type NavItem = { to: string; label: string; icon: ReactNode; adminOnly?: boolean };

const svg = (d: ReactNode) => (
  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 shrink-0">
    {d}
  </svg>
);

const I = {
  home: svg(<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>),
  devices: svg(<><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>),
  health: svg(<path d="M3 12h4l2-5 4 10 2-5h6" />),
  reports: svg(<><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></>),
  fields: svg(<><path d="M4 7h16M4 12h10M4 17h7" /><path d="M17 15l2 2 3-4" /></>),
  move: svg(<><path d="M5 12h14M13 6l6 6-6 6" /><path d="M5 5v14" /></>),
  updates: svg(<><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></>),
  software: svg(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><path d="M17.5 14v7M14 17.5h7" /></>),
  policy: svg(<><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></>),
  server: svg(<><rect x="3" y="4" width="18" height="7" rx="1.5" /><rect x="3" y="13" width="18" height="7" rx="1.5" /><path d="M7 7.5h.01M7 16.5h.01" /></>),
  lifecycle: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
  compliance: svg(<><path d="M9 11l3 3 8-8" /><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" /></>),
  network: svg(<><rect x="9" y="3" width="6" height="5" rx="1" /><rect x="3" y="16" width="6" height="5" rx="1" /><rect x="15" y="16" width="6" height="5" rx="1" /><path d="M12 8v4M6 16v-2h12v2" /></>),
  changes: svg(<><path d="M7 4v16M7 20l-3-3M7 20l3-3" /><path d="M17 20V4M17 4l-3 3M17 4l3 3" /></>),
  bell: svg(<><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0" /></>),
  cleanup: svg(<><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></>),
  onboarding: svg(<><circle cx="9" cy="8" r="4" /><path d="M2 21a7 7 0 0 1 14 0M19 8v6M16 11h6" /></>),
  automation: svg(<path d="M13 2L4 14h7l-1 8 9-12h-7z" />),
  customers: svg(<><circle cx="9" cy="8" r="4" /><path d="M2 21a7 7 0 0 1 14 0M16 3.1a4 4 0 0 1 0 7.8M22 21a7 7 0 0 0-4-6.3" /></>),
  building: svg(<><rect x="4" y="3" width="16" height="18" rx="1.5" /><path d="M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01M10 21v-3h4v3" /></>),
  settings: svg(<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>),
};

/**
 * Daily work first and always visible; everything else in folded groups (the group with the current page opens by
 * itself, and "Find a page" searches all of them). Every page keeps its URL.
 */
export const NAV_GROUPS: { label: string; items: NavItem[]; folded?: boolean }[] = [
  { label: "Daily work", items: [
    { to: "/", label: "Dashboard", icon: I.home }, { to: "/assets", label: "Devices", icon: I.devices },
    { to: "/device-health", label: "Device health", icon: I.health }, { to: "/reports", label: "Reports", icon: I.reports },
  ] },
  { label: "Changes in VSA X", items: [
    { to: "/custom-fields", label: "Custom fields", icon: I.fields }, { to: "/group-moves", label: "Group moves", icon: I.move },
  ] },
  { label: "Patching & software", folded: true, items: [
    { to: "/windows-updates", label: "Windows updates", icon: I.updates }, { to: "/software", label: "Software", icon: I.software },
    { to: "/patch-policies", label: "Patch policies", icon: I.policy }, { to: "/servers", label: "Servers & owners", icon: I.server },
    { to: "/lifecycle", label: "Lifecycle", icon: I.lifecycle }, { to: "/compliance", label: "Compliance", icon: I.compliance },
  ] },
  { label: "Inventory & network", folded: true, items: [
    { to: "/groups", label: "Groups & network", icon: I.network }, { to: "/changes", label: "Inventory changes", icon: I.changes },
    { to: "/notifications", label: "Notifications", icon: I.bell }, { to: "/cleanup", label: "Cleanup", icon: I.cleanup },
    { to: "/onboarding", label: "Onboarding check", icon: I.onboarding }, { to: "/automation", label: "Automation", icon: I.automation },
  ] },
  { label: "Administration", folded: true, items: [
    { to: "/all-customers", label: "All customers", icon: I.building }, { to: "/customers", label: "Customers", icon: I.customers },
    { to: "/admin", label: "Settings", icon: I.settings, adminOnly: true },
  ] },
];
export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

export const isHere = (item: { to: string }, pathname: string) =>
  item.to === "/" ? pathname === "/" : pathname === item.to || pathname.startsWith(`${item.to}/`);

/** The navigation section of a path ("Patching & software"), shown above each page title. */
export function sectionFor(pathname: string): string | undefined {
  return NAV_GROUPS.find((group) => group.items.some((item) => isHere(item, pathname)))?.label;
}
