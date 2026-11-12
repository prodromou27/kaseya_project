"""Seed clearly-labelled DEMO data for local development and the P0 gate.

Creates two demo customers and demo users with distinct roles. No vendor data, no real customers, no real
credentials. Refuses to run in production. Idempotent.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.audit.services import record_event
from apps.customers.models import Customer, CustomerMembership, CustomerSourceMapping
from apps.integrations.models import IntegrationInstance
from config.env import env_str

DEMO_CUSTOMERS = [
    ("DEMO-A", "Demo Customer A (fixture)"),
    ("DEMO-B", "Demo Customer B (fixture)"),
]
DEMO_USERS = [
    # email, display name, global role, {customer_code: role}
    ("demo.superadmin@demo.invalid", "Demo Super Admin", "super_admin", {}),
    ("demo.admin.a@demo.invalid", "Demo Admin (A)", None, {"DEMO-A": "admin"}),
    ("demo.engineer.a@demo.invalid", "Demo Engineer (A)", None, {"DEMO-A": "engineer"}),
    ("demo.viewer.b@demo.invalid", "Demo Viewer (B)", None, {"DEMO-B": "viewer"}),
]


class Command(BaseCommand):
    help = "Seed DEMO customers/users (development only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.IS_PRODUCTION:
            raise CommandError("seed_demo is disabled in production.")
        password = env_str("DEMO_USER_PASSWORD", "")
        if len(password) < 14:
            raise CommandError("Set DEMO_USER_PASSWORD (min 14 chars) to seed demo users.")
        with transaction.atomic():
            customers = {}
            for code, name in DEMO_CUSTOMERS:
                customers[code], _ = Customer.objects.get_or_create(
                    code=code, defaults={"name": name, "status": Customer.Status.ACTIVE, "notes": "DEMO DATA"}
                )
            roles = {r.key: r for r in Role.objects.all()}
            for email, display, global_role, grants in DEMO_USERS:
                user = User.objects.filter(email=email).first()
                if user is None:
                    user = User.objects.create_user(
                        email=email,
                        password=password,
                        display_name=display,
                        global_role=roles[global_role] if global_role else None,
                    )
                for code, role_key in grants.items():
                    CustomerMembership.objects.get_or_create(
                        customer=customers[code], user=user, defaults={"role": roles[role_key]}
                    )
            vsa, _ = IntegrationInstance.objects.get_or_create(
                name="Demo VSA X (fixture)",
                defaults={
                    "provider": IntegrationInstance.Provider.VSA_X,
                    "base_url": "https://vsa-demo.invalid",
                    "is_fixture": True,
                },
            )
            CustomerSourceMapping.objects.get_or_create(
                integration_instance=vsa,
                external_org_id="demo-org-1001",
                defaults={
                    "customer": customers["DEMO-A"],
                    "external_org_name": "Demo Org A (fixture)",
                    "mapping_status": CustomerSourceMapping.Status.PROPOSED,
                },
            )
            record_event(action="system.demo_seeded", outcome="success", actor_label="system:seed_demo")
        self.stdout.write(self.style.SUCCESS("Demo data seeded (fixture-only; no vendor data)."))
