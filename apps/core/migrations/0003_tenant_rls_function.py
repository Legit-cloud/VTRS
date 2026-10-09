from django.db import migrations

# Tenant isolation policy (spec section 6.2), applied per table by later migrations:
#   SELECT vtrs_enable_tenant_rls('<table>', '<organization column>');
# Rows are visible only when the column matches app.current_org, or inside an explicit
# system context. With neither set, a tenant table returns nothing.
SQL = """
CREATE OR REPLACE FUNCTION vtrs_enable_tenant_rls(tbl regclass, col text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    rule text := format(
        '(current_setting(''app.rls_system'', true) = ''on'' '
        'OR %I::text = current_setting(''app.current_org'', true))',
        col
    );
BEGIN
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format(
        'CREATE POLICY tenant_isolation ON %s USING %s WITH CHECK %s', tbl, rule, rule
    );
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0002_immutable_row_function")]

    operations = [
        migrations.RunSQL(
            SQL, reverse_sql="DROP FUNCTION IF EXISTS vtrs_enable_tenant_rls(regclass, text);"
        ),
    ]
