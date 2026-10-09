"""Malware scanning adapters. The production scanner (ClamAV or a managed service) is an
open decision; production settings refuse the development scanner."""

from typing import Protocol

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
