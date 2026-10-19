from django.db import migrations

SQL = """
SELECT vtrs_enable_tenant_rls('party', 'organization_id');
SELECT vtrs_enable_tenant_rls('election_party', 'organization_id');
SELECT vtrs_enable_tenant_rls('config_issue', 'organization_id');
"""

REVERSE = """
DROP POLICY IF EXISTS tenant_isolation ON party;
ALTER TABLE party DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON election_party;
ALTER TABLE election_party DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON config_issue;
ALTER TABLE config_issue DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("elections", "0004_require_type_constituency_party"),
    ]

    operations = [migrations.RunSQL(SQL, reverse_sql=REVERSE)]
