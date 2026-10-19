from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.aggregation import services
from apps.core.rls import system_context
from apps.elections.models import Contest


class Command(BaseCommand):
    help = (
        "Recalculate rollups from head versions (an operator repair; the workers keep them "
        "current). Without arguments it rebuilds every contest of every election."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--election", type=UUID, help="Only this election")
        parser.add_argument("--contest", type=UUID, help="Only this contest")

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic(), system_context():
            contests = Contest.objects.all()
            if options["election"]:
                contests = contests.filter(election_id=options["election"])
            if options["contest"]:
                contests = contests.filter(id=options["contest"])
            targets = list(contests.values_list("organization_id", "id", "constituency__name"))
        for organization_id, contest_id, title in targets:
            wards = services.rebuild_contest(organization_id=organization_id, contest_id=contest_id)
            self.stdout.write(f"{title} ({contest_id}): rebuilt {wards} wards")
        self.stdout.write(self.style.SUCCESS(f"Rebuilt {len(targets)} contest(s)"))
