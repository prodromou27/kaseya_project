"""VSA4-04 / R16: observed differences between two *complete* published generations of one customer's VSA scope.

Rules (VSA-F18):
* Only published/superseded generations of the **same** customer, VSA instance and dataset are comparable.
* A change is "observed between snapshot A (published at t1) and snapshot B (published at t2)". The portal never
  invents when it happened or who made it: VSA X audit logs are not collected, so no actor is attributed.
* A section (network, software) is compared for a device only when it was collected in **both** snapshots; otherwise
  the device is counted as ``not_compared`` for that section, never as "no change".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from apps.integrations.models import DatasetGeneration

from .models import AssetObservation, IpAddressObservation
from .network import is_review_relevant
from .queries import current_generations

COMPARABLE_STATES = (DatasetGeneration.State.PUBLISHED, DatasetGeneration.State.SUPERSEDED)
KINDS = (
    "device_added",
    "device_removed",
    "hostname",
    "group",
    "site",
    "os",
    "agent_version",
    "agent_installed",
    "ip_addresses",
    "software",
)
NOTE = (
    "Changes are differences observed between two complete VSA X snapshots. The time shown is the snapshot window, "
    "not when the change happened, and no person is attributed (VSA X audit logs are not collected)."
)


class NotComparable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def comparable_generations(customer_id: Any) -> list[DatasetGeneration]:
    return list(
        DatasetGeneration.objects.filter(customer_id=customer_id, state__in=COMPARABLE_STATES, dataset="vsa_assets")
        .select_related("integration_instance")
        .order_by("-published_at")[:100]
    )


def resolve_pair(
    customer_id: Any, from_id: Any = None, to_id: Any = None
) -> tuple[DatasetGeneration, DatasetGeneration]:
    gens = {str(g.pk): g for g in comparable_generations(customer_id)}
    if to_id:
        to = gens.get(str(to_id))
        if to is None:
            raise NotComparable("The 'to' snapshot is not a complete snapshot of this customer.")
    else:
        current = list(current_generations(customer_id))
        if len(current) != 1:
            raise NotComparable("Choose a snapshot: this customer has several or no current snapshots.")
        to = current[0]
    if from_id:
        frm = gens.get(str(from_id))
        if frm is None:
            raise NotComparable("The 'from' snapshot is not a complete snapshot of this customer.")
    else:
        frm = (
            DatasetGeneration.objects.filter(
                customer_id=customer_id,
                integration_instance_id=to.integration_instance_id,
                dataset=to.dataset,
                state__in=COMPARABLE_STATES,
                published_at__lt=to.published_at,
            )
            .order_by("-published_at")
            .first()
        )
        if frm is None:
            raise NotComparable("There is no earlier complete snapshot to compare with.")
    if frm.integration_instance_id != to.integration_instance_id or frm.dataset != to.dataset:
        raise NotComparable("Snapshots from different VSA instances cannot be compared.")
    if frm.pk == to.pk:
        raise NotComparable("Choose two different snapshots.")
    if frm.published_at and to.published_at and frm.published_at > to.published_at:
        frm, to = to, frm  # always older -> newer
    return frm, to


def _addresses(customer_id: Any, gen: DatasetGeneration) -> dict[Any, set[str]]:
    out: dict[Any, set[str]] = defaultdict(set)
    for asset_id, address, kind in IpAddressObservation.objects.filter(
        customer_id=customer_id, generation=gen
    ).values_list("asset_id", "address", "kind"):
        if address and is_review_relevant(kind):
            out[asset_id].add(address)
    return out


def _software(customer_id: Any, gen: DatasetGeneration) -> dict[Any, set[tuple[str, str]]]:
    from apps.software.models import SoftwareInstallation

    out: dict[Any, set[tuple[str, str]]] = defaultdict(set)
    for asset_id, name, version in SoftwareInstallation.objects.filter(
        customer_id=customer_id, generation=gen
    ).values_list("asset_id", "raw_name", "raw_version"):
        out[asset_id].add((name, version))
    return out


def _scalar(changes: list[dict[str, Any]], kind: str, old: Any, new: Any) -> None:
    if old != new:
        changes.append({"kind": kind, "from": old, "to": new})


def diff(customer_id: Any, frm: DatasetGeneration, to: DatasetGeneration) -> dict[str, Any]:
    fields = (
        "asset_id",
        "hostname",
        "group_external_id",
        "group_name",
        "site_external_id",
        "os_name",
        "os_version",
        "client_version",
        "is_agent_installed",
        "network_status",
        "software_status",
    )
    before = {
        o["asset_id"]: o
        for o in AssetObservation.objects.filter(customer_id=customer_id, generation=frm).values(*fields)
    }
    after = {
        o["asset_id"]: o
        for o in AssetObservation.objects.filter(customer_id=customer_id, generation=to).values(*fields)
    }
    from .models import Asset

    external = dict(
        Asset.objects.filter(customer_id=customer_id, pk__in=set(before) | set(after)).values_list("pk", "external_id")
    )
    ips_a, ips_b = _addresses(customer_id, frm), _addresses(customer_id, to)
    sw_a, sw_b = _software(customer_id, frm), _software(customer_id, to)
    not_compared: Counter[str] = Counter()
    devices: list[dict[str, Any]] = []

    def row(asset_id: Any, obs: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "asset_id": str(asset_id),
            "external_id": external.get(asset_id, ""),
            "hostname": obs["hostname"],
            "group_external_id": obs["group_external_id"],
            "changes": changes,
        }

    for asset_id in sorted(set(after) - set(before), key=lambda a: after[a]["hostname"].casefold()):
        devices.append(row(asset_id, after[asset_id], [{"kind": "device_added"}]))
    for asset_id in sorted(set(before) - set(after), key=lambda a: before[a]["hostname"].casefold()):
        devices.append(row(asset_id, before[asset_id], [{"kind": "device_removed"}]))
    for asset_id in sorted(set(before) & set(after), key=lambda a: after[a]["hostname"].casefold()):
        a, b = before[asset_id], after[asset_id]
        changes: list[dict[str, Any]] = []

        _scalar(changes, "hostname", a["hostname"], b["hostname"])
        _scalar(changes, "group", a["group_external_id"], b["group_external_id"])
        _scalar(changes, "site", a["site_external_id"], b["site_external_id"])
        _scalar(changes, "os", f"{a['os_name']} {a['os_version']}".strip(), f"{b['os_name']} {b['os_version']}".strip())
        _scalar(changes, "agent_version", a["client_version"], b["client_version"])
        if a["is_agent_installed"] is not None and b["is_agent_installed"] is not None:
            _scalar(changes, "agent_installed", a["is_agent_installed"], b["is_agent_installed"])
        if a["network_status"] == "collected" and b["network_status"] == "collected":
            added, removed = ips_b[asset_id] - ips_a[asset_id], ips_a[asset_id] - ips_b[asset_id]
            if added or removed:
                changes.append({"kind": "ip_addresses", "added": sorted(added), "removed": sorted(removed)})
        else:
            not_compared["ip_addresses"] += 1
        if a["software_status"] == "collected" and b["software_status"] == "collected":
            added_sw, removed_sw = sw_b[asset_id] - sw_a[asset_id], sw_a[asset_id] - sw_b[asset_id]
            if added_sw or removed_sw:
                changes.append(
                    {
                        "kind": "software",
                        "added": [f"{n} {v}".strip() for n, v in sorted(added_sw)][:200],
                        "removed": [f"{n} {v}".strip() for n, v in sorted(removed_sw)][:200],
                    }
                )
        else:
            not_compared["software"] += 1
        if changes:
            devices.append(row(asset_id, b, changes))

    counts = Counter(c["kind"] for d in devices for c in d["changes"])
    return {
        "from": {
            "id": str(frm.pk),
            "published_at": frm.published_at,
            "data_basis": frm.data_basis,
            "devices": len(before),
        },
        "to": {"id": str(to.pk), "published_at": to.published_at, "data_basis": to.data_basis, "devices": len(after)},
        "counts": {k: counts.get(k, 0) for k in KINDS},
        "devices_compared": len(set(before) & set(after)),
        "not_compared": {"ip_addresses": not_compared["ip_addresses"], "software": not_compared["software"]},
        "devices": devices,
        "note": NOTE,
    }
