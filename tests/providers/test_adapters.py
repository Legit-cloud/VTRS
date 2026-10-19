"""Real provider adapters (PB-07), tested against the protocols they speak: a recording HTTP
seam, a local clamd, and Twilio's published signature vector."""

import base64
import json
import socket
import struct
import threading
import urllib.parse

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import ValidationError

from apps.accounts import bot_challenge
from apps.core import http
from apps.core.http import HttpError, HttpResponse
from apps.evidence.scanning import EICAR, ClamAvScanner, ScanUnavailable
from apps.notifications.providers import (
    ProviderError,
    TwilioSmsProvider,
    TwilioWhatsAppProvider,
    twilio_signature,
)


class Recorder:
    """Stands in for `apps.core.http.post` and records every call."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected extra request to " + url)
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _json(status: int, **body) -> HttpResponse:
    return HttpResponse(status, json.dumps(body).encode())


@pytest.fixture
def twilio(settings):
    settings.VTRS_TWILIO_ACCOUNT_SID = "AC123"
    settings.VTRS_TWILIO_AUTH_TOKEN = "secret-token"
    settings.VTRS_TWILIO_SMS_FROM = "+15005550006"
    settings.VTRS_TWILIO_WHATSAPP_FROM = "+14155238886"
    settings.VTRS_TWILIO_MESSAGING_SERVICE_SID = ""
    settings.VTRS_PUBLIC_BASE_URL = "https://vtrs.example.org"


# --- Twilio ---------------------------------------------------------------------------------


def test_twilio_sms_request_shape(twilio, monkeypatch):
    rec = Recorder(_json(201, sid="SM999"))
    monkeypatch.setattr(http, "post", rec)
    message_id = TwilioSmsProvider().send("+2348031234567", "Hello there")
    assert message_id == "SM999"
    [call] = rec.calls
    assert call["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert call["form"] == {
        "To": "+2348031234567",
        "Body": "Hello there",
        "From": "+15005550006",
        "StatusCallback": "https://vtrs.example.org/api/v1/webhooks/twilio/status",
    }
    credentials = call["headers"]["Authorization"].removeprefix("Basic ")
    assert base64.b64decode(credentials) == b"AC123:secret-token"


def test_a_messaging_service_replaces_the_from_number(twilio, settings, monkeypatch):
    settings.VTRS_TWILIO_MESSAGING_SERVICE_SID = "MG42"
    rec = Recorder(_json(201, sid="SM1"))
    monkeypatch.setattr(http, "post", rec)
    TwilioSmsProvider().send("+2348031234567", "x")
    form = rec.calls[0]["form"]
    assert form["MessagingServiceSid"] == "MG42" and "From" not in form


def test_twilio_whatsapp_prefixes_both_numbers(twilio, monkeypatch):
    rec = Recorder(_json(201, sid="SM2"))
    monkeypatch.setattr(http, "post", rec)
    TwilioWhatsAppProvider().send("+2348031234567", "alert")
    form = rec.calls[0]["form"]
    assert form["To"] == "whatsapp:+2348031234567"
    assert form["From"] == "whatsapp:+14155238886"


def test_a_refusal_is_an_error_that_does_not_echo_the_message(twilio, monkeypatch):
    rec = Recorder(_json(400, code=21211, message="Invalid 'To' Phone Number: +234803..."))
    monkeypatch.setattr(http, "post", rec)
    with pytest.raises(ProviderError) as caught:
        TwilioSmsProvider().send("+2348031234567", "secret body text")
    assert "21211" in str(caught.value)
    assert "secret body text" not in str(caught.value)
    assert "+234803" not in str(caught.value)


def test_missing_credentials_fail_loudly(settings):
    settings.VTRS_TWILIO_ACCOUNT_SID = ""
    with pytest.raises(ProviderError):
        TwilioSmsProvider()


def test_the_signature_matches_twilios_published_example():
    # From Twilio's webhook security documentation.
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    assert twilio_signature(url, params, "12345") == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


# --- Bot challenge ----------------------------------------------------------------------------


@pytest.fixture
def turnstile(settings):
    settings.VTRS_BOT_CHALLENGE_PROVIDER = "turnstile"
    settings.VTRS_BOT_CHALLENGE_SECRET = "0x-secret"


def test_a_passed_challenge(turnstile, monkeypatch):
    rec = Recorder(_json(200, success=True))
    monkeypatch.setattr(http, "post", rec)
    bot_challenge.verify("client-token", "203.0.113.9")
    [call] = rec.calls
    assert call["url"] == bot_challenge.VERIFY_URLS["turnstile"]
    assert call["form"] == {
        "secret": "0x-secret",
        "response": "client-token",
        "remoteip": "203.0.113.9",
    }


def test_a_failed_or_missing_challenge_is_refused(turnstile, monkeypatch):
    monkeypatch.setattr(http, "post", Recorder(_json(200, success=False)))
    with pytest.raises(ValidationError):
        bot_challenge.verify("bad", None)
    with pytest.raises(ValidationError):
        bot_challenge.verify(None, None)  # no token: refused without calling the provider
    with pytest.raises(ValidationError):
        bot_challenge.verify("x" * 5000, None)


def test_an_unreachable_provider_refuses_rather_than_waves_through(turnstile, monkeypatch):
    monkeypatch.setattr(http, "post", Recorder(HttpError("TimeoutError")))
    with pytest.raises(bot_challenge.BotChallengeUnavailable):
        bot_challenge.verify("token", None)
    monkeypatch.setattr(http, "post", Recorder(_json(500)))
    with pytest.raises(bot_challenge.BotChallengeUnavailable):
        bot_challenge.verify("token", None)


def test_the_challenge_needs_a_known_provider_and_a_secret(settings):
    settings.VTRS_BOT_CHALLENGE_PROVIDER = "mystery"
    with pytest.raises(ImproperlyConfigured):
        bot_challenge.verify("t", None)
    settings.VTRS_BOT_CHALLENGE_PROVIDER = "hcaptcha"
    settings.VTRS_BOT_CHALLENGE_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        bot_challenge.verify("t", None)


# --- ClamAV ---------------------------------------------------------------------------------------


class FakeClamd:
    """Speaks just enough clamd INSTREAM to be scanned against."""

    def __init__(self, reply: bytes | None) -> None:
        self.reply = reply
        self.received = b""
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _recv(self, conn, count):
        data = b""
        while len(data) < count:
            part = conn.recv(count - len(data))
            if not part:
                break
            data += part
        return data

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            assert self._recv(conn, 10) == b"zINSTREAM\0"
            while True:
                (length,) = struct.unpack("!I", self._recv(conn, 4))
                if length == 0:
                    break
                self.received += self._recv(conn, length)
            if self.reply is not None:
                conn.sendall(self.reply)
        self.sock.close()


def _scanner(settings, fake: FakeClamd) -> ClamAvScanner:
    settings.VTRS_CLAMD_HOST = "127.0.0.1"
    settings.VTRS_CLAMD_PORT = fake.port
    settings.VTRS_CLAMD_TIMEOUT_SECONDS = 3
    return ClamAvScanner()


def test_clamd_clean(settings):
    fake = FakeClamd(b"stream: OK\0")
    payload = b"\x89PNG" + bytes(range(256)) * 600  # several chunks
    assert _scanner(settings, fake).scan(payload) is None
    assert fake.received == payload


def test_clamd_finds_a_threat(settings):
    fake = FakeClamd(b"stream: Eicar-Test-Signature FOUND\0")
    assert _scanner(settings, fake).scan(EICAR) == "Eicar-Test-Signature"


def test_an_error_or_a_dead_scanner_is_never_a_clean_verdict(settings):
    fake = FakeClamd(b"INSTREAM size limit exceeded. ERROR\0")
    with pytest.raises(ScanUnavailable):
        _scanner(settings, fake).scan(b"data")
    settings.VTRS_CLAMD_HOST = "127.0.0.1"
    settings.VTRS_CLAMD_PORT = 1  # nothing listens here
    settings.VTRS_CLAMD_TIMEOUT_SECONDS = 1
    with pytest.raises(ScanUnavailable):
        ClamAvScanner().scan(b"data")


# --- The HTTP seam ---------------------------------------------------------------------------


def test_providers_must_use_https():
    with pytest.raises(HttpError):
        http.post("http://api.example.com/send", form={"a": "b"})
    with pytest.raises(HttpError):
        http.post("ftp://api.example.com/send")


def test_urlencoding_of_forms_is_what_twilio_expects():
    assert urllib.parse.urlencode({"To": "whatsapp:+234", "Body": "a b"}) == (
        "To=whatsapp%3A%2B234&Body=a+b"
    )
