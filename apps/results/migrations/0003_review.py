import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.core.ids

SQL = """
CREATE TRIGGER result_review_immutable
    BEFORE UPDATE OR DELETE ON result_review
    FOR EACH ROW EXECUTE FUNCTION vtrs_immutable_row();

SELECT vtrs_enable_tenant_rls('result_review', 'organization_id');
"""

GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_app') THEN
        REVOKE ALL ON result_review FROM vtrs_app;
        GRANT SELECT, INSERT ON result_review TO vtrs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vtrs_readonly') THEN
        GRANT SELECT ON result_review TO vtrs_readonly;
    END IF;
END;
$$;
"""

REVERSE = "DROP TRIGGER IF EXISTS result_review_immutable ON result_review;"


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_tenant_rls"),
        ("elections", "0002_tenant_rls"),
        ("geography", "0001_initial"),
        ("organizations", "0001_initial"),
        ("results", "0002_integrity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ResultReview",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.core.ids.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        choices=[("APPROVED", "APPROVED"), ("REJECTED", "REJECTED")],
                        max_length=10,
                    ),
                ),
                ("from_state", models.CharField(max_length=16)),
                ("reason", models.TextField(blank=True, default="")),
                ("acknowledged_flags", models.JSONField(default=list)),
                ("decided_at", models.DateTimeField()),
                (
                    "contest",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="elections.contest",
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lga",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="geography.lga",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "polling_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="geography.pollingunit",
                    ),
                ),
                (
                    "pu_result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="results.puresult",
                    ),
                ),
                (
                    "result_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reviews",
                        to="results.resultversion",
                    ),
                ),
                (
                    "ward",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="geography.ward",
                    ),
                ),
            ],
            options={"db_table": "result_review"},
        ),
        migrations.AddIndex(
            model_name="resultreview",
            index=models.Index(
                fields=["result_version", "decided_at"], name="review_version_idx"
            ),
        ),
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
        migrations.RunSQL(GRANTS, reverse_sql=migrations.RunSQL.noop),
    ]
