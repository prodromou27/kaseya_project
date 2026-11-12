"""DB-level customer consistency for software rows and immutability of published catalog revisions."""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION software_installation_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM (SELECT customer_id FROM inventory_asset WHERE id = NEW.asset_id)
       OR NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM integrations_datasetgeneration WHERE id = NEW.generation_id) THEN
        RAISE EXCEPTION 'customer mismatch on software_softwareinstallation' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER software_installation_customer_check
    BEFORE INSERT OR UPDATE ON software_softwareinstallation
    FOR EACH ROW EXECUTE FUNCTION software_installation_customer_check();

CREATE OR REPLACE FUNCTION software_result_customer_check() RETURNS trigger AS $$
BEGIN
    IF NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM software_softwareinstallation WHERE id = NEW.installation_id)
       OR NEW.customer_id IS DISTINCT FROM
          (SELECT customer_id FROM software_complianceevaluation WHERE id = NEW.evaluation_id) THEN
        RAISE EXCEPTION 'customer mismatch on software_complianceresult' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER software_result_customer_check
    BEFORE INSERT OR UPDATE ON software_complianceresult
    FOR EACH ROW EXECUTE FUNCTION software_result_customer_check();

CREATE OR REPLACE FUNCTION software_revision_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'catalog revisions cannot be deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.product_id IS DISTINCT FROM OLD.product_id
       OR NEW.reference_version IS DISTINCT FROM OLD.reference_version
       OR NEW.version_scheme IS DISTINCT FROM OLD.version_scheme
       OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
       OR NEW.reviewed_by_id IS DISTINCT FROM OLD.reviewed_by_id
       OR (OLD.state = 'retired' AND NEW.state <> 'retired') THEN
        RAISE EXCEPTION 'published catalog revisions are immutable' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER software_revision_immutable
    BEFORE UPDATE OR DELETE ON software_catalogrevision
    FOR EACH ROW EXECUTE FUNCTION software_revision_immutable();
"""

REVERSE = """
DROP TRIGGER IF EXISTS software_revision_immutable ON software_catalogrevision;
DROP FUNCTION IF EXISTS software_revision_immutable();
DROP TRIGGER IF EXISTS software_result_customer_check ON software_complianceresult;
DROP FUNCTION IF EXISTS software_result_customer_check();
DROP TRIGGER IF EXISTS software_installation_customer_check ON software_softwareinstallation;
DROP FUNCTION IF EXISTS software_installation_customer_check();
"""


class Migration(migrations.Migration):
    dependencies = [("software", "0001_initial"), ("inventory", "0002_customer_consistency_trigger")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
