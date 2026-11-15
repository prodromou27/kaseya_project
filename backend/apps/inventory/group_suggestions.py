"""Source-scoped placement hints. Network evidence ranks above naming; never a move command."""

import ipaddress
import re
from collections import defaultdict

from django.db.models import Count

from .models import AssetObservation, ExpectedSubnet, GroupNode, GroupSetting, IpAddressObservation
from .network import CidrStatus, is_review_relevant

NOTE = (
    "Network evidence takes priority: approved group subnets, then subnets observed on destination devices, "
    "then naming hints. Observed networks and names are not approved placement policy. "
    "VPNs, multiple adapters and reused subnets can mislead. No match is not evidence of incorrect placement. "
    "Administrators transfer agents manually in VSA."
)
GENERIC_NAMES = {"desktop", "laptop", "server", "workstation", "workstations", "windows", "computer", "localhost"}


def onboarding(customer_id, instance_id, group_id):
    return GroupSetting.objects.filter(
        customer_id=customer_id, integration_instance_id=instance_id, group_external_id=group_id, is_onboarding=True
    ).exists()


def naming_prefix(hostname):
    """An explicit first naming token, never fuzzy matching or identity resolution."""
    token = re.split(r"[-_.\s]+", hostname.casefold())[0]
    token = re.sub(r"\d+$", "", token)
    return token if len(token) >= 3 and token.isalpha() and token not in GENERIC_NAMES else ""


class SuggestionContext:
    """Load destination evidence once for an entire page, not once per device."""

    def __init__(self, source):
        self.onboarding_ids = set(
            GroupSetting.objects.filter(
                customer_id=source.customer_id,
                integration_instance_id=source.generation.integration_instance_id,
                is_onboarding=True,
            ).values_list("group_external_id", flat=True)
        )
        self.groups = list(
            GroupNode.objects.filter(
                customer_id=source.customer_id,
                generation_id=source.generation_id,
                organization_external_id=source.organization_external_id,
                is_active=True,
            )
            .exclude(external_id__in=self.onboarding_ids | {source.group_external_id})
            .order_by("name", "external_id")
        )
        ids = [g.external_id for g in self.groups]
        self.networks = defaultdict(list)
        rules = ExpectedSubnet.objects.filter(
            customer_id=source.customer_id,
            integration_instance_id=source.generation.integration_instance_id,
            scope_type="group",
            scope_external_id__in=ids,
            state="approved",
        ).order_by("cidr")
        for rule in rules:
            self.add_network(rule.scope_external_id, rule.cidr, "approved_subnet")
        peers = AssetObservation.objects.filter(
            customer_id=source.customer_id,
            generation_id=source.generation_id,
            organization_external_id=source.organization_external_id,
            group_external_id__in=ids,
        )
        observed = (
            IpAddressObservation.objects.filter(
                customer_id=source.customer_id,
                generation_id=source.generation_id,
                adapter__observation__in=peers.filter(network_status="collected"),
                kind__in=["private", "public", "other"],
                cidr_status=CidrStatus.DERIVED,
            )
            .exclude(network_cidr="")
            .values("adapter__observation__group_external_id", "network_cidr")
            .annotate(devices=Count("asset_id", distinct=True))
            .order_by("network_cidr")
        )
        for row in observed:
            self.add_network(
                row["adapter__observation__group_external_id"], row["network_cidr"], "observed_subnet", row["devices"]
            )
        self.prefixes = defaultdict(set)
        for group_id, hostname in peers.values_list("group_external_id", "hostname").iterator():
            if prefix := naming_prefix(hostname):
                self.prefixes[group_id].add(prefix)

    def add_network(self, group_id, cidr, basis, devices=0):
        try:
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError:
            return
        if network.prefixlen == 0 or network.is_loopback or network.is_link_local or network.is_multicast:
            return
        self.networks[group_id].append((network, basis, devices))

    def evaluate(self, observation, ips):
        addresses = set()
        if observation.network_status == "collected":
            for ip in ips:
                if ip.address and is_review_relevant(ip.kind):
                    try:
                        addresses.add(ipaddress.ip_address(ip.address))
                    except ValueError:
                        continue
        prefix = naming_prefix(observation.hostname)
        candidates = []
        for group in self.groups:
            matches = []
            for network, basis, count in self.networks[group.external_id]:
                matched = sorted(str(ip) for ip in addresses if ip.version == network.version and ip in network)
                if matched:
                    matches.append({"cidr": str(network), "addresses": matched, "basis": basis, "peer_devices": count})
            group_tokens = set(re.findall(r"[a-z]+", group.name.casefold()))
            naming = []
            if prefix and prefix in group_tokens:
                naming.append(f"Device naming token '{prefix}' matches the group name.")
            if prefix and prefix in self.prefixes[group.external_id]:
                naming.append(f"Device naming token '{prefix}' matches existing destination device names.")
            if not matches and not naming:
                continue
            rank = 1 if any(m["basis"] == "approved_subnet" for m in matches) else 2 if matches else 3
            candidates.append(
                {
                    "id": str(group.id),
                    "name": group.name,
                    "external_id": group.external_id,
                    "site": group.site_external_id,
                    "basis": {1: "approved_subnet", 2: "observed_subnet", 3: "naming"}[rank],
                    "rank": rank,
                    "matches": matches,
                    "naming_evidence": naming,
                }
            )
        candidates.sort(key=lambda row: (row["rank"], row["name"].casefold(), row["external_id"]))
        return {
            "source_is_onboarding": observation.group_external_id in self.onboarding_ids,
            "suggestions": candidates,
            "suggestions_ambiguous": len(candidates) > 1,
            "suggestion_note": NOTE,
        }


def suggestions(observation):
    context = SuggestionContext(observation)
    ips = IpAddressObservation.objects.filter(customer_id=observation.customer_id, adapter__observation=observation)
    return context.evaluate(observation, ips)
