"""Seed clearly-labelled DEMO data for local development and the phase gates.

Creates demo customers, demo users with distinct roles, an enabled *fixture* VSA X instance (never touches the
network), source mappings and an illustrative demo software catalog. No vendor data, no real customers, no real
credentials. Refuses to run in production. Idempotent.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

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
    ("demo.reviewer@demo.invalid", "Demo Catalog Reviewer", "super_admin", {}),
    ("demo.admin.a@demo.invalid", "Demo Admin (A)", None, {"DEMO-A": "admin"}),
    ("demo.engineer.a@demo.invalid", "Demo Engineer (A)", None, {"DEMO-A": "engineer"}),
    ("demo.viewer.b@demo.invalid", "Demo Viewer (B)", None, {"DEMO-B": "viewer"}),
]
EVIDENCE_URL = "https://catalog-evidence.demo.invalid/illustrative"


class Command(BaseCommand):
    help = "Seed DEMO customers/users/fixture integration/catalog (development only)."

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
                    "enabled": True,
                    "max_rps": 20,
                    "installed_updates_budget": 60,  # rotate per-device InstalledUpdates over the 130-device demo org
                },
            )
            reviewer = User.objects.get(email="demo.reviewer@demo.invalid")
            # DEMO-A's mapping stays *proposed* so the review workflow can be exercised; DEMO-B is pre-approved.
            CustomerSourceMapping.objects.get_or_create(
                integration_instance=vsa,
                external_org_id="1001",
                defaults={
                    "customer": customers["DEMO-A"],
                    "external_org_name": "Demo Org A (fixture)",
                    "mapping_status": CustomerSourceMapping.Status.PROPOSED,
                },
            )
            CustomerSourceMapping.objects.get_or_create(
                integration_instance=vsa,
                external_org_id="1002",
                defaults={
                    "customer": customers["DEMO-B"],
                    "external_org_name": "Demo Org B (fixture)",
                    "mapping_status": CustomerSourceMapping.Status.APPROVED,
                    "reviewed_by": reviewer,
                    "reviewed_at": timezone.now(),
                    "review_note": "DEMO seed",
                },
            )
            self._seed_catalog(User.objects.get(email="demo.superadmin@demo.invalid"), reviewer)
            record_event(action="system.demo_seeded", outcome="success", actor_label="system:seed_demo")
        self.stdout.write(self.style.SUCCESS("Demo data seeded (fixture-only; no vendor data)."))

    def _seed_catalog(self, importer: User, reviewer: User) -> None:
        """Illustrative DEMO catalog: reference versions are NOT verified vendor facts (evidence URL is .invalid)."""
        from apps.software.catalog import approve_import
        from apps.software.models import CatalogImport

        if CatalogImport.objects.filter(rows__0__vendor="DEMO Google").exists():
            return
        checked = (timezone.now() - timedelta(days=1)).isoformat()

        def row(vendor: str, product: str, version: str, aliases: list[tuple[str, str, str]], **extra: str) -> dict:
            return {
                "vendor": vendor,
                "product": product,
                "reference_version": version,
                "vendor_url": EVIDENCE_URL,
                "source_type": "manual_verification",
                "source_checked_at": checked,
                "aliases": [{"name_pattern": n, "publisher_pattern": p, "match_type": m} for n, p, m in aliases],
                **extra,
            }

        rows = [
            row("DEMO Google", "Chrome", "131.0.6778.86", [("Google Chrome", "Google LLC", "exact")]),
            row(
                "DEMO Google",
                "Chrome",
                "132.0.6834.15",
                [("Google Chrome Beta", "Google LLC", "exact")],
                channel="beta",
            ),
            row("DEMO Mozilla", "Firefox", "132.0.2", [("Mozilla Firefox (", "Mozilla", "prefix")]),
            row("DEMO Mozilla", "Firefox", "128.4.0", [("Mozilla Firefox ESR", "Mozilla", "prefix")], channel="esr"),
            row("DEMO Igor Pavlov", "7-Zip", "24.08", [("7-Zip", "Igor Pavlov", "prefix")], architecture="x64"),
            row("DEMO Adobe", "Acrobat Reader", "24.004.20220", [("Adobe Acrobat Reader", "Adobe", "prefix")]),
            row("DEMO Notepad++", "Notepad++", "8.7.1", [("Notepad++", "Notepad++ Team", "prefix")]),
        ]
        imp = CatalogImport.objects.create(rows=rows, created_by=importer, preview=[])
        approve_import(imp, reviewer)
