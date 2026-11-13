"""DB-level customer consistency for onboarding runs/results (defence in depth for VSA2-03 isolation).

* a run's upload and pinned generation must belong to the run's customer;
* a result's customer, matched asset and reviewer-chosen asset must equal its run's customer;
* engine output on a result (classification, evidence, input, match) is immutable once written.
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION onboarding_run_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM onboarding_expectedinventoryupload WHERE id = NEW.upload_id)
       OR NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on %', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION onboarding_result_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM onboarding_reconciliationrun WHERE id = NEW.run_id)
       OR (NEW.asset_id IS NOT NULL AND NEW.customer_id IS DISTINCT FROM
           (SELECT customer_id FROM inventory_asset WHERE id = NEW.asset_id))
       OR (NEW.reviewed_asset_id IS NOT NULL AND NEW.customer_id IS DISTINCT FROM
           (SELECT customer_id FROM inventory_asset WHERE id = NEW.reviewed_asset_id)) THEN
        RAISE EXCEPTION 'customer mismatch on %', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.kind IS DISTINCT FROM OLD.kind
        OR NEW.row_number IS DISTINCT FROM OLD.row_number OR NEW.input IS DISTINCT FROM OLD.input
        OR NEW.classification IS DISTINCT FROM OLD.classification OR NEW.flags IS DISTINCT FROM OLD.flags
        OR NEW.evidence IS DISTINCT FROM OLD.evidence OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
        OR NEW.candidate_asset_ids IS DISTINCT FROM OLD.candidate_asset_ids OR NEW.actual IS DISTINCT FROM OLD.actual
    ) THEN
        RAISE EXCEPTION 'reconciliation results are immutable' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER onboarding_run_customer_check BEFORE INSERT OR UPDATE ON onboarding_reconciliationrun
    FOR EACH ROW EXECUTE FUNCTION onboarding_run_customer_check();
CREATE TRIGGER onboarding_result_customer_check BEFORE INSERT OR UPDATE ON onboarding_reconciliationresult
    FOR EACH ROW EXECUTE FUNCTION onboarding_result_customer_check();
"""

REVERSE = """
DROP TRIGGER IF EXISTS onboarding_run_customer_check ON onboarding_reconciliationrun;
DROP TRIGGER IF EXISTS onboarding_result_customer_check ON onboarding_reconciliationresult;
DROP FUNCTION IF EXISTS onboarding_run_customer_check();
DROP FUNCTION IF EXISTS onboarding_result_customer_check();
"""


class Migration(migrations.Migration):
    dependencies = [("onboarding", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
