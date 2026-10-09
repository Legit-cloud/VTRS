from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class AccessTokenScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.api.authentication.AccessTokenAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
