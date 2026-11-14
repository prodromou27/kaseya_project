# Deployment and rollback — Codex remediation

No production deployment was performed. No production data, environment file, secret or vendor credential was accessed or changed. All execution evidence uses local synthetic fixtures.

## Affected services and changes

- Frontend: new workflow navigation, scoped search, responsive tabs/forms, persistent investigation filters, selected-device exports, approval UI and route chunks.
- API: shared inventory filters, current summary consumers, source-qualified hierarchy, compact health aggregation, internal proposal/review endpoints, updated OpenAPI schema.
- Worker/report process: same shared inventory filters and pinned relative-time cutoff; redeploy the backend image for workers as well as the API. Celery queues and vendor collection routes are unchanged.
- PostgreSQL: additive `inventory.0009_group_move_proposals` and `inventory.0010_guard_group_moves`. New proposal table, indexes, constraints and immutable-record/customer-consistency trigger. No existing data migration or destructive alteration.
- Roles: engineers may propose internal group changes; customer administrators and super administrators may independently review them. No role can execute a vendor move. Self-review is always refused for this workflow, regardless of the legacy single-admin catalog setting.

## Before an approved rollout

1. Review the implementation commits and CODEX_VERIFICATION.md. Use an isolated staging environment first.
2. Take and verify the approved encrypted PostgreSQL backup and configuration/key recovery path. Keep report storage and encryption keys recoverable under the existing runbook.
3. Confirm owner approval for data handling, real SSO/MFA, TLS, secrets management and the read-only pilot. Verify the separate independent security and host/container gates. Do not use the benchmark command on an application database.
4. Build the existing backend and frontend images from the reviewed revision. Apply migrations through the existing deployment process before exposing the new proposal screens. Restart API, worker and beat against the same backend revision; publish matching frontend assets atomically.
5. Keep vendor credentials read-only. This implementation has no vendor execute action, write credential or vendor write call. An approved portal proposal is not permission to enable execution.

## Validation after rollout

- Django system/migration checks and container/proxy health checks pass.
- Authorized customer selection and foreign-customer denial work through the deployed proxy.
- A complete sync preserves the last-good dataset during failures; data-source freshness/error states remain visible.
- Device search/filter/export return the same population; test CSV/XLSX/PDF download and expired/revoked access.
- Group links include the VSA instance; ambiguous unqualified IDs fail rather than merge sources.
- Health totals reconcile with detailed classifications; measure representative inventory sizes on the actual host.
- An internal proposal can be independently reviewed and audited; self-approval, expired approval and execution are refused.
- Desktop/mobile navigation and lazy route loading work behind the production proxy. Deployments should retain prior immutable static chunks while old browser sessions transition.

## Rollback

Preferred rollback: restore the previous application images/frontend release while retaining the additive proposal schema and records. Existing tables remain compatible, and preserving the new records avoids deleting the audit history. No vendor movement occurred, so no vendor state requires reversal.

If schema removal is explicitly approved, first archive proposal and audit records and verify the backup. The migration reverse drops the trigger then the new table; it deletes proposal records. Do not run it against a populated production database as a routine rollback.

Actual disposable-database proof: migrated inventory from `0010` back to `0008` and forward to `0010`; both directions passed. All **100,000 synthetic assets were retained**, and the newly recreated proposal table contained zero rows. This is migration proof on PostgreSQL 16.2, not a production restore drill or AlmaLinux/Compose deployment proof.
