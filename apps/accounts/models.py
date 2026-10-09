"""Identity: users, memberships (role + scope), devices, sessions and one-time credentials.

Contact details are encrypted per field; lookups go through HMAC blind indexes (section 16).
Every secret (OTP, refresh token, invitation token, reset token, recovery code) is stored
hashed only.
"""

from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.domain.actor import ROLE_SCOPE_KIND, ScopeKind
from apps.core.domain.permissions import Role
from apps.core.fields import EncryptedTextField
from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet


class UserStatus(models.TextChoices):
    INVITED = "INVITED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class UserManager(BaseUserManager["User"]):
    def create_user(self, password: str | None = None, **fields: Any) -> "User":
        user = self.model(**fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, UUIDv7Model):
    full_name = models.CharField(max_length=150, blank=True, default="")
    email = EncryptedTextField(context="account_user.email", blank=True, default="")
    email_index = models.CharField(max_length=64, null=True, blank=True, unique=True)
    phone = EncryptedTextField(context="account_user.phone", blank=True, default="")
    phone_index = models.CharField(max_length=64, null=True, blank=True, unique=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=UserStatus.choices, default=UserStatus.PENDING_VERIFICATION
    )
    mfa_enabled = models.BooleanField(default=False)
    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    # Bumped to invalidate every outstanding access token at once.
    session_version = models.PositiveIntegerField(default=1)
    # Bumped whenever role or scope changes.
    scope_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    # Contact details are encrypted, so the stable unique field is the id.
    USERNAME_FIELD = "id"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = UserManager()

    class Meta:
        db_table = "account_user"
        constraints = [
            models.CheckConstraint(
                condition=Q(email_index__isnull=False) | Q(phone_index__isnull=False),
                name="user_has_contact",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        # Only ACTIVE accounts may authenticate or receive tokens.
        return self.status == UserStatus.ACTIVE


class MembershipStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


def _role_scope_rule() -> Q:
    rule = Q()
    for role, kind in ROLE_SCOPE_KIND.items():
        rule |= Q(role=role.value, scope_type=kind.value)
    return rule


class Membership(UUIDv7Model):
    """A user's role and geographic scope inside one organization (section 8)."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="memberships"
    )
    role = models.CharField(max_length=24, choices=[(r.value, r.value) for r in Role])
    scope_type = models.CharField(max_length=8, choices=[(k.value, k.value) for k in ScopeKind])
    scope_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    granted_permissions = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    status = models.CharField(
        max_length=8, choices=MembershipStatus.choices, default=MembershipStatus.ACTIVE
    )
    created_by_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "account_membership"
        constraints = [
            # One active membership per user for the pilot.
            models.UniqueConstraint(
                fields=["user"], condition=Q(status="ACTIVE"), name="membership_one_active"
            ),
            models.CheckConstraint(condition=_role_scope_rule(), name="membership_role_scope"),
        ]
        indexes = [models.Index(fields=["organization", "created_at"], name="membership_org_idx")]


class DeviceStatus(models.TextChoices):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Device(UUIDv7Model):
    """A registered agent device. One active device per agent by default."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="devices")
    platform = models.CharField(max_length=10, choices=[("ANDROID", "ANDROID"), ("IOS", "IOS")])
    app_version = models.CharField(max_length=32)
    public_key = models.TextField(blank=True, default="")
    push_token = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=8, choices=DeviceStatus.choices, default=DeviceStatus.ACTIVE
    )
    # Play Integrity / App Attest verdicts. A failed verdict raises a flag; it never blocks.
    integrity = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "account_device"
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=Q(status="ACTIVE"), name="device_one_active"
            )
        ]


class SessionClient(models.TextChoices):
    WEB = "WEB"
    MOBILE = "MOBILE"


class Session(UUIDv7Model):
    """A sign-in. Its refresh tokens form one rotation family; reuse revokes the session."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sessions")
    device = models.ForeignKey(Device, null=True, blank=True, on_delete=models.PROTECT)
    client = models.CharField(max_length=8, choices=SessionClient.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    mfa_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        db_table = "account_session"
        indexes = [
            models.Index(
                fields=["user"], condition=Q(revoked_at__isnull=True), name="session_live_idx"
            )
        ]


class RefreshToken(UUIDv7Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "account_refresh_token"


class OtpPurpose(models.TextChoices):
    REGISTRATION = "REGISTRATION"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 - an enum label, not a password
    INVITATION = "INVITATION"


class OtpChannel(models.TextChoices):
    SMS = "SMS"
    EMAIL = "EMAIL"


class OtpChallenge(UUIDv7Model):
    purpose = models.CharField(max_length=16, choices=OtpPurpose.choices)
    channel = models.CharField(max_length=8, choices=OtpChannel.choices)
    destination = EncryptedTextField(context="otp_challenge.destination")
    destination_index = models.CharField(max_length=64)
    # The user (registration, reset) or invitation (acceptance) this code proves control for.
    subject_id = models.UUIDField()
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    last_sent_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_otp_challenge"
        indexes = [models.Index(fields=["destination_index", "created_at"], name="otp_dest_idx")]


class Invitation(UUIDv7Model):
    """Invite-only onboarding (FR-6.1.5, FR-6.2.x). The token is sent, never stored."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="invitations"
    )
    role = models.CharField(max_length=24, choices=[(r.value, r.value) for r in Role])
    scope_type = models.CharField(max_length=8, choices=[(k.value, k.value) for k in ScopeKind])
    scope_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    granted_permissions = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    full_name = models.CharField(max_length=150, blank=True, default="")
    phone = EncryptedTextField(context="account_invitation.phone", blank=True, default="")
    # NULL means no contact of this kind, matching the user table's unique indexes.
    phone_index = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    email = EncryptedTextField(context="account_invitation.email", blank=True, default="")
    email_index = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user_id = models.UUIDField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "account_invitation"
        constraints = [
            models.CheckConstraint(condition=_role_scope_rule(), name="invitation_role_scope"),
        ]
        indexes = [models.Index(fields=["organization", "created_at"], name="invitation_org_idx")]


class PasswordResetToken(UUIDv7Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_password_reset"


class RecoveryCode(UUIDv7Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_recovery_code"
