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
# Words that say nothing about placement when they appear in a group or site name.
NAME_STOPWORDS = GENERIC_NAMES | {
    "group",
    "groups",
    "site",
    "office",
    "users",
    "user",
    "devices",
    "pcs",
    "all",
    "main",
    "new",
    "old",
    "the",
    "and",
    "org",
    "demo",
    "servers",
    "laptops",
    "desktops",
}
MIN_PREFIX, MAX_PREFIX = 3, 12


def onboarding(customer_id, instance_id, group_id):
    return GroupSetting.objects.filter(
        customer_id=customer_id, integration_instance_id=instance_id, group_external_id=group_id, is_onboarding=True
    ).exists()


def naming_prefix(hostname):
    """The leading letters of a hostname ("DEPARTMENTUSERSX" -> "departmentusersx", "FIN-PC01" -> "fin").

    Naming conventions put the department or location first, so the start of the name is what is compared - never
    fuzzy matching or identity resolution. Generic names (DESKTOP-..., LAPTOP-...) give no evidence."""
    lead = re.match(r"[a-z]*", hostname.casefold()).group(0)
    if len(lead) < MIN_PREFIX or any(lead.startswith(g) for g in GENERIC_NAMES):
        return ""
    return lead


def _common(a, b):
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def peer_prefixes(hostnames):
    """Prefixes (3-12 letters) shared by at least half of a group's devices: {prefix: (devices, total)}."""
    leads = [naming_prefix(h) for h in hostnames]
    total = len(leads)
    counts = defaultdict(int)
    for lead in leads:
        for length in range(MIN_PREFIX, min(len(lead), MAX_PREFIX) + 1):
            counts[lead[:length]] += 1
    return {p: (c, total) for p, c in counts.items() if total and c * 2 >= total}


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
        hostnames = defaultdict(list)
        for group_id, hostname in peers.values_list("group_external_id", "hostname").iterator():
            hostnames[group_id].append(hostname)
        self.prefixes = {g: peer_prefixes(names) for g, names in hostnames.items()}
        from .models import SiteNode

        self.site_names = dict(
            SiteNode.objects.filter(customer_id=source.customer_id, generation_id=source.generation_id).values_list(
                "external_id", "name"
            )
        )

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
            naming, strength = [], 0
            if prefix:
                owned = [p for p in self.prefixes.get(group.external_id, {}) if prefix.startswith(p)]
                if owned:
                    best = max(owned, key=len)
                    count, total = self.prefixes[group.external_id][best]
                    strength = len(best)
                    naming.append(f"Name starts with '{best.upper()}' like {count} of {total} device(s) in this group.")
                site = self.site_names.get(group.site_external_id, "")
                for label, text in (("group", group.name), ("site", site)):
                    for word in re.findall(r"[a-z]+", (text or "").casefold()):
                        if len(word) < MIN_PREFIX or word in NAME_STOPWORDS:
                            continue
                        common = _common(prefix, word)
                        if common >= MIN_PREFIX:
                            strength = max(strength, common)
                            naming.append(
                                f"Name starts with '{prefix[:common].upper()}', the start of the {label} name '{text}'."
                            )
                            break
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
                    "naming_strength": strength,
                }
            )
        # Within the same evidence rank, a longer shared name prefix is stronger.
        candidates.sort(
            key=lambda row: (row["rank"], -row["naming_strength"], row["name"].casefold(), row["external_id"])
        )
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


def clear_winner(candidates):
    """The suggestion that beats every other one, or None when the evidence ties (an administrator decides)."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    a, b = candidates[0], candidates[1]
    if a["rank"] < b["rank"]:
        return a
    if a["rank"] == b["rank"] == 3 and a["naming_strength"] > b["naming_strength"]:
        return a
    return None


def plan(context, observations, ips_by_observation, site_names):
    """Group onboarding devices by their clearly best destination."""
    destinations, ambiguous, unmatched = {}, [], []
    for row in observations:
        result = context.evaluate(row, ips_by_observation.get(row.id, []))
        device = {"asset_id": str(row.asset_id), "hostname": row.hostname}
        winner = clear_winner(result["suggestions"])
        if winner is None and result["suggestions"]:
            ambiguous.append({**device, "candidates": [c["name"] for c in result["suggestions"][:4]]})
            continue
        if winner is None:
            unmatched.append(device)
            continue
        dest = destinations.setdefault(
            winner["external_id"],
            {
                "id": winner["id"],
                "external_id": winner["external_id"],
                "name": winner["name"],
                "site_external_id": winner["site"],
                "site_name": site_names.get(winner["site"], ""),
                "devices": [],
            },
        )
        evidence = [f"{m['cidr']} ({m['basis'].replace('_', ' ')})" for m in winner["matches"]] + winner[
            "naming_evidence"
        ]
        dest["devices"].append({**device, "basis": winner["basis"], "evidence": evidence[:2]})
    ordered = sorted(destinations.values(), key=lambda d: (-len(d["devices"]), d["site_name"], d["name"].casefold()))
    return {"destinations": ordered, "ambiguous": ambiguous, "unmatched": unmatched}
