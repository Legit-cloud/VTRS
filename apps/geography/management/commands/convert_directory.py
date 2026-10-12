import csv
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.geography.domain.directory import DirectoryFormatError, parse_directory
from apps.geography.domain.master_data import OPTIONAL_COLUMNS, REQUIRED_COLUMNS


class Command(BaseCommand):
    help = (
        "Convert a names-only polling-unit directory (Markdown) into the master-data CSV that "
        "import_master_data reads. Codes are provisional (DIR-prefixed) and positional."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("source", type=Path, help="Markdown directory file")
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--state-code", default="OY", help="Short state code (default OY)")
        parser.add_argument("--state-name", default="Oyo", help="State name (default Oyo)")

    def handle(self, *args: Any, **options: Any) -> None:
        source: Path = options["source"]
        if not source.is_file():
            raise CommandError(f"{source} does not exist")
        try:
            with source.open(encoding="utf-8-sig") as handle:
                rows = list(
                    parse_directory(
                        handle,
                        state_code=options["state_code"],
                        state_name=options["state_name"],
                    )
                )
        except DirectoryFormatError as exc:
            raise CommandError(str(exc)) from exc
        if not rows:
            raise CommandError("no polling units found in the directory")

        with options["out"].open("w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        lgas = len({r["lga_code"] for r in rows})
        wards = len({r["ward_code"] for r in rows})
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(rows)} polling units ({lgas} LGAs, {wards} wards) to {options['out']}"
            )
        )
        self.stdout.write(
            "Import with --no-expectations: the directory is incomplete by design "
            "(units added in 2022 are missing) and has no coordinates."
        )
