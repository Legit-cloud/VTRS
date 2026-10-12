"""Create (or reset) a platform operator.

Operators are not invited through the product: an invitation is issued by a party admin, and
no party admin may hold this role. They are created here, on a trusted machine, and enrol an
authenticator the first time they sign in.
"""

from typing import Any

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.domain.contact import normalize_email, normalize_phone
from apps.accounts.models import Membership, User, UserStatus
from apps.core.crypto import blind_index
from apps.core.rls import system_context
from apps.organizations.models import Organization, OrganizationStatus

PLATFORM_NAME = "VTRS platform"


class Command(BaseCommand):
    help = "Create a platform operator (full access across all parties). Prompts nothing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--phone", default="")
        parser.add_argument("--password", required=True, help="At least 14 characters.")

    def handle(self, *args: Any, **options: Any) -> None:
        if len(options["password"]) < 14:
            raise CommandError("Use a password of at least 14 characters.")
        try:
            email = normalize_email(options["email"])
            phone = normalize_phone(options["phone"]) if options["phone"] else ""
        except ValueError as exc:
            raise CommandError(str(exc)) from None

        with transaction.atomic(), system_context():
            org, _ = Organization.objects.get_or_create(
                is_platform=True,
                defaults={"name": PLATFORM_NAME, "status": OrganizationStatus.ACTIVE},
            )
            user = User.objects.filter(email_index=blind_index("email", email)).first()
            if (
                user is not None
                and Membership.objects.filter(user=user, status="ACTIVE")
                .exclude(organization=org)
                .exists()
            ):
                raise CommandError("That person already belongs to a party.")
            if user is None:
                user = User.objects.create_user(
                    password=None,
                    full_name=options["name"],
                    email=email,
                    email_index=blind_index("email", email),
                    phone=phone,
                    phone_index=blind_index("phone", phone) if phone else None,
                    status=UserStatus.ACTIVE,
                )
            user.password = make_password(options["password"])
            user.status = UserStatus.ACTIVE
            user.save()
            Membership.objects.get_or_create(
                user=user,
                organization=org,
                defaults={"role": "PLATFORM_ADMIN", "scope_type": "ORG", "scope_ids": []},
            )
        self.stdout.write(self.style.SUCCESS(f"Platform operator ready: {email}"))
