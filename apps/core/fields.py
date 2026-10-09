from typing import Any

from django.db import models

from .crypto import decrypt, encrypt


class EncryptedTextField(models.TextField):
    """Stores ciphertext; reads back plaintext. Not filterable: look up via a blind index."""

    def __init__(self, *args: Any, context: str, **kwargs: Any) -> None:
        self.context = context
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        kwargs["context"] = self.context
        return name, path, args, kwargs

    def from_db_value(self, value: str | None, expression: Any, connection: Any) -> str | None:
        if not value:
            return value
        return decrypt(value, context=self.context)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if not value:
            return value
        return encrypt(value, context=self.context)
