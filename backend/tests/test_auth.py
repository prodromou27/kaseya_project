"""P0-04 identity & sessions; TESTING.md AUTH-01."""

from __future__ import annotations

import time

import pytest
from django.core.management import CommandError, call_command
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from apps.accounts.middleware import AUTH_AT_SESSION_KEY
from apps.accounts.models import User
from apps.audit.models import AuditEvent

from .factories import TEST_PASSWORD, UserFactory, role

pytestmark = pytest.mark.django_db

PUBLIC_ROUTES = {
    "health-live",
    "health-ready",
    "auth-config",
    "auth-login",
    "oidc-login",
    "oidc-callback",
}


def _iter_api_routes(resolver: URLResolver | None = None, prefix: str = ""):
    resolver = resolver or get_resolver()
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            yield from _iter_api_routes(p, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _concrete(path: str) -> str:
    import re

    path = re.sub(r"<str:customer_pk>", "11111111-1111-1111-1111-111111111111", path)
    path = re.sub(r"\(\?P<pk>\[\^/\.\]\+\)", "22222222-2222-2222-2222-222222222222", path)
    path = re.sub(r"\(\?P<format>[^)]*\)", "", path)
    return "/" + path.replace("^", "").replace("$", "").replace("\\.", ".").replace("\\", "")


def test_every_non_public_api_route_rejects_anonymous_requests():
    """AUTH-01: anonymous requests to any non-public route return 401 with no data."""
    client = APIClient()
    checked = 0
    for raw, pattern in _iter_api_routes():
        if not raw.startswith("api/v1/") or pattern.name in PUBLIC_ROUTES or "format" in raw:
            continue
        url = _concrete(raw)
        for method in ("get", "post", "patch", "delete"):
            resp = getattr(client, method)(url)
            if resp.status_code == 405:
                continue
            assert resp.status_code == 401, f"{method.upper()} {url} -> {resp.status_code}"
            if resp["Content-Type"].startswith("application/json"):
                assert set(resp.json()) == {"error"}
            checked += 1
    assert checked > 20


def test_every_view_is_authenticated_or_explicitly_public():
    from rest_framework.permissions import AllowAny

    for raw, pattern in _iter_api_routes():
        if not raw.startswith("api/v1/"):
            continue
        cls = getattr(pattern.callback, "cls", None)
        if cls is None:
            continue
        perms = getattr(cls, "permission_classes", [])
        if AllowAny in perms:
            assert getattr(cls, "public_endpoint", False), f"{cls.__name__} is AllowAny but not marked public"
            assert pattern.name in PUBLIC_ROUTES, f"{raw} unexpectedly public"


def test_local_login_success_creates_session_and_audits(client_csrf):
    user = UserFactory(email="login@example.test")
    resp = client_csrf.post("/api/v1/auth/login/", {"email": "LOGIN@example.test", "password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.content
    assert resp.json()["email"] == "login@example.test"
    cookie = resp.cookies["okp_session"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert AuditEvent.objects.filter(action="auth.login", outcome="success", actor=user).exists()
    assert client_csrf.get("/api/v1/auth/me/").status_code == 200


def test_local_login_failure_is_generic_and_audited(client_csrf):
    UserFactory(email="login@example.test")
    resp = client_csrf.post("/api/v1/auth/login/", {"email": "login@example.test", "password": "wrong-password-123"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_credentials"
    resp2 = client_csrf.post("/api/v1/auth/login/", {"email": "missing@example.test", "password": "x" * 20})
    assert resp2.json()["error"]["message"] == resp.json()["error"]["message"]
    assert AuditEvent.objects.filter(action="auth.login", outcome="failure").count() == 2
    assert not AuditEvent.objects.filter(metadata__has_key="password").exists()


def test_login_requires_csrf_token():
    UserFactory(email="login@example.test")
    client = APIClient(enforce_csrf_checks=True)
    resp = client.post("/api/v1/auth/login/", {"email": "login@example.test", "password": TEST_PASSWORD}, format="json")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["error"]["message"]


def test_authenticated_mutation_requires_csrf(world):
    from .conftest import login

    client = login(APIClient(enforce_csrf_checks=True), world.super_admin)
    resp = client.post("/api/v1/customers/", {"code": "NEWCO", "name": "New Co"}, format="json")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["error"]["message"]


def test_inactive_user_cannot_log_in(client_csrf):
    UserFactory(email="off@example.test", is_active=False)
    resp = client_csrf.post("/api/v1/auth/login/", {"email": "off@example.test", "password": TEST_PASSWORD})
    assert resp.status_code == 400


def test_oidc_user_cannot_use_local_password(client_csrf):
    user = UserFactory(
        email="sso@example.test", auth_source=User.AuthSource.OIDC, oidc_issuer="https://idp", oidc_subject="s1"
    )
    user.set_password(TEST_PASSWORD)
    user.save()
    resp = client_csrf.post("/api/v1/auth/login/", {"email": "sso@example.test", "password": TEST_PASSWORD})
    assert resp.status_code == 400


def test_local_login_disabled(settings, client_csrf):
    settings.LOCAL_LOGIN_ENABLED = False
    UserFactory(email="login@example.test")
    resp = client_csrf.post("/api/v1/auth/login/", {"email": "login@example.test", "password": TEST_PASSWORD})
    assert resp.status_code == 403


def test_login_is_rate_limited(monkeypatch, client_csrf):
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"login": "3/min"})
    codes = [
        client_csrf.post("/api/v1/auth/login/", {"email": "x@example.test", "password": "y" * 15}).status_code
        for _ in range(5)
    ]
    assert codes == [400, 400, 400, 429, 429]


def test_absolute_session_timeout_logs_out(world, settings):
    from .conftest import login

    client = login(APIClient(), world.engineer_a)
    session = client.session
    session[AUTH_AT_SESSION_KEY] = time.time() - settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS - 5
    session.save()
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert AuditEvent.objects.filter(action="auth.session_expired", actor=world.engineer_a).exists()


def test_logout_ends_session(world):
    from .conftest import login

    client = login(APIClient(), world.engineer_a)
    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 401


def test_deactivated_user_session_is_rejected(world):
    from .conftest import login

    client = login(APIClient(), world.engineer_a)
    User.objects.filter(pk=world.engineer_a.pk).update(is_active=False)
    assert client.get("/api/v1/customers/").status_code == 401


def test_me_payload_lists_only_own_memberships(world):
    data = world.client(world.engineer_a).get("/api/v1/auth/me/").json()
    assert [m["customer"]["code"] for m in data["memberships"]] == ["ACME"]
    assert data["memberships"][0]["role"] == "engineer"
    assert data["is_super_admin"] is False
    assert "password" not in str(data).lower()


def test_auth_config_is_public_and_sets_csrf_cookie():
    resp = APIClient().get("/api/v1/auth/config/")
    assert resp.status_code == 200
    assert "okp_csrftoken" in resp.cookies


def test_bootstrap_admin_is_one_time(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "A-Very-Strong-Passphrase-42")
    call_command("bootstrap_admin", email="Root@Example.test")
    user = User.objects.get(email="root@example.test")
    assert user.is_super_admin and user.auth_source == "local"
    assert AuditEvent.objects.filter(action="auth.bootstrap_admin_created").exists()
    with pytest.raises(CommandError, match="one-time"):
        call_command("bootstrap_admin", email="second@example.test")


def test_bootstrap_admin_rejects_weak_password(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "password")
    with pytest.raises(CommandError):
        call_command("bootstrap_admin", email="root@example.test")
    assert not User.objects.exists()


def test_bootstrap_admin_refused_when_local_login_disabled(settings, monkeypatch):
    settings.LOCAL_LOGIN_ENABLED = False
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "A-Very-Strong-Passphrase-42")
    with pytest.raises(CommandError):
        call_command("bootstrap_admin", email="root@example.test")


def test_super_admin_global_role_only_assignable_from_global_roles(world):
    client = world.client(world.super_admin)
    resp = client.patch(f"/api/v1/users/{world.outsider.id}/", {"global_role": "engineer"}, format="json")
    assert resp.status_code == 400
    resp = client.patch(f"/api/v1/users/{world.outsider.id}/", {"global_role": "super_admin"}, format="json")
    assert resp.status_code == 200
    world.outsider.refresh_from_db()
    assert world.outsider.global_role == role("super_admin")


def test_super_admin_cannot_demote_or_deactivate_self(world):
    client = world.client(world.super_admin)
    assert (
        client.patch(f"/api/v1/users/{world.super_admin.id}/", {"is_active": False}, format="json").status_code == 400
    )
    assert (
        client.patch(f"/api/v1/users/{world.super_admin.id}/", {"global_role": None}, format="json").status_code == 400
    )


def test_non_super_admin_cannot_manage_users(world):
    for user in (world.admin_a, world.engineer_a):
        client = world.client(user)
        assert client.get("/api/v1/users/").status_code == 403
        assert (
            client.patch(f"/api/v1/users/{user.id}/", {"global_role": "super_admin"}, format="json").status_code == 403
        )
    assert not User.objects.filter(pk=world.admin_a.pk, global_role__isnull=False).exists()


def test_user_api_never_returns_password_hash(world):
    data = world.client(world.super_admin).get("/api/v1/users/").json()
    assert "pbkdf2" not in str(data)
    assert all("password" not in u for u in data["results"])


@pytest.fixture
def client_csrf() -> APIClient:
    return APIClient()
