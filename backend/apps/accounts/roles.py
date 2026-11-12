"""Role and capability definitions — the single source of truth for RBAC.

Roles are seeded into the ``accounts_role`` table by migration so memberships can reference them, but the
capabilities each role grants are defined here in code and are not editable at runtime.
"""

from __future__ import annotations

from typing import Final


class Cap:
    CUSTOMER_READ: Final = "customer.read"
    CUSTOMER_EXPORT: Final = "customer.export"
    CUSTOMER_SYNC: Final = "customer.sync"
    CUSTOMER_AUDIT_READ: Final = "customer.audit.read"
    CUSTOMER_MANAGE_MEMBERS: Final = "customer.manage_members"
    CUSTOMER_PROPOSE_MAPPINGS: Final = "customer.propose_mappings"
    CUSTOMER_MANAGE_EXCEPTIONS: Final = "customer.manage_exceptions"
    # Global-only capabilities (never granted by a customer membership):
    SYSTEM_MANAGE: Final = "system.manage"  # customers, users, integrations, mapping approval
    SYSTEM_CROSS_CUSTOMER: Final = "system.cross_customer"  # multi-customer analysis
    SYSTEM_AUDIT_READ: Final = "system.audit.read"


SUPER_ADMIN: Final = "super_admin"
ADMIN: Final = "admin"
ENGINEER: Final = "engineer"
VIEWER: Final = "viewer"

ROLE_DEFINITIONS: Final[dict[str, dict[str, object]]] = {
    SUPER_ADMIN: {
        "name": "Super administrator",
        "description": "All customers and system administration. Global role only.",
        "is_global": True,
        "capabilities": frozenset(
            {
                Cap.CUSTOMER_READ,
                Cap.CUSTOMER_EXPORT,
                Cap.CUSTOMER_SYNC,
                Cap.CUSTOMER_AUDIT_READ,
                Cap.CUSTOMER_MANAGE_MEMBERS,
                Cap.CUSTOMER_PROPOSE_MAPPINGS,
                Cap.CUSTOMER_MANAGE_EXCEPTIONS,
                Cap.SYSTEM_MANAGE,
                Cap.SYSTEM_CROSS_CUSTOMER,
                Cap.SYSTEM_AUDIT_READ,
            }
        ),
    },
    ADMIN: {
        "name": "Customer administrator",
        "description": "Delegated administration of an assigned customer: members, mapping proposals, audit.",
        "is_global": False,
        "capabilities": frozenset(
            {
                Cap.CUSTOMER_READ,
                Cap.CUSTOMER_EXPORT,
                Cap.CUSTOMER_SYNC,
                Cap.CUSTOMER_AUDIT_READ,
                Cap.CUSTOMER_MANAGE_MEMBERS,
                Cap.CUSTOMER_PROPOSE_MAPPINGS,
                Cap.CUSTOMER_MANAGE_EXCEPTIONS,
            }
        ),
    },
    ENGINEER: {
        "name": "Engineer",
        "description": "Read, report and start read-only syncs for an assigned customer.",
        "is_global": False,
        "capabilities": frozenset({Cap.CUSTOMER_READ, Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_SYNC}),
    },
    VIEWER: {
        "name": "Viewer",
        "description": "Read an assigned customer. Export only when explicitly granted on the membership.",
        "is_global": False,
        "capabilities": frozenset({Cap.CUSTOMER_READ}),
    },
}

MEMBERSHIP_ROLES: Final = (ADMIN, ENGINEER, VIEWER)
GLOBAL_ROLES: Final = (SUPER_ADMIN,)
# Roles a non-super-admin (customer administrator) may grant on their own customer.
DELEGABLE_ROLES: Final = (ENGINEER, VIEWER)


def capabilities_for_role(role_key: str | None) -> frozenset[str]:
    if not role_key or role_key not in ROLE_DEFINITIONS:
        return frozenset()
    return ROLE_DEFINITIONS[role_key]["capabilities"]  # type: ignore[return-value]
