# CIDR-02 - network-first onboarding suggestions

The previous implementation only displayed hints inside Device Operations and required approved destination CIDRs. That left the onboarding group without a suggestion list and produced no hints before subnet configuration. CIDR-02 adds a group-level investigation and additional explicitly weaker evidence. Baseline: `573e096`. Implementation: `32a8407`.

## End-user path

Open Groups & network, open the source-qualified generic installation group and enable **Use as an onboarding group** if needed. **Suggested destinations for onboarding devices** lists every device in that group, including devices without matches. Search by hostname and use the full bounded pager. Clicking a device opens Operations, where a suggested destination can fill the existing proposal form. Administrators still transfer agents manually in VSA; no vendor operation is implemented.

Destination suggestions are ordered by strongest evidence:

1. **Approved subnet:** a reported relevant device address belongs to an administrator-approved, source-qualified group CIDR. Administrators can add more destination CIDRs through the existing Propose subnet/review controls.
2. **Observed subnet:** an address belongs to a valid subnet derived from addresses/masks on devices already in the destination group, in the same current snapshot. The UI shows the CIDR and number of supporting destination devices, and states that this is not reviewed placement policy. Missing masks do not produce guessed /24s or IPv6 prefixes.
3. **Naming only:** a meaningful first hostname token matches a group-name token or the naming prefix of an existing destination device. This evidence cannot outrank a network match. It is advisory and never resolves customer/source identity.

Naming matching is deliberately explicit: case-insensitive first tokens split by hyphen, underscore, dot or whitespace; trailing device numbers are removed. Tokens must contain at least three letters; generic prefixes such as DESKTOP, SERVER, WINDOWS and COMPUTER are ignored. NIC-WS001 can match NIC Office or NIC-WS999; arbitrary abbreviations, fuzzy substrings and opaque naming schemes are not inferred.

Every match explains its basis and shows site/stable group ID, so identical display names remain distinguishable. Several destinations remain visibly ambiguous even when ranked; nothing is selected automatically. VPNs, multiple adapters, reused subnets and inconsistent device placement can mislead. A device with no evidence stays unclassified, rather than being declared incorrectly placed. Reported device data is not changed.

## Scope, API and compatibility

New read endpoint: GET /api/v1/customers/{customer}/groups/{group}/suggestions/?instance={source UUID}. It requires customer read access and a current mapped source/group. Results contain asset identity, hostname and ranked candidates; search is bounded to 100 characters and standard server paging is capped at 200. Standard groups return an empty disabled population; the UI displays this investigation only for explicitly marked onboarding groups.

Destinations are restricted to active groups in the same customer, VSA instance, snapshot and organization. The source group and all marked onboarding groups are excluded. Stale evidence requires synchronization; revoked mappings and foreign objects fail closed. Existing approved subnet semantics remain unchanged: proposed/rejected/retired/legacy-unqualified rules cannot become approved evidence. Observed peer evidence is independent and labelled. Invalid networks, /0, loopback/link-local/multicast networks and irrelevant/malformed addresses cannot produce network matches.

The group endpoint loads destination evidence once per page and batch-loads device addresses, avoiding per-device database queries. Existing Device Operations uses the same engine. Subnet changes invalidate suggestion caches. No schema migration, credential, vendor endpoint/field, vendor write or remote telemetry was added. Source data uses the existing normalized fixture-tested network fields; no new live verification is claimed.

## Validation and failures

Actual terminal outputs, screenshots and final acceptance counts are retained under evidence/cidr-02. Checks cover approved/observed/naming priority, missing/invalid evidence, IPv6, generic names, source/customer/organization boundaries, inactive/onboarding destinations, stale/revoked mapping, page/search recovery and constant page query count. UI checks cover evidence labels, weaker naming, no-match rows, paging/search, API failure and manual-only selection. The browser workflow checks the real group-level approved-CIDR evidence and the unchanged source membership, plus phone-width overflow.

- Full PostgreSQL suite: **624 passed in 354.12s**. After the final additive site/ID disambiguation, all **22 affected backend cases passed in 20.62s**.
- Full frontend suite: **94 passed**, 22 files; TypeScript, ESLint and production build passed.
- Ruff/format: passed, 181 files; Django checks: no issues; migration drift: no changes; OpenAPI validation with --fail-on-warn: passed.
- Final full browser suite: **43 passed (3.6 minutes)** on a fresh fixture database. Settled desktop/phone capture at 1440px/390px: one filtered row, no JavaScript errors or page overflow; both inspected. The capture waits for the filtered row count after debounce rather than accepting the previously displayed population. [Screenshots and terminal evidence](evidence/cidr-02/README.md).

Initial legacy tests failed because they expected no hints without an approved rule and an exact old response shape. They now assert that independently observed evidence is labelled and that unreviewed rules never become approved evidence. A new pagination fixture assertion assumed two devices; the fixture contains three and the assertion was corrected. TypeScript caught a test-only unsupported exact option and browser DOM references in the Node configuration; both were corrected before final gates.

The first full browser run had 41 passes and two failures: a software-return scenario timed out at Checking your session during a reported 11.4-hour gap, and the onboarding scenario found two identically named destination buttons. Site/group IDs now disambiguate the suggestions, with a dedicated UI regression proving selection by identity. The unrelated software workflow is included unchanged in the final fresh-database rerun; no timeout was relaxed.

Commands (backend): .venv/Scripts/ruff.exe check ., ruff.exe format --check ., manage.py check, manage.py makemigrations --check --dry-run, manage.py spectacular --file openapi.yaml --validate --fail-on-warn, .venv/Scripts/python.exe -m pytest -q --basetemp=var/codex-audit/pytest-cidr2-full --tb=line. Focused run: tests/test_group_suggestions.py tests/test_group_suggestions_ranked.py tests/test_group_moves.py.

Commands (frontend): npm.cmd run typecheck, npm.cmd run lint, npm.cmd run test -- --run --maxWorkers=2, npm.cmd run build, npx.cmd playwright test --output=../backend/var/codex-audit/cidr2-final-browser-traces. The local QA API uses a fresh synthetic PostgreSQL database, eager Celery, POSTGRES_CONN_MAX_AGE=0 and LOGIN_THROTTLE_RATE=1000/min; production defaults are unchanged. Browser credentials are synthetic only. No CI/deployment/live customer validation is claimed.

## Rollout and remaining work

Deploy backend/frontend together through the reviewed deployment process. No migration/backfill is needed. Rollback restores prior application images while retaining settings, subnet rules, snapshots and proposals; the prior approved-CIDR-only device workflow remains compatible. Existing report schemas are unchanged. No production deployment is performed here.

Next product work remains LIST-03 guided reconciliation. Historical P0-02/VSA0-02 Docker acceptance and approved production/SSO/MFA/secrets/restore/load/security/live-pilot gates remain open.
