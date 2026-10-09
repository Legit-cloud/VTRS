from django.db import migrations

SQL = """
SELECT vtrs_enable_tenant_rls('election', 'organization_id');
SELECT vtrs_enable_tenant_rls('contest', 'organization_id');
SELECT vtrs_enable_tenant_rls('candidate', 'organization_id');
"""

REVERSE = """
DROP POLICY IF EXISTS tenant_isolation ON election;
ALTER TABLE election DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON contest;
ALTER TABLE contest DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON candidate;
ALTER TABLE candidate DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("elections", "0001_initial"),
    ]

    operations = [migrations.RunSQL(SQL, reverse_sql=REVERSE)]
