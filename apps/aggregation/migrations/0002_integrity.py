from django.db import migrations

# Tenant isolation on every table, and an append-only reconciliation snapshot: the app role
# may insert it but never change or remove it, and a trigger refuses it for everyone else.
SQL = """
SELECT vtrs_enable_tenant_rls('rollup', 'organization_id');
SELECT vtrs_enable_tenant_rls('rollup_vote', 'organization_id');
SELECT vtrs_enable_tenant_rls('reconciliation_snapshot', 'organization_id');

CREATE TRIGGER reconciliation_snapshot_immutable
    BEFORE UPDATE OR DELETE ON reconciliation_snapshot
    FOR EACH ROW EXECUTE FUNCTION vtrs_immutable_row();
"""

GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        REVOKE ALL ON reconciliation_snapshot FROM vtrs_app;
        GRANT SELECT, INSERT ON reconciliation_snapshot TO vtrs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON rollup, rollup_vote, reconciliation_snapshot TO vtrs_readonly;
    END IF;
END;
$$;
"""

REVERSE = "DROP TRIGGER IF EXISTS reconciliation_snapshot_immutable ON reconciliation_snapshot;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("aggregation", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
