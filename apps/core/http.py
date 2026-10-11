"""One outbound HTTP call for every provider adapter.

Adapters call `post` through this module (never `urllib` directly) so a single seam has the
timeout, the size cap and the "no redirects to somewhere else" rule, and so tests replace one
function instead of the network.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_TIMEOUT = 8.0
MAX_BODY = 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a provider that redirects is misconfigured; do not follow it elsewhere


_opener = urllib.request.build_opener(_NoRedirect)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HttpError(Exception):
    """The provider could not be reached (timeout, DNS, TLS, connection reset)."""


def post(
    url: str,
    *,
    form: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HttpResponse:
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        raise HttpError("Provider URLs must use https")
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        content_type = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        content_type = "application/json"
    else:
        data, content_type = b"", "application/octet-stream"
    request = urllib.request.Request(url, data=data, method="POST")  # noqa: S310 - https only
    request.add_header("Content-Type", content_type)
    request.add_header("Accept", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with _opener.open(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read(MAX_BODY))
    except urllib.error.HTTPError as err:
        return HttpResponse(err.code, err.read(MAX_BODY))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(type(exc).__name__) from exc
