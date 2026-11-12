"""DB-level guarantee that an observation's customer equals its asset's and its generation's customer."""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION inventory_observation_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM inventory_asset WHERE id = NEW.asset_id)
       OR NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on inventory_assetobservation' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_observation_customer_check
    BEFORE INSERT OR UPDATE ON inventory_assetobservation
    FOR EACH ROW EXECUTE FUNCTION inventory_observation_customer_check();
"""

REVERSE = """
DROP TRIGGER IF EXISTS inventory_observation_customer_check ON inventory_assetobservation;
DROP FUNCTION IF EXISTS inventory_observation_customer_check();
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
