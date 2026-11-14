# LIST-02 fixture evidence

Baseline application: `2cc5998`. Before screenshots reuse the retained LIST-01 final captures from the same baseline, not a recreated mockup. After screenshots use the final LIST-02 source on a fresh synthetic PostgreSQL database; labels identify fixture origin. No real customer data or credential is included.

| Workspace | Before desktop / phone | After desktop / phone |
|---|---|---|
| Software overview | [1440](before/software-1440.png) / [390](before/software-390.png) | [1440](after/software-1440.png) / [390](after/software-390.png) |
| Software installations | Previously below overview in the same page | [1440](after/software-installations-1440.png) / [390](after/software-installations-390.png) |
| Windows update records | [1440](before/windows-updates-1440.png) / [390](before/windows-updates-390.png) | [1440](after/windows-updates-1440.png) / [390](after/windows-updates-390.png) |
| Device collection coverage | Previously selected by a status chip; capped request | [1440](after/update-coverage-1440.png) / [390](after/update-coverage-390.png) |

Eight final captures: no JavaScript errors or document-width overflow; see [observations](after/observations.json) and [visual output](logs/visual.txt). Tables/tabs scroll within their containers on phones. Representative desktop software/installation and phone coverage/record screens were inspected.

Actual terminal evidence:

- [Backend full](logs/backend-full.txt): 614 passed; [final affected feature run](logs/backend-feature-final.txt): 11 passed after the late device-type restoration.
- [Backend lint/schema/migration gates](logs/backend-gates.txt): passed; 180 files formatted, no model changes.
- [Frontend tests](logs/frontend-tests.txt): 89 passed; [type/lint gates](logs/frontend-gates.txt) and [production build](logs/build.txt): passed.
- [Final full browser run](logs/browser-final.txt): 43 passed on final source. [New targeted workflows](logs/browser-targeted.txt): 3 passed.
- Corrected failures retained: [initial backend](logs/backend-initial-failures.txt), [test harness recheck](logs/backend-test-harness-recheck.txt), [initial targeted browser](logs/browser-initial-targeted.txt), [first full browser](logs/browser-first-run.txt) (42 passed/1 failed, device type regression fixed).

Commands, assumptions, changed files, interpretation, rollback and outstanding production/live gates: [INTELLIGENCE_LISTS.md](../../INTELLIGENCE_LISTS.md). Full path list: [changed-files.txt](changed-files.txt). SHA256 artifact inventory: [manifest.sha256](manifest.sha256). No CI, live API or deployment validation is claimed.
