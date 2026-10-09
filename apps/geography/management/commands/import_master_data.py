import csv
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.geography.domain.master_data import Expectations
from apps.geography.services import import_master_data


class Command(BaseCommand):
    help = "Validate and import the polling-unit master dataset (CSV, one row per polling unit)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("path", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Validate only; write nothing.")
        parser.add_argument("--report", type=Path, help="Write the validation report as JSON.")
        parser.add_argument(
            "--no-expectations",
            action="store_true",
            help="Skip the expected LGA/ward/polling-unit counts (for partial datasets).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        if not path.is_file():
            raise CommandError(f"{path} does not exist")
        expectations = (
            None
            if options["no_expectations"]
            else Expectations.from_mapping(settings.VTRS_GEOGRAPHY_EXPECTED)
        )
        with path.open(newline="", encoding="utf-8-sig") as handle:
            outcome = import_master_data(
                csv.DictReader(handle), expectations=expectations, dry_run=options["dry_run"]
            )

        result = outcome.as_dict()
        if options["report"]:
            options["report"].write_text(json.dumps(result, indent=2), encoding="utf-8")

        counts = result["counts"]
        self.stdout.write(
            f"states={counts.get('states', 0)} lgas={counts.get('lgas', 0)} "
            f"wards={counts.get('wards', 0)} polling_units={counts.get('polling_units', 0)} "
            f"coordinate_coverage={result['coordinate_coverage']:.1%}"
        )
        for warning in result["warnings"]:
            self.stdout.write(self.style.WARNING(f"warning: {warning}"))
        for error in result["errors"]:
            self.stderr.write(f"error: {error}")
        if not outcome.report.ok:
            raise CommandError(f"Import rejected: {outcome.report.error_count} errors")
        if outcome.applied:
            self.stdout.write(self.style.SUCCESS(f"Imported: {json.dumps(outcome.changes)}"))
        else:
            self.stdout.write(self.style.SUCCESS("Dataset is valid (dry run, nothing written)"))
