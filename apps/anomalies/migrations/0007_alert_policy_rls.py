from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("anomalies", "0006_alert_policy"),
    ]

    operations = [
        migrations.RunSQL(
            "SELECT vtrs_enable_tenant_rls('alert_policy', 'organization_id');",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
