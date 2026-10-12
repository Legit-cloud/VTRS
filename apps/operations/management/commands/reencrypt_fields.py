from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.core.fields import EncryptedTextField
from apps.core.rls import system_context

BATCH = 500


class Command(BaseCommand):
    help = (
        "Rewrite encrypted columns that were sealed with an older key so they use the active "
        "key (VTRS_FIELD_ENCRYPTION_ACTIVE_KEY). Run after rotating, then retire the old key. "
        "Safe to repeat; rows already on the active key are left alone."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count, change nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        from django.conf import settings

        active = settings.VTRS_FIELD_ENCRYPTION_ACTIVE_KEY
        keep = f"v1:{active}:%"
        total = 0
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, EncryptedTextField):
                    continue
                table = model._meta.db_table
                column = str(field.column)
                pk = str(model._meta.pk.column)  # type: ignore[union-attr]
                changed = self._rewrite(model, field.name, table, column, pk, keep, options)
                total += changed
                self.stdout.write(f"{table}.{column}: {changed} row(s)")
        verb = "would re-encrypt" if options["dry_run"] else "re-encrypted"
        self.stdout.write(self.style.SUCCESS(f"{verb} {total} value(s) onto key {active!r}"))

    def _rewrite(
        self, model: Any, name: str, table: str, column: str, pk: str, keep: str, options: dict
    ) -> int:
        done = 0
        while True:
            with transaction.atomic(), system_context(), connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT "{pk}" FROM "{table}" '  # noqa: S608  # nosec B608 - identifiers come from model metadata, values are bound
                    f'WHERE "{column}" <> \'\' AND "{column}" NOT LIKE %s '
                    f'ORDER BY "{pk}" LIMIT %s',
                    [keep, BATCH],
                )
                ids = [row[0] for row in cursor.fetchall()]
                if not ids:
                    return done
                if options["dry_run"]:
                    count = model.objects.filter(pk__in=ids).count() if len(ids) < BATCH else None
                    return done + (count or len(ids))  # one batch is enough to say "yes"
                for pk_value, plaintext in model.objects.filter(pk__in=ids).values_list("pk", name):
                    # Saving the decrypted value seals it again with the active key.
                    model.objects.filter(pk=pk_value).update(**{name: plaintext})
                done += len(ids)
