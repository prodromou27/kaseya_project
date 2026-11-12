from django.db import migrations

ROLES = [
    ("super_admin", "Super administrator", "All customers and system administration. Global role only.", True),
    ("admin", "Customer administrator", "Delegated administration of an assigned customer.", False),
    ("engineer", "Engineer", "Read, report and start read-only syncs for an assigned customer.", False),
    ("viewer", "Viewer", "Read an assigned customer; export only when granted.", False),
]


def seed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for key, name, description, is_global in ROLES:
        Role.objects.update_or_create(
            key=key, defaults={"name": name, "description": description, "is_global": is_global}
        )


def unseed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(key__in=[r[0] for r in ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
