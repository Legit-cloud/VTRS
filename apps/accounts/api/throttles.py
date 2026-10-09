"""Cache-backed throttles for public auth endpoints (spec section 9, SEC-07).

Rates are read from settings at request time so they can be tuned without a deploy.
"""

import hashlib
from typing import Any

from django.conf import settings
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class _SettingsRateThrottle(SimpleRateThrottle):
    scope = ""

    def __init__(self) -> None:  # DRF reads the rate in __init__; keep it dynamic.
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

    def get_rate(self) -> str:
        return settings.VTRS_THROTTLE_RATES[self.scope]


class _PerIp(_SettingsRateThrottle):
    def get_cache_key(self, request: Request, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginIpThrottle(_PerIp):
    scope = "login_ip"


class LoginAccountThrottle(_SettingsRateThrottle):
    scope = "login_account"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        data = request.data if isinstance(request.data, dict) else {}
        identifier = str(data.get("identifier", "")).strip().lower()
        if not identifier:
            return None
        # Hash so contact details never appear in cache keys.
        digest = hashlib.sha256(identifier.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class OtpIpThrottle(_PerIp):
    scope = "otp_ip"


class RegistrationIpThrottle(_PerIp):
    scope = "registration_ip"


class PasswordIpThrottle(_PerIp):
    scope = "password_ip"


class InvitationIpThrottle(_PerIp):
    scope = "invitation_ip"


class RefreshIpThrottle(_PerIp):
    scope = "refresh_ip"
