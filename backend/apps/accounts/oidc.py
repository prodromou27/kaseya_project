"""OpenID Connect (authorization code + PKCE) relying-party implementation.

Targets Microsoft Entra ID in production (P5-01) but is provider-agnostic and fully testable against a mock
IdP via an injectable HTTP transport. Validates: discovery issuer match, ``state`` (constant-time), PKCE,
ID-token signature from JWKS (RS256 only), ``iss``, ``aud``, ``exp``/``iat``, ``nonce`` and optional ``amr``.

Not yet validated against a real Entra tenant — that is UAT evidence required by P5-01.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

import jwt
import requests
from django.core.cache import cache

SESSION_KEY = "okp_oidc_flow"
FLOW_MAX_AGE_SECONDS = 600
ALLOWED_ALGORITHMS = ["RS256"]
HTTP_TIMEOUT_SECONDS = 10


class OIDCError(Exception):
    """Authentication failed. ``code`` is safe to show; details are never returned to the browser."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class HttpTransport(Protocol):
    def get_json(self, url: str) -> dict[str, Any]: ...

    def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]: ...


class RequestsTransport:
    """Real transport: TLS verification always on, short timeouts, no redirects followed for token calls."""

    def get_json(self, url: str) -> dict[str, Any]:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=False)
        resp.raise_for_status()
        return resp.json()

    def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        resp = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SECONDS, allow_redirects=False)
        resp.raise_for_status()
        return resp.json()


@dataclass(frozen=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _require_https(url: str) -> str:
    if urlsplit(url).scheme != "https":
        raise OIDCError("insecure_endpoint")
    return url


class OIDCClient:
    def __init__(self, config: dict[str, Any], transport: HttpTransport | None = None):
        self.config = config
        self.transport = transport or RequestsTransport()

    # -- discovery -----------------------------------------------------------------------------------
    def metadata(self) -> ProviderMetadata:
        cache_key = "oidc_metadata:" + hashlib.sha256(self.config["ISSUER"].encode()).hexdigest()
        cached = cache.get(cache_key)
        if cached:
            return ProviderMetadata(**cached)
        issuer = self.config["ISSUER"].rstrip("/")
        try:
            doc = self.transport.get_json(f"{issuer}/.well-known/openid-configuration")
        except Exception as exc:
            raise OIDCError("discovery_failed") from exc
        if str(doc.get("issuer", "")).rstrip("/") != issuer:
            raise OIDCError("issuer_mismatch")
        meta = ProviderMetadata(
            issuer=doc["issuer"],
            authorization_endpoint=_require_https(doc["authorization_endpoint"]),
            token_endpoint=_require_https(doc["token_endpoint"]),
            jwks_uri=_require_https(doc["jwks_uri"]),
        )
        cache.set(cache_key, meta.__dict__, 3600)
        return meta

    # -- step 1: redirect to IdP -------------------------------------------------------------------
    def begin(self, session: Any) -> str:
        meta = self.metadata()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        session[SESSION_KEY] = {"state": state, "nonce": nonce, "verifier": verifier, "ts": time.time()}
        params = {
            "response_type": "code",
            "client_id": self.config["CLIENT_ID"],
            "redirect_uri": self.config["REDIRECT_URI"],
            "scope": self.config["SCOPES"],
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{meta.authorization_endpoint}?{urlencode(params)}"

    # -- step 2: callback ----------------------------------------------------------------------------
    def complete(self, session: Any, params: dict[str, str]) -> dict[str, Any]:
        flow = session.pop(SESSION_KEY, None)
        if not flow or time.time() - float(flow.get("ts", 0)) > FLOW_MAX_AGE_SECONDS:
            raise OIDCError("flow_expired")
        if params.get("error"):
            raise OIDCError("idp_error")
        if not hmac.compare_digest(str(params.get("state", "")), str(flow["state"])):
            raise OIDCError("state_mismatch")
        code = params.get("code")
        if not code:
            raise OIDCError("missing_code")
        meta = self.metadata()
        try:
            tokens = self.transport.post_form(
                meta.token_endpoint,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.config["REDIRECT_URI"],
                    "client_id": self.config["CLIENT_ID"],
                    "client_secret": self.config["CLIENT_SECRET"],
                    "code_verifier": flow["verifier"],
                },
            )
        except Exception as exc:
            raise OIDCError("token_exchange_failed") from exc
        id_token = tokens.get("id_token")
        if not id_token:
            raise OIDCError("missing_id_token")
        return self.validate_id_token(id_token, expected_nonce=flow["nonce"], meta=meta)

    def validate_id_token(self, id_token: str, *, expected_nonce: str, meta: ProviderMetadata) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OIDCError("invalid_token") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise OIDCError("invalid_algorithm")
        try:
            jwks = self.transport.get_json(meta.jwks_uri)
            keyset = jwt.PyJWKSet.from_dict(jwks)
        except Exception as exc:
            raise OIDCError("jwks_failed") from exc
        kid = header.get("kid")
        key = next((k for k in keyset.keys if k.key_id == kid), None)
        if key is None:
            raise OIDCError("unknown_signing_key")
        try:
            claims = jwt.decode(
                id_token,
                key=key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self.config["CLIENT_ID"],
                issuer=meta.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
                leeway=60,
            )
        except jwt.PyJWTError as exc:
            raise OIDCError("invalid_token") from exc
        if not hmac.compare_digest(str(claims.get("nonce", "")), expected_nonce):
            raise OIDCError("nonce_mismatch")
        required_amr = set(self.config.get("REQUIRED_AMR") or [])
        if required_amr and not required_amr.issubset(set(claims.get("amr") or [])):
            raise OIDCError("mfa_required")
        return claims


def provision_user(claims: dict[str, Any], config: dict[str, Any]) -> Any:
    """Find (or, if allowed, create without any grants) the portal user for a validated OIDC identity.

    Users are matched only by (issuer, subject) — never by email — so an IdP email change or a colliding
    email cannot take over an existing account.
    """
    from .models import User

    issuer, subject = str(claims["iss"]), str(claims["sub"])
    user = User.objects.filter(oidc_issuer=issuer, oidc_subject=subject).first()
    if user is not None:
        if not user.is_active:
            raise OIDCError("account_disabled")
        return user
    if not config.get("AUTO_PROVISION"):
        raise OIDCError("account_not_provisioned")
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email or "@" not in email:
        raise OIDCError("missing_email")
    if User.objects.filter(email__iexact=email).exists():
        # An account with this email exists but is not linked to this identity: require admin action.
        raise OIDCError("account_link_required")
    return User.objects.create_user(
        email=email,
        display_name=str(claims.get("name", ""))[:200],
        auth_source=User.AuthSource.OIDC,
        oidc_issuer=issuer,
        oidc_subject=subject,
    )
