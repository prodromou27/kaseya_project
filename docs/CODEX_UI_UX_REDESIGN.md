# UI/UX redesign plan

Use existing React 19, Tailwind 4, TanStack Query/Table and accessible native controls. No new UI framework, font download, telemetry, or decorative image assets.

## Workflow architecture

Persistent navigation groups: Overview (Dashboard); VSA operations (Devices, Groups & network, Device health, Notifications, Inventory changes); Software & patching (Software, Windows updates, Patch policies, Lifecycle); Inventory reconciliation (Onboarding check); Reporting (Reports); Administration (Customers, super-admin Settings). All links resolve to implemented screens. Search filters navigation locally and can open device search scoped by the existing customer selector. No cross-customer search is implied.

Keep the authorized customer selector in the top bar and a compact scope strip above content. Breadcrumbs identify the current workflow and detail context. Mobile navigation must close after selection and on Escape, with no page-level horizontal overflow. Tables and tabs scroll in their own containers.

## Shared visual language

Neutral slate surfaces, white cards, blue action accent; green for evidenced positive observations, amber for attention/unknown/stale, red for failure. Use system fonts, 4px spacing rhythm, 6–10px radii, subtle borders, consistent 32–36px controls and 36px table rows. Keep focus rings and reduced-motion support. Do not encode status by color alone. Defer dark mode until all page surfaces can be validated together.

## Investigation paths

- Dashboard: current customer population, exact attention drilldowns, source freshness/errors; historical trend is clearly separate.
- Devices: search/filter toolbar, clear active filters, stable URL/page, column chooser, export of the same filtered population, saved views.
- Detail: compact identity/context header; grouped operational overview; retained software/patch/network/history capabilities; scrollable accessible tabs.
- Reconciliation: upload → map/preview → compare → review/export, with explicit snapshot and stale-data acknowledgement.
- Reports: preserve protected async jobs; show format and filter context, never silently export another population.

## Browser review protocol

Use only synthetic seeded data. Capture baseline and after views for dashboard, devices/detail, software, Windows updates, onboarding, groups, reports, settings at 1440px and 390px. Review actual images; assert navigation, filters, page retention, keyboard tab behavior, mobile menu and no body overflow. Screenshot output must contain no real credentials/customer data. Log exact commands/results in IMPLEMENTATION_EVIDENCE.md.
