"""Give the newest simulated organization people who can sign in to the portal.

`simulate_election_day` mints tokens for its users, so none of them has a password. This turns
the latest simulated organization into something a person (or the browser tests in
`frontend/e2e`) can use: the admin, a ward coordinator, an LGA coordinator and one agent,
each with a password. Sign-in codes go to these addresses; in development they land in the
local mailbox (Mailpit, http://localhost:8025).

Development databases only, like the simulator. Safe to run again: it resets the passwords.
"""

import os
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, User, UserStatus
from apps.assignments.models import AgentAssignment, AssignmentStatus
from apps.core.crypto import blind_index
from apps.core.rls import system_context
from apps.elections.models import Election
from apps.organizations.models import Organization, OrganizationStatus

DOMAIN = "demo.example"


class Command(BaseCommand):
    help = "Create sign-in accounts for the newest simulated organization (development only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--password", default="Demo-passphrase-2026")

    def handle(self, *args: Any, **options: Any) -> None:
        if not (settings.DEBUG or os.environ.get("VTRS_ALLOW_SIMULATION") == "1"):
            raise CommandError("Refusing to run outside development (see simulate_election_day).")
        password = make_password(options["password"])

        with transaction.atomic(), system_context():
            org = (
                Organization.objects.filter(name__startswith="Sim ").order_by("-created_at").first()
            )
            if org is None:
                raise CommandError("Run simulate_election_day first.")
            # The election the simulator staffed, not one created by hand afterwards.
            election = (
                Election.objects.filter(organization=org, assignments__isnull=False)
                .order_by("-created_at")
                .first()
            )
            # A still-deployed agent: a browser test may have deactivated an earlier one.
            first = (
                AgentAssignment.objects.filter(
                    election=election,
                    status=AssignmentStatus.ACTIVE,
                    agent__status=UserStatus.ACTIVE,
                )
                .select_related("polling_unit")
                .order_by("polling_unit__inec_code")
                .first()
                if election
                else None
            )
            if election is None or first is None:
                raise CommandError("The simulated organization has no election with agents.")

            admin_membership = Membership.objects.select_related("user").get(
                organization=org, role="PARTY_ADMIN"
            )
            admin = admin_membership.user
            admin.email = f"admin@{DOMAIN}"
            admin.email_index = blind_index("email", admin.email)
            admin.full_name = "Adaeze Bello"
            admin.password = password
            admin.status = UserStatus.ACTIVE
            admin.save()

            def person(email: str, name: str, role: str, scope_type: str, scope_ids: list) -> None:
                index = blind_index("email", email)
                user = User.objects.filter(email_index=index).first()
                if user is None:
                    user = User.objects.create_user(
                        password=None,
                        full_name=name,
                        email=email,
                        email_index=index,
                        status=UserStatus.ACTIVE,
                    )
                    Membership.objects.create(
                        user=user,
                        organization=org,
                        role=role,
                        scope_type=scope_type,
                        scope_ids=scope_ids,
                    )
                user.password = password
                user.save()

            unit = first.polling_unit
            person(f"ward@{DOMAIN}", "Tunde Okafor", "WARD_OFFICER", "WARD", [unit.ward_id])
            person(f"lga@{DOMAIN}", "Funmi Adeyemi", "LGA_OFFICER", "LGA", [unit.lga_id])
            # The first deployed agent signs in to the same web app, from a phone browser.
            agent = User.objects.get(id=first.agent_id)
            agent_email = f"agent@{DOMAIN}"
            agent_index = blind_index("email", agent_email)
            # The address moves to this agent; whoever had it before keeps their history.
            for previous in User.objects.filter(email_index=agent_index).exclude(id=agent.id):
                previous.email = f"retired-{previous.id}@{DOMAIN}"
                previous.email_index = blind_index("email", previous.email)
                previous.save()
            agent.email = agent_email
            agent.email_index = agent_index
            agent.full_name = "Kemi Adebayo"
            agent.password = password
            agent.save()

        # A platform operator, and registrations waiting for them to decide on.
        operator_password = options["password"] + "-ops"
        call_command(
            "create_platform_admin",
            email=f"ops@{DOMAIN}",
            name="Ngozi Eze",
            phone="",
            password=operator_password,
            verbosity=0,
        )
        with transaction.atomic(), system_context():
            Organization.objects.filter(
                name__startswith="Pending Party", status=OrganizationStatus.PENDING_APPROVAL
            ).delete()
            for n in (1, 2, 3):
                Organization.objects.create(
                    name=f"Pending Party {n}",
                    legal_name=f"Pending Party {n} Limited",
                    status=OrganizationStatus.PENDING_APPROVAL,
                    verified_at=timezone.now(),
                )

        self.stdout.write(
            f"Ready: {org.name}, election {election.name}.\n"
            f"  admin@{DOMAIN} (party admin)\n"
            f"  ward@{DOMAIN}  (ward coordinator)\n"
            f"  lga@{DOMAIN}   (LGA coordinator)\n"
            f"  agent@{DOMAIN} (polling unit agent, {unit.inec_code})\n"
            f"  password: {options['password']}\n"
            f"  ops@{DOMAIN}   (platform operator)\n"
            f"  password: {operator_password}\n"
            "  sign-in codes: http://localhost:8025"
        )
