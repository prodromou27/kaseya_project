"""Connector base-URL egress policy (SSRF defence, SECURITY.md §3, TESTING.md SEC-01).

Rules, applied whenever an administrator saves an integration instance:

* ``https`` only; no userinfo, query string or fragment; default port 443 unless explicitly allowed.
* Hostname must be on the per-provider allowlist from settings (exact match, case-insensitive).
* IP-literal hosts are rejected unless inside an administrator-approved private CIDR (on-prem VSA only).
* Link-local / loopback / metadata-service ranges are always rejected.

DNS-resolution checks at connection time (rebinding defence) are part of the collector HTTP client (P1/P5-02).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError

_ALWAYS_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. cloud metadata 169.254.169.254
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fd00:ec2::/32"),
]


def _approved_private_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(cidr, strict=False) for cidr in settings.CONNECTOR_APPROVED_PRIVATE_CIDRS]


def validate_connector_base_url(url: str, provider: str) -> str:
    """Validate and return a normalised base URL (no trailing slash) or raise ``ValidationError``."""
    if not url or len(url) > 500:
        raise ValidationError("A base URL is required (max 500 characters).")
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise ValidationError("Malformed URL.") from exc
    if parts.scheme != "https":
        raise ValidationError("Only https:// connector URLs are permitted.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValidationError("Credentials must not be embedded in the URL.")
    if parts.query or parts.fragment:
        raise ValidationError("Query strings and fragments are not permitted in a base URL.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValidationError("URL has no host.")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValidationError("Invalid port.") from exc
    if port not in (None, 443):
        raise ValidationError("Only the default HTTPS port (443) is permitted.")
    if parts.path not in ("", "/"):
        raise ValidationError("Base URL must not include a path; adapters append documented API paths.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if any(ip in net for net in _ALWAYS_BLOCKED_NETWORKS):
            raise ValidationError("Loopback, link-local and metadata-service addresses are blocked.")
        if provider != "vsa_x" or not any(ip in net for net in _approved_private_networks()):
            raise ValidationError("IP-literal hosts are only allowed for VSA X inside an approved private CIDR.")
        return f"https://{host}"

    allowed = {h.lower() for h in settings.CONNECTOR_ALLOWED_HOSTS.get(provider, [])}
    if host not in allowed:
        raise ValidationError(
            f"Host '{host}' is not on the approved {provider} connector allowlist. "
            "An operator must add it to the deployment configuration first."
        )
    return f"https://{host}"
