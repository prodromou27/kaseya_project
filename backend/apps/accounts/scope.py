"""Customer scope policy — the single authority for tenant isolation (ARCHITECTURE.md §3, SECURITY.md §2).

Every customer-owned queryset, object lookup, export and background job must go through this module.

Rules:
* Inactive / anonymous users have no access.
* ``super_admin`` (explicit global role) may access every customer, including suspended/archived ones.
* Everyone else gets access only through an *active* membership on a customer whose status is visible to
  members, and only for capabilities granted by that membership's role.
* Membership alone never grants cross-customer analysis; that requires ``Cap.SYSTEM_CROSS_CUSTOMER``.
* Denials surface as 404 (no existence leak) and are audited.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from django.db.models import Model, QuerySet
from rest_framework.exceptions import NotFound

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.customers.models import Customer

_CACHE_ATTR = "_okp_customer_caps"


def _user_ok(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False) and user.is_active)


def membership_capabilities(user: Any) -> dict[uuid.UUID, frozenset[str]]:
    """Map of customer_id -> capabilities from the user's active memberships (cached per user object)."""
    if not _user_ok(user):
        return {}
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    from apps.customers.models import Customer, CustomerMembership

    memberships = CustomerMembership.objects.filter(
        user=user, is_active=True, customer__status__in=Customer.MEMBER_VISIBLE_STATUSES
    ).select_related("role")
    result = {m.customer_id: m.capabilities for m in memberships}
    setattr(user, _CACHE_ATTR, result)
    return result


def invalidate_cache(user: Any) -> None:
    if hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)


def has_global_capability(user: Any, capability: str) -> bool:
    return _user_ok(user) and capability in user.global_capabilities


def capabilities_for_customer(user: Any, customer_id: uuid.UUID) -> frozenset[str]:
    if not _user_ok(user):
        return frozenset()
    caps = set(membership_capabilities(user).get(customer_id, frozenset()))
    caps |= {c for c in user.global_capabilities if c.startswith("customer.")}
    return frozenset(caps)


def has_customer_capability(user: Any, customer_id: uuid.UUID, capability: str) -> bool:
    return capability in capabilities_for_customer(user, customer_id)


def accessible_customer_ids(user: Any, capability: str) -> set[uuid.UUID] | None:
    """Customer IDs on which ``user`` holds ``capability``. ``None`` means *all* (super admin)."""
    if not _user_ok(user):
        return set()
    if capability in user.global_capabilities:
        return None
    return {cid for cid, caps in membership_capabilities(user).items() if capability in caps}


def scope_queryset[M: Model](
    queryset: QuerySet[M], user: Any, capability: str, customer_field: str = "customer"
) -> QuerySet[M]:
    """Filter any customer-owned queryset to what ``user`` may see for ``capability``. Fails closed."""
    ids = accessible_customer_ids(user, capability)
    if ids is None:
        return queryset
    if not ids:
        return queryset.none()
    lookup = "id__in" if customer_field in ("", "self", "pk") else f"{customer_field}_id__in"
    return queryset.filter(**{lookup: ids})


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def get_customer_or_404(user: Any, customer_id: Any, capability: str, request: HttpRequest | None = None) -> Customer:
    """Resolve a customer from the database and require ``capability`` on it.

    Unknown, malformed and unauthorised IDs are indistinguishable to the caller (all 404).
    """
    from apps.customers.models import Customer

    cid = _parse_uuid(customer_id)
    customer = Customer.objects.filter(pk=cid).first() if cid else None
    if customer is not None and _user_ok(user):
        if capability in user.global_capabilities:
            return customer
        if customer.status in Customer.MEMBER_VISIBLE_STATUSES and capability in membership_capabilities(user).get(
            customer.id, frozenset()
        ):
            return customer
    _audit_denial(user, request, "customer", str(customer_id)[:64], capability)
    raise NotFound()


def _audit_denial(user: Any, request: Any, target_type: str, target_id: str, capability: str) -> None:
    if not _user_ok(user):
        return
    from apps.audit.services import record_event

    record_event(
        action="authz.denied",
        actor=user,
        outcome="denied",
        target_type=target_type,
        target_id=target_id,
        request=request,
        metadata={"capability": capability},
    )
