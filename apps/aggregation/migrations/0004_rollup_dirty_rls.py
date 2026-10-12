from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("aggregation", "0003_rollup_dirty"),
    ]

    operations = [
        migrations.RunSQL(
            "SELECT vtrs_enable_tenant_rls('rollup_dirty', 'organization_id');",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
