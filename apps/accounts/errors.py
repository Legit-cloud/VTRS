from rest_framework.exceptions import APIException

from apps.core.errors import CommitsSideEffects


class InvalidCredentials(CommitsSideEffects, APIException):
    # Same answer for unknown accounts, wrong passwords and locked accounts (no enumeration).
    status_code = 401
    default_detail = "The credentials are not valid."
    default_code = "invalid_credentials"


class AccountNotActive(APIException):
    status_code = 403
    default_detail = "This account is not active."
    default_code = "account_not_active"


class OrganizationNotActive(APIException):
    status_code = 403
    default_detail = "This organization is not active yet."
    default_code = "organization_not_active"


class DeviceNotRegistered(APIException):
    status_code = 403
    default_detail = "This device is not registered for the account."
    default_code = "device_not_registered"


class InvalidRefreshToken(CommitsSideEffects, APIException):
    status_code = 401
    default_detail = "The refresh token is not valid."
    default_code = "invalid_refresh_token"


class TokenRevoked(APIException):
    status_code = 401
    default_detail = "The session has ended. Sign in again."
    default_code = "token_revoked"


class InvalidToken(APIException):
    status_code = 401
    default_detail = "The access token is not valid or has expired."
    default_code = "invalid_token"


class OtpInvalid(CommitsSideEffects, APIException):
    # Wrong, expired, used-up or unknown codes all look the same.
    status_code = 400
    default_detail = "The code is not valid. Request a new one if it has expired."
    default_code = "otp_invalid"


class OtpBudgetExceeded(APIException):
    status_code = 429
    default_detail = "Too many codes requested. Try again later."
    default_code = "otp_budget_exceeded"


class OtpResendTooSoon(APIException):
    status_code = 429
    default_detail = "Wait a minute before requesting another code."
    default_code = "otp_resend_too_soon"


class SmsDestinationNotAllowed(APIException):
    status_code = 400
    default_detail = "SMS codes can only be sent to supported country codes."
    default_code = "sms_destination_not_allowed"


class InvalidMfaCode(CommitsSideEffects, APIException):
    status_code = 400
    default_detail = "The authentication code is not valid."
    default_code = "mfa_invalid"


class InvitationInvalid(APIException):
    # Used, expired, revoked and unknown invitations all look the same.
    status_code = 400
    default_detail = "This invitation is not valid."
    default_code = "invitation_invalid"


class ContactInUse(APIException):
    status_code = 409
    default_detail = "An account already uses this phone number or email address."
    default_code = "contact_in_use"


class LastAdmin(APIException):
    status_code = 409
    default_detail = "The last active admin cannot be removed or demoted."
    default_code = "last_admin"


class InvalidResetToken(APIException):
    status_code = 400
    default_detail = "The reset token is not valid or has expired."
    default_code = "invalid_reset_token"
