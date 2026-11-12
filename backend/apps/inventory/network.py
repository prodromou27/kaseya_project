"""Pure network derivations for reported VSA adapter data (VSA1-04 / VSA2-05). No database access.

Rules (docs/GROUP_NETWORK_AND_MOVES.md):
* A subnet (CIDR) is derived **only** from a valid IPv4 address together with the valid, contiguous SubnetMask that
  VSA reported for that same address. Anything else is ``prefix_not_reported`` / ``invalid_mask`` — never guessed.
* IPv6 prefixes are not reported by the documented fields, so IPv6 networks are never derived.
* These are reported facts per device, not discovered topology, VLANs or authoritative subnets.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass


class CidrStatus:
    DERIVED = "derived"
    PREFIX_NOT_REPORTED = "prefix_not_reported"
    INVALID_MASK = "invalid_mask"
    NOT_APPLICABLE = "not_applicable"  # loopback / unspecified


@dataclass(frozen=True)
class ParsedAddress:
    raw: str
    address: str  # canonical compressed form, zone removed; "" when unparseable
    zone: str
    version: int | None
    kind: str  # private | public | link_local | loopback | unspecified | multicast | other | invalid
    prefix_length: int | None
    network_cidr: str
    cidr_status: str


def _kind(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_private:
        return "private"
    if ip.is_global:
        return "public"
    return "other"


def mask_prefix(mask: str) -> int | None:
    """Prefix length for a dotted IPv4 netmask, or None if absent/non-contiguous/invalid."""
    if not mask:
        return None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except (ValueError, ipaddress.NetmaskValueError):
        return None


def parse_address(raw: str, *, subnet_mask: str = "", mask_applies: bool = False) -> ParsedAddress:
    text = (raw or "").strip()
    address_part, _, zone = text.partition("%")
    try:
        ip = ipaddress.ip_address(address_part)
    except ValueError:
        return ParsedAddress(text, "", "", None, "invalid", None, "", CidrStatus.PREFIX_NOT_REPORTED)
    kind = _kind(ip)
    if kind in ("loopback", "unspecified"):
        return ParsedAddress(text, ip.compressed, zone, ip.version, kind, None, "", CidrStatus.NOT_APPLICABLE)
    if ip.version == 4 and mask_applies and subnet_mask:
        prefix = mask_prefix(subnet_mask)
        if prefix is None:
            return ParsedAddress(text, ip.compressed, zone, 4, kind, None, "", CidrStatus.INVALID_MASK)
        network = ipaddress.IPv4Interface(f"{ip}/{prefix}").network
        return ParsedAddress(text, ip.compressed, zone, 4, kind, prefix, str(network), CidrStatus.DERIVED)
    return ParsedAddress(text, ip.compressed, zone, ip.version, kind, None, "", CidrStatus.PREFIX_NOT_REPORTED)


def mac_is_locally_administered(mac: str) -> bool:
    """Bit 1 of the first octet set ⇒ locally administered (typical of virtual/randomised adapters)."""
    if len(mac) != 12:
        return False
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


def is_review_relevant(kind: str) -> bool:
    """Addresses worth comparing across devices (duplicate review). Link-local/loopback collide by design."""
    return kind in ("private", "public", "other")
