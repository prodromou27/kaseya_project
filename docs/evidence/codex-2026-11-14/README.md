# Fixture UI and validation evidence

All records, identifiers and accounts shown here are fictional seeded fixtures. No real credentials or customer datasets are included. Baseline frontend: `595d3e3`. Final screenshots are from the verified implementation worktree; use the delivery commits and CODEX_VERIFICATION.md for source history.

The baseline captured 30 screens. Four representative baseline images and its full observations are retained here. Final capture covers **17 pages at 1440px and 390px = 34 screens**, with **zero JavaScript errors and zero page-level horizontal overflows**. Long tables now scroll inside a focusable region with sticky headers; their full DOM remains accessible.

| Comparison | Baseline | After |
|---|---|---|
| Dashboard | [Desktop](baseline/dashboard-1440.png) | [Desktop](after/dashboard-1440.png) |
| Inventory | [Desktop](baseline/devices-1440.png) | [Desktop](after/devices-1440.png) |
| Device detail | [Phone: 812px overflow](baseline/device-detail-390.png) | [Phone: fits 390px](after/device-detail-390.png) |
| Settings | [Phone: 675px overflow](baseline/settings-390.png) | [Phone: fits 390px](after/settings-390.png) |

| Final view | Desktop | Phone |
|---|---|---|
| Dashboard | [1440px](after/dashboard-1440.png) | [390px](after/dashboard-390.png) |
| Devices | [1440px](after/devices-1440.png) | [390px](after/devices-390.png) |
| Device investigation | [1440px](after/device-detail-1440.png) | [390px](after/device-detail-390.png) |
| Software | [1440px](after/software-1440.png) | [390px](after/software-390.png) |
| Windows updates | [1440px](after/windows-updates-1440.png) | [390px](after/windows-updates-390.png) |
| Excel reconciliation | [1440px](after/onboarding-1440.png) | [390px](after/onboarding-390.png) |
| Organization hierarchy | [1440px](after/groups-1440.png) | [390px](after/groups-390.png) |
| Group network and export | [1440px](after/group-network-1440.png) | [390px](after/group-network-390.png) |
| Reports | [1440px](after/reports-1440.png) | [390px](after/reports-390.png) |
| Settings | [1440px](after/settings-1440.png) | [390px](after/settings-390.png) |
| Device health | [1440px](after/health-1440.png) | [390px](after/health-390.png) |
| Inventory changes | [1440px](after/changes-1440.png) | [390px](after/changes-390.png) |
| Notifications | [1440px](after/notifications-1440.png) | [390px](after/notifications-390.png) |
| Patch policies | [1440px](after/policies-1440.png) | [390px](after/policies-390.png) |
| Lifecycle | [1440px](after/lifecycle-1440.png) | [390px](after/lifecycle-390.png) |
| Customers | [1440px](after/customers-1440.png) | [390px](after/customers-390.png) |
| Internal group approvals | [1440px](after/group-moves-1440.png) | [390px](after/group-moves-390.png) |

Machine-readable [final observations](after/observations.json), [baseline observations](baseline/observations.json) and [verification metadata](verification.json) accompany the images. Successful terminal summaries and scans are in [logs](logs/). Full final backend: [585 passed](logs/backend-complete.txt); frontend: [74 passed](logs/frontend-verified.txt); full browser run: [36 passed](logs/playwright-release.txt); added network download: [passed](logs/playwright-network-report.txt).

Visual inspection covered representative dashboard, inventory/detail, software, updates, reconciliation, hierarchy/network, reports, settings and approval screens. Automated browser tests additionally exercised filters, return navigation, keyboard/mobile navigation, comparison/export, schedules, source grouping and independent review. Screenshots alone are not functional proof or live-tenant validation.
