"""Approved lifecycle entries are evidence: immutable except retirement; never deleted once reviewed."""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION software_lifecycle_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state <> 'proposed' THEN
            RAISE EXCEPTION 'reviewed lifecycle entries cannot be deleted' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.state IN ('approved', 'rejected', 'retired') AND (
           NEW.kind IS DISTINCT FROM OLD.kind
        OR NEW.os_family IS DISTINCT FROM OLD.os_family
        OR NEW.product_id IS DISTINCT FROM OLD.product_id
        OR NEW.release_label IS DISTINCT FROM OLD.release_label
        OR NEW.version_prefix IS DISTINCT FROM OLD.version_prefix
        OR NEW.release_date IS DISTINCT FROM OLD.release_date
        OR NEW.end_of_mainstream IS DISTINCT FROM OLD.end_of_mainstream
        OR NEW.end_of_support IS DISTINCT FROM OLD.end_of_support
        OR NEW.extended_until IS DISTINCT FROM OLD.extended_until
        OR NEW.source_url IS DISTINCT FROM OLD.source_url
        OR NEW.source_type IS DISTINCT FROM OLD.source_type
        OR NEW.source_checked_at IS DISTINCT FROM OLD.source_checked_at
        OR NEW.confidence IS DISTINCT FROM OLD.confidence
        OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
        OR NEW.reviewed_by_id IS DISTINCT FROM OLD.reviewed_by_id
        OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
        OR (OLD.state = 'approved' AND NEW.state NOT IN ('approved', 'retired'))
        OR (OLD.state IN ('rejected', 'retired') AND NEW.state IS DISTINCT FROM OLD.state)
    ) THEN
        RAISE EXCEPTION 'reviewed lifecycle entries are immutable (retire and propose a new one)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER software_lifecycle_immutable
    BEFORE UPDATE OR DELETE ON software_lifecycleentry
    FOR EACH ROW EXECUTE FUNCTION software_lifecycle_immutable();
"""

REVERSE = """
DROP TRIGGER IF EXISTS software_lifecycle_immutable ON software_lifecycleentry;
DROP FUNCTION IF EXISTS software_lifecycle_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("software", "0003_lifecycle_entry")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
