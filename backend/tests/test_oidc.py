"""P0-04 OIDC contract tests against a mock IdP (no real Entra tenant — that is P5-01 UAT evidence)."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from apps.accounts import oidc
from apps.accounts.models import User
from apps.audit.models import AuditEvent

from .factories import UserFactory

pytestmark = pytest.mark.django_db

ISSUER = "https://login.mock-idp.test/tenant/v2.0"
CLIENT_ID = "portal-client"


class MockIdP:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "kid-1"
        self.next_claims: dict[str, Any] = {}
        self.sign_with = self.key
        self.alg = "RS256"
        self.token_requests: list[dict[str, str]] = []

    def jwks(self) -> dict[str, Any]:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def get_json(self, url: str) -> dict[str, Any]:
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": "https://login.mock-idp.test/authorize",
                "token_endpoint": "https://login.mock-idp.test/token",
                "jwks_uri": "https://login.mock-idp.test/keys",
            }
        if url.endswith("/keys"):
            return self.jwks()
        raise AssertionError(url)

    def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        self.token_requests.append(data)
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "subject-123",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "email": "Jane.Doe@Example.test",
            "name": "Jane Doe",
        }
        claims.update(self.next_claims)
        claims = {k: v for k, v in claims.items() if v is not None}
        if self.alg == "HS256":
            return {
                "id_token": jwt.encode(
                    claims, "shared-secret-value-long-enough-123", algorithm="HS256", headers={"kid": self.kid}
                )
            }
        return {"id_token": jwt.encode(claims, self.sign_with, algorithm="RS256", headers={"kid": self.kid})}


@pytest.fixture
def idp(settings, monkeypatch) -> MockIdP:
    settings.OIDC = {
        "ENABLED": True,
        "ISSUER": ISSUER,
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET": "client-secret-value",
        "REDIRECT_URI": "https://portal.test/api/v1/auth/oidc/callback/",
        "SCOPES": "openid email profile",
        "AUTO_PROVISION": True,
        "REQUIRED_AMR": [],
        "POST_LOGIN_REDIRECT": "/",
    }
    mock = MockIdP()
    original_init = oidc.OIDCClient.__init__

    def init(self: oidc.OIDCClient, config: dict[str, Any], transport: Any = None) -> None:
        original_init(self, config, transport=mock)

    monkeypatch.setattr(oidc.OIDCClient, "__init__", init)
    return mock


def _begin(client: APIClient, idp: MockIdP) -> dict[str, str]:
    resp = client.get("/api/v1/auth/oidc/login/")
    assert resp.status_code == 302
    query = {k: v[0] for k, v in parse_qs(urlsplit(resp["Location"]).query).items()}
    assert query["code_challenge_method"] == "S256"
    assert query["client_id"] == CLIENT_ID
    idp.nonce = query["nonce"]
    return query


def test_successful_oidc_login_provisions_user_without_grants(idp):
    client = APIClient()
    q = _begin(client, idp)
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": q["state"]})
    assert resp.status_code == 302 and resp["Location"] == "/"
    user = User.objects.get(oidc_subject="subject-123")
    assert user.email == "jane.doe@example.test" and user.auth_source == "oidc"
    assert user.global_role is None and not user.memberships.exists()
    assert not user.has_usable_password()
    assert idp.token_requests[0]["code_verifier"]  # PKCE verifier sent
    me = client.get("/api/v1/auth/me/").json()
    assert me["memberships"] == []
    assert AuditEvent.objects.filter(action="auth.login", outcome="success", actor=user).exists()


def test_existing_identity_matched_by_issuer_and_subject_not_email(idp):
    existing = UserFactory(email="old@example.test", auth_source="oidc", oidc_issuer=ISSUER, oidc_subject="subject-123")
    client = APIClient()
    q = _begin(client, idp)
    client.get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": q["state"]})
    assert client.get("/api/v1/auth/me/").json()["id"] == str(existing.id)


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda idp: idp.next_claims.update(aud="another-client"), "invalid_token"),
        (lambda idp: idp.next_claims.update(iss="https://evil.test"), "invalid_token"),
        (lambda idp: idp.next_claims.update(exp=int(time.time()) - 3600), "invalid_token"),
        (lambda idp: idp.next_claims.update(nonce="replayed-nonce"), "nonce_mismatch"),
        (lambda idp: idp.next_claims.update(nonce=None), "invalid_token"),
        (lambda idp: setattr(idp, "sign_with", idp.other_key), "invalid_token"),
        (lambda idp: setattr(idp, "kid", "unknown") or None, "unknown_signing_key"),
        (lambda idp: setattr(idp, "alg", "HS256"), "invalid_algorithm"),
    ],
)
def test_invalid_id_tokens_are_rejected(idp, mutate, expected_error):
    client = APIClient()
    q = _begin(client, idp)
    if expected_error == "unknown_signing_key":
        # Sign with a kid the JWKS does not publish.
        original_post = idp.post_form

        def post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
            token = original_post(url, data)["id_token"]
            claims = jwt.decode(token, options={"verify_signature": False})
            return {"id_token": jwt.encode(claims, idp.key, algorithm="RS256", headers={"kid": "unknown"})}

        idp.post_form = post_form  # type: ignore[method-assign]
    else:
        mutate(idp)
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": q["state"]})
    assert resp.status_code == 302
    assert resp["Location"] == f"/login?error={expected_error}"
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert not User.objects.exists()


def test_state_mismatch_rejected(idp):
    client = APIClient()
    _begin(client, idp)
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": "forged"})
    assert resp["Location"] == "/login?error=state_mismatch"
    assert not idp.token_requests  # no code exchange on bad state


def test_callback_without_flow_rejected(idp):
    resp = APIClient().get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": "x"})
    assert resp["Location"] == "/login?error=flow_expired"


def test_state_cannot_be_replayed(idp):
    client = APIClient()
    q = _begin(client, idp)
    client.get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": q["state"]})
    client.post("/api/v1/auth/logout/")
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "abc", "state": q["state"]})
    assert resp["Location"] == "/login?error=flow_expired"


def test_required_amr_enforced(idp, settings):
    settings.OIDC = {**settings.OIDC, "REQUIRED_AMR": ["mfa"]}
    client = APIClient()
    q = _begin(client, idp)
    idp.next_claims.update(amr=["pwd"])
    assert client.get("/api/v1/auth/oidc/callback/", {"code": "a", "state": q["state"]})["Location"].endswith(
        "mfa_required"
    )
    q = _begin(client, idp)
    idp.next_claims.update(amr=["pwd", "mfa"])
    assert client.get("/api/v1/auth/oidc/callback/", {"code": "a", "state": q["state"]})["Location"] == "/"


def test_auto_provision_disabled_denies_unknown_identity(idp, settings):
    settings.OIDC = {**settings.OIDC, "AUTO_PROVISION": False}
    client = APIClient()
    q = _begin(client, idp)
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "a", "state": q["state"]})
    assert resp["Location"] == "/login?error=account_not_provisioned"


def test_email_collision_requires_admin_link(idp):
    UserFactory(email="jane.doe@example.test")  # local account with same email: must NOT be taken over
    client = APIClient()
    q = _begin(client, idp)
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "a", "state": q["state"]})
    assert resp["Location"] == "/login?error=account_link_required"


def test_disabled_oidc_user_denied(idp):
    UserFactory(
        email="j@example.test", auth_source="oidc", oidc_issuer=ISSUER, oidc_subject="subject-123", is_active=False
    )
    client = APIClient()
    q = _begin(client, idp)
    resp = client.get("/api/v1/auth/oidc/callback/", {"code": "a", "state": q["state"]})
    assert resp["Location"] == "/login?error=account_disabled"


def test_discovery_issuer_mismatch_fails_closed(idp, monkeypatch):
    original = idp.get_json
    monkeypatch.setattr(idp, "get_json", lambda url: {**original(url), "issuer": "https://evil.test"})
    resp = APIClient().get("/api/v1/auth/oidc/login/")
    assert resp["Location"] == "/login?error=sso_unavailable"


def test_oidc_disabled_returns_403(settings):
    settings.OIDC = {**settings.OIDC, "ENABLED": False}
    assert APIClient().get("/api/v1/auth/oidc/login/").status_code == 403
