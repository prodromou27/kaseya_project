"""One inventory filter contract for the portal and pinned report populations.

Callers must supply an already customer-scoped queryset. These filters never widen it.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone
from rest_framework import serializers

ORDERING = (
    "hostname",
    "-hostname",
    "last_seen_online",
    "-last_seen_online",
    "group_name",
    "-group_name",
    "os_name",
    "-os_name",
)
EXACT_FIELDS = {
    "group": "group_name",
    "os": "os_name",
    "device_type": "device_type",
    "site": "site_external_id",
    "group_id": "group_external_id",
    "software_status": "software_status",
    "organization": "organization_external_id",
    "instance": "generation__integration_instance_id",
}
# CFA-10: condition on an approved device custom field, from the values collected by the latest sync.
CUSTOM_FIELD_STATES = {
    "missing": "is empty",
    "set": "has any value",
    "equals": "is the value",
    "not_equals": "has a value other than",
    "missing_or_equals": "is empty or the value",
    "not_read": "was not read in the latest sync",
}
NEEDS_VALUE = {"equals", "not_equals", "missing_or_equals"}
# FLT-01: up to three custom field rules, all of which must match: custom_field, custom_field_2, custom_field_3.
CF_SUFFIXES = ("", "_2", "_3")
# FLT-01: hardware and identity, matched case-insensitively (model: part of the name).
TEXT_FIELDS = {
    "manufacturer": "manufacturer__iexact",
    "model": "model__icontains",
    "os_version": "os_version",
    "agent_version": "client_version",
    "domain": "domain__iexact",
}
MISSING_UPDATES = ("critical", "important", "any", "none")
NO_POLICY, UNKNOWN_POLICY = "__none__", "__unknown__"


class AssetFilters(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    group = serializers.CharField(required=False, allow_blank=True, max_length=255)
    os = serializers.CharField(required=False, allow_blank=True, max_length=255)
    device_type = serializers.CharField(required=False, allow_blank=True, max_length=255)
    site = serializers.CharField(required=False, allow_blank=True, max_length=255)
    group_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    organization = serializers.CharField(required=False, allow_blank=True, max_length=255)
    instance = serializers.UUIDField(required=False)
    software_status = serializers.ChoiceField(choices=["collected", "not_collected"], required=False)
    offline = serializers.BooleanField(required=False)
    offline_days = serializers.IntegerField(required=False, min_value=1, max_value=365)
    ordering = serializers.ChoiceField(choices=ORDERING, required=False)
    custom_field = serializers.CharField(required=False, max_length=120, help_text="Approved device custom field name.")
    custom_field_state = serializers.ChoiceField(choices=list(CUSTOM_FIELD_STATES), required=False)
    custom_field_value = serializers.CharField(required=False, max_length=255)
    custom_field_2 = serializers.CharField(required=False, max_length=120)
    custom_field_state_2 = serializers.ChoiceField(choices=list(CUSTOM_FIELD_STATES), required=False)
    custom_field_value_2 = serializers.CharField(required=False, max_length=255)
    custom_field_3 = serializers.CharField(required=False, max_length=120)
    custom_field_state_3 = serializers.ChoiceField(choices=list(CUSTOM_FIELD_STATES), required=False)
    custom_field_value_3 = serializers.CharField(required=False, max_length=255)
    manufacturer = serializers.CharField(required=False, max_length=255)
    model = serializers.CharField(required=False, max_length=255)
    os_version = serializers.CharField(required=False, max_length=64)
    agent_version = serializers.CharField(required=False, max_length=64)
    domain = serializers.CharField(required=False, max_length=255)
    tag = serializers.CharField(required=False, max_length=255)
    role = serializers.ChoiceField(choices=["server", "workstation"], required=False)
    software = serializers.CharField(required=False, max_length=255, help_text="Part of an installed program name.")
    software_presence = serializers.ChoiceField(choices=["installed", "not_installed"], required=False)
    software_outdated = serializers.BooleanField(required=False)
    missing_updates = serializers.ChoiceField(choices=list(MISSING_UPDATES), required=False)
    patch_policy = serializers.CharField(
        required=False,
        max_length=255,
        help_text=f"Policy name, {NO_POLICY} (none or not reported) or {UNKNOWN_POLICY}.",
    )
    asset_ids = serializers.CharField(
        required=False, max_length=19000, help_text="Comma-separated device UUIDs, at most 500."
    )

    def validate_asset_ids(self, value: str) -> str:
        parts = value.split(",")
        if len(parts) > 500:
            raise serializers.ValidationError("Select at most 500 devices.")
        field = serializers.UUIDField()
        return ",".join(dict.fromkeys(str(field.run_validation(part.strip())) for part in parts))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for sfx in CF_SUFFIXES:
            name, state, value = f"custom_field{sfx}", f"custom_field_state{sfx}", f"custom_field_value{sfx}"
            if attrs.get(state) and not attrs.get(name):
                raise serializers.ValidationError({name: "Choose the custom field."})
            if attrs.get(name):
                attrs.setdefault(state, "missing")
                if attrs[state] in NEEDS_VALUE and not attrs.get(value, "").strip():
                    raise serializers.ValidationError({value: "Enter the value to compare with."})
        if attrs.get("software_presence") and not attrs.get("software", "").strip():
            raise serializers.ValidationError({"software": "Enter part of the program name."})
        if attrs.get("software", "").strip():
            attrs.setdefault("software_presence", "installed")
        return attrs

    def validate_for_customer(self, customer: Any, data: dict[str, Any]) -> None:
        from .models import Asset, CustomFieldAllowlist

        for sfx in CF_SUFFIXES:
            if name := data.get(f"custom_field{sfx}"):
                approved = CustomFieldAllowlist.objects.filter(
                    customer=customer, name_key=name.strip().casefold(), state=CustomFieldAllowlist.State.APPROVED
                ).exists()
                if not approved:
                    raise serializers.ValidationError(
                        {f"custom_field{sfx}": "Values of this field are not collected for this customer. Approve it."}
                    )

        if selected := data.get("asset_ids"):
            ids = selected.split(",")
            if Asset.objects.filter(customer=customer, pk__in=ids).count() != len(ids):
                raise serializers.ValidationError({"asset_ids": "A selected device was not found for this customer."})


def filter_inventory(qs: QuerySet, filters: dict[str, Any], *, as_of: datetime | None = None) -> QuerySet:
    if selected := filters.get("asset_ids"):
        qs = qs.filter(asset_id__in=selected.split(","))
    search = filters.get("search", "").strip()
    if search:
        cond = Q(hostname__icontains=search) | Q(serial_number__icontains=search) | Q(asset__external_id=search)
        mac = re.sub(r"[^0-9A-Fa-f]", "", search).upper()
        if len(mac) == 12:
            cond |= Q(adapters__mac=mac)
        with contextlib.suppress(ValueError):
            cond |= Q(adapters__ips__address=ipaddress.ip_address(search.partition("%")[0]).compressed)
        qs = qs.filter(cond).distinct()
    for param, field in EXACT_FIELDS.items():
        if value := filters.get(param):
            qs = qs.filter(**{field: value})
    for sfx in CF_SUFFIXES:
        if filters.get(f"custom_field{sfx}"):
            qs = _custom_field_condition(qs, filters, sfx)
    for param, lookup in TEXT_FIELDS.items():
        if value := filters.get(param, "").strip():
            qs = qs.filter(**{lookup: value})
    if tag := filters.get("tag", "").strip():
        qs = qs.filter(tags__contains=[tag])
    if role := filters.get("role"):
        qs = qs.filter(_server_q()) if role == "server" else qs.exclude(_server_q())
    qs = _software_and_patching(qs, filters)
    if "offline" in filters:
        cutoff = (as_of or timezone.now()) - timedelta(days=filters.get("offline_days", 7))
        cond = Q(last_seen_online__lt=cutoff) | Q(last_seen_online__isnull=True)
        qs = qs.filter(cond) if filters["offline"] else qs.exclude(cond)
    return qs.order_by(filters.get("ordering", "hostname"), "asset_id")


def _server_q() -> Q:
    """SRV-01 rule: marked a server, or "server" in the OS name unless marked "not a server"."""
    marked = Q(asset__server_designation__is_server=True)
    detected = Q(os_name__icontains="server") & ~Q(asset__server_designation__is_server=False)
    return marked | detected


def _software_and_patching(qs: QuerySet, filters: dict[str, Any]) -> QuerySet:
    """FLT-01. Each condition only answers for devices whose data was collected: a device whose software or OS
    updates were not collected never counts as "not installed", "nothing outdated" or "no updates missing"."""
    from apps.patching.models import AppliedPolicyObservation, DeviceOsUpdate, PatchObservation, UpdateStatus
    from apps.software.models import ComplianceResult, SoftwareInstallation

    if name := filters.get("software", "").strip():
        present = Exists(SoftwareInstallation.objects.filter(observation=OuterRef("pk"), raw_name__icontains=name))
        if filters.get("software_presence", "installed") == "installed":
            qs = qs.filter(present)
        else:
            qs = qs.filter(~present, software_status="collected")
    if "software_outdated" in filters:
        outdated = Exists(
            ComplianceResult.objects.filter(
                installation__observation=OuterRef("pk"),
                evaluation__is_current=True,
                state=ComplianceResult.State.OUTDATED,
            )
        )
        qs = qs.filter(outdated) if filters["software_outdated"] else qs.filter(~outdated, software_status="collected")
    if wanted := filters.get("missing_updates"):
        available = DeviceOsUpdate.objects.filter(
            patch_observation__observation=OuterRef("pk"), state=DeviceOsUpdate.State.AVAILABLE
        )
        if wanted in ("critical", "important"):
            qs = qs.filter(Exists(available.filter(severity__iexact=wanted)))
        elif wanted == "any":
            qs = qs.filter(Exists(available))
        else:
            read = PatchObservation.objects.filter(
                observation=OuterRef("pk"),
                available_status__in=(UpdateStatus.COLLECTED, UpdateStatus.CARRIED_FORWARD),
            )
            qs = qs.filter(Exists(read), ~Exists(available))
    if policy := filters.get("patch_policy", "").strip():
        states = AppliedPolicyObservation.objects.filter(observation=OuterRef("pk"))
        if policy == NO_POLICY:
            qs = qs.filter(Exists(states.filter(patch_state__in=("explicit_none", "not_reported"))))
        elif policy == UNKNOWN_POLICY:
            qs = qs.filter(~Exists(states.exclude(patch_state="unknown")))
        else:
            qs = qs.filter(Exists(states.filter(patch_state="assigned", patch_policy_name__iexact=policy)))
    return qs


def _custom_field_condition(qs: QuerySet, filters: dict[str, Any], sfx: str = "") -> QuerySet:
    """Devices by one custom field, using the values the latest sync stored for each observation.

    "Empty" only counts devices whose custom fields were actually read (collected or carried forward); devices that were
    not read are found with ``not_read`` and are never reported as empty.
    """
    from .models import DeviceCustomField, DeviceDetailFetch

    name = filters[f"custom_field{sfx}"].strip()
    rows = DeviceCustomField.objects.filter(fetch__observation=OuterRef("pk"), name__iexact=name)
    filled = Exists(rows.exclude(value__regex=r"^\s*$"))
    read = Exists(
        DeviceDetailFetch.objects.filter(
            observation=OuterRef("pk"),
            kind=DeviceDetailFetch.Kind.CUSTOM_FIELDS,
            status__in=(DeviceDetailFetch.Status.COLLECTED, DeviceDetailFetch.Status.CARRIED_FORWARD),
        )
    )
    value = filters.get(f"custom_field_value{sfx}", "").strip()
    equal = Exists(rows.filter(value__iexact=value))
    state = filters.get(f"custom_field_state{sfx}", "missing")
    condition = {
        "missing": read & ~filled,
        "set": filled,
        "equals": equal,
        "not_equals": filled & ~equal,
        "missing_or_equals": read & (~filled | equal),
        "not_read": ~read,
    }[state]
    return qs.filter(condition)
