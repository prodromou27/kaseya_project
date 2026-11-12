"""DB-level guarantee that patching rows carry the same customer as their asset and generation."""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION patching_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM inventory_asset WHERE id = NEW.asset_id)
       OR NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on %', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER patching_observation_customer_check BEFORE INSERT OR UPDATE ON patching_patchobservation
    FOR EACH ROW EXECUTE FUNCTION patching_customer_check();
CREATE TRIGGER patching_device_update_customer_check BEFORE INSERT OR UPDATE ON patching_deviceosupdate
    FOR EACH ROW EXECUTE FUNCTION patching_customer_check();
"""

REVERSE = """
DROP TRIGGER IF EXISTS patching_device_update_customer_check ON patching_deviceosupdate;
DROP TRIGGER IF EXISTS patching_observation_customer_check ON patching_patchobservation;
DROP FUNCTION IF EXISTS patching_customer_check();
"""


class Migration(migrations.Migration):
    dependencies = [("patching", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
