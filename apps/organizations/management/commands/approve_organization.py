from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.core.rls import system_context
from apps.organizations import services
from apps.organizations.models import Organization


class Command(BaseCommand):
    help = "Approve a verified organization registration (platform operator action)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("organization_id", type=UUID)
        parser.add_argument(
            "--operator", required=True, help="Who is approving (for the audit log)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic(), system_context():
            try:
                org = services.approve(options["organization_id"], operator=options["operator"])
            except Organization.DoesNotExist:
                raise CommandError("No such organization") from None
            except ValueError as exc:
                raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(f"Approved {org.name} ({org.id})"))
