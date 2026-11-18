"""Connector credentials: resolved at the moment of use, never returned by the API, logged, or put into task payloads.

Two sources, checked in this order:

1. **Entered in the portal** by a super admin (``IntegrationInstance.credential_ciphertext``): every credential field
   the provider needs (``providers.PROVIDERS``) is stored as ONE encrypted JSON blob. Encrypted with Fernet
   (AES-128-CBC + HMAC-SHA256) under ``CONNECTOR_ENCRYPTION_KEY``, which lives in a Docker secret file on the host and
   never in the database, so a database dump or backup alone does not reveal the token. The plaintext is bound to the
   integration's id, so a ciphertext copied onto another integration row does not decrypt.
2. ``credential_ref = "env:NAME"``: environment variable ``NAME`` or the file named by ``NAME_FILE`` (Docker secret).

A vault/KMS backend remains P5-02 (DEC-07).
"""

from __future__ import annotations

import json
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
# Connector credentials may only come from connector-named variables, never from the server's own secrets
# (DJANGO_SECRET_KEY, POSTGRES_PASSWORD, CONNECTOR_ENCRYPTION_KEY, ...), which would otherwise be sent to the vendor.
CONNECTOR_SECRET_PREFIXES = ("VSA_", "ITGLUE_", "AUTOTASK_")
READ_REF = re.compile(r"^env:(?:VSA|ITGLUE|AUTOTASK)_(?!WRITE_)[A-Z0-9_]{1,60}$")
WRITE_REF = re.compile(r"^env:VSA_WRITE_[A-Z0-9_]{1,50}$")
VAULT_REF = re.compile(r"^vault:[A-Za-z0-9_./-]{1,190}$")


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


def encrypt_fields(instance: IntegrationInstance, fields: dict[str, str]) -> str:
    """Encrypt ALL credential fields of an integration as one blob (secret and non-secret alike).

    Fields must already be validated (``providers.validate_fields``). The plaintext is bound to the integration id and
    provider, so a ciphertext copied onto another row does not decrypt.
    """
    plaintext = json.dumps(
        {"v": 2, "integration": str(instance.id), "provider": instance.provider, "fields": fields},
        separators=(",", ":"),
    )
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_fields(instance: IntegrationInstance) -> dict[str, str]:
    try:
        plaintext = _cipher().decrypt(instance.credential_ciphertext.encode()).decode()
    except CredentialStorageUnavailable as exc:
        raise CredentialUnavailable(str(exc)) from exc
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise CredentialUnavailable(
            "The stored credentials cannot be decrypted (encryption key changed?). Enter them again."
        ) from exc
    foreign = CredentialUnavailable("The stored credentials do not belong to this integration. Enter them again.")
    if plaintext.startswith("{"):
        try:
            data = json.loads(plaintext)
        except ValueError as exc:
            raise foreign from exc
        if (
            data.get("integration") != str(instance.id)
            or data.get("provider") != instance.provider
            or data.get("purpose", "read") != "read"  # a write-token blob is never the read credential
        ):
            raise foreign
        fields = data.get("fields")
        if not isinstance(fields, dict):
            raise foreign
        return {str(k): str(v) for k, v in fields.items()}
    # v1 (first release of portal-entered tokens): "<integration id>\n<token_id>:<token_secret>".
    bound_id, _, value = plaintext.partition("\n")
    if bound_id != str(instance.id) or ":" not in value:
        raise foreign
    token_id, token_secret = value.split(":", 1)
    return {"token_id": token_id, "token_secret": token_secret}


def resolve_secret(credential_ref: str) -> str:
    match = _ENV_REF.match(credential_ref or "")
    if not match:
        raise CredentialUnavailable("Unsupported or missing credential reference.")
    if not match.group(1).startswith(CONNECTOR_SECRET_PREFIXES):
        raise CredentialUnavailable("Credential references must name a VSA_, ITGLUE_ or AUTOTASK_ variable.")
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


def encrypt_write_token(instance: IntegrationInstance, token_id: str, token_secret: str) -> str:
    """The separate VSA X write token entered in the portal. Bound to the integration, provider AND purpose."""
    plaintext = json.dumps(
        {
            "v": 2,
            "integration": str(instance.id),
            "provider": instance.provider,
            "purpose": "write",
            "fields": {"token_id": token_id, "token_secret": token_secret},
        },
        separators=(",", ":"),
    )
    return _cipher().encrypt(plaintext.encode()).decode()


def has_write_credential(instance: IntegrationInstance) -> bool:
    """A write token is configured (portal-entered or a valid server reference). Does not decrypt or read it."""
    return bool(instance.write_credential_ciphertext) or bool(WRITE_REF.fullmatch(instance.write_credential_ref or ""))


def write_credential_source(instance: IntegrationInstance) -> str:
    if instance.write_credential_ciphertext:
        return "portal"
    if WRITE_REF.fullmatch(instance.write_credential_ref or ""):
        return "server"
    return "none"


def resolve_instance_write(instance: IntegrationInstance) -> BasicCredential:
    """The write token: portal-entered first, then the ``env:VSA_WRITE_*`` server reference."""
    if instance.write_credential_ciphertext:
        try:
            plaintext = _cipher().decrypt(instance.write_credential_ciphertext.encode()).decode()
            data = json.loads(plaintext)
        except CredentialStorageUnavailable as exc:
            raise CredentialUnavailable(str(exc)) from exc
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise CredentialUnavailable("The stored write token cannot be decrypted. Enter it again.") from exc
        fields = data.get("fields") if isinstance(data, dict) else None
        if (
            not isinstance(fields, dict)
            or data.get("integration") != str(instance.id)
            or data.get("provider") != instance.provider
            or data.get("purpose") != "write"
        ):
            raise CredentialUnavailable("The stored write token does not belong to this integration. Enter it again.")
        if not fields.get("token_id") or not fields.get("token_secret"):
            raise CredentialUnavailable("The stored write token is incomplete. Enter it again.")
        return BasicCredential(str(fields["token_id"]), str(fields["token_secret"]))
    if not WRITE_REF.fullmatch(instance.write_credential_ref or ""):
        raise CredentialUnavailable("No separate VSA X write token is configured.")
    return resolve_basic(instance.write_credential_ref)


def can_write(instance: IntegrationInstance) -> bool:
    """A token is available for writes: the optional separate write token, else the integration's own API token."""
    return has_write_credential(instance) or bool(instance.credential_ciphertext or instance.credential_ref)


def resolve_write_auth(instance: IntegrationInstance) -> BasicCredential:
    """The token used for writes: the separate write token when one is set, otherwise the integration's API token
    (product owner decision 2026-11-18: one token is enough; a separate token stays optional)."""
    if has_write_credential(instance):
        return resolve_instance_write(instance)
    return resolve_instance_basic(instance)


def resolve_instance_basic(instance: IntegrationInstance) -> BasicCredential:
    """The credential the connector should use: portal-entered first, then the server reference."""
    if instance.credential_ciphertext:
        fields = decrypt_fields(instance)
        if not fields.get("token_id") or not fields.get("token_secret"):
            raise CredentialUnavailable("The stored credentials are incomplete. Enter them again.")
        return BasicCredential(fields["token_id"], fields["token_secret"])
    return resolve_basic(instance.credential_ref)
