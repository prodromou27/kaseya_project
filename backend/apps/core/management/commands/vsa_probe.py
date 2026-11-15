"""Read-only VSA X data probe for operators:
`docker compose ... exec backend python manage.py vsa_probe`.

Makes a handful of GET calls through the same allowlisted, rate-limited client as the sync (one small asset page and
a few per-device detail calls) and reports which data sections VSA X returns and their *field names*. It never
prints values (hostnames, IPs, software names, versions), credentials or tokens. Use it to tell "VSA X does not
return this" apart from "the portal does not show it".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.core.management.base import BaseCommand, CommandError

SECTIONS = [
    "Tags",
    "AssetInfo",
    "InstalledSoftware",
    "Updates",
    "AvailableUpdates",
    "IpAddresses",
    "LocalIpAddresses",
    "Disks",
    "Security",
]

MEANING = {
    "InstalledSoftware": "Software page / Installed programs",
    "AvailableUpdates": "Windows updates (available)",
    "Updates": "Windows update counts",
    "Disks": "Device health: disk space",
    "Security": "Device health: antivirus and firewall",
    "AssetInfo": "Operating system, manufacturer, model, serial",
    "IpAddresses": "Groups & network",
    "LocalIpAddresses": "Groups & network",
    "Tags": "Device tags",
}


def _keys(items: Any) -> list[str]:
    """Union of field names of the first few list items (names only, never values)."""
    names: set[str] = set()
    if isinstance(items, list):
        for item in items[:5]:
            if isinstance(item, dict):
                names.update(str(k) for k in item)
    elif isinstance(items, dict):
        names.update(str(k) for k in items)
    return sorted(names)


def _size(value: Any) -> int | None:
    if isinstance(value, (list, dict)):
        return len(value)
    return None


class Command(BaseCommand):
    help = "Read-only check of which data sections VSA X returns for a few devices (names and counts only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--integration", help="Integration name (default: the only enabled live VSA X one).")
        parser.add_argument("--org", help="VSA X organisation ID (default: the first approved mapping).")
        parser.add_argument("--devices", type=int, default=3, help="Devices to sample (1-10, default 3).")
        parser.add_argument("--no-details", action="store_true", help="Skip the per-device detail calls.")

    def handle(self, *args: Any, **options: Any) -> None:
        from apps.audit.services import record_event
        from apps.customers.models import CustomerSourceMapping
        from apps.integrations.http import ConnectorError
        from apps.integrations.models import IntegrationInstance
        from apps.integrations.vsa.adapter import VsaXAdapter

        qs = IntegrationInstance.objects.filter(provider=IntegrationInstance.Provider.VSA_X)
        if options["integration"]:
            qs = qs.filter(name=options["integration"])
        else:
            qs = qs.filter(enabled=True, is_fixture=False)
        instances = list(qs[:2])
        if len(instances) != 1:
            names = ", ".join(IntegrationInstance.objects.filter(provider="vsa_x").values_list("name", flat=True))
            raise CommandError(f"Pick one integration with --integration NAME (VSA X integrations: {names or 'none'}).")
        inst = instances[0]

        org = options["org"]
        if not org:
            mapping = (
                CustomerSourceMapping.objects.filter(integration_instance=inst, mapping_status="approved")
                .order_by("created_at")
                .first()
            )
            if mapping is None:
                raise CommandError("No approved organisation mapping for this integration; pass --org ID.")
            org = mapping.external_org_id
        devices = max(1, min(int(options["devices"]), 10))

        out = self.stdout
        findings: list[str] = []
        out.write(f"Integration: {inst.name} ({'fixture' if inst.is_fixture else 'live'}) - organisation {org}")
        out.write("Read-only GET calls only. Values are never printed.\n")

        try:
            adapter = VsaXAdapter(inst)
        except Exception as exc:  # credential missing / undecryptable
            raise CommandError(
                f"Cannot build the VSA X client: {type(exc).__name__}. Check Settings -> Integrations."
            ) from None

        def call(label: str, fn: Callable[[], Any]) -> Any:
            try:
                return fn()
            except ConnectorError as exc:
                status = f" HTTP {exc.status}" if exc.status else ""
                out.write(f"  {label}: FAILED ({exc.code}{status})")
                findings.append(f"{label} failed with {exc.code}{status}.")
            except Exception as exc:
                out.write(f"  {label}: FAILED ({type(exc).__name__})")
                findings.append(f"{label} failed ({type(exc).__name__}).")
            return None

        out.write("Asset list (same request as the sync):")
        page = call("GET /api/v3/assets", lambda: adapter.sample_assets(org, devices))
        records: list[dict[str, Any]] = page.records if page is not None else []
        if page is not None:
            total = page.total_count if page.total_count is not None else "not reported"
            out.write(f"  returned {len(records)} device(s); total in organisation: {total}")
            if not records:
                findings.append("VSA X returned no devices for this organisation (check the organisation ID).")
            top = sorted({str(k) for r in records for k in r})
            out.write(f"  top-level fields: {', '.join(top) or '-'}")
            out.write("\nSections requested with include=...:")
            for name in SECTIONS:
                present = [r[name] for r in records if name in r]
                non_empty = [v for v in present if _size(v)]
                sizes = [_size(v) for v in present if _size(v) is not None]
                size_txt = f", items {min(sizes)}-{max(sizes)}" if sizes else ""
                out.write(
                    f"  {name:<18} present {len(present)}/{len(records)}, non-empty {len(non_empty)}/{len(records)}"
                    f"{size_txt}  -> {MEANING.get(name, '')}"
                )
                fields = _keys(non_empty[0]) if non_empty else []
                if name == "AssetInfo" and non_empty:
                    cats = sorted({str(c.get("CategoryName")) for v in non_empty for c in v if isinstance(c, dict)})
                    out.write(f"      categories: {', '.join(cats)}")
                elif fields:
                    out.write(f"      fields: {', '.join(fields)}")
                if records and not present:
                    findings.append(
                        f"{name} is missing on every sampled device -> {MEANING.get(name, name)} stays empty."
                    )
                elif records and present and not non_empty:
                    findings.append(
                        f"{name} is present but empty on every sampled device -> {MEANING.get(name, name)}."
                    )

        if records and not options["no_details"]:
            out.write("\nPer-device detail calls (first sampled device):")
            ident = str(records[0].get("Identifier", ""))
            checks: list[tuple[str, Callable[[], Any]]] = [
                (
                    "Installed updates (assets/{id}?include=InstalledUpdates)",
                    lambda: adapter.get_installed_updates(ident),
                ),
                ("Applied policies (devices/{id}/appliedpolicies)", lambda: adapter.get_applied_policies(ident)),
                ("Notifications (devices/{id}/notifications)", lambda: adapter.get_notifications(ident, 5)),
                ("Custom fields (devices/{id}/customfields)", lambda: adapter.get_custom_fields(ident)),
            ]
            for label, fn in checks:
                body = call(label, fn)
                if body is None:
                    continue
                if isinstance(body, dict):
                    inner = body.get("Data", body)
                    items = inner.get("InstalledUpdates") if isinstance(inner, dict) else None
                    count = len(items) if isinstance(items, list) else "section missing"
                    out.write(f"  {label}: OK, InstalledUpdates items: {count}")
                else:
                    out.write(f"  {label}: OK, {len(body)} item(s); fields: {', '.join(_keys(body)) or '-'}")

        out.write(f"\nAPI requests made: {adapter.client.request_count}")
        record_event(
            action="integration.probe",
            outcome="success" if not findings else "failure",
            actor_label="system:cli",
            target_type="integration_instance",
            target_id=str(inst.id),
            metadata={"organization": str(org), "devices": len(records), "findings": len(findings)},
        )
        out.write("\nFindings:")
        if findings:
            for f in findings:
                out.write(f"  - {f}")
        else:
            out.write("  - Every requested section came back with data.")
