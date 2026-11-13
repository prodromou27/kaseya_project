# VSA group hierarchy, network investigation and controlled device movement

## Hierarchy and network group views

Browse `Customer > VSA Instance > Organization > Site > Group > Devices` using stable vendor IDs and approved internal mappings. Show group member counts, OS/agent distribution, stale/offline and patch policy coverage. Preserve exact org/site/group values alongside display names.

Summarize **reported** per-device network adapters: IPv4/IPv6, mask/CIDR, gateway, DNS, DHCP, MAC, interface name, public IP and source time. Handle multi-NIC, multiple addresses and virtual adapters. Derive subnet only for validated IP/netmask; mark unresolvable or conflicting data `UNKNOWN`. Optional reviewed expected subnet policy per site/group supports drift observations.

Report duplicate IPs, MAC reuse, changing IPs, IPs outside expected subnet and missing fields. These are review flags; **do not claim discovered physical LAN topology, switch-port, VLAN or subnet authority from VSA group membership alone**. Site Maps/Advanced Reporting discovered devices may be explored only through supported approved machine interfaces (VSA 10.26+, one site map per report).

### Implementation notes (`ea26682`, `5dbb567`; fixture-tested only)

* The expected-subnet policy is per site or group. A customer admin proposes it and a different admin approves it.
  It uses a strict CIDR with no host bits and no `/0`, and the scope must exist in the customer's snapshot.
* An address counts as outside only when an approved expectation of the **same IP version** covers the group or its
  site. Otherwise it is counted as *not evaluated*. Link-local and loopback addresses are never evaluated.
* Changing IPs (NET-02) are compared with the previous **complete** snapshot of the same VSA instance. Only devices
  whose network section was collected in both snapshots are compared. With several or no current snapshots the check
  is *not evaluated*.
* The review-flag summary lists: duplicate IP, MAC reuse, outside expected subnet, address changed, network not
  collected, and address without a derivable subnet. A flag is raised at any non-zero count, and flags that could not
  be evaluated are labelled as such.
* Device moves remain **disabled** (BLOCKED_APPROVAL). Nothing in this view calls a write endpoint.

## Group move — exception to read-only policy

Documented vendor route: `PUT /api/v3/devices/{deviceId}/move`, JSON `{"GroupId": <integer>}`. This operation is **not active by default**. It requires a written owner/security approval for instance/customer, separate vaulted write-capable token, named identities and explicit portal permissions `vsa.move.propose`, `vsa.move.approve`, `vsa.move.execute`. Do not implement cross-customer transfers or unapproved group creation.

### State machine

`DRAFT → PENDING_APPROVAL → APPROVED → EXECUTING → VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN_OUTCOME`, plus `REJECTED`, `EXPIRED`, `CANCELLED`, `INVALIDATED`.

### One-device procedure

1. Engineer selects device in assigned customer and **proposes** exact target group/reason/change reference.
2. Fetch fresh device, target group, hierarchy and assigned policy information. Preview before/after, inherited-policy change risk and maintenance sensitivity.
3. Store immutable proposal, expected original group, source generation, target group and expiry with tamper-resistant digest.
4. Independent authorized approver reviews exact proposal; no self-approval.
5. Prior to execution re-check permissions, group/customer/instance mapping, proposal expiry, device original group and policy-impact risk. Fail closed on drift.
6. Write one durable execution attempt before calling VSA. Perform one `PUT`, **never auto-retry ambiguous writes**.
7. Read source device from VSA and verify observed GroupId. Success, explicit failure or unknown. A timeout triggers readback; if result still unknown, manual resolution, not another write.
8. Audit actor, source/target group, UTC times, change reference, attempt/correlation ID, vendor status and verification. Trigger safe scoped resync.

A successful move may alter inherited policy. Require an operator confirmation and policy-difference preview. No automatic rollback without new approval; do not make claims of reversible changes where policies changed meanwhile.

### Mandatory controls

- Separate read and write credentials and per-customer feature flags.
- Deny viewer; deny wrong customer or unmapped source org; deny different VSA instance.
- Deny self-approval and execution of rejected/expired proposals.
- Admin-level audit, secrets-redacted source errors and idempotency guard.
- UI must clearly state vendor modification risk.
- Bulk move **deferred**, and auto-move based on Excel findings explicitly prohibited.

## Acceptance tests

Cross-customer request, stale group, changed current group, revoked approver, API 403/429, timeout-after-server-write, multi-NIC, dual-stack, duplicate IP, policy inheritance change, replay/double click, audit redaction. Every failure must produce an explainable state.
