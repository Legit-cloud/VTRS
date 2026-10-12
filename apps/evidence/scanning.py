"""Malware scanning adapters. Production uses ClamAV through clamd's INSTREAM protocol;
production settings refuse the development scanner. A scan that cannot complete raises, so
verification is retried and the photo is never treated as clean by default."""

import socket
import struct
from typing import Protocol

from django.conf import settings

# The industry-standard antivirus test string (harmless by design).
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class Scanner(Protocol):
    def scan(self, data: bytes) -> str | None:
        """Return a threat name, or None when clean."""
        ...


class EicarOnlyScanner:
    """Development and test stand-in: detects only the EICAR test signature."""

    def scan(self, data: bytes) -> str | None:
        return "EICAR-Test-Signature" if EICAR in data else None


class ScanUnavailable(Exception):
    """The scanner could not give a verdict (down, timed out, or answered with an error)."""


class ClamAvScanner:
    """Streams the bytes to clamd (TCP) with INSTREAM and reads its one-line verdict."""

    CHUNK = 64 * 1024

    def __init__(self) -> None:
        self.host = settings.VTRS_CLAMD_HOST
        self.port = settings.VTRS_CLAMD_PORT
        self.timeout = settings.VTRS_CLAMD_TIMEOUT_SECONDS

    def scan(self, data: bytes) -> str | None:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.settimeout(self.timeout)
                conn.sendall(b"zINSTREAM\0")
                for start in range(0, len(data), self.CHUNK):
                    chunk = data[start : start + self.CHUNK]
                    conn.sendall(struct.pack("!I", len(chunk)) + chunk)
                conn.sendall(struct.pack("!I", 0))
                reply = b""
                while not reply.endswith(b"\0") and len(reply) < 4096:
                    part = conn.recv(1024)
                    if not part:
                        break
                    reply += part
        except OSError as exc:
            raise ScanUnavailable(type(exc).__name__) from exc
        verdict = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
        if verdict.endswith("OK"):
            return None
        if verdict.endswith("FOUND"):
            name = verdict.removeprefix("stream:").removesuffix("FOUND").strip()
            return name or "malware"
        raise ScanUnavailable(f"unexpected scanner reply: {verdict[:80]}")
