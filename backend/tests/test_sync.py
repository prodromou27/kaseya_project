"""P1-02 / P1-03 sync engine: atomic publication, checkpoints, idempotency, quarantine. Fixture-based."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.roles import Cap
from apps.audit.models import AuditEvent
from apps.customers.models import CustomerMembership, CustomerSourceMapping
from apps.integrations import sync
from apps.integrations.models import DatasetGeneration, IntegrationInstance, SyncQuarantine, SyncRun
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.inventory.models import Asset, AssetObservation
from apps.software.models import ComplianceEvaluation, SoftwareInstallation

pytestmark = pytest.mark.django_db


def assets(n: int, org: int = 1001, prefix: str = "a", software: bool = True) -> list[dict]:
    out = []
    for i in range(n):
        item = {
            "Identifier": f"{prefix}-{i:04d}",
            "Name": f"HOST-{prefix}-{i}",
            "OrganizationId": org,
            "SiteId": 5,
            "GroupName": "Org - HQ - Workstations",
            "LastSeenOnline": "2026-11-10T08:00:00Z",
            "Type": "windows",
        }
        if software:
            item["InstalledSoftware"] = [
                {"Name": "Google Chrome", "Publisher": "Google LLC", "Version": "131.0.6778.86"},
                {"Name": "7-Zip", "Publisher": "Igor Pavlov", "Version": "24.08"},
            ]
        out.append(item)
    return out


@pytest.fixture
def vsa(world):
    inst = IntegrationInstance.objects.create(
        name="VSA fixture", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True, enabled=True, max_rps=20
    )
    mapping = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="1001",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    return inst, mapping


def run_with(run: SyncRun, transport: FixtureVsaTransport) -> SyncRun:
    return sync.execute(
        str(run.id), adapter_factory=lambda inst: VsaXAdapter(inst, transport=transport, sleeper=lambda s: None)
    )


def new_run(mapping, user, **kw) -> SyncRun:
    run, _ = sync.request_sync(mapping, requested_by=user, **kw)
    return run


def current(customer) -> DatasetGeneration | None:
    return DatasetGeneration.objects.filter(customer=customer, is_current=True).first()


# ---------------------------------------------------------------- happy path & reconciliation


def test_full_sync_publishes_and_counts_reconcile(world, vsa):
    _, mapping = vsa
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(150)))
    assert run.state == "completed", run.error_code
    gen = current(world.customer_a)
    assert gen.row_count == 150 == run.fetched_count == run.source_total_count == run.accepted_count
    assert gen.software_row_count == 300 == SoftwareInstallation.objects.filter(generation=gen).count()
    assert gen.data_basis == "fixture" and run.pages_fetched == 2 and run.api_requests == 2
    assert Asset.objects.filter(customer=world.customer_a, active=True).count() == 150
    assert ComplianceEvaluation.objects.get(generation=gen, is_current=True).summary == {"unsupported": 300}
    assert AuditEvent.objects.filter(action="sync.completed", target_id=str(run.id)).exists()


def test_missing_software_section_recorded_as_not_collected(world, vsa):
    _, mapping = vsa
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(2, software=False)))
    obs = AssetObservation.objects.filter(generation=run.generation)
    assert {o.software_status for o in obs} == {"not_collected"}
    assert all(o.software_count is None for o in obs)


def test_identical_duplicate_software_entries_are_preserved(world, vsa):
    _, mapping = vsa
    data = assets(1)
    data[0]["InstalledSoftware"].append(dict(data[0]["InstalledSoftware"][0]))
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(data))
    assert SoftwareInstallation.objects.filter(generation=run.generation).count() == 3


# ---------------------------------------------------------------- quarantine / mapping (P1-03, VSA-05)


def test_records_from_other_organisations_are_quarantined_never_attributed(world, vsa):
    _, mapping = vsa
    leaked = assets(2, org=9999, prefix="other")
    # A misbehaving source ignores the filter and returns another org's assets in the same response.
    transport = FixtureVsaTransport(
        [], scripted=[FakeResponse(200, {"Data": assets(3) + leaked, "Meta": {"TotalCount": 5}})]
    )
    run = run_with(new_run(mapping, world.engineer_a), transport)
    assert run.state == "completed" and run.quarantined_count == 2
    assert run.accepted_count == run.fetched_count - 2
    assert set(SyncQuarantine.objects.values_list("reason", flat=True)) == {"organization_mismatch"}
    assert not Asset.objects.filter(external_id__startswith="other").exists()
    assert current(world.customer_a).row_count == 3


def test_malformed_records_are_quarantined_with_minimal_snapshot(world, vsa):
    _, mapping = vsa
    bad = {
        "Name": "no-id",
        "OrganizationId": 1001,
        "AssetInfo": [{"CategoryName": "Operating System", "CategoryData": {"Product Key": "SECRET-KEY"}}],
    }
    transport = FixtureVsaTransport(
        [], scripted=[FakeResponse(200, {"Data": [*assets(2), bad], "Meta": {"TotalCount": 3}})]
    )
    run = run_with(new_run(mapping, world.engineer_a), transport)
    q = SyncQuarantine.objects.get(sync_run=run)
    assert q.reason == "missing_identifier" and "SECRET-KEY" not in str(q.snapshot)
    assert run.state == "completed"


def test_unapproved_mapping_cannot_be_synced(world, vsa):
    _, mapping = vsa
    for status in ("proposed", "rejected", "revoked"):
        CustomerSourceMapping.objects.filter(pk=mapping.pk).update(mapping_status=status)
        mapping.refresh_from_db()
        with pytest.raises(sync.SyncRefused):
            sync.request_sync(mapping, requested_by=world.engineer_a)


def test_mapping_revoked_after_request_is_refused_in_worker(world, vsa):
    """AUTH-04: rejected before any vendor call."""
    _, mapping = vsa
    run = new_run(mapping, world.engineer_a)
    CustomerSourceMapping.objects.filter(pk=mapping.pk).update(mapping_status="revoked")
    transport = FixtureVsaTransport(assets(3))
    run = run_with(run, transport)
    assert run.state == "failed" and run.error_code == "mapping_not_approved"
    assert transport.calls == []


def test_requester_losing_sync_capability_is_refused_in_worker(world, vsa):
    _, mapping = vsa
    run = new_run(mapping, world.engineer_a)
    CustomerMembership.objects.filter(user=world.engineer_a).update(is_active=False)
    transport = FixtureVsaTransport(assets(3))
    assert run_with(run, transport).error_code == "authorization_revoked"
    assert transport.calls == []


def test_restricted_customer_is_never_ingested(world, vsa):
    _, mapping = vsa
    world.customer_a.restricted_data = True
    world.customer_a.save()
    mapping.refresh_from_db()
    with pytest.raises(sync.SyncRefused) as exc:
        sync.request_sync(mapping, requested_by=world.engineer_a)
    assert exc.value.code == "restricted_customer"


def test_disabled_instance_refused(world, vsa):
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(enabled=False)
    mapping.refresh_from_db()
    with pytest.raises(sync.SyncRefused):
        sync.request_sync(mapping, requested_by=world.engineer_a)


def test_vendor_id_never_reattributed_to_another_customer(world, vsa):
    inst, mapping_a = vsa
    run_with(new_run(mapping_a, world.engineer_a), FixtureVsaTransport(assets(2, prefix="shared")))
    mapping_b = CustomerSourceMapping.objects.create(
        customer=world.customer_b,
        integration_instance=inst,
        external_org_id="2002",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    run_b = run_with(new_run(mapping_b, world.engineer_b), FixtureVsaTransport(assets(2, org=2002, prefix="shared")))
    assert run_b.quarantined_count == 2
    assert set(SyncQuarantine.objects.filter(sync_run=run_b).values_list("reason", flat=True)) == {"customer_conflict"}
    assert not AssetObservation.objects.filter(customer=world.customer_b).exists()


# ---------------------------------------------------------------- atomic publication & resume (SYNC-01/02/03)


def test_interrupted_sync_keeps_last_good_generation_then_resumes(world, vsa):
    _, mapping = vsa
    first = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(120)))
    good = current(world.customer_a)

    data = assets(250, prefix="b")
    flaky = FixtureVsaTransport(data)
    calls = {"n": 0}

    def fail_on_third(path, params):
        calls["n"] += 1
        if calls["n"] == 3:
            flaky.scripted.extend([FakeResponse(503)] * 5)

    flaky.on_request = fail_on_third
    second = run_with(new_run(mapping, world.engineer_a), flaky)
    assert second.state == "partial" and second.error_code == "vendor_unavailable"
    assert second.next_skip == 200  # two pages committed with their checkpoint
    assert current(world.customer_a) == good  # last good dataset still published
    assert Asset.objects.filter(customer=world.customer_a, external_id__startswith="a-", active=True).count() == 120

    resumed = run_with(second, FixtureVsaTransport(data))
    assert resumed.state == "completed" and resumed.attempts == 2
    new_gen = current(world.customer_a)
    assert new_gen != good and new_gen.row_count == 250
    good.refresh_from_db()
    assert good.state == "superseded" and first.state == "completed"
    # Tombstoning after a complete crawl: assets absent from the new inventory become inactive.
    assert Asset.objects.filter(customer=world.customer_a, external_id__startswith="a-", active=True).count() == 0


def test_replay_of_completed_run_is_noop(world, vsa):
    _, mapping = vsa
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(5)))
    transport = FixtureVsaTransport(assets(5))
    again = run_with(run, transport)
    assert again.state == "completed" and transport.calls == []
    assert DatasetGeneration.objects.filter(customer=world.customer_a, state="published").count() == 1


def test_idempotency_key_returns_same_run(world, vsa):
    _, mapping = vsa
    r1, created1 = sync.request_sync(mapping, requested_by=world.engineer_a, idempotency_key="key-1")
    r2, created2 = sync.request_sync(mapping, requested_by=world.engineer_a, idempotency_key="key-1")
    assert r1.id == r2.id and created1 and not created2


def test_one_active_run_per_scope(world, vsa):
    _, mapping = vsa
    r1 = new_run(mapping, world.engineer_a)
    r2 = new_run(mapping, world.engineer_a)
    assert r1.id == r2.id
    with pytest.raises(IntegrityError), transaction.atomic():
        SyncRun.objects.create(
            integration_instance=r1.integration_instance,
            customer=r1.customer,
            mapping=mapping,
            dataset=r1.dataset,
            idempotency_key="dup",
        )


def test_source_changing_during_crawl_is_not_published(world, vsa):
    """SYNC-03: $skip paging over a shrinking source misses records → count mismatch, nothing published."""
    _, mapping = vsa
    run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(150)))
    good = current(world.customer_a)
    data = assets(150)
    transport = FixtureVsaTransport(data)

    def delete_after_first_page(path, params):
        if params.get("$skip") == "100":
            del data[0:10]  # 10 assets deleted between page 1 and page 2

    transport.on_request = delete_after_first_page
    run = run_with(new_run(mapping, world.engineer_a), transport)
    assert run.state == "failed" and run.error_code == "source_changed_during_crawl"
    assert current(world.customer_a) == good
    assert run.generation.state == "discarded"
    assert Asset.objects.filter(customer=world.customer_a, active=False).count() == 0  # no premature deletion


def test_auth_failure_preserves_published_data(world, vsa):
    inst, mapping = vsa
    run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(3)))
    good = current(world.customer_a)
    transport = FixtureVsaTransport([], scripted=[FakeResponse(401)])
    run = run_with(new_run(mapping, world.engineer_a), transport)
    assert run.state == "failed" and run.error_code == "auth_failed" and len(transport.calls) == 1
    assert current(world.customer_a) == good
    inst.refresh_from_db()
    assert inst.status == "failed"


def test_large_drop_is_not_auto_published(world, vsa):
    _, mapping = vsa
    run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(100)))
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(10)))
    assert run.error_code == "row_count_drop_guard"
    assert current(world.customer_a).row_count == 100


def test_malformed_page_fails_run(world, vsa):
    _, mapping = vsa
    run = run_with(
        new_run(mapping, world.engineer_a),
        FixtureVsaTransport([], scripted=[FakeResponse(200, {"Data": "oops", "Meta": {}})]),
    )
    assert run.state == "failed" and run.error_code == "malformed_page"


def test_rate_limit_exhaustion_pauses_run(world, vsa):
    _, mapping = vsa
    run = run_with(
        new_run(mapping, world.engineer_a),
        FixtureVsaTransport([], scripted=[FakeResponse(429, headers={"Retry-After": "9999"})]),
    )
    assert run.state == "partial" and run.error_code == "rate_limited"


def test_attempt_budget_is_bounded(world, vsa):
    _, mapping = vsa
    run = new_run(mapping, world.engineer_a)
    SyncRun.objects.filter(pk=run.pk).update(attempts=sync.MAX_ATTEMPTS, state="partial")
    assert run_with(run, FixtureVsaTransport(assets(1))).error_code == "retry_budget_exhausted"


def test_scheduled_trigger_needs_no_requester(world, vsa):
    _, mapping = vsa
    run, _ = sync.request_sync(mapping, requested_by=None, trigger="schedule")
    assert run_with(run, FixtureVsaTransport(assets(1))).state == "completed"


def test_engineer_capability_constant():
    assert Cap.CUSTOMER_SYNC == "customer.sync"


# ---------------------------------------------------------------- DB-level guarantees


def test_db_rejects_observation_with_mismatched_customer(world, vsa):
    _, mapping = vsa
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(1)))
    asset = Asset.objects.get(customer=world.customer_a)
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        AssetObservation.objects.filter(asset=asset, generation=run.generation).update(customer=world.customer_b)


def test_db_allows_only_one_current_generation_per_scope(world, vsa):
    _, mapping = vsa
    run = run_with(new_run(mapping, world.engineer_a), FixtureVsaTransport(assets(1)))
    with pytest.raises(IntegrityError), transaction.atomic():
        DatasetGeneration.objects.create(
            integration_instance=run.integration_instance,
            customer=world.customer_a,
            mapping=mapping,
            dataset="vsa_assets",
            state="published",
            is_current=True,
            data_basis="fixture",
        )


def test_demo_tenant_full_sync(world, vsa):
    """The bundled fictional demo tenant syncs completely via the default fixture transport."""
    _, mapping = vsa
    run = sync.execute(str(new_run(mapping, world.engineer_a).id))
    assert run.state == "completed", run.error_code
    gen = current(world.customer_a)
    assert gen.row_count == 130 and run.quarantined_count == 0
    assert AssetObservation.objects.filter(generation=gen, software_status="not_collected").count() == 3
    obs = AssetObservation.objects.filter(generation=gen).first()
    stored = str(obs.__dict__)
    assert "XXXXX" not in stored and "should-not-be-stored" not in stored
