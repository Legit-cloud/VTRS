from django.db import migrations

# audit_event: partitioned monthly by `at`, insert-only (spec sections 6.2, 16).
# The only permitted UPDATE is the sealer setting batch_id once, leaving every other column alone.
CREATE_EVENTS = """
CREATE TABLE audit_event (
    id uuid NOT NULL,
    at timestamptz NOT NULL,
    actor_id uuid NULL,
    actor_role varchar(32) NOT NULL DEFAULT '',
    organization_id uuid NULL,
    action varchar(100) NOT NULL,
    object_type varchar(100) NOT NULL,
    object_id varchar(64) NOT NULL DEFAULT '',
    ip inet NULL,
    request_id varchar(64) NOT NULL DEFAULT '',
    diff jsonb NOT NULL DEFAULT '{}'::jsonb,
    batch_id uuid NULL,
    PRIMARY KEY (id, at)
) PARTITION BY RANGE (at);

CREATE TABLE audit_event_default PARTITION OF audit_event DEFAULT;

CREATE INDEX audit_event_org_at_idx ON audit_event (organization_id, at);
CREATE INDEX audit_event_object_idx ON audit_event (object_type, object_id);
CREATE INDEX audit_event_batch_idx ON audit_event (batch_id);
CREATE INDEX audit_event_unsealed_idx ON audit_event (id) WHERE batch_id IS NULL;

-- Runs as the owner so the app role can extend partitions without DDL rights.
CREATE OR REPLACE FUNCTION audit_ensure_partitions(months_ahead integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    first_month date := date_trunc('month', now())::date;
    month_start date;
    partition_name text;
BEGIN
    FOR i IN 0..months_ahead LOOP
        month_start := (first_month + make_interval(months => i))::date;
        partition_name := format('audit_event_%s', to_char(month_start, 'YYYYMM'));
        IF to_regclass(partition_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF audit_event FOR VALUES FROM (%L) TO (%L)',
                partition_name, month_start, (month_start + interval '1 month')::date
            );
        END IF;
    END LOOP;
END;
$$;

SELECT audit_ensure_partitions(3);

CREATE OR REPLACE FUNCTION audit_event_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.batch_id IS NULL
       AND NEW.batch_id IS NOT NULL
       AND (NEW.id, NEW.at, NEW.actor_id, NEW.actor_role, NEW.organization_id, NEW.action,
            NEW.object_type, NEW.object_id, NEW.ip, NEW.request_id, NEW.diff)
           IS NOT DISTINCT FROM
           (OLD.id, OLD.at, OLD.actor_id, OLD.actor_role, OLD.organization_id, OLD.action,
            OLD.object_type, OLD.object_id, OLD.ip, OLD.request_id, OLD.diff)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_event is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_event_append_only
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_guard();

CREATE TRIGGER audit_batch_immutable
    BEFORE UPDATE OR DELETE ON audit_batch
    FOR EACH ROW EXECUTE FUNCTION vtrs_immutable_row();
"""

# Restricted grants for the app role, when it exists (it does in the Compose stack, not in CI).
GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        REVOKE ALL ON audit_event, audit_batch FROM vtrs_app;
        GRANT SELECT, INSERT ON audit_event, audit_batch TO vtrs_app;
        GRANT UPDATE (batch_id) ON audit_event TO vtrs_app;
        GRANT EXECUTE ON FUNCTION audit_ensure_partitions(integer) TO vtrs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON audit_event, audit_batch TO vtrs_readonly;
    END IF;
END;
$$;
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_batch_immutable ON audit_batch;
DROP TABLE IF EXISTS audit_event CASCADE;
DROP FUNCTION IF EXISTS audit_event_guard();
DROP FUNCTION IF EXISTS audit_ensure_partitions(integer);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("core", "0002_immutable_row_function"),
    ]

    operations = [
        migrations.RunSQL(CREATE_EVENTS, reverse_sql=REVERSE),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
