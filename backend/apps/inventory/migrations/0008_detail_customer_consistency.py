"""VSA4-03: DB-level customer consistency for notification/custom-field rows (reuses the VSA1 trigger function)."""

from django.db import migrations

TABLES = ["inventory_devicedetailfetch", "inventory_devicenotification", "inventory_devicecustomfield"]

FORWARD = "".join(
    f"CREATE TRIGGER {t}_customer_check BEFORE INSERT OR UPDATE ON {t} "
    f"FOR EACH ROW EXECUTE FUNCTION inventory_asset_row_customer_check();\n"
    for t in TABLES
)
REVERSE = "".join(f"DROP TRIGGER IF EXISTS {t}_customer_check ON {t};\n" for t in TABLES)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_notifications_custom_fields")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
