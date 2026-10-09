"""Per-request context (request id, client IP) available to services, audit and logging."""

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)


def get_request_id() -> str:
    return request_id_var.get()


def get_client_ip() -> str | None:
    return client_ip_var.get()
