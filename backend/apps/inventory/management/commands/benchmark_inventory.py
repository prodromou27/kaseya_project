"""Reproducible normalized-inventory benchmark in a new, explicitly disposable database."""

import json
from datetime import timedelta
from time import perf_counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import Role, User
from apps.customers.models import Customer, CustomerSourceMapping
from apps.integrations.models import DatasetGeneration, IntegrationInstance
from apps.inventory.health_views import CustomerDeviceHealthViewSet
from apps.inventory.models import Asset, AssetObservation
from apps.inventory.views import CustomerAssetViewSet


class Command(BaseCommand):
    help = "Benchmark synthetic normalized inventory. Requires an empty bench_* development database. No vendor calls."

    def add_arguments(self, parser):
        parser.add_argument("--rows", type=int, default=100_000)
        parser.add_argument("--confirm-fixture-only", action="store_true")
        parser.add_argument("--measure-existing", action="store_true")

    def handle(self, *args, **options):
        if (
            settings.IS_PRODUCTION
            or not settings.DATABASES["default"]["NAME"].startswith("bench_")
            or not options["confirm_fixture_only"]
        ):
            raise CommandError(
                "Use a new bench_* development database and --confirm-fixture-only. Production is refused."
            )
        count = options["rows"]
        if not 1 <= count <= 100_000:
            raise CommandError("Rows must be between 1 and 100000.")
        if options["measure_existing"]:
            if (
                Customer.objects.count() != 1
                or not Customer.objects.filter(code="BENCH", name="Synthetic benchmark fixture").exists()
                or IntegrationInstance.objects.exclude(is_fixture=True).exists()
                or Asset.objects.exclude(external_id__startswith="bench-").exists()
            ):
                raise CommandError("Existing database is not the synthetic benchmark fixture.")
            customer = Customer.objects.get(code="BENCH")
            user = User.objects.get(email="benchmark@fixture.invalid")
            count = Asset.objects.filter(customer=customer).count()
            seed_seconds = None
        else:
            if Customer.objects.exists() or IntegrationInstance.objects.exists() or User.objects.exists():
                raise CommandError("Benchmark refuses a database containing existing customers, users or integrations.")
            start = perf_counter()
            now = timezone.now()
            with transaction.atomic():
                user = User(email="benchmark@fixture.invalid", global_role=Role.objects.get(key="super_admin"))
                user.set_unusable_password()
                user.save()
                customer = Customer.objects.create(code="BENCH", name="Synthetic benchmark fixture", status="active")
                instance = IntegrationInstance.objects.create(
                    name="Offline benchmark fixture",
                    provider="vsa_x",
                    base_url="https://benchmark.invalid",
                    is_fixture=True,
                )
                mapping = CustomerSourceMapping.objects.create(
                    customer=customer,
                    integration_instance=instance,
                    external_org_id="1001",
                    mapping_status="approved",
                    reviewed_by=user,
                    reviewed_at=now,
                )
                generation = DatasetGeneration.objects.create(
                    customer=customer,
                    integration_instance=instance,
                    mapping=mapping,
                    dataset="vsa_assets",
                    data_basis="fixture",
                )
                for offset in range(0, count, 1000):
                    assets = [
                        Asset(customer=customer, integration_instance=instance, external_id=f"bench-{i:06d}")
                        for i in range(offset, min(offset + 1000, count))
                    ]
                    Asset.objects.bulk_create(assets, batch_size=1000)
                    AssetObservation.objects.bulk_create(
                        [
                            AssetObservation(
                                customer=customer,
                                asset=asset,
                                generation=generation,
                                hostname=f"BENCH-{offset + index:06d}",
                                collected_at=now,
                                device_type="windows",
                                os_name="Windows 11 (fixture)",
                                organization_external_id="1001",
                                site_external_id="2001",
                                group_external_id="3001",
                                group_name="Synthetic group",
                                client_version="5.1.2",
                                software_status="not_collected",
                                last_seen_online=now - timedelta(days=index % 30),
                                is_agent_installed=True,
                            )
                            for index, asset in enumerate(assets)
                        ],
                        batch_size=1000,
                    )
                generation.state, generation.is_current = "published", True
                generation.published_at, generation.row_count = now, count
                generation.save(update_fields=["state", "is_current", "published_at", "row_count"])
            seed_seconds = perf_counter() - start
        factory = APIRequestFactory()

        def measure(view, action, params):
            request = factory.get(f"/api/v1/customers/{customer.id}/", params, HTTP_HOST="localhost")
            force_authenticate(request, user=User.objects.get(pk=user.id))
            started = perf_counter()
            with CaptureQueriesContext(connection) as queries:
                response = view.as_view({"get": action})(request, customer_pk=str(customer.id))
                response.render()
            if response.status_code != 200:
                raise CommandError(f"Benchmark endpoint failed with HTTP {response.status_code}.")
            return {
                "seconds": round(perf_counter() - started, 4),
                "queries": len(queries),
                "population": response.data.get("count", response.data.get("devices")),
            }

        result = {
            "data_basis": "synthetic fixture; normalized storage only, not vendor synchronization or concurrency",
            "rows": count,
            "database": connection.vendor,
            "seed_seconds": round(seed_seconds, 3) if seed_seconds is not None else None,
            "list_page_50": measure(CustomerAssetViewSet, "list", {"page_size": 50}),
            "hostname_search": measure(CustomerAssetViewSet, "list", {"search": f"BENCH-{count - 1:06d}"}),
            "offline_filter": measure(CustomerAssetViewSet, "list", {"offline": "true", "page_size": 50}),
            "health_summary": measure(CustomerDeviceHealthViewSet, "summary", {}),
        }
        self.stdout.write(json.dumps(result, indent=2))
