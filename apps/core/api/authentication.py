from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request


class BearerChallengeAuthentication(BaseAuthentication):
    """Placeholder until token authentication lands (M1).

    Authenticates nobody, but supplies a challenge header so DRF answers unauthenticated
    requests with 401 rather than 403.
    """

    def authenticate(self, request: Request) -> None:
        return None

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="vtrs"'
