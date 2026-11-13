"""Connector credentials: resolved at the moment of use, never returned by the API, logged, or put into task payloads.

Two sources, checked in this order:

1. **Entered in the portal** by a super admin (``IntegrationInstance.credential_ciphertext``). Encrypted with Fernet
   (AES-128-CBC + HMAC-SHA256) under ``CONNECTOR_ENCRYPTION_KEY``, which lives in a Docker secret file on the host and
   never in the database, so a database dump or backup alone does not reveal the token. The plaintext is bound to the
   integration's id, so a ciphertext copied onto another integration row does not decrypt.
2. ``credential_ref = "env:NAME"``: environment variable ``NAME`` or the file named by ``NAME_FILE`` (Docker secret).

A vault/KMS backend remains P5-02 (DEC-07).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.env import env_str

if TYPE_CHECKING:
    from .models import IntegrationInstance

_ENV_REF = re.compile(r"^env:([A-Z][A-Z0-9_]{2,63})$")
# Printable ASCII without spaces; the VSA X token id must not contain ':' (it is the Basic auth separator).
_TOKEN_ID = re.compile(r"^[\x21-\x39\x3b-\x7e]{1,200}$")
_TOKEN_SECRET = re.compile(r"^[\x21-\x7e]{1,500}$")


class CredentialUnavailable(Exception):
    """Raised with a safe message; never includes the secret or its value."""


class CredentialStorageUnavailable(Exception):
    """The server has no CONNECTOR_ENCRYPTION_KEY, so credentials cannot be entered in the portal."""


@dataclass(frozen=True)
class BasicCredential:
    username: str
    password: str

    def __repr__(self) -> str:  # never print secrets
        return "BasicCredential(<redacted>)"


def _cipher() -> MultiFernet:
    keys = [k.strip() for k in (settings.CONNECTOR_ENCRYPTION_KEY or "").split(",") if k.strip()]
    if not keys:
        raise CredentialStorageUnavailable(
            "Credential storage is not configured on this server (CONNECTOR_ENCRYPTION_KEY). Run the installer or "
            "infra/almalinux/prepare-secrets.sh."
        )
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except ValueError as exc:  # malformed key: say so without echoing it
        raise CredentialStorageUnavailable("CONNECTOR_ENCRYPTION_KEY is not a valid key.") from exc


def storage_available() -> bool:
    try:
        _cipher()
    except CredentialStorageUnavailable:
        return False
    return True


def validate_token_pair(token_id: str, token_secret: str) -> None:
    """Raise ValueError with a safe message (never the value)."""
    if not _TOKEN_ID.match(token_id or ""):
        raise ValueError("Token ID must be 1-200 printable characters without spaces or ':'.")
    if not _TOKEN_SECRET.match(token_secret or ""):
        raise ValueError("Token secret must be 1-500 printable characters without spaces.")


def encrypt_for(instance: IntegrationInstance, token_id: str, token_secret: str) -> str:
    validate_token_pair(token_id, token_secret)
    plaintext = f"{instance.id}\n{token_id}:{token_secret}"
    return _cipher().encrypt(plaintext.encode()).decode()


def _decrypt_for(instance: IntegrationInstance) -> str:
    try:
        plaintext = _cipher().decrypt(instance.credential_ciphertext.encode()).decode()
    except CredentialStorageUnavailable as exc:
        raise CredentialUnavailable(str(exc)) from exc
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise CredentialUnavailable(
            "The stored credential cannot be decrypted (encryption key changed?). Enter the API token again."
        ) from exc
    bound_id, _, value = plaintext.partition("\n")
    if bound_id != str(instance.id) or not value:
        raise CredentialUnavailable("The stored credential does not belong to this integration. Enter it again.")
    return value


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


def _split_basic(raw: str) -> BasicCredential:
    """``TOKEN_ID:TOKEN_SECRET`` stored as one secret value (VSA X Basic auth)."""
    if ":" not in raw:
        raise CredentialUnavailable("Credential must be in the form TOKEN_ID:TOKEN_SECRET.")
    username, password = raw.split(":", 1)
    if not username or not password:
        raise CredentialUnavailable("Credential must be in the form TOKEN_ID:TOKEN_SECRET.")
    return BasicCredential(username, password)


def resolve_basic(credential_ref: str) -> BasicCredential:
    return _split_basic(resolve_secret(credential_ref))


def credential_source(instance: IntegrationInstance) -> str:
    if instance.credential_ciphertext:
        return "portal"
    if instance.credential_ref:
        return "server"
    return "none"


def resolve_instance_basic(instance: IntegrationInstance) -> BasicCredential:
    """The credential the connector should use: portal-entered first, then the server reference."""
    if instance.credential_ciphertext:
        return _split_basic(_decrypt_for(instance))
    return resolve_basic(instance.credential_ref)
