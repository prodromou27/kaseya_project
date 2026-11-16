"""Reproducible normalized-inventory benchmark in a new, explicitly disposable database.

``--related`` (P5-06) also generates the per-device evidence the newer pages read - installed software, OS update
rows, patch status, applied patch policy and a 10% server population - so the database holds millions of
observation rows. Every measured path runs against that synthetic data only; nothing calls a vendor.
"""

import hashlib
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

SOFTWARE_PER_DEVICE = 15
SOFTWARE_POOL = 300
OS_UPDATE_POOL = 40
SEVERITIES = ("Critical", "Important", "Moderate", "Low")
REPORTS = (
    ("asset_inventory", "csv"),
    ("asset_inventory", "xlsx"),
    ("server_owner_patching", "csv"),
    ("server_owner_patching", "pdf"),
    ("customer_scorecard", "pdf"),
    ("software_distribution", "csv"),
    ("patch_policy_coverage", "csv"),
)


def _is_server(index: int) -> bool:
    return index % 10 == 0


class Command(BaseCommand):
    help = "Benchmark synthetic normalized inventory. Requires an empty bench_* development database. No vendor calls."

    def add_arguments(self, parser):
        parser.add_argument("--rows", type=int, default=100_000)
        parser.add_argument("--confirm-fixture-only", action="store_true")
        parser.add_argument("--measure-existing", action="store_true")
        parser.add_argument(
            "--related",
            action="store_true",
            help="Also generate installed software, OS updates, patch status/policy and servers (P5-06).",
        )
        parser.add_argument("--skip-reports", action="store_true", help="Measure API paths only.")

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
            customer, user = self._seed(count, related=options["related"])
            seed_seconds = perf_counter() - start

        from apps.software.models import SoftwareInstallation

        related = SoftwareInstallation.objects.filter(customer=customer).exists()
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
            data = response.data if isinstance(response.data, dict) else {}
            return {
                "seconds": round(perf_counter() - started, 4),
                "queries": len(queries),
                "population": data.get("count", data.get("devices")),
                "response_bytes": len(response.content),
            }

        result = {
            "data_basis": "synthetic fixture; normalized storage only, not vendor synchronization or concurrency",
            "rows": count,
            "database": connection.vendor,
            "seed_seconds": round(seed_seconds, 3) if seed_seconds is not None else None,
            "observation_rows": self._row_counts(customer),
            "list_page_50": measure(CustomerAssetViewSet, "list", {"page_size": 50}),
            "hostname_search": measure(CustomerAssetViewSet, "list", {"search": f"BENCH-{count - 1:06d}"}),
            "offline_filter": measure(CustomerAssetViewSet, "list", {"offline": "true", "page_size": 50}),
            "health_summary": measure(CustomerDeviceHealthViewSet, "summary", {}),
        }
        if related:
            from apps.patching.policy_views import CustomerPatchPolicyViewSet
            from apps.patching.views import CustomerOsUpdateViewSet
            from apps.reporting import scorecard
            from apps.servers.views import ServerViewSet
            from apps.software.views import CustomerSoftwareViewSet

            result.update(
                {
                    "servers_list": measure(ServerViewSet, "list", {}),
                    "servers_attention_filter": measure(ServerViewSet, "list", {"attention": "true"}),
                    "servers_all_devices": measure(ServerViewSet, "list", {"scope": "all"}),
                    "software_summary": measure(CustomerSoftwareViewSet, "summary", {}),
                    "os_updates_summary": measure(CustomerOsUpdateViewSet, "summary", {}),
                    "os_updates_page_50": measure(CustomerOsUpdateViewSet, "list", {"page_size": 50}),
                    "patch_policy_summary": measure(CustomerPatchPolicyViewSet, "summary", {}),
                }
            )
            started = perf_counter()
            with CaptureQueriesContext(connection) as queries:
                scorecard.rows(customer)
            result["scorecard_rows"] = {"seconds": round(perf_counter() - started, 4), "queries": len(queries)}
        if not options["skip_reports"]:
            result["reports"] = {
                f"{key}.{fmt}": self._report(customer, user, key, fmt)
                for key, fmt in REPORTS
                if related or key == "asset_inventory"
            }
        self.stdout.write(json.dumps(result, indent=2))

    # ------------------------------------------------------------------------------------------------ seeding

    def _seed(self, count, *, related):
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
            updates = self._os_update_pool() if related else []
            for offset in range(0, count, 1000):
                assets = [
                    Asset(customer=customer, integration_instance=instance, external_id=f"bench-{i:06d}")
                    for i in range(offset, min(offset + 1000, count))
                ]
                Asset.objects.bulk_create(assets, batch_size=1000)
                observations = AssetObservation.objects.bulk_create(
                    [
                        AssetObservation(
                            customer=customer,
                            asset=asset,
                            generation=generation,
                            hostname=f"BENCH-{offset + index:06d}",
                            collected_at=now,
                            device_type="windows",
                            os_name=(
                                "Windows Server 2019 Standard (fixture)"
                                if related and _is_server(offset + index)
                                else "Windows 11 (fixture)"
                            ),
                            os_version="10.0.17763" if related and _is_server(offset + index) else "",
                            organization_external_id="1001",
                            site_external_id="2001",
                            group_external_id="3001",
                            group_name="Synthetic group",
                            client_version="5.1.2",
                            software_status="collected" if related else "not_collected",
                            last_seen_online=now - timedelta(days=index % 30),
                            is_agent_installed=True,
                        )
                        for index, asset in enumerate(assets)
                    ],
                    batch_size=1000,
                )
                if related:
                    self._seed_related(customer, generation, observations, offset, updates, now)
            generation.state, generation.is_current = "published", True
            generation.published_at, generation.row_count = now, count
            generation.save(update_fields=["state", "is_current", "published_at", "row_count"])
        return customer, user

    def _os_update_pool(self):
        from apps.patching.models import OsUpdate

        return OsUpdate.objects.bulk_create(
            [
                OsUpdate(
                    update_id=f"bench-update-{n:03d}",
                    revision_number=1,
                    kb_article=f"{5000000 + n}",
                    title=f"Synthetic update {n}",
                    severity=SEVERITIES[n % len(SEVERITIES)],
                    category="Security Updates",
                )
                for n in range(OS_UPDATE_POOL)
            ]
        )

    def _seed_related(self, customer, generation, observations, offset, updates, now):
        from apps.patching.models import (
            AppliedPolicyObservation,
            DeviceOsUpdate,
            PatchObservation,
            PatchPolicyState,
            UpdateStatus,
        )
        from apps.software.models import SoftwareInstallation

        patch, policies, software = [], [], []
        for index, obs in enumerate(observations):
            n = offset + index
            available = n % 7
            patch.append(
                PatchObservation(
                    observation=obs,
                    customer=customer,
                    asset_id=obs.asset_id,
                    generation=generation,
                    available_status=UpdateStatus.COLLECTED,
                    available_count=available,
                    installed_status=UpdateStatus.COLLECTED,
                    installed_count=2,
                    collected_at=now,
                )
            )
            policies.append(
                AppliedPolicyObservation(
                    observation=obs,
                    customer=customer,
                    asset_id=obs.asset_id,
                    generation=generation,
                    status=UpdateStatus.COLLECTED,
                    collected_at=now,
                    patch_state=PatchPolicyState.EXPLICIT_NONE if n % 25 == 0 else PatchPolicyState.ASSIGNED,
                    patch_policy_id="" if n % 25 == 0 else "301",
                    patch_policy_name="" if n % 25 == 0 else "Synthetic workstation policy",
                )
            )
            for s in range(SOFTWARE_PER_DEVICE):
                product = (n * 7 + s * 13) % SOFTWARE_POOL
                name, publisher, version = f"Synthetic App {product:03d}", f"Vendor {product % 40:02d}", f"{s}.{n % 5}"
                software.append(
                    SoftwareInstallation(
                        customer=customer,
                        asset_id=obs.asset_id,
                        observation=obs,
                        generation=generation,
                        raw_name=name,
                        raw_publisher=publisher,
                        raw_version=version,
                        row_hash=hashlib.sha256(f"{name}\x1f{publisher}\x1f{version}\x1f1".encode()).hexdigest(),
                    )
                )
        PatchObservation.objects.bulk_create(patch, batch_size=1000)
        AppliedPolicyObservation.objects.bulk_create(policies, batch_size=1000)
        SoftwareInstallation.objects.bulk_create(software, batch_size=5000)
        rows = []
        for index, po in enumerate(patch):
            n = offset + index
            chosen = [updates[(n + k * 3) % OS_UPDATE_POOL] for k in range(po.available_count)]
            installed = [updates[(n + 20 + k) % OS_UPDATE_POOL] for k in range(2)]
            for state, items in ((DeviceOsUpdate.State.AVAILABLE, chosen), (DeviceOsUpdate.State.INSTALLED, installed)):
                rows.extend(
                    DeviceOsUpdate(
                        customer=customer,
                        asset_id=po.asset_id,
                        patch_observation=po,
                        generation=generation,
                        os_update=u,
                        state=state,
                        severity=u.severity,
                        category=u.category,
                    )
                    for u in items
                )
        DeviceOsUpdate.objects.bulk_create(rows, batch_size=5000, ignore_conflicts=True)

    # ------------------------------------------------------------------------------------------------ measuring

    def _row_counts(self, customer):
        from apps.patching.models import AppliedPolicyObservation, DeviceOsUpdate, PatchObservation
        from apps.software.models import SoftwareInstallation

        counts = {
            "asset_observations": AssetObservation.objects.filter(customer=customer).count(),
            "software_installations": SoftwareInstallation.objects.filter(customer=customer).count(),
            "device_os_updates": DeviceOsUpdate.objects.filter(customer=customer).count(),
            "patch_observations": PatchObservation.objects.filter(customer=customer).count(),
            "policy_observations": AppliedPolicyObservation.objects.filter(customer=customer).count(),
        }
        counts["total"] = sum(counts.values())
        return counts

    def _report(self, customer, user, key, fmt):
        """Generate one report synchronously the way the worker does; the artifact file is removed afterwards."""
        from apps.reporting.models import ReportRun
        from apps.reporting.registry import REPORT_TYPES
        from apps.reporting.services import filters_hash, generate, storage_path

        report_type = REPORT_TYPES[key]
        run = ReportRun.objects.create(
            customer=customer,
            requested_by=user,
            report_type=key,
            format=fmt,
            filters={},
            filters_hash=filters_hash(key, {}),
            data_basis=report_type.data_basis,
        )
        started = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            run = generate(str(run.id))
        seconds = round(perf_counter() - started, 4)
        out = {"seconds": seconds, "queries": len(queries), "state": run.state, "rows": run.row_count}
        if run.error_code:
            out["error_code"] = run.error_code
        artifact = getattr(run, "artifact", None) if run.state == ReportRun.State.COMPLETED else None
        if artifact is not None:
            out["bytes"] = artifact.bytes
            storage_path(artifact.storage_key).unlink(missing_ok=True)
        return out
