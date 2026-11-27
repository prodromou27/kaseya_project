"""MOV-02: move a list of devices to one group (product owner, 2026-11-27).

The operator pastes or uploads a list of devices and picks the destination group. ``check`` matches every line with the
same rules as custom field lists (device ID -> serial -> FQDN -> hostname, exact, this customer only) and says what
would happen to it. Nothing is recorded or sent here: the moves themselves go through the existing one-device steps
(``moves.move_now`` or ``moves.propose``), so every check, approval rule and audit event still applies per device.

Devices that are not in VSA X (not onboarded, so not in the current inventory) are skipped, as are devices already in
the destination group, in another VSA organisation, ambiguous lines, and lines that are not valid identifiers.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.customfields import matching

from . import move_execution
from .models import GroupMoveRequest, GroupNode
from .queries import current_generations, current_observations, stale_cutoff

MOVE = "move"
SKIP_NOTES = {
    "not_in_vsa": "Not in VSA X (not onboarded) - skipped",
    "already_there": "Already in this group - skipped",
    "other_organization": "In another VSA organisation than the group - skipped",
    "no_group": "VSA X reports no group for this device - skipped",
    "stale": "Inventory is out of date - synchronize first",
    "ambiguous": "Several devices match - use the device ID or serial number",
    "other_customer": "Belongs to another customer - skipped",
    "invalid": "Not a valid device name or ID - skipped",
    "duplicate": "Listed twice - skipped",
    "unsupported": "Asset tags are not collected from VSA X - skipped",
}
_FROM_MATCH = {
    "not_found": "not_in_vsa",
    "multiple": "ambiguous",
    "other_customer": "other_customer",
    "invalid": "invalid",
    "duplicate": "duplicate",
    "unsupported": "unsupported",
}


def destinations(customer_id: Any) -> list[dict[str, str]]:
    """Active groups of the current inventory, the choices for "Move to"."""
    return [
        {
            "id": str(g.id),
            "external_id": g.external_id,
            "name": g.name or g.external_id,
            "site": g.site_external_id,
            "organization": g.organization_external_id,
            "source": g.generation.integration_instance.name,
        }
        for g in GroupNode.objects.filter(
            customer_id=customer_id, generation__in=current_generations(customer_id), is_active=True
        )
        .select_related("generation__integration_instance")
        .order_by("name", "external_id")
    ]


def records_from(data: Any, files: Any) -> list[matching.InputRecord]:
    """Pasted text (``text``) or an uploaded TXT/CSV/XLSX (``file``); a file's identifier columns are recognised by
    their header (device ID, serial, FQDN, hostname, ...), otherwise the first column is read as device names."""
    upload = files.get("file")
    if upload is not None:
        header, rows = matching.read_file(upload.name, upload.read())
        mapping = {
            role: index
            for role, index in matching.guess_mapping(header).items()
            if role in ("device_id", "serial", "fqdn", "hostname")
        }
        if not mapping:  # no recognised header: the first row is data, not a header
            mapping, rows = {"hostname": 0}, [(1, header), *rows]
        return matching.from_rows(rows, mapping)
    return matching.from_text(data.get("text", ""))


def check(customer: Any, user: Any, target_id: Any, records: list[matching.InputRecord]) -> dict[str, Any]:
    target = (
        GroupNode.objects.filter(
            customer=customer, pk=target_id, generation__in=current_generations(customer.id), is_active=True
        )
        .select_related("generation__integration_instance")
        .first()
    )
    if target is None:
        raise ValidationError({"target_group": "Choose an active group of this customer's current inventory."})
    instance = target.generation.integration_instance
    items = matching.match(customer, user, instance, records, workstations_only=False)
    asset_ids = [i["asset_id"] for i in items if i.get("match_status") == "matched"]
    observations = {
        str(o.asset_id): o
        for o in current_observations(customer.id).filter(asset_id__in=asset_ids, asset__integration_instance=instance)
    }
    pending = set(
        GroupMoveRequest.objects.filter(customer=customer, asset_id__in=asset_ids, state="pending").values_list(
            "asset_id", flat=True
        )
    )
    cutoff = stale_cutoff()
    rows = []
    for item in items:
        status = _FROM_MATCH.get(item.get("match_status", ""), "")
        o = observations.get(str(item.get("asset_id"))) if not status else None
        if not status:
            if o is None:
                status = "not_in_vsa"
            elif o.generation.published_at < cutoff:
                status = "stale"
            elif not o.group_external_id:
                status = "no_group"
            elif str(o.organization_external_id) != str(target.organization_external_id):
                status = "other_organization"
            elif o.group_external_id == target.external_id:
                status = "already_there"
            else:
                status = MOVE
        rows.append(
            {
                "line": item.get("input_row") or item["position"] + 1,
                "input": item["input_identifier"],
                "status": status,
                "note": "Will be moved" if status == MOVE else SKIP_NOTES[status],
                "asset_id": str(item["asset_id"]) if item.get("asset_id") else None,
                "hostname": item.get("hostname") or "",
                "current_group": (o.group_name if o else item.get("group")) or "",
                "site": item.get("site") or "",
                "has_pending_suggestion": bool(o and o.asset_id in pending),
            }
        )
    available, why = move_execution.availability(instance)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "target": {
            "id": str(target.id),
            "name": target.name or target.external_id,
            "external_id": target.external_id,
            "organization": target.organization_external_id,
        },
        "rows": rows,
        "counts": counts,
        "to_move": counts.get(MOVE, 0),
        "execution_available": available,
        "execution_unavailable_reason": why,
        "move_now_allowed": (
            available
            and not settings.CATALOG_REQUIRE_SEPARATE_REVIEWER
            and scope.has_customer_capability(user, customer.id, Cap.CUSTOMER_APPROVE_MOVE)
        ),
    }
