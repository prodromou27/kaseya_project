"""VSA3-04: DB-level customer consistency for applied-policy rows and policy definitions (defence in depth)."""

from django.db import migrations

FORWARD = """
CREATE TRIGGER patching_policy_obs_customer_check BEFORE INSERT OR UPDATE ON patching_appliedpolicyobservation
    FOR EACH ROW EXECUTE FUNCTION patching_customer_check();
CREATE TRIGGER patching_applied_policy_customer_check BEFORE INSERT OR UPDATE ON patching_appliedpolicy
    FOR EACH ROW EXECUTE FUNCTION patching_customer_check();

CREATE OR REPLACE FUNCTION patching_generation_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on %', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER patching_policydef_customer_check BEFORE INSERT OR UPDATE ON patching_patchpolicydefinition
    FOR EACH ROW EXECUTE FUNCTION patching_generation_customer_check();
"""

REVERSE = """
DROP TRIGGER IF EXISTS patching_policydef_customer_check ON patching_patchpolicydefinition;
DROP FUNCTION IF EXISTS patching_generation_customer_check();
DROP TRIGGER IF EXISTS patching_applied_policy_customer_check ON patching_appliedpolicy;
DROP TRIGGER IF EXISTS patching_policy_obs_customer_check ON patching_appliedpolicyobservation;
"""


class Migration(migrations.Migration):
    dependencies = [("patching", "0003_applied_policies")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
