from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("assignments", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(
            "SELECT vtrs_enable_tenant_rls('agent_assignment', 'organization_id');",
            reverse_sql=(
                "DROP POLICY IF EXISTS tenant_isolation ON agent_assignment;"
                "ALTER TABLE agent_assignment DISABLE ROW LEVEL SECURITY;"
            ),
        )
    ]
