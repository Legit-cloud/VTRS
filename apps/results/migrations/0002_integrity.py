from django.db import migrations

# Immutability (spec section 6.2): a result version's data never changes. The only permitted
# UPDATE is a review decision moving `state`; vote lines never change at all.
SQL = """
CREATE OR REPLACE FUNCTION result_version_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(NEW) - 'state') = (to_jsonb(OLD) - 'state')
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'result_version is immutable: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER result_version_immutable
    BEFORE UPDATE OR DELETE ON result_version
    FOR EACH ROW EXECUTE FUNCTION result_version_guard();

CREATE TRIGGER vote_line_immutable
    BEFORE UPDATE OR DELETE ON vote_line
    FOR EACH ROW EXECUTE FUNCTION vtrs_immutable_row();

SELECT vtrs_enable_tenant_rls('pu_result', 'organization_id');
SELECT vtrs_enable_tenant_rls('result_version', 'organization_id');
SELECT vtrs_enable_tenant_rls('vote_line', 'organization_id');
"""

GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        REVOKE ALL ON result_version, vote_line FROM vtrs_app;
        GRANT SELECT, INSERT ON result_version, vote_line TO vtrs_app;
        GRANT UPDATE (state) ON result_version TO vtrs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON pu_result, result_version, vote_line TO vtrs_readonly;
    END IF;
END;
$$;
"""

REVERSE = """
DROP TRIGGER IF EXISTS result_version_immutable ON result_version;
DROP TRIGGER IF EXISTS vote_line_immutable ON vote_line;
DROP FUNCTION IF EXISTS result_version_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_tenant_rls_function"),
        ("results", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
