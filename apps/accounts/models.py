"""User accounts (spec section 7).

Only the user table exists so far, because AUTH_USER_MODEL must be fixed before the first
migration. Memberships, OTP, invitations, devices and sessions arrive with M1.
"""

from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from apps.core.ids import uuid7


class UserStatus(models.TextChoices):
    INVITED = "INVITED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class UserManager(BaseUserManager["User"]):
    def create_user(self, email: str, password: str | None = None, **extra: Any) -> "User":
        user = self.model(email=self.normalize_email(email), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, default="")
    status = models.CharField(
        max_length=24, choices=UserStatus.choices, default=UserStatus.PENDING_VERIFICATION
    )
    mfa_enabled = models.BooleanField(default=False)
    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = UserManager()

    class Meta:
        db_table = "account_user"

    def __str__(self) -> str:
        return str(self.id)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        # Only ACTIVE accounts may authenticate or receive tokens.
        return self.status == UserStatus.ACTIVE
