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

## P5-07 focused review - 2026-11-16 (features added since the first review)

Scope: VSA5-EXEC group-move execution (`apps/integrations/vsa/writer.py`, `apps/inventory/move_execution.py`,
`move_views.py`, integration credential fields), SRV-01 servers and owner groups (`apps/servers`), SCR-01 script
collectors, AUT-01 automation, CF-02 scope custom fields, GR-01 rules/scopes, alerts, cleanup, all-customers overview
and the `bad_response` diagnostics. Source review plus local tests and scanners; synthetic data only, nothing deployed
was probed. **Superseded statement:** "vendor execution is absent" above no longer holds - ADR-029 adds one gated write.

**Finding 1 (fixed) - credential references could name the server's own secrets.** Lower-trust principal: a portal
super administrator (not a host operator). `credential_ref` and `write_credential_ref` were declared as plain serializer
fields, so the model's format validator never ran, and `resolve_secret` accepted any `env:NAME`. Setting
`credential_ref = env:DJANGO_SECRET_KEY` (or `POSTGRES_PASSWORD`, `CONNECTOR_ENCRYPTION_KEY`) made the connector send
that host secret as Basic-auth credentials to the configured (allowlisted) VSA host. Severity **low**: super-admin only
and limited to allowlisted hosts, but it crosses from portal administration into host secrets. Fix: the API accepts only
`env:VSA_|ITGLUE_|AUTOTASK_<NAME>` (or a not-yet-resolvable `vault:` reference) for read
tokens (never `VSA_WRITE_*`) and `env:VSA_WRITE_<NAME>` for the write token,
and `resolve_secret` refuses any other name, so a reference stored earlier is refused at use as well. Regression test:
`test_credential_references_cannot_name_server_secrets`. Operator impact: a server reference not starting with `VSA_`
must be renamed (portal-entered credentials are unaffected).

**Finding 2 (fixed, tooling) - semgrep blocker.** `move_execution.execute(...)` matched the Django raw-SQL rule
(`sql-injection-db-cursor-execute`); no SQL is involved, but the CI job runs semgrep with `--error`. Renamed to
`execute_move`.

**Reviewed, no finding:**
- Tenant isolation: every new customer route is covered by the resolver-driven sweep (`tests/test_idor_sweep.py`:
  other customers get 404, viewers cannot write). Owner groups, designations, script values, scope fields and
  executions are filtered by customer; designations reject foreign devices/groups; report filters validate the owner
  group against the report's customer; pinned generations are customer-constrained.
- Group-move execution: two server-side switches plus a separate `env:VSA_WRITE_*` token; requester cannot execute;
  approval age, unchanged source group, active destination in the same customer organisation and fresh inventory are
  re-checked under a row lock; one attempt per proposal (one-to-one, committed before sending); no retries; fixed
  path regex and integer group id; shared egress policy; base-URL change clears the switch; all steps audited.
- Secrets/logging: write reference write-only in responses; `vendor_bad_response` logs endpoint templates with
  identifiers masked, never bodies; owner contact details are not copied into audit metadata; script collectors keep
  only allowlisted variables and refuse credential-like names; scope criteria drop custom-field values.
- Frontend: no `dangerouslySetInnerHTML`; the owner email link is a fixed `mailto:` with `encodeURIComponent`
  parts and a validated email; alert links are router paths; exports neutralise formula cells.
- Residual (needs validation on a live tenant): workflow `failed_step` keeps the first failed step's Outcome text (max
  300 chars); if a customer's VSA scripts print secrets into step outcomes, that text would be stored. Review a
  sample after the first live collection.

**Scans (local, 2026-11-16):** `pip-audit --strict` on `requirements.lock`: no known vulnerabilities. `bandit -ll`:
exit 0, no medium/high. `npm audit` (production and all deps): 0 vulnerabilities. `semgrep` with the CI rule packs
(p/django, p/python, p/secrets, p/typescript, p/react; `--metrics=off --error`): exit 0 after Finding 2. Secret scan:
gitleaks/Docker not available on this workstation; a pattern scan of the full git history (cloud keys, private-key
blocks, chat/GitHub/API tokens, `*PASSWORD|SECRET|TOKEN=` assignments) found only the documented dev placeholders.
The gitleaks job in `.github/workflows/security.yml` remains the authoritative secret scan.

Scanners and tests do not prove absence of vulnerabilities; the independent audit below is still required.

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
