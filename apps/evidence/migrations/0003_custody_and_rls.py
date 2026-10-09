from django.db import migrations

# custody_event: append-only, hash-chained per file, partitioned monthly from day one
# (spec sections 6.1, 12, 17). Created here because Django cannot declare partitioned tables.
SQL = """
CREATE OR REPLACE FUNCTION vtrs_ensure_partitions(parent text, months_ahead integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    first_month date := date_trunc('month', now())::date;
    month_start date;
    partition_name text;
BEGIN
    IF parent NOT IN ('custody_event') THEN
        RAISE EXCEPTION 'not a managed partitioned table: %', parent;
    END IF;
    FOR i IN 0..months_ahead LOOP
        month_start := (first_month + make_interval(months => i))::date;
        partition_name := format('%s_%s', parent, to_char(month_start, 'YYYYMM'));
        IF to_regclass(partition_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                partition_name, parent, month_start, (month_start + interval '1 month')::date
            );
        END IF;
    END LOOP;
END;
$$;

CREATE TABLE custody_event (
    id uuid NOT NULL,
    at timestamptz NOT NULL,
    organization_id uuid NOT NULL,
    evidence_file_id uuid NOT NULL,
    seq integer NOT NULL CHECK (seq >= 1),
    event_type varchar(40) NOT NULL,
    actor_id uuid NULL,
    ip inet NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash varchar(64) NOT NULL,
    hash varchar(64) NOT NULL,
    PRIMARY KEY (id, at)
) PARTITION BY RANGE (at);

CREATE TABLE custody_event_default PARTITION OF custody_event DEFAULT;
CREATE INDEX custody_event_file_idx ON custody_event (evidence_file_id, seq);
SELECT vtrs_ensure_partitions('custody_event', 3);

CREATE TRIGGER custody_event_immutable
    BEFORE UPDATE OR DELETE ON custody_event
    FOR EACH ROW EXECUTE FUNCTION vtrs_immutable_row();

SELECT vtrs_enable_tenant_rls('custody_event', 'organization_id');
SELECT vtrs_enable_tenant_rls('evidence_file', 'organization_id');
"""

GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        REVOKE ALL ON custody_event FROM vtrs_app;
        GRANT SELECT, INSERT ON custody_event TO vtrs_app;
        REVOKE DELETE, TRUNCATE ON evidence_file FROM vtrs_app;
        GRANT EXECUTE ON FUNCTION vtrs_ensure_partitions(text, integer) TO vtrs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON custody_event, evidence_file TO vtrs_readonly;
    END IF;
END;
$$;
"""

REVERSE = """
DROP TABLE IF EXISTS custody_event CASCADE;
DROP FUNCTION IF EXISTS vtrs_ensure_partitions(text, integer);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("evidence", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
