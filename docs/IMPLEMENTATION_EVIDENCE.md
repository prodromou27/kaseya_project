# Implementation evidence log

**Initial state:** No implementation or tests have been performed in this documentation-only package.

| Task ID | Commit | Implemented artifacts | Test command/result | Fixture or live | Gaps / next action |
|---|---|---|---|---|---|
| VSA0-01/03/04/05 | `d799241`, `66c440f` | Django/React monorepo, auth/RBAC/OIDC (mock), mappings, audit | `pytest` 146 passed (P0); clean clone OK; see PHASE_ACCEPTANCE_P0.md | fixture | CI never executed; Compose never booted |
| VSA1-03, VSA3-01/02 | `23550d1` | sync engine, catalog, comparator, software views | `pytest` 276 passed; Playwright 10/10 | fixture | live pilot |
| VSA3-03/05 | `c483a8f` | OS updates, reports (CSV/XLSX/PDF), schedules, history | `pytest` 324 passed; Vitest 34; Playwright 16/16 | fixture | live pilot; mail delivery BLOCKED_APPROVAL |
| VSA1-02/04/06, VSA2-05 (partial), VSA3-07 | `ea26682` | sites/groups/devices adapter; NIC/IP/disk/security observations; hierarchy + group network APIs/UI; MAC/IP search; explicit third-party UNAVAILABLE | `uv run python -m pytest -q` → **358 passed** (2026-11-13); `npx vitest --run` → **37 passed**; Playwright full run 18/19 then the one failing test was fixed (it had selected the wrong site's group) and `vsa1.spec.ts` rerun 3/3; ruff, tsc, eslint, `manage.py check`, schema `--fail-on-warn` clean | fixture (documented examples + synthetic demo) | LIVE_VALIDATION_PENDING for every route; expected-subnet thresholds; Docker/CI |

Update only after actual code and tests. Never mark a task complete on written design alone.
