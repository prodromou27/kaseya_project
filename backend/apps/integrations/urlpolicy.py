"""Connector base-URL egress policy (SSRF defence, SECURITY.md §3, TESTING.md SEC-01).

Rules, applied whenever an administrator saves an integration instance:

* ``https`` only; no userinfo, query string or fragment; default port 443 unless explicitly allowed.
* Hostname must be on the per-provider allowlist: the deployment settings plus hosts a super admin approved in the
  portal (``ConnectorHost``). Exact match, case-insensitive.
* IP-literal hosts are rejected unless inside an administrator-approved private CIDR (on-prem VSA only).
* Link-local / loopback / metadata-service ranges are always rejected.

DNS-resolution checks at connection time (rebinding defence) are part of the collector HTTP client (P1/P5-02).
"""

from __future__ import annotations

import ipaddress
import re
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

    if not is_host_allowed(host, provider):
        raise ValidationError(
            f"Host '{host}' is not on the approved {provider} connector allowlist. "
            "A super admin must add it under Admin → Integrations → Allowed API hosts first."
        )
    return f"https://{host}"


def is_host_allowed(host: str, provider: str) -> bool:
    host = host.lower().rstrip(".")
    if host in {h.lower() for h in settings.CONNECTOR_ALLOWED_HOSTS.get(provider, [])}:
        return True
    from .models import ConnectorHost  # local import: models import this module

    return ConnectorHost.objects.filter(provider=provider, hostname=host).exists()


_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME = re.compile(rf"^(?:{_LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?$")


def normalize_api_hostname(raw: str) -> str:
    """Validate a hostname an administrator wants to allow. Returns it lower-cased or raises ``ValidationError``."""
    value = (raw or "").strip().lower()
    if value.startswith("https://"):
        value = value[len("https://") :]
    value = value.rstrip("/").rstrip(".")
    if not value or len(value) > 253:
        raise ValidationError("Enter a hostname such as vsa.example.com.")
    if "*" in value:
        raise ValidationError("Wildcards are not allowed: add each exact hostname.")
    if any(c in value for c in "/:@?#") or " " in value:
        raise ValidationError("Enter only the hostname (no scheme, port, path or credentials).")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValidationError("IP addresses cannot be allowed here; use the VSA server's DNS name.")
    if value == "localhost" or value.endswith((".localhost", ".local", ".internal", ".invalid", ".test")):
        raise ValidationError("Local, internal and reserved names cannot be allowed.")
    if not _HOSTNAME.match(value):
        raise ValidationError("That is not a valid hostname.")
    return value
