# Security review evidence and remaining gates

Date: 2026-11-14. Scope: VSA Phase 1 remediation in this repository. Test data is synthetic. No live credential or deployed service was probed.

## Verified development controls

- Full PostgreSQL suite: **585 passed**, including the automatic customer-route IDOR/read-only-role sweep and existing session, CSRF, SSRF, safe-upload, immutable snapshot, artifact authorization, formula injection, scheduling and authorization-revocation regressions.
- New export tests reject cross-customer selected IDs; ordinary filtering never widens an authorized queryset. IP/MAC/source-ID search now uses the same implementation for lists and reports.
- New proposal API authorizes the customer before validation. Target groups must belong to the same current customer/source/organization. Separate capabilities protect proposing and reviewing; self-review remains forbidden even in single-admin mode.
- Database triggers prevent proposal-content changes, customer/source mismatches and alteration of final decisions. Decisions have audit records. Expired or changed-snapshot proposals cannot be approved.
- Vendor execution is absent, not merely hidden in the browser. There is no execute route, vendor write request or new write credential. Portal approval does not move a device.
- Multi-instance hierarchy IDs are qualified by source. An ambiguous group ID cannot silently merge sources; legacy subnet expectations with colliding source IDs are not applied.
- Existing connector HTTPS/GET allowlists, TLS verification, redirect blocking, bounded retries and Retry-After handling remain in place. Existing connector tests were rerun; no new live API validation occurred.
- `npm.cmd audit --json`: **0 vulnerabilities**, including development tooling.
- `uvx --offline --python 3.12 pip-audit --strict --disable-pip -r backend/requirements.lock`: exit 0, **No known vulnerabilities found**. `--offline` applies to cached tool resolution; the audit queried advisories.
- `uvx --offline bandit -q -r backend/apps backend/config -ll`: exit 0, no medium/high findings.

Scanners and regression tests do not establish that no vulnerabilities exist. No new independently confirmed security finding is claimed by this report. The source-group collision fixed here is a data correctness defect within an authorized customer scope.

- `uvx --offline --from shellcheck-py shellcheck -S warning ...`: exit 0 for install, preflight/secrets, backup and restore scripts.
- Production-mode `manage.py check --deploy --fail-level ERROR` with dummy configuration: exit 0; existing security.W008 remains because HTTPS redirect is delegated to the proxy. The deployed redirect/TLS behavior still needs host validation.

## Independent audit status: incomplete

The [security-audit skill](C:/Users/cprodromou/.agents/skills/security-audit/SKILL.md) requires:

> If every control cannot be enforced, do not execute target code: report the missing sandbox capability as a needs-validation blocker and give a safe validation plan.

Its full attack-reproduction workflow requires OS-enforced network/environment/resource isolation, a read-only target/toolchain with restricted scratch writes, a separate retained output directory, coverage ledger and independent source verifiers. That environment was not established in this Windows session. The ordinary development/browser tests above are functional QA, not evidence of satisfying that independent audit workflow. No prior compatible coverage ledger was supplied. Status: **incomplete**; reason: `isolated_security_execution_environment_unavailable`.

Safe next step: run the independent source-first audit in an approved isolated environment using dummy tenants and retained, independently verified evidence. Do not probe production to compensate for missing isolation.

## External acceptance gates

- Real Entra issuer/audience/MFA enforcement, bootstrap-account policy and session/cookie behavior behind the deployed proxy.
- Approved secrets vault/key custody, rotation, egress and DNS policy on the actual host.
- Docker/AlmaLinux service health, non-root filesystem permissions and deployment headers.
- Encrypted off-host backup and owner-observed restore with approved RPO/RTO.
- Representative concurrent workload, actual software/network volumes and real tenant field/pagination accuracy.
- Formal data handling, independent security review and pilot sign-off.

No production-readiness or successful CI claim is made by this run.
