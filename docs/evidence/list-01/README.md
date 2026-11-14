# LIST-01 - fixture UI evidence

Baseline: ddaefa1. Every customer/device/account shown here is fictional seeded fixture data. No live customer data or credential is retained. After captures cover 17 app pages at 1440px and 390px (34 screens): zero JavaScript errors and zero page-level horizontal overflow. Tables retain their own focusable scroll region on narrow screens. Screenshots are visual evidence; functional checks are separately recorded in LIST_USABILITY.md.

| View | Before | After |
|---|---|---|
| Devices, desktop | [Before](before/devices-1440.png) | [After](after/devices-1440.png) |
| Devices, phone | [Before](before/devices-390.png) | [After](after/devices-390.png) |
| Groups, desktop | [Before](before/groups-1440.png) | [After](after/groups-1440.png) |
| Groups, phone | [Before](before/groups-390.png) | [After](after/groups-390.png) |

Full [after observations](after/observations.json) and [baseline observations](before/observations.json) are retained. Baseline observations also describe four software/update captures that are not copied here. The [after directory](after/) contains the additional dashboard, detail, software, update, reconciliation, reports, settings, health, changes, notifications, policy, approvals, lifecycle, customer and network screenshots.

Actual output: [603 backend tests](logs/backend.txt), [85 frontend tests](logs/frontend.txt), [production build](logs/build.txt), [migration preservation](logs/migration.txt), [corrected browser paths](logs/browser-keyboard.txt). The [full 40-test browser run passed](logs/browser.txt). [Mobile page recovery](logs/page-recovery.txt) is also retained. Source changes and intermediate failures are explained in [the delivery guide](../../LIST_USABILITY.md).
