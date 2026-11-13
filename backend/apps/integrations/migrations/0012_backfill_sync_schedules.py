"""Approved mappings without a sync schedule never synced automatically: give each one a daily schedule, due now."""

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    Mapping = apps.get_model("customers", "CustomerSourceMapping")
    SyncSchedule = apps.get_model("integrations", "SyncSchedule")
    now = timezone.now()
    for mapping in Mapping.objects.filter(mapping_status="approved", schedule__isnull=True):
        SyncSchedule.objects.create(mapping=mapping, interval_hours=24, next_run_at=now, enabled=True)


class Migration(migrations.Migration):
    dependencies = [("integrations", "0011_connector_hosts"), ("customers", "0001_initial")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
