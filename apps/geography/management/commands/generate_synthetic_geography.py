import csv
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.geography.domain.master_data import OPTIONAL_COLUMNS, REQUIRED_COLUMNS
from apps.geography.domain.synthetic import synthetic_master_data


class Command(BaseCommand):
    help = "Write a synthetic Oyo-shaped master dataset (33 LGAs, 351 wards, 6,390 PUs) as CSV."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args: Any, **options: Any) -> None:
        rows = synthetic_master_data(seed=options["seed"])
        with options["out"].open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {len(rows)} polling units to {options['out']}")
        )
