from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("anomalies", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(
            "SELECT vtrs_enable_tenant_rls('anomaly_flag', 'organization_id');",
            reverse_sql=(
                "DROP POLICY IF EXISTS tenant_isolation ON anomaly_flag;"
                "ALTER TABLE anomaly_flag DISABLE ROW LEVEL SECURITY;"
            ),
        )
    ]
