from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.aggregation import services
from apps.core import rls
from apps.core.rls import system_context
from apps.elections.models import Contest


class Command(BaseCommand):
    help = (
        "Compare every stored rollup with a fresh calculation from head versions. "
        "Exits non-zero if any figure differs; run rebuild_rollups to repair."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--election", type=UUID, help="Only this election")

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic(), system_context():
            contests = Contest.objects.select_related("election")
            if options["election"]:
                contests = contests.filter(election_id=options["election"])
            targets = [(c.organization_id, c.id) for c in contests]
        differences = 0
        for organization_id, contest_id in targets:
            with transaction.atomic():
                rls.set_tenant(organization_id)
                contest = Contest.objects.select_related("election").get(id=contest_id)
                problems = services.verify_contest(contest)
            for problem in problems:
                self.stderr.write(f"{contest_id}: {problem}")
            differences += len(problems)
        if differences:
            raise CommandError(f"{differences} difference(s) in {len(targets)} contest(s)")
        self.stdout.write(self.style.SUCCESS(f"All rollups reconcile ({len(targets)} contest(s))"))
