# CIDR-01 - onboarding groups and destination suggestions

A generic workstation/server installation may intentionally enter a temporary onboarding group. Administrators transfer agents manually later. This slice records that purpose explicitly and suggests destinations from approved subnet evidence; it never calls a vendor write endpoint.

## Working path and acceptance

1. An authorized administrator opens a source-qualified group in Groups & network and enables **Use as an onboarding group**. Purpose is stored against customer, VSA instance and stable group external ID, so it survives snapshot replacement. It is not inferred from the display name.
2. On an eventual destination group, the administrator proposes one or more strict IPv4/IPv6 CIDRs with a reason. The existing separate-reviewer policy governs approval; only approved group-scoped source-qualified rules drive suggestions. /0 and host-bit CIDRs are rejected. Site expectations still support network review, but do not nominate groups.
3. Device Operations compares reported relevant addresses against active destinations in the same customer, current source snapshot and organization. Each candidate explains the matched IP/CIDR. Onboarding groups are excluded as suggested final destinations. Multiple matching groups are explicitly ambiguous, with no automatic ranking/selection. Unknown/absent evidence produces no placement verdict. VPN/multiple-adapter and shared-subnet caveats remain visible.
4. **Use [group]** fills the target only. Submitting a proposal still requires a reason and independent administrator review. Neither selection nor approval moves the device. Administrators perform any transfer manually in VSA.

Purpose updates require customer.manage_exceptions, validate a current approved source/group and produce an audit event. Other customers, revoked mappings and foreign instances cannot configure groups. New subnet rules infer the source only when exactly one source owns that scope; colliding IDs require explicit source identity. Customer/source is checked server-side, not taken from names.

## Schema, compatibility and rollback

Inventory 0011 adds GroupSetting and nullable ExpectedSubnet.integration_instance; 0012 preserves the old uniqueness rule specifically for unqualified legacy rows. Source-qualified active rules are unique within customer/source/scope/CIDR. Existing rows remain unchanged; no speculative source backfill or data deletion occurs. Legacy rules retain conservative, unambiguous network-review behavior but never generate destination hints; re-propose them with source identity to enable hints.

Both new migrations applied successfully to the local PostgreSQL fixture database. Prefer application rollback while retaining these additive schema changes and administrative records. Reversing 0011 removes the new purpose data/source bindings and restores a broader old uniqueness constraint; it can fail if different sources now have identical scope/CIDR rules. Do not reverse against populated production without a reviewed archive/reconciliation plan and backup. No production migration or restore claim is made.

## Verification - actual local fixture results

- `backend: .venv/Scripts/ruff.exe check .` and `ruff.exe format --check .`: passed, 178 files formatted.
- `manage.py check`: no issues; `makemigrations --check --dry-run`: no changes; `spectacular --file openapi.yaml --validate --fail-on-warn`: passed.
- `.venv/Scripts/python.exe -m pytest -q --basetemp=var/codex-audit/pytest-onboarding-full --tb=line`: **589 passed in 88.05s**. New tests cover onboarding settings, role/customer isolation, approved/retired/legacy rules, absent network evidence, overlapping candidates and duplicate group IDs across sources.
- `frontend: npm.cmd run test -- --run`: **78 passed**, 19 files. New UI tests cover purpose updates, evidence/ambiguity, keyboard selection without submission and API failure.
- `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`: passed. The affected UI suites and build were rerun after the browser-detected checkbox save-state fix.
- `npx.cmd playwright test e2e/onboarding-groups.spec.ts`: **1 passed (8.5s)** against the actual loopback fixture API and frontend. Administrator marked onboarding purpose, proposed a subnet, another administrator approved it, device showed the evidence and selection; source group membership remained unchanged. This is an additional workflow, not a rerun of the previously recorded 36-test browser suite.
- `git diff --check`: required clean before commit/push.

The fixture API used loopback PostgreSQL port 56487, a dedicated test database, eager Celery and local-only LOGIN_THROTTLE_RATE=1000/min. No production defaults were changed. No live credentials or vendor calls were used. No new vendor endpoint, field, pagination or write capability was introduced; existing VSA adapter coverage remains fixture-tested, live validation pending.

Intermediate checks caught a nonexistent test helper import, duplicate frontend type declaration, a test fixture that initially used the wrong group ID, and a DRF action named settings that shadowed framework configuration. All were corrected before the full pass. Browser testing caught checkbox state reverting during an asynchronous save; pending state and the query cache now update immediately, and the workflow passed on rerun. An attempted fixture PostgreSQL start found its existing running instance; it was reused without deleting lock files or data.

Evidence: [backend output](evidence/cidr-01/backend-tests.txt), [browser output](evidence/cidr-01/browser.txt), [device screenshot](evidence/cidr-01/device-suggestions.png). Screenshot was visually inspected. Backend changes: inventory/models.py, network_views.py, hierarchy.py, views.py, move_views.py, group_suggestions.py, migrations 0011/0012, updated OpenAPI, test_group_suggestions.py. Frontend changes: ExpectedSubnets.tsx, GroupNetworkPage.tsx, GroupMovesPage.tsx, types.ts, network-review.test.tsx, group-suggestions.test.tsx, e2e/onboarding-groups.spec.ts. Documentation: this guide, README, TASKS, ROADMAP, CHANGELOG, ADMIN_GUIDE and USER_GUIDE.

Next external task remains P0-02/VSA0-02 (Docker boot), with live field verification, deployment/SSO/restore and independent security gates unchanged. No new complete security audit or production-readiness claim is made.
