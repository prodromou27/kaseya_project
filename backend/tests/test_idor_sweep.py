"""VSAP-03 IDOR regression sweep: every customer-scoped route refuses another customer's member.

Walks the URL resolver, so a route added later without a customer check fails this test automatically. The request
uses customer A's REAL id and is sent by customer B's engineer with every method; it must be refused before any
validation (404, or 405 when the method does not exist). A 400 would mean input was processed before authorisation.
"""

from __future__ import annotations

import re

import pytest

from apps.integrations.vsa.fixtures import FixtureVsaTransport

from .test_auth import _iter_api_routes
from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db
PLACEHOLDER_UUID = "33333333-3333-3333-3333-333333333333"


def _concrete(raw: str, customer_id: str) -> str:
    path = raw.replace("<str:customer_pk>", customer_id)
    path = re.sub(r"\(\?P<pk>\[0-9\]\{1,18\}\)", "51", path)
    path = re.sub(r"\(\?P<[a-z_]+>[^)]*\)", PLACEHOLDER_UUID, path)
    path = re.sub(r"\(\?P<format>[^)]*\)", "", path)
    return "/" + path.replace("^", "").replace("$", "").replace("\\.", ".").replace("\\", "")


def test_every_customer_scoped_route_refuses_other_customers(world, env):  # noqa: F811
    run(env["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10")]))  # real A data exists
    intruder = world.client(world.engineer_b)
    checked, routes = 0, set()
    for raw, _pattern in _iter_api_routes():
        if "customers/<str:customer_pk>/" not in raw or "format" in raw:
            continue
        url = _concrete(raw, str(world.customer_a.id))
        routes.add(raw)
        for method in ("get", "post", "patch", "delete"):
            resp = getattr(intruder, method)(url, {}, format="json")
            if resp.status_code == 405:
                continue
            assert resp.status_code == 404, f"{method.upper()} {url} -> {resp.status_code}"
            if resp["Content-Type"].startswith("application/json"):
                assert set(resp.json()) == {"error"}, f"{method.upper()} {url} leaked a body"
            checked += 1
    assert len(routes) >= 30 and checked >= 40, (len(routes), checked)


# Personal, owner-controlled resources a read-only member may create by design (P2-03 saved views; editing someone
# else's is refused by ``_owned``). Adding a route here is a deliberate, reviewed decision.
VIEWER_PERSONAL_WRITE_ROUTES = ("/saved-views/",)


def test_viewer_cannot_write_to_own_customer(world, env):  # noqa: F811
    """Read-only role: every write to its own customer's scoped routes is refused (404/405/403), never applied."""
    viewer = world.client(world.viewer_a)
    for raw, _pattern in _iter_api_routes():
        if "customers/<str:customer_pk>/" not in raw or "format" in raw:
            continue
        url = _concrete(raw, str(world.customer_a.id))
        if any(r in url for r in VIEWER_PERSONAL_WRITE_ROUTES):
            continue
        for method in ("post", "patch", "delete"):
            resp = getattr(viewer, method)(url, {}, format="json")
            assert resp.status_code in (403, 404, 405), f"{method.upper()} {url} -> {resp.status_code}"
