from django.db import migrations

# The flag's history is append-only: the app role may add events, never change or remove them,
# and a trigger refuses it for everyone else.
SQL = """
CREATE TRIGGER anomaly_flag_event_immutable
    BEFORE UPDATE OR DELETE ON anomaly_flag_event
    FOR EACH ROW EXECUTE FUNCTION vtrs_immutable_row();

SELECT vtrs_enable_tenant_rls('anomaly_flag_event', 'organization_id');
"""

GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        REVOKE ALL ON anomaly_flag_event FROM vtrs_app;
        GRANT SELECT, INSERT ON anomaly_flag_event TO vtrs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON anomaly_flag_event TO vtrs_readonly;
    END IF;
END;
$$;
"""

REVERSE = "DROP TRIGGER IF EXISTS anomaly_flag_event_immutable ON anomaly_flag_event;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("anomalies", "0004_triage_and_escalation"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
