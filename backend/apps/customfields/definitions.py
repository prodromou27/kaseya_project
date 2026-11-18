"""Custom field definitions: refresh from VSA X, eligibility for device writes, typed value validation."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.inventory.details import is_sensitive_field_name

from .models import CustomFieldDefinition

TYPES = {"Text", "Number", "Boolean", "Date"}
MAX_TEXT = 255
_NUMBER = re.compile(r"^-?\d{1,18}(?:\.\d{1,10})?$")
_TRUE, _FALSE = {"true", "yes", "1"}, {"false", "no", "0"}


class ValueInvalid(ValueError):
    pass


def refresh(instance: Any, adapter: Any = None) -> dict[str, int]:
    """Re-read every definition the token can see. Fields no longer listed are kept but marked not present."""
    from apps.integrations.vsa.adapter import VsaXAdapter

    rows = (adapter or VsaXAdapter(instance)).list_custom_field_definitions()
    now = timezone.now()
    seen: set[str] = set()
    created = 0
    for row in rows:
        fid = str(row.get("Id") or "")
        if not fid.isdigit():
            continue
        seen.add(fid)
        contexts = row.get("Contexts", row.get("Context")) or []
        expiration = parse_datetime(str(row.get("ExpirationDate"))) if row.get("ExpirationDate") else None
        _, was_created = CustomFieldDefinition.objects.update_or_create(
            integration_instance=instance,
            external_id=fid,
            defaults={
                "name": str(row.get("Name") or "")[:255],
                "description": str(row.get("Description") or "")[:1000],
                "type": str(row.get("Type") or "")[:16],
                "default_value": str(row.get("DefaultValue") or "")[:255],
                "is_read_only": bool(row.get("IsReadOnly")),
                "contexts": [str(c)[:20] for c in contexts if isinstance(c, str)][:10],
                "expiration_date": expiration,
                "present": True,
                "fetched_at": now,
            },
        )
        created += int(was_created)
    gone = (
        CustomFieldDefinition.objects.filter(integration_instance=instance, present=True)
        .exclude(external_id__in=seen)
        .update(present=False, fetched_at=now)
    )
    return {"fields": len(seen), "new": created, "no_longer_listed": gone}


def device_capable(d: CustomFieldDefinition) -> tuple[bool, str]:
    """Whether VSA X allows a device-level value at all (before the portal's own setting)."""
    if not d.present:
        return False, "No longer listed by VSA X"
    if "Device" not in (d.contexts or []):
        return False, "Not available for devices"
    if d.is_read_only:
        return False, "Read-only in VSA X"
    if d.expiration_date and d.expiration_date <= timezone.now():
        return False, "Expired"
    if d.type not in TYPES:
        return False, f"Unsupported type {d.type or '(none)'}"
    if is_sensitive_field_name(d.name):
        return False, "Credential-like name: never edited through the portal"
    return True, ""


def eligibility(d: CustomFieldDefinition) -> tuple[bool, str]:
    ok, reason = device_capable(d)
    if not ok:
        return ok, reason
    if not d.portal_writable:
        return False, "Not enabled for editing in the portal"
    return True, ""


def for_customer(customer: Any) -> QuerySet[CustomFieldDefinition]:
    """Definitions of the VSA X integrations this customer is mapped to (approved mappings only)."""
    from apps.customers.models import CustomerSourceMapping

    instances = CustomerSourceMapping.objects.filter(
        customer=customer, mapping_status="approved", integration_instance__provider="vsa_x"
    ).values("integration_instance_id")
    return CustomFieldDefinition.objects.filter(integration_instance_id__in=instances).select_related(
        "integration_instance"
    )


def normalise(ftype: str, raw: Any) -> str:
    """Validate a requested value for the field type and return the text sent to VSA X."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise ValueInvalid("Enter a value.")
    if len(text) > MAX_TEXT or any(ord(c) < 32 for c in text):
        raise ValueInvalid(f"At most {MAX_TEXT} characters, no control characters.")
    if ftype == "Number":
        if not _NUMBER.fullmatch(text):
            raise ValueInvalid("Enter a number, e.g. 42 or 3.5.")
        return text
    if ftype == "Boolean":
        low = text.casefold()
        if low in _TRUE:
            return "true"
        if low in _FALSE:
            return "false"
        raise ValueInvalid("Enter true or false.")
    if ftype == "Date":
        try:
            return dt.date.fromisoformat(text[:10]).isoformat() if len(text) == 10 else _bad_date()
        except ValueError as exc:
            raise ValueInvalid("Enter a date as YYYY-MM-DD.") from exc
    return text


def _bad_date() -> str:
    raise ValueError("date")


def same(ftype: str, current: str | None, requested: str) -> bool:
    """Whether VSA X already holds the requested value (type-aware comparison)."""
    if current is None:
        return False
    current = current.strip()
    if ftype == "Number":
        try:
            return Decimal(current) == Decimal(requested)
        except InvalidOperation:
            return False
    if ftype == "Boolean":
        return current.casefold() in (_TRUE if requested == "true" else _FALSE)
    if ftype == "Date":
        return current[:10] == requested
    return current == requested
