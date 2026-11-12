"""Resolve a connector ``credential_ref`` to a secret value at the moment of use.

Supported reference schemes (P1). A vault/KMS backend is P5-02 (DEC-07):

* ``env:NAME`` — reads environment variable ``NAME`` or the file named by ``NAME_FILE`` (Docker secret).

Secrets are never stored in the database, returned by the API, logged, or put into task payloads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from config.env import env_str

_ENV_REF = re.compile(r"^env:([A-Z][A-Z0-9_]{2,63})$")


class CredentialUnavailable(Exception):
    """Raised with a safe message; never includes the secret or its value."""


@dataclass(frozen=True)
class BasicCredential:
    username: str
    password: str

    def __repr__(self) -> str:  # never print secrets
        return "BasicCredential(<redacted>)"


def resolve_secret(credential_ref: str) -> str:
    match = _ENV_REF.match(credential_ref or "")
    if not match:
        raise CredentialUnavailable("Unsupported or missing credential reference.")
    try:
        value = env_str(match.group(1), "")
    except (OSError, ImproperlyConfigured) as exc:
        raise CredentialUnavailable("Credential could not be read.") from exc
    if not value:
        raise CredentialUnavailable("Credential reference resolved to an empty value.")
    return value


def resolve_basic(credential_ref: str) -> BasicCredential:
    """``TOKEN_ID:TOKEN_SECRET`` stored as one secret value (VSA X Basic auth)."""
    raw = resolve_secret(credential_ref)
    if ":" not in raw:
        raise CredentialUnavailable("Credential must be in the form TOKEN_ID:TOKEN_SECRET.")
    username, password = raw.split(":", 1)
    if not username or not password:
        raise CredentialUnavailable("Credential must be in the form TOKEN_ID:TOKEN_SECRET.")
    return BasicCredential(username, password)
