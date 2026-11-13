"""Integration provider catalog: what an administrator must enter for each provider in the portal.

Every field marked ``secret`` is stored only inside the encrypted credential blob (``apps.integrations.secrets``).
Non-secret connection settings (the base URL / domain) live on the integration row because the egress policy must
read them on every request; they are not credentials.

Only providers with ``implemented=True`` accept credentials. Planned providers are listed so the Integrations page
shows the roadmap, but the portal does not collect secrets for a connector that does not exist yet (an unused secret
is only exposure). Auth fields follow docs/API_INTEGRATIONS.md; re-verify against the vendor docs when implementing.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_PRINTABLE_NO_SPACE = r"^[\x21-\x7e]+$"


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool
    max_length: int = 500
    pattern: str = _PRINTABLE_NO_SPACE
    pattern_message: str = "Printable characters only, no spaces."
    help: str = ""

    def validate(self, value: str) -> str | None:
        """Return an error message (never echoing the value) or ``None``."""
        if not value:
            return "Required."
        if len(value) > self.max_length:
            return f"At most {self.max_length} characters."
        if not re.match(self.pattern, value):
            return self.pattern_message
        return None


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    implemented: bool
    phase: str
    base_url_help: str
    fields: tuple[CredentialField, ...] = field(default_factory=tuple)
    notes: str = ""

    def as_dict(self) -> dict:
        data = asdict(self)
        for f in data["fields"]:
            f.pop("pattern", None)
        return data


PROVIDERS: dict[str, ProviderSpec] = {
    "vsa_x": ProviderSpec(
        key="vsa_x",
        label="Kaseya VSA X",
        implemented=True,
        phase="Phase 1 (available)",
        base_url_help="https://<your VSA X server>, e.g. https://yourcompany.vsax.net. Allow the hostname first.",
        fields=(
            CredentialField(
                "token_id",
                "Token ID",
                secret=False,
                max_length=200,
                pattern=r"^[\x21-\x39\x3b-\x7e]+$",
                pattern_message="Printable characters without spaces or ':'.",
                help="VSA X → Settings → API tokens. Use a token with read-only rights.",
            ),
            CredentialField(
                "token_secret", "Token secret", secret=True, help="Shown once by VSA X when the token is created."
            ),
        ),
        notes="Read-only GET calls only. Device moves stay disabled.",
    ),
    "itglue": ProviderSpec(
        key="itglue",
        label="IT Glue",
        implemented=False,
        phase="Planned (P3)",
        base_url_help="Regional API host: api.itglue.com, api.eu.itglue.com or api.au.itglue.com.",
        fields=(CredentialField("api_key", "API key", secret=True, help="Sent as the x-api-key header."),),
        notes="Passwords and secret resources will never be read.",
    ),
    "autotask": ProviderSpec(
        key="autotask",
        label="Autotask PSA",
        implemented=False,
        phase="Planned (P4)",
        base_url_help="Zone host from Autotask zoneInformation.",
        fields=(
            CredentialField("username", "API user name", secret=False, max_length=254),
            CredentialField("secret", "API user secret", secret=True),
            CredentialField("integration_code", "API tracking identifier", secret=True),
        ),
        notes="A dedicated read-only API user is required.",
    ),
    "tenable": ProviderSpec(
        key="tenable",
        label="Tenable",
        implemented=False,
        phase="Planned (later phase)",
        base_url_help="To be confirmed when the connector is designed.",
        fields=(
            CredentialField("access_key", "Access key", secret=True),
            CredentialField("secret_key", "Secret key", secret=True),
        ),
    ),
}


def spec_for(provider: str) -> ProviderSpec | None:
    return PROVIDERS.get(provider)


def validate_fields(provider: str, values: object) -> tuple[dict[str, str], dict[str, str]]:
    """Return (clean values, errors by field). Unknown fields are refused; values are stripped, never echoed."""
    spec = spec_for(provider)
    if spec is None or not spec.implemented:
        return {}, {"provider": "This provider's connector is not available yet; no credentials are stored for it."}
    if not isinstance(values, dict):
        return {}, {"fields": "Expected an object of field values."}
    errors: dict[str, str] = {}
    known = {f.name for f in spec.fields}
    for extra in sorted(set(values) - known):
        errors[str(extra)[:50]] = "Unknown field."
    clean: dict[str, str] = {}
    for f in spec.fields:
        raw = values.get(f.name, "")
        value = raw.strip() if isinstance(raw, str) else ""
        problem = f.validate(value)
        if problem:
            errors[f.name] = problem
        else:
            clean[f.name] = value
    return clean, errors
