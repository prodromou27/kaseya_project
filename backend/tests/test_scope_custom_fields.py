"""CF-02 organisation/site/group custom fields: only customer-approved names, no calls without approvals."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.inventory.models import CustomFieldAllowlist, ScopeCustomField

from .test_automation import demo  # noqa: F401
from .test_script_values import resync

pytestmark = pytest.mark.django_db


def approve(world, name):
    CustomFieldAllowlist.objects.create(
        customer=world.customer_a,
        name=name,
        name_key=name.casefold(),
        reason="useful context",
        state="approved",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )


def test_nothing_is_collected_without_approved_names(world, demo):  # noqa: F811
    assert not ScopeCustomField.objects.exists()
    assert (
        world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/scope-custom-fields/").json() == []
    )


def test_only_approved_organisation_and_site_fields_are_kept(world, demo):  # noqa: F811
    approve(world, "Contract tier")
    approve(world, "Site contact")
    resync(world, demo)
    body = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/scope-custom-fields/").json()
    flat = {(s["scope_type"], f["name"]): f["value"] for s in body for f in s["fields"]}
    assert flat == {
        ("organization", "Contract tier"): "Gold (fixture)",
        ("site", "Site contact"): "Front desk (fixture)",
    }
    assert not ScopeCustomField.objects.filter(name__icontains="password").exists()
    assert body[0]["scope_type"] == "organization" and body[1]["scope_name"]  # site name resolved from the hierarchy
    assert (
        world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_a.id}/scope-custom-fields/").status_code
        == 404
    )


def test_scope_fields_are_a_custom_report_source(world, demo):  # noqa: F811
    approve(world, "Contract tier")
    resync(world, demo)
    preview = (
        world.client(world.engineer_a)
        .post(
            f"/api/v1/customers/{world.customer_a.id}/custom-reports/preview/",
            {"source": "scope_fields"},
            format="json",
        )
        .json()
    )
    assert preview["count"] == 1 and preview["rows"][0][2:] == ["Contract tier", "Gold (fixture)"]
