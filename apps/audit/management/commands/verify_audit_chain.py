from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.audit import services


class Command(BaseCommand):
    help = "Recompute audit batch Merkle roots and the chain between them."

    def handle(self, *args: Any, **options: Any) -> None:
        problems = services.verify_chain()
        if problems:
            for problem in problems:
                self.stderr.write(problem)
            raise CommandError(f"Audit chain verification failed ({len(problems)} problems)")
        self.stdout.write(self.style.SUCCESS("Audit chain intact"))
