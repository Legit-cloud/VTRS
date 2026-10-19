import csv
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.geography.services import derive_constituencies, import_constituencies


class Command(BaseCommand):
    help = (
        "Map polling units to constituencies. --derive builds the STATE, LGA and WARD "
        "constituencies from geography; a CSV (kind, code, name, state_code, lga_code, "
        "ward_code) adds senatorial districts, federal and state constituencies."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path, nargs="?")
        parser.add_argument(
            "--derive", action="store_true", help="Derive STATE, LGA and WARD constituencies."
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate only; write nothing.")
        parser.add_argument("--report", type=Path, help="Write the validation report as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path | None = options["path"]
        if not path and not options["derive"]:
            raise CommandError("Give a CSV file, --derive, or both.")
        if options["derive"] and not options["dry_run"]:
            mapped = derive_constituencies()
            self.stdout.write(self.style.SUCCESS(f"Derived: {json.dumps(mapped)}"))
        if not path:
            return
        if not path.is_file():
            raise CommandError(f"{path} does not exist")
        with path.open(newline="", encoding="utf-8-sig") as handle:
            outcome = import_constituencies(csv.DictReader(handle), dry_run=options["dry_run"])
        result = outcome.as_dict()
        if options["report"]:
            options["report"].write_text(json.dumps(result, indent=2), encoding="utf-8")
        self.stdout.write(f"constituencies={json.dumps(result['constituencies'])}")
        for warning in result["warnings"]:
            self.stdout.write(self.style.WARNING(f"warning: {warning}"))
        for error in result["errors"]:
            self.stderr.write(f"error: {error}")
        if not outcome.report.ok:
            raise CommandError(f"Import rejected: {outcome.report.error_count} errors")
        if outcome.applied:
            self.stdout.write(self.style.SUCCESS(f"Imported: {json.dumps(outcome.mapped)}"))
        else:
            self.stdout.write(self.style.SUCCESS("File is valid (dry run, nothing written)"))
