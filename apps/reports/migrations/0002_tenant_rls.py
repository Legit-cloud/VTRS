from django.db import migrations

SQL = "SELECT vtrs_enable_tenant_rls('export_job', 'organization_id');"

GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON export_job TO vtrs_readonly;
    END IF;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
