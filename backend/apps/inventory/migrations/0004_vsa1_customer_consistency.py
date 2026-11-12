"""DB-level customer consistency for VSA1 hierarchy/network/disk/security rows (defence in depth)."""

from django.db import migrations

ASSET_TABLES = [
    "inventory_networkadapterobservation",
    "inventory_ipaddressobservation",
    "inventory_diskobservation",
    "inventory_securityobservation",
]
NODE_TABLES = ["inventory_organizationnode", "inventory_sitenode", "inventory_groupnode"]

FUNCTIONS = """
CREATE OR REPLACE FUNCTION inventory_asset_row_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM inventory_asset WHERE id = NEW.asset_id)
       OR NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on %', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION inventory_node_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on %', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

FORWARD = FUNCTIONS + "".join(
    f"CREATE TRIGGER {t}_customer_check BEFORE INSERT OR UPDATE ON {t} "
    f"FOR EACH ROW EXECUTE FUNCTION inventory_asset_row_customer_check();\n"
    for t in ASSET_TABLES
) + "".join(
    f"CREATE TRIGGER {t}_customer_check BEFORE INSERT OR UPDATE ON {t} "
    f"FOR EACH ROW EXECUTE FUNCTION inventory_node_customer_check();\n"
    for t in NODE_TABLES
)

REVERSE = "".join(f"DROP TRIGGER IF EXISTS {t}_customer_check ON {t};\n" for t in ASSET_TABLES + NODE_TABLES) + (
    "DROP FUNCTION IF EXISTS inventory_asset_row_customer_check();\n"
    "DROP FUNCTION IF EXISTS inventory_node_customer_check();\n"
)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_vsa1_hierarchy_network")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
