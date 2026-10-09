from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self) -> None:
        from .api import schema  # noqa: F401  registers the OpenAPI security scheme
