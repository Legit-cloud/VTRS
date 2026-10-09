from django.db import migrations

# Row Level Security on tenant tables (spec section 6.2). See core 0003 for the policy.
SQL = """
SELECT vtrs_enable_tenant_rls('organization', 'id');
SELECT vtrs_enable_tenant_rls('account_membership', 'organization_id');
SELECT vtrs_enable_tenant_rls('account_invitation', 'organization_id');
"""

REVERSE = """
DROP POLICY IF EXISTS tenant_isolation ON organization;
ALTER TABLE organization DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON account_membership;
ALTER TABLE account_membership DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON account_invitation;
ALTER TABLE account_invitation DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("organizations", "0001_initial"),
        ("accounts", "0002_device_invitation_membership_otpchallenge_and_more"),
    ]

    operations = [migrations.RunSQL(SQL, reverse_sql=REVERSE)]
