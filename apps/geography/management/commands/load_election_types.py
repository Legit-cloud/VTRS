import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.geography.services import load_election_types


class Command(BaseCommand):
    help = "Load the configured election types (default: data/election_types.json)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "path", type=Path, nargs="?", default=settings.BASE_DIR / "data" / "election_types.json"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        if not path.is_file():
            raise CommandError(f"{path} does not exist")
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
            changes = load_election_types(entries)
        except (ValueError, TypeError) as exc:
            raise CommandError(f"Election types rejected: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Election types loaded: {json.dumps(changes)}"))
