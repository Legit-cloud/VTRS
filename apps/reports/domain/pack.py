"""Evidence pack layout, manifest and the verification script shipped inside it (FR-6.10.5).

A pack is meant to be handed to a reviewer who does not trust the system's say-so, so it carries
what is needed to check it offline: every file's SHA-256, each file's hash-chained custody
events, and a standard-library script that recomputes both. It proves the files are the ones
the platform stored and that their custody record was not edited. It does not, and says it
does not, establish legal admissibility (FR-6.10.6).
"""

from typing import Any

from .formats import slug

PACK_NOTICE = (
    "Provisional party-side record. These files are copies of what agents captured and the "
    "platform stored; they are not an official result or declaration."
)
PACK_DISCLAIMER = (
    "This pack provides evidence integrity and chain-of-custody information. It does not "
    "guarantee legal admissibility in any court."
)

README = """VTRS evidence pack
==================

{notice}

Contents
  manifest.json        every file, its SHA-256, and its chain of custody
  results.csv          the result versions these photos belong to
  evidence/            the original photos, as uploaded
  verify.py            offline integrity check (Python 3, standard library only)

Check it
  python verify.py

verify.py recomputes each file's SHA-256 and each custody chain, and exits non-zero on any
difference. It prints the SHA-256 of manifest.json: compare it with the `manifest_sha256` the
platform recorded for this export.

{disclaimer}
"""

VERIFY_SCRIPT = '''"""Offline integrity check for a VTRS evidence pack. Standard library only."""

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
GENESIS = "0" * 64
CHAIN_FIELDS = ("evidence_file_id", "seq", "event_type", "actor_id", "at", "ip", "details")


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def main():
    manifest_bytes = (ROOT / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    problems = []
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        if not path.exists():
            problems.append(f"{entry['path']}: file is missing")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            problems.append(f"{entry['path']}: content does not match its recorded SHA-256")
        previous = GENESIS
        for event in entry["custody"]:
            view = {name: event[name] for name in CHAIN_FIELDS}
            expected = hashlib.sha256(previous.encode() + canonical(view)).hexdigest()
            if event["prev_hash"] != previous or event["hash"] != expected:
                problems.append(f"{entry['path']}: custody event {event['seq']} does not chain")
            previous = event["hash"]
    print(f"files checked: {len(manifest['files'])}")
    print(f"manifest sha256: {hashlib.sha256(manifest_bytes).hexdigest()}")
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("OK: every file and every custody chain verifies")
    return 0


sys.exit(main())
'''


def evidence_path(
    polling_unit_code: str, version_no: int, kind: str, evidence_id: Any, ext: str
) -> str:
    return f"evidence/{slug(polling_unit_code, 40)}/v{version_no}-{kind}-{evidence_id}.{ext}"


def readme() -> str:
    return README.format(notice=PACK_NOTICE, disclaimer=PACK_DISCLAIMER)
