from __future__ import annotations

import time
from dataclasses import dataclass

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.middleware import AUTH_AT_SESSION_KEY
from apps.accounts.models import User
from apps.customers.models import Customer

from .factories import CustomerFactory, MembershipFactory, UserFactory, role


@pytest.fixture(autouse=True)
def _isolate(settings, tmp_path):
    cache.clear()  # throttling + OIDC discovery caches
    settings.REPORT_STORAGE_DIR = tmp_path / "reports"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # test speed only
    # Existing suites exercise the stricter two-person mode; test_single_admin.py covers the default (off).
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = True
    yield
    cache.clear()


def login(client: APIClient, user: User) -> APIClient:
    client.force_login(user)
    session = client.session
    session[AUTH_AT_SESSION_KEY] = time.time()
    session.save()
    return client


@dataclass
class World:
    """Two customers and a full role matrix for isolation tests."""

    customer_a: Customer
    customer_b: Customer
    super_admin: User
    admin_a: User
    engineer_a: User
    viewer_a: User
    engineer_b: User
    outsider: User

    def client(self, user: User | None, **kwargs: object) -> APIClient:
        c = APIClient(**kwargs)
        return login(c, user) if user is not None else c


@pytest.fixture
def world(db) -> World:
    a = CustomerFactory(code="ACME", name="Acme Ltd")
    b = CustomerFactory(code="BETA", name="Beta plc")
    super_admin = UserFactory(email="super@example.test", global_role=role("super_admin"))
    admin_a = UserFactory(email="admin.a@example.test")
    engineer_a = UserFactory(email="eng.a@example.test")
    viewer_a = UserFactory(email="viewer.a@example.test")
    engineer_b = UserFactory(email="eng.b@example.test")
    outsider = UserFactory(email="nobody@example.test")
    MembershipFactory(customer=a, user=admin_a, role=role("admin"))
    MembershipFactory(customer=a, user=engineer_a, role=role("engineer"))
    MembershipFactory(customer=a, user=viewer_a, role=role("viewer"))
    MembershipFactory(customer=b, user=engineer_b, role=role("engineer"))
    return World(a, b, super_admin, admin_a, engineer_a, viewer_a, engineer_b, outsider)
