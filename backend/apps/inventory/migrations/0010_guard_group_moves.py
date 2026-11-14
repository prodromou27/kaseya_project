from django.db import migrations

FORWARD = """
CREATE FUNCTION inventory_guard_group_move() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Group move proposals are retained audit records';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM inventory_asset a
        JOIN integrations_datasetgeneration g ON g.id = NEW.generation_id
        JOIN inventory_groupnode t ON t.id = NEW.target_group_id
        WHERE a.id = NEW.asset_id AND a.customer_id = NEW.customer_id
          AND g.customer_id = NEW.customer_id AND t.customer_id = NEW.customer_id
          AND a.integration_instance_id = g.integration_instance_id
          AND t.generation_id = NEW.generation_id AND t.external_id <> NEW.source_group_id
    ) THEN
        RAISE EXCEPTION 'Group move customer or source mismatch';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.customer_id, NEW.asset_id, NEW.generation_id, NEW.target_group_id,
            NEW.source_group_id, NEW.source_group_name, NEW.device_name, NEW.reason,
            NEW.policy_impact, NEW.requested_by_id, NEW.created_at, NEW.expires_at)
           IS DISTINCT FROM
           (OLD.customer_id, OLD.asset_id, OLD.generation_id, OLD.target_group_id,
            OLD.source_group_id, OLD.source_group_name, OLD.device_name, OLD.reason,
            OLD.policy_impact, OLD.requested_by_id, OLD.created_at, OLD.expires_at) THEN
            RAISE EXCEPTION 'Group move proposal content is immutable';
        END IF;
        IF OLD.state <> 'pending' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'Group move decision is immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER inventory_group_move_guard BEFORE INSERT OR UPDATE OR DELETE ON inventory_groupmoverequest
FOR EACH ROW EXECUTE FUNCTION inventory_guard_group_move();
"""

REVERSE = """
DROP TRIGGER IF EXISTS inventory_group_move_guard ON inventory_groupmoverequest;
DROP FUNCTION IF EXISTS inventory_guard_group_move();
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0009_group_move_proposals")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
