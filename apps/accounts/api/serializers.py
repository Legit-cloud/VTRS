from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.domain.contact import mask_email, mask_phone
from apps.accounts.models import Device, Invitation, Membership
from apps.core.api.serializers import StrictSerializer
from apps.core.domain.permissions import Perm, Role

CHANNELS = [("SMS", "SMS"), ("EMAIL", "EMAIL")]
ROLES = [(r.value, r.value) for r in Role]
PERMISSIONS = [(p.value, p.value) for p in Perm]


# --- Requests -------------------------------------------------------------------------------


class RegisterOrganizationSerializer(StrictSerializer):
    organization_name = serializers.CharField(max_length=200)
    legal_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    admin_name = serializers.CharField(max_length=150)
    email = serializers.CharField(max_length=254)
    phone = serializers.CharField(max_length=32)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    otp_channel = serializers.ChoiceField(choices=CHANNELS)
    bot_token = serializers.CharField(max_length=4096, required=False, allow_blank=True)


class OtpRequestSerializer(StrictSerializer):
    challenge_id = serializers.UUIDField()
    bot_token = serializers.CharField(max_length=4096, required=False, allow_blank=True)


class OtpVerifySerializer(StrictSerializer):
    challenge_id = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{6}$")


class LoginSerializer(StrictSerializer):
    identifier = serializers.CharField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    client = serializers.ChoiceField(choices=[("WEB", "WEB"), ("MOBILE", "MOBILE")], default="WEB")
    device_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class MfaLoginSerializer(StrictSerializer):
    mfa_token = serializers.CharField(max_length=1024)
    code = serializers.CharField(max_length=16)


class RefreshSerializer(StrictSerializer):
    refresh_token = serializers.CharField(max_length=128)
    device_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class PasswordForgotSerializer(StrictSerializer):
    identifier = serializers.CharField(max_length=254)
    bot_token = serializers.CharField(max_length=4096, required=False, allow_blank=True)


class PasswordResetSerializer(StrictSerializer):
    reset_token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class InvitationAcceptSerializer(StrictSerializer):
    token = serializers.CharField(max_length=128)


class DeviceRegistrationSerializer(StrictSerializer):
    platform = serializers.ChoiceField(choices=[("ANDROID", "ANDROID"), ("IOS", "IOS")])
    app_version = serializers.CharField(max_length=32)
    public_key = serializers.CharField(
        max_length=4096, required=False, allow_blank=True, default=""
    )
    push_token = serializers.CharField(
        max_length=4096, required=False, allow_blank=True, default=""
    )


class InvitationCompleteSerializer(StrictSerializer):
    token = serializers.CharField(max_length=128)
    challenge_id = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{6}$")
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    device = DeviceRegistrationSerializer(required=False, allow_null=True, default=None)


class MfaCodeSerializer(StrictSerializer):
    code = serializers.CharField(max_length=16)


class InvitationCreateSerializer(StrictSerializer):
    role = serializers.ChoiceField(choices=ROLES)
    scope_ids = serializers.ListField(child=serializers.UUIDField(), max_length=500, default=list)
    granted_permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=PERMISSIONS), max_length=20, default=list
    )
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.CharField(max_length=254, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class MembershipUpdateSerializer(StrictSerializer):
    role = serializers.ChoiceField(choices=ROLES)
    scope_ids = serializers.ListField(child=serializers.UUIDField(), max_length=500, default=list)
    granted_permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=PERMISSIONS), max_length=20, default=list
    )


# --- Responses ------------------------------------------------------------------------------


class TokenPairSerializer(serializers.Serializer):
    token_type = serializers.CharField()
    access_token = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh_token = serializers.CharField()
    refresh_expires_at = serializers.DateTimeField()
    session_id = serializers.UUIDField()


class LoginResponseSerializer(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    mfa_token = serializers.CharField(required=False)
    mfa_enrolment_required = serializers.BooleanField(required=False)
    token_type = serializers.CharField(required=False)
    access_token = serializers.CharField(required=False)
    access_expires_at = serializers.DateTimeField(required=False)
    refresh_token = serializers.CharField(required=False)
    refresh_expires_at = serializers.DateTimeField(required=False)
    session_id = serializers.UUIDField(required=False)


class RegistrationResponseSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField()
    challenge_id = serializers.UUIDField()


class OtpVerifyResponseSerializer(serializers.Serializer):
    purpose = serializers.CharField()
    organization_status = serializers.CharField(required=False)
    reset_token = serializers.CharField(required=False)


class ChallengeResponseSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    channel = serializers.CharField(required=False)
    destination_hint = serializers.CharField(required=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.CharField()


class AccessTokenSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    access_expires_at = serializers.DateTimeField()


class TotpSetupSerializer(serializers.Serializer):
    secret_base32 = serializers.CharField()
    otpauth_uri = serializers.CharField()


class TotpConfirmSerializer(AccessTokenSerializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())


def _masked_email(value: str) -> str:
    return mask_email(value) if value else ""


def _masked_phone(value: str) -> str:
    return mask_phone(value) if value else ""


class ScopeSerializer(serializers.Serializer):
    type = serializers.CharField()
    ids = serializers.ListField(child=serializers.UUIDField())


class MemberSerializer(serializers.ModelSerializer):
    """Team listing. Contact details are masked (DG-02 data minimisation)."""

    user_id = serializers.UUIDField(source="user.id")
    full_name = serializers.CharField(source="user.full_name")
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    status = serializers.CharField(source="user.status")
    mfa_enabled = serializers.BooleanField(source="user.mfa_enabled")
    scope = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = (
            "user_id",
            "full_name",
            "email",
            "phone",
            "status",
            "mfa_enabled",
            "role",
            "scope",
            "granted_permissions",
            "created_at",
        )

    def get_email(self, obj: Membership) -> str:
        return _masked_email(obj.user.email)

    def get_phone(self, obj: Membership) -> str:
        return _masked_phone(obj.user.phone)

    @extend_schema_field(ScopeSerializer)
    def get_scope(self, obj: Membership) -> dict[str, object]:
        return {"type": obj.scope_type, "ids": [str(i) for i in obj.scope_ids]}


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ("id", "platform", "app_version", "status", "created_at", "last_seen_at")


class InvitationSerializer(serializers.ModelSerializer):
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = (
            "id",
            "role",
            "scope_type",
            "scope_ids",
            "granted_permissions",
            "full_name",
            "email",
            "phone",
            "status",
            "expires_at",
            "created_at",
        )

    def get_email(self, obj: Invitation) -> str:
        return _masked_email(obj.email)

    def get_phone(self, obj: Invitation) -> str:
        return _masked_phone(obj.phone)

    def get_status(self, obj: Invitation) -> str:
        if obj.accepted_at:
            return "ACCEPTED"
        if obj.revoked_at:
            return "REVOKED"
        return "EXPIRED" if obj.expires_at <= timezone.now() else "PENDING"


class MeSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    organization = serializers.DictField()
    role = serializers.CharField()
    scope = ScopeSerializer()
    permissions = serializers.ListField(child=serializers.CharField())
    mfa_enabled = serializers.BooleanField()
    mfa_required = serializers.BooleanField()
