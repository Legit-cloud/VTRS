from django.urls import path

from . import views_auth as auth
from . import views_team as team

auth_urls = [
    path("auth/organizations", auth.RegisterOrganizationView.as_view(), name="auth-register"),
    path("auth/otp/request", auth.OtpRequestView.as_view(), name="auth-otp-request"),
    path("auth/otp/verify", auth.OtpVerifyView.as_view(), name="auth-otp-verify"),
    path("auth/login", auth.LoginView.as_view(), name="auth-login"),
    path("auth/login/mfa", auth.MfaLoginView.as_view(), name="auth-login-mfa"),
    path("auth/refresh", auth.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", auth.LogoutView.as_view(), name="auth-logout"),
    path("auth/password/forgot", auth.PasswordForgotView.as_view(), name="auth-password-forgot"),
    path("auth/password/reset", auth.PasswordResetView.as_view(), name="auth-password-reset"),
    path(
        "auth/invitations/accept",
        auth.InvitationAcceptView.as_view(),
        name="auth-invitation-accept",
    ),
    path(
        "auth/invitations/complete",
        auth.InvitationCompleteView.as_view(),
        name="auth-invitation-complete",
    ),
    path("auth/mfa/totp/setup", auth.TotpSetupView.as_view(), name="auth-totp-setup"),
    path("auth/mfa/totp/confirm", auth.TotpConfirmView.as_view(), name="auth-totp-confirm"),
    path("auth/mfa/step-up", auth.StepUpView.as_view(), name="auth-step-up"),
]

team_urls = [
    path("me", team.MeView.as_view(), name="me"),
    path("users", team.UserListView.as_view(), name="users"),
    path("users/<uuid:user_id>", team.UserDetailView.as_view(), name="user-detail"),
    path(
        "users/<uuid:user_id>/deactivate", team.UserDeactivateView.as_view(), name="user-deactivate"
    ),
    path(
        "users/<uuid:user_id>/membership",
        team.MembershipUpdateView.as_view(),
        name="user-membership",
    ),
    path(
        "users/<uuid:user_id>/devices/<uuid:device_id>/revoke",
        team.DeviceRevokeView.as_view(),
        name="user-device-revoke",
    ),
    path("invitations", team.InvitationListView.as_view(), name="invitations"),
    path(
        "invitations/<uuid:invitation_id>/revoke",
        team.InvitationRevokeView.as_view(),
        name="invitation-revoke",
    ),
]

urlpatterns = auth_urls + team_urls
