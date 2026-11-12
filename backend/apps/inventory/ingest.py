"""Persist VSA1 detail sections and the org/site/group hierarchy for a staged generation (called by the sync engine)."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.integrations.vsa.schema import RecordInvalid, VsaAsset, normalize_device_ref, normalize_group, normalize_site

from .models import (
    AssetObservation,
    DiskObservation,
    GroupNode,
    IpAddressObservation,
    NetworkAdapterObservation,
    OrganizationNode,
    SectionStatus,
    SecurityObservation,
    SiteNode,
)
from .network import mac_is_locally_administered, parse_address

logger = logging.getLogger("portal.inventory")


def record_details(observation: AssetObservation, asset: VsaAsset) -> None:
    """Adapters/IPs, disks and security items for one observation. Absent sections stay ``not_collected``."""
    common = {
        "customer_id": observation.customer_id,
        "asset_id": observation.asset_id,
        "generation_id": observation.generation_id,
    }
    if asset.network_adapters is not None:
        observation.network_status = SectionStatus.COLLECTED
        for adapter in asset.network_adapters:
            nic = NetworkAdapterObservation.objects.create(
                observation=observation,
                name=adapter.name,
                mac=adapter.mac,
                mac_locally_administered=mac_is_locally_administered(adapter.mac),
                dhcp_enabled=adapter.dhcp_enabled,
                subnet_mask=adapter.subnet_mask,
                gateways=list(adapter.gateways),
                dns_servers=list(adapter.dns_servers),
                sources=sorted(adapter.sources),
                **common,
            )
            ips = []
            for raw in adapter.addresses:
                parsed = parse_address(
                    raw,
                    subnet_mask=adapter.subnet_mask,
                    mask_applies=bool(adapter.mask_address) and raw == adapter.mask_address,
                )
                ips.append(
                    IpAddressObservation(
                        adapter=nic,
                        raw=parsed.raw,
                        address=parsed.address,
                        zone=parsed.zone[:32],
                        version=parsed.version,
                        kind=parsed.kind,
                        prefix_length=parsed.prefix_length,
                        network_cidr=parsed.network_cidr,
                        cidr_status=parsed.cidr_status,
                        **common,
                    )
                )
            IpAddressObservation.objects.bulk_create(ips)
    if asset.disks is not None:
        observation.disks_status = SectionStatus.COLLECTED
        DiskObservation.objects.bulk_create(
            [
                DiskObservation(
                    observation=observation,
                    name=d.name,
                    is_system=d.is_system,
                    free_percentage=d.free_percentage,
                    total_value_raw=d.total_value_raw,
                    **common,
                )
                for d in asset.disks
            ]
        )
    if asset.security is not None:
        observation.security_status = SectionStatus.COLLECTED
        SecurityObservation.objects.bulk_create(
            [
                SecurityObservation(
                    observation=observation,
                    type=s.type,
                    name=s.name,
                    enabled=s.enabled,
                    up_to_date=s.up_to_date,
                    **common,
                )
                for s in asset.security
            ]
        )
    observation.public_ip = asset.public_ip
    observation.save(update_fields=["network_status", "disks_status", "security_status", "public_ip"])


def collect_hierarchy(run: Any, generation: Any, adapter: Any) -> None:
    """Sites, groups and the device list (group membership) for the run's single approved organisation.

    Records from other organisations are ignored (the filter already restricts them; this is defence in depth).
    Vendor errors propagate so the run fails or pauses exactly like the asset crawl.
    """
    org = run.mapping.external_org_id
    customer_id = run.customer_id
    sites, groups, devices = [], [], {}
    for page in adapter.iter_sites(org):
        for item in page.records:
            try:
                site = normalize_site(item)
            except RecordInvalid:
                continue
            if site.organization_id == org:
                sites.append(site)
    org_name = ""
    for page in adapter.iter_groups(org):
        for item in page.records:
            try:
                group = normalize_group(item)
            except RecordInvalid:
                continue
            if group.organization_id == org:
                groups.append(group)
                org_name = org_name or group.organization_name
    device_total = None
    for page in adapter.iter_devices(org):
        device_total = page.total_count
        for item in page.records:
            try:
                ref = normalize_device_ref(item)
            except RecordInvalid:
                continue
            if ref.organization_id == org:
                devices[ref.identifier] = ref

    with transaction.atomic():
        OrganizationNode.objects.get_or_create(
            generation=generation,
            external_id=org,
            defaults={"customer_id": customer_id, "name": org_name or run.mapping.external_org_name},
        )
        for site in sites:
            SiteNode.objects.get_or_create(
                generation=generation,
                external_id=site.id,
                defaults={"customer_id": customer_id, "name": site.name, "organization_external_id": org},
            )
        for group in groups:
            GroupNode.objects.get_or_create(
                generation=generation,
                external_id=group.id,
                defaults={
                    "customer_id": customer_id,
                    "name": group.name,
                    "is_active": group.is_active,
                    "site_external_id": group.site_id,
                    "organization_external_id": org,
                },
            )
        site_names = {s.id: s.name for s in sites}
        updated = []
        for obs in AssetObservation.objects.filter(generation=generation).select_related("asset"):
            ref = devices.get(obs.asset.external_id)
            if ref is None:
                obs.site_name = site_names.get(obs.site_external_id, "")
            else:
                obs.group_external_id = ref.group_id
                obs.site_name = site_names.get(obs.site_external_id, "") or ref.site_name
                obs.is_agent_installed = ref.is_agent_installed
                obs.is_mdm_enrolled = ref.is_mdm_enrolled
            updated.append(obs)
        AssetObservation.objects.bulk_update(
            updated, ["group_external_id", "site_name", "is_agent_installed", "is_mdm_enrolled"], batch_size=1000
        )
        asset_ids = {o.asset.external_id for o in updated}
        matched = sum(1 for d in devices if d in asset_ids)
        generation.hierarchy_status = SectionStatus.COLLECTED
        generation.device_list_count = len(devices) if device_total is None else device_total
        generation.devices_without_asset = len(devices) - matched
        generation.save(update_fields=["hierarchy_status", "device_list_count", "devices_without_asset"])
