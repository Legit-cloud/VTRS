"""Public and session endpoints under /auth (spec section 9)."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import bot_challenge
from apps.accounts.errors import OtpInvalid
from apps.accounts.models import OtpPurpose
from apps.accounts.services import invitations, login, mfa, otp, passwords, registration, sessions
from apps.core.authz import AUTHENTICATED
from apps.core.context import get_client_ip

from . import serializers as s
from .throttles import (
    InvitationIpThrottle,
    LoginAccountThrottle,
    LoginIpThrottle,
    OtpIpThrottle,
    PasswordIpThrottle,
    RefreshIpThrottle,
    RegistrationIpThrottle,
)


def _valid(serializer_class: type, request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class PublicView(APIView):
    public = True
    authentication_classes = ()


class RegisterOrganizationView(PublicView):
    throttle_classes = (RegistrationIpThrottle,)

    @extend_schema(
        request=s.RegisterOrganizationSerializer,
        responses={201: s.RegistrationResponseSerializer},
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.RegisterOrganizationSerializer, request)
        bot_challenge.verify(data.pop("bot_token", None), get_client_ip())
        result = registration.register_organization(**data, ip=get_client_ip())
        return Response(
            {"organization_id": result.organization_id, "challenge_id": result.challenge_id},
            status=201,
        )


class OtpRequestView(PublicView):
    """Resend the code for an existing challenge (60-second cooldown, hourly budgets)."""

    throttle_classes = (OtpIpThrottle,)

    @extend_schema(
        request=s.OtpRequestSerializer, responses={202: s.StatusSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.OtpRequestSerializer, request)
        bot_challenge.verify(data.get("bot_token"), get_client_ip())
        otp.resend(data["challenge_id"], ip=get_client_ip())
        return Response({"status": "sent"}, status=202)


class OtpVerifyView(PublicView):
    throttle_classes = (OtpIpThrottle,)

    @extend_schema(
        request=s.OtpVerifySerializer, responses={200: s.OtpVerifyResponseSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.OtpVerifySerializer, request)
        purpose = otp.peek_purpose(data["challenge_id"])
        if purpose == OtpPurpose.REGISTRATION:
            registration.confirm_registration(data["challenge_id"], data["code"])
            return Response({"purpose": purpose, "organization_status": "PENDING_APPROVAL"})
        if purpose == OtpPurpose.PASSWORD_RESET:
            token = passwords.issue_reset_token(data["challenge_id"], data["code"])
            return Response({"purpose": purpose, "reset_token": token})
        # Unknown challenges, and invitation codes (verified by /invitations/complete).
        raise OtpInvalid()


class LoginView(PublicView):
    throttle_classes = (LoginIpThrottle, LoginAccountThrottle)

    @extend_schema(
        request=s.LoginSerializer, responses={200: s.LoginResponseSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.LoginSerializer, request)
        result = login.login(**data, ip=get_client_ip())
        return Response(result.as_dict())


class MfaLoginView(PublicView):
    throttle_classes = (LoginIpThrottle,)

    @extend_schema(
        request=s.MfaLoginSerializer, responses={200: s.TokenPairSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.MfaLoginSerializer, request)
        pair = login.complete_mfa(**data, ip=get_client_ip())
        return Response(pair.as_dict())


class RefreshView(PublicView):
    throttle_classes = (RefreshIpThrottle,)

    @extend_schema(
        request=s.RefreshSerializer, responses={200: s.TokenPairSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.RefreshSerializer, request)
        return Response(
            sessions.refresh(data["refresh_token"], device_id=data["device_id"]).as_dict()
        )


class LogoutView(APIView):
    required_permission = AUTHENTICATED
    allow_without_mfa = True

    @extend_schema(request=None, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        sessions.logout(request.actor)  # type: ignore[attr-defined]
        return Response(status=204)


class PasswordForgotView(PublicView):
    throttle_classes = (PasswordIpThrottle,)

    @extend_schema(
        request=s.PasswordForgotSerializer,
        responses={202: s.ChallengeResponseSerializer},
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.PasswordForgotSerializer, request)
        bot_challenge.verify(data.get("bot_token"), get_client_ip())
        challenge_id = passwords.request_reset(data["identifier"], ip=get_client_ip())
        return Response({"challenge_id": challenge_id}, status=202)


class PasswordResetView(PublicView):
    throttle_classes = (PasswordIpThrottle,)

    @extend_schema(request=s.PasswordResetSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        data = _valid(s.PasswordResetSerializer, request)
        passwords.reset_password(data["reset_token"], data["new_password"])
        return Response(status=204)


class InvitationAcceptView(PublicView):
    throttle_classes = (InvitationIpThrottle,)

    @extend_schema(
        request=s.InvitationAcceptSerializer,
        responses={200: s.ChallengeResponseSerializer},
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.InvitationAcceptSerializer, request)
        started = invitations.start_acceptance(data["token"], ip=get_client_ip())
        return Response(
            {
                "challenge_id": started.challenge_id,
                "channel": started.channel,
                "destination_hint": started.destination_hint,
            }
        )


class InvitationCompleteView(PublicView):
    throttle_classes = (InvitationIpThrottle,)

    @extend_schema(
        request=s.InvitationCompleteSerializer,
        responses={200: s.TokenPairSerializer},
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.InvitationCompleteSerializer, request)
        result = invitations.complete_acceptance(**data, ip=get_client_ip())
        return Response(result.tokens.as_dict())


class TotpSetupView(APIView):
    required_permission = AUTHENTICATED
    allow_without_mfa = True

    @extend_schema(request=None, responses={200: s.TotpSetupSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        enrolment = mfa.begin_totp(request.actor)  # type: ignore[attr-defined]
        return Response(
            {"secret_base32": enrolment.secret_base32, "otpauth_uri": enrolment.otpauth_uri}
        )


class TotpConfirmView(APIView):
    required_permission = AUTHENTICATED
    allow_without_mfa = True

    @extend_schema(
        request=s.MfaCodeSerializer, responses={200: s.TotpConfirmSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.MfaCodeSerializer, request)
        return Response(mfa.confirm_totp(request.actor, data["code"]))  # type: ignore[attr-defined]


class StepUpView(APIView):
    required_permission = AUTHENTICATED
    allow_without_mfa = True

    @extend_schema(
        request=s.MfaCodeSerializer, responses={200: s.AccessTokenSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.MfaCodeSerializer, request)
        return Response(mfa.step_up(request.actor, data["code"]))  # type: ignore[attr-defined]
