""" "Connect VSA" wizard: the whole setup in two calls, built from the same audited building blocks.

1. ``connect``: allow the API host, create (or reuse) the integration for that URL, store the credentials encrypted,
   run the read-only connection test and list the VSA organisations.
2. ``import_organizations``: for each ticked organisation, use or create a customer, create an approved mapping
   (which creates its sync schedule), enable the integration and start the first sync.

Nothing here bypasses a control: the URL policy (https, no private/internal names), encryption, read-only adapter,
customer isolation and the audit trail all still apply.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import record_event

from .models import ConnectorHost, IntegrationInstance
from .providers import validate_fields
from .secrets import CredentialStorageUnavailable, encrypt_fields
from .urlpolicy import normalize_api_hostname

DEFAULT_BUDGET = 100


def _host_from(url: str) -> str:
    raw = (url or "").strip()
    if not raw.startswith(("https://", "http://")):
        raw = f"https://{raw}"
    if raw.startswith("http://"):
        raise ValidationError({"base_url": "Use https."})
    try:
        return normalize_api_hostname(urlsplit(raw).hostname or "")
    except DjangoValidationError as exc:
        raise ValidationError({"base_url": exc.messages}) from exc


def connect(user: Any, request: Any, *, base_url: str, token_id: str, token_secret: str, name: str = "") -> dict:
    from .views import _test_connection  # shared with the admin "Test connection" button

    host = _host_from(base_url)
    clean, errors = validate_fields("vsa_x", {"token_id": token_id, "token_secret": token_secret})
    if errors:
        raise ValidationError(errors)
    with transaction.atomic():
        allowed, created_host = ConnectorHost.objects.get_or_create(
            provider="vsa_x", hostname=host, defaults={"added_by": user, "reason": "Connect VSA wizard"}
        )
        if created_host:
            record_event(
                action="integration.host_allowed",
                outcome="success",
                actor=user,
                target_type="connector_host",
                target_id=str(allowed.id),
                request=request,
                metadata={"provider": "vsa_x", "hostname": host, "reason": "Connect VSA wizard"},
            )
        url = f"https://{host}"
        instance = IntegrationInstance.objects.filter(provider="vsa_x", base_url=url, is_fixture=False).first()
        if instance is None:
            instance = IntegrationInstance(
                name=(name or f"VSA X ({host})")[:120],
                provider="vsa_x",
                base_url=url,
                installed_updates_budget=DEFAULT_BUDGET,
                applied_policies_budget=DEFAULT_BUDGET,
                notifications_budget=DEFAULT_BUDGET,
                custom_fields_budget=DEFAULT_BUDGET,
            )
            try:
                instance.full_clean(exclude=["credential_ref"])
            except DjangoValidationError as exc:
                raise ValidationError(exc.message_dict) from exc
            instance.save()
            record_event(
                action="integration.created",
                outcome="success",
                actor=user,
                target_type="integration",
                target_id=str(instance.id),
                request=request,
                metadata={"provider": "vsa_x", "base_url": url, "is_fixture": False, "via": "connect_wizard"},
            )
        try:
            instance.credential_ciphertext = encrypt_fields(instance, clean)
        except CredentialStorageUnavailable as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        instance.credential_set_at, instance.credential_set_by = timezone.now(), user
        instance.save(update_fields=["credential_ciphertext", "credential_set_at", "credential_set_by", "updated_at"])
        record_event(
            action="integration.credential_set",
            outcome="success",
            actor=user,
            target_type="integration",
            target_id=str(instance.id),
            request=request,
            metadata={"via": "connect_wizard"},
        )
    result = _test_connection(instance)
    instance.last_test_at, instance.last_test_outcome, instance.last_test_result = (
        timezone.now(),
        result["outcome"],
        result,
    )
    instance.save(update_fields=["last_test_at", "last_test_outcome", "last_test_result"])
    record_event(
        action="integration.connection_test",
        outcome="success" if result["outcome"] == "ok" else "failure",
        actor=user,
        target_type="integration",
        target_id=str(instance.id),
        request=request,
        metadata={"outcome": result["outcome"], "via": "connect_wizard"},
    )
    body: dict[str, Any] = {"integration_id": str(instance.id), "connection": result, "organizations": []}
    if result["outcome"] == "ok":
        from .views import _discover_organizations

        body["organizations"] = _discover_organizations(instance).data["organizations"]
    return body


def _customer_code(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:28] or "CUSTOMER"
    if len(base) < 2:
        base = f"{base}X"
    code, n = base, 2
    while code in taken:
        code, n = f"{base[:28]}-{n}", n + 1
    return code


def import_organizations(user: Any, request: Any, instance: IntegrationInstance, picks: list[dict]) -> dict:
    """``picks``: [{"external_org_id", "name", "customer_id"?}] - no customer_id creates a customer from the name."""
    from apps.customers.models import Customer, CustomerSourceMapping
    from apps.customers.views import ensure_sync_schedule

    from .sync import SyncRefused, request_sync

    if instance.provider != IntegrationInstance.Provider.VSA_X:
        raise ValidationError({"detail": "Only VSA X organisations can be imported."})
    if not isinstance(picks, list) or not picks:
        raise ValidationError({"organizations": "Tick at least one organisation."})
    if len(picks) > 500:
        raise ValidationError({"organizations": "At most 500 organisations at a time."})
    now = timezone.now()
    imported: list[dict[str, Any]] = []
    with transaction.atomic():
        taken = set(Customer.objects.values_list("code", flat=True))
        for pick in picks:
            org_id = str((pick or {}).get("external_org_id", "")).strip()
            org_name = str((pick or {}).get("name", "")).strip()[:200] or f"VSA organisation {org_id}"
            if not org_id:
                raise ValidationError({"organizations": "Every organisation needs its VSA ID."})
            live = CustomerSourceMapping.objects.filter(
                integration_instance=instance, external_org_id=org_id, mapping_status__in=["proposed", "approved"]
            ).first()
            if live is not None and live.mapping_status == "approved":
                imported.append({"external_org_id": org_id, "customer": live.customer.code, "status": "already linked"})
                ensure_sync_schedule(live)
                continue
            if pick.get("customer_id"):
                customer = Customer.objects.filter(pk=pick["customer_id"]).first()
                if customer is None:
                    raise ValidationError({"organizations": f"Customer for organisation {org_id} not found."})
            else:
                code = _customer_code(org_name, taken)
                taken.add(code)
                customer = Customer.objects.create(code=code, name=org_name, status=Customer.Status.ACTIVE)
                record_event(
                    action="customer.created",
                    outcome="success",
                    actor=user,
                    customer=customer,
                    target_type="customer",
                    target_id=str(customer.id),
                    request=request,
                    metadata={"code": code, "via": "connect_wizard"},
                )
            mapping = live or CustomerSourceMapping(
                customer=customer, integration_instance=instance, external_org_id=org_id, proposed_by=user
            )
            mapping.customer = customer
            mapping.external_org_name = org_name[:200]
            mapping.mapping_status = CustomerSourceMapping.Status.APPROVED
            mapping.reviewed_by, mapping.reviewed_at = user, now
            mapping.review_note = "Approved in the Connect VSA wizard"
            mapping.save()
            ensure_sync_schedule(mapping)
            record_event(
                action="mapping.approved",
                outcome="success",
                actor=user,
                customer=customer,
                target_type="source_mapping",
                target_id=str(mapping.id),
                request=request,
                metadata={"external_org_id": org_id, "via": "connect_wizard"},
            )
            imported.append(
                {"external_org_id": org_id, "customer": customer.code, "mapping": mapping, "status": "linked"}
            )
        if not instance.enabled:
            instance.enabled = True
            instance.save(update_fields=["enabled", "updated_at"])
            record_event(
                action="integration.updated",
                outcome="success",
                actor=user,
                target_type="integration",
                target_id=str(instance.id),
                request=request,
                metadata={"changed": ["enabled"], "enabled": True, "via": "connect_wizard"},
            )
    started = 0
    for item in imported:
        mapping = item.pop("mapping", None)
        if mapping is None:
            continue
        try:
            _, created = request_sync(mapping, requested_by=user)
            started += int(created)
            item["sync"] = "started"
        except SyncRefused as exc:
            item["sync"] = f"not started: {exc.code}"
    return {"integration_id": str(instance.id), "imported": imported, "syncs_started": started}
