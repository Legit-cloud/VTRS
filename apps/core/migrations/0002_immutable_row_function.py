from django.db import migrations

# Shared guard for immutable tables (result versions, vote lines, custody events, audit
# batches): attach as BEFORE UPDATE OR DELETE ... FOR EACH ROW.
SQL = """
CREATE OR REPLACE FUNCTION vtrs_immutable_row() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is immutable: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.RunSQL(SQL, reverse_sql="DROP FUNCTION IF EXISTS vtrs_immutable_row();"),
    ]
