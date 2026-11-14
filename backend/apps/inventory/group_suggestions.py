"""Conservative, source-scoped hints from reviewed portal subnet rules. Never a move command."""

import ipaddress

from .models import ExpectedSubnet, GroupSetting, IpAddressObservation
from .network import is_review_relevant


def onboarding(customer_id, instance_id, group_id):
    return GroupSetting.objects.filter(
        customer_id=customer_id, integration_instance_id=instance_id, group_external_id=group_id, is_onboarding=True
    ).exists()


def suggestions(observation, groups):
    groups = list(groups)
    instance_id = observation.generation.integration_instance_id
    addresses = []
    for ip in IpAddressObservation.objects.filter(
        customer_id=observation.customer_id, adapter__observation=observation
    ):
        if ip.address and is_review_relevant(ip.kind):
            try:
                addresses.append(ipaddress.ip_address(ip.address))
            except ValueError:
                continue
    rules = ExpectedSubnet.objects.filter(
        customer_id=observation.customer_id,
        integration_instance_id=instance_id,
        scope_type="group",
        scope_external_id__in=[g.external_id for g in groups],
        state="approved",
    )
    onboarding_ids = set(
        GroupSetting.objects.filter(
            customer_id=observation.customer_id,
            integration_instance_id=instance_id,
            is_onboarding=True,
        ).values_list("group_external_id", flat=True)
    )
    matches = {}
    for rule in rules:
        if rule.scope_external_id in onboarding_ids:
            continue
        try:
            network = ipaddress.ip_network(rule.cidr, strict=True)
        except ValueError:
            continue  # Legacy malformed evidence must never produce a recommendation.
        ips = sorted({str(ip) for ip in addresses if ip.version == network.version and ip in network})
        if ips:
            matches.setdefault(rule.scope_external_id, []).append({"cidr": rule.cidr, "addresses": ips})
    return {
        "source_is_onboarding": onboarding(observation.customer_id, instance_id, observation.group_external_id),
        "suggestions": [
            {"id": str(g.id), "name": g.name, "external_id": g.external_id, "matches": matches[g.external_id]}
            for g in groups
            if g.external_id in matches
        ],
        "suggestions_ambiguous": len(matches) > 1,
        "suggestion_note": "CIDR matches are advisory. VPNs, multiple adapters and reused subnets can mislead. "
        "No match is not evidence of incorrect placement. Administrators transfer agents manually in VSA.",
    }
