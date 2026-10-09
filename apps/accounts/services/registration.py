"""Organization registration (FR-6.1.1, FR-6.1.2, AC-01).

The organization stays pending until the signer verifies an OTP and a platform operator
approves it. Face verification (FR-6.1.3) stays behind VTRS_FEATURE_FACE_VERIFICATION, off.
"""

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.core.crypto import blind_index
from apps.core.domain.actor import ScopeKind
from apps.core.domain.permissions import Role
from apps.core.rls import system_context
from apps.organizations import services as organizations

from ..domain.contact import normalize_email, normalize_phone
from ..models import Membership, OtpChannel, OtpPurpose, User, UserStatus
from . import otp


@dataclass(frozen=True)
class Registration:
    organization_id: UUID
    challenge_id: UUID


def normalized_contact(email: str, phone: str) -> tuple[str, str]:
    errors = {}
    try:
        email = normalize_email(email) if email else ""
    except ValueError as exc:
        errors["email"] = [str(exc)]
    try:
        phone = normalize_phone(phone) if phone else ""
    except ValueError as exc:
        errors["phone"] = [str(exc)]
    if errors:
        raise ValidationError(errors)
    return email, phone


def check_password_strength(password: str, user: User | None = None) -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from None


def register_organization(
    *,
    organization_name: str,
    legal_name: str,
    admin_name: str,
    email: str,
    phone: str,
    password: str,
    otp_channel: str,
    ip: str | None,
) -> Registration:
    email, phone = normalized_contact(email, phone)
    check_password_strength(password)
    channel = OtpChannel(otp_channel)
    destination = phone if channel == OtpChannel.SMS else email
    email_index, phone_index = blind_index("email", email), blind_index("phone", phone)
    try:
        with transaction.atomic(), system_context():
            if (
                User.objects.filter(email_index=email_index).exists()
                or User.objects.filter(phone_index=phone_index).exists()
            ):
                raise ValidationError(
                    {"email": ["An account already uses this email or phone number."]},
                    code="already_registered",
                )
            org = organizations.create_organization(name=organization_name, legal_name=legal_name)
            user = User.objects.create_user(
                password=password,
                full_name=admin_name,
                email=email,
                email_index=email_index,
                phone=phone,
                phone_index=phone_index,
                status=UserStatus.PENDING_VERIFICATION,
            )
            Membership.objects.create(
                user=user, organization=org, role=Role.PARTY_ADMIN, scope_type=ScopeKind.ORG
            )
            challenge = otp.start(
                purpose=OtpPurpose.REGISTRATION,
                channel=channel,
                destination=destination,
                subject_id=user.id,
                ip=ip,
            )
            audit.record(
                action="organization.registered",
                object_type="organization",
                object_id=org.id,
                organization_id=org.id,
                diff={"admin_user_id": user.id, "otp_channel": channel},
            )
    except IntegrityError:
        # Lost a race with a concurrent registration for the same contact.
        raise ValidationError(
            {"email": ["An account already uses this email or phone number."]},
            code="already_registered",
        ) from None
    return Registration(organization_id=org.id, challenge_id=challenge.id)


def confirm_registration(challenge_id: UUID, code: str) -> UUID:
    challenge = otp.verify(challenge_id, code, purpose=OtpPurpose.REGISTRATION)
    with transaction.atomic(), system_context():
        user = User.objects.select_for_update().get(id=challenge.subject_id)
        now = timezone.now()
        if challenge.channel == OtpChannel.SMS:
            user.phone_verified_at = now
        else:
            user.email_verified_at = now
        user.status = UserStatus.ACTIVE
        user.save(update_fields=["phone_verified_at", "email_verified_at", "status"])
        membership = Membership.objects.get(user=user)
        organizations.mark_verified(membership.organization_id)
        audit.record(
            action="organization.signer_verified",
            object_type="organization",
            object_id=membership.organization_id,
            organization_id=membership.organization_id,
            diff={"user_id": user.id, "channel": challenge.channel},
        )
    return membership.organization_id
