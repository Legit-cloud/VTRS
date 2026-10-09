"""Evidence pipeline (spec section 12; FR-6.10.x, AC-12).

1. Stubs come from the submission manifest (or POST /evidence/uploads) with a presigned PUT.
2. The device uploads straight to object storage; the store checks the SHA-256.
3. The device confirms; a worker verifies (checksum, magic bytes, bounded decode, malware
   scan) and either records VERIFIED with derivatives and metadata, or QUARANTINES the object.
Every step appends a hash-chained custody event for the file.
"""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework.exceptions import ValidationError

from apps.core import services as core
from apps.core.authz import authorize
from apps.core.context import get_client_ip
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.core.rls import system_context

from . import processing
from .domain.rules import (
    ALLOWED_TYPES,
    GENESIS_HASH,
    MAX_BYTES,
    EvidenceStatus,
    custody_hash,
    object_key,
    sniff_mime,
)
from .errors import EvidenceConflict, EvidenceNotReady, EvidenceQuarantined, UploadNotFound
from .models import CustodyEvent, EvidenceFile
from .storage import get_storage

_IDENTITY_FIELDS = ("kind", "size", "mime", "sha256_client")


# --- Custody chain --------------------------------------------------------------------------


def append_custody(
    evidence: EvidenceFile, event_type: str, *, actor_id: Any = None, details: dict | None = None
) -> CustodyEvent:
    """Append to the file's chain. Callers hold the evidence row lock, so seq is race-free."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Custody events must be written inside a transaction")
    last = CustodyEvent.objects.filter(evidence_file_id=evidence.id).order_by("-seq").first()
    prev_hash = last.hash if last else GENESIS_HASH
    seq = last.seq + 1 if last else 1
    at = timezone.now()
    ip = get_client_ip()
    details = details or {}
    event = _chain_view(evidence.id, seq, event_type, actor_id, at, ip, details)
    return CustodyEvent.objects.create(
        at=at,
        organization_id=evidence.organization_id,
        evidence_file_id=evidence.id,
        seq=seq,
        event_type=event_type,
        actor_id=actor_id,
        ip=ip,
        details=details,
        prev_hash=prev_hash,
        hash=custody_hash(prev_hash, event),
    )


def _chain_view(
    evidence_id: Any, seq: int, event_type: str, actor_id: Any, at: Any, ip: Any, details: dict
) -> dict[str, Any]:
    return {
        "evidence_file_id": str(evidence_id),
        "seq": seq,
        "event_type": event_type,
        "actor_id": str(actor_id) if actor_id else None,
        "at": at.isoformat(),
        "ip": ip,
        "details": details,
    }


def verify_custody(evidence_id: UUID) -> list[str]:
    """Recompute a file's chain. Empty list = intact."""
    problems = []
    prev_hash, expected_seq = GENESIS_HASH, 1
    for event in CustodyEvent.objects.filter(evidence_file_id=evidence_id).order_by("seq"):
        if event.seq != expected_seq:
            problems.append(f"event {event.seq}: expected sequence {expected_seq}")
        if event.prev_hash != prev_hash:
            problems.append(f"event {event.seq}: does not chain to the previous event")
        view = _chain_view(
            event.evidence_file_id,
            event.seq,
            event.event_type,
            event.actor_id,
            event.at,
            event.ip,
            event.details,
        )
        if custody_hash(event.prev_hash, view) != event.hash:
            problems.append(f"event {event.seq}: hash mismatch (event altered)")
        prev_hash, expected_seq = event.hash, event.seq + 1
    return problems


# --- Upload stubs ---------------------------------------------------------------------------


def _validate_declared(mime: str, size: int) -> None:
    if mime not in ALLOWED_TYPES:
        raise ValidationError({"mime": [f"Allowed types: {sorted(ALLOWED_TYPES)}"]})
    if not 0 < size <= MAX_BYTES:
        raise ValidationError({"size": [f"Images must be 1 byte to {MAX_BYTES} bytes."]})


def _stub(
    version: Any, uploader_id: Any, item: Mapping[str, Any], election_id: Any
) -> EvidenceFile:
    """Create or match an evidence stub for a version. Same id, same details = idempotent."""
    _validate_declared(item["mime"], item["size"])
    existing = EvidenceFile.objects.select_for_update().filter(id=item["evidence_id"]).first()
    declared = {
        "kind": item["kind"],
        "size": item["size"],
        "mime": item["mime"],
        "sha256_client": item["sha256"].lower(),
    }
    if existing is not None:
        same = existing.result_version_id == version.id and all(
            getattr(existing, k) == v for k, v in declared.items()
        )
        if not same:
            raise EvidenceConflict()
        return existing
    evidence = EvidenceFile.objects.create(
        id=item["evidence_id"],
        organization_id=version.organization_id,
        result_version=version,
        polling_unit_id=version.polling_unit_id,
        ward_id=version.ward_id,
        lga_id=version.lga_id,
        uploaded_by_id=uploader_id,
        object_key=object_key(
            organization_id=version.organization_id,
            election_id=election_id,
            polling_unit_id=version.polling_unit_id,
            version_id=version.id,
            evidence_id=item["evidence_id"],
            mime=item["mime"],
        ),
        **declared,
    )
    append_custody(evidence, "upload_requested", actor_id=uploader_id, details=declared)
    return evidence


def create_stubs(
    version: Any, uploader_id: Any, manifest: Iterable[Mapping[str, Any]], election_id: Any
) -> list[EvidenceFile]:
    """Called inside the result submission transaction."""
    return [_stub(version, uploader_id, item, election_id) for item in manifest]


def upload_instructions(evidence: EvidenceFile) -> dict[str, Any]:
    entry: dict[str, Any] = {"evidence_id": str(evidence.id), "status": evidence.status}
    if evidence.status == EvidenceStatus.PENDING_UPLOAD:
        entry["upload"] = (
            get_storage()
            .presign_upload(
                evidence.object_key,
                mime=evidence.mime,
                sha256_hex=evidence.sha256_client,
                size=evidence.size,
            )
            .as_dict()
        )
    return entry


def request_upload(actor: Actor, version: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """POST /evidence/uploads: an extra photo, or a fresh URL after the first one expired."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    with transaction.atomic():
        evidence = _stub(version, actor.user_id, item, version.pu_result.election_id)
    return upload_instructions(evidence)


def complete_upload(actor: Actor, evidence: EvidenceFile) -> EvidenceFile:
    """The device says the PUT succeeded. Idempotent: later calls return the current state."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    with transaction.atomic():
        evidence = EvidenceFile.objects.select_for_update().get(id=evidence.id)
        if evidence.status == EvidenceStatus.PENDING_UPLOAD:
            _mark_uploaded(evidence, actor_id=actor.user_id, via="device_confirmation")
    return evidence


def _mark_uploaded(evidence: EvidenceFile, *, actor_id: Any, via: str) -> None:
    stored_size = get_storage().size_of(evidence.object_key)
    if stored_size is None:
        raise UploadNotFound()
    evidence.status = EvidenceStatus.UPLOADED
    evidence.uploaded_at = timezone.now()
    evidence.save(update_fields=["status", "uploaded_at"])
    append_custody(
        evidence, "uploaded", actor_id=actor_id, details={"size": stored_size, "via": via}
    )
    core.emit("evidence.uploaded", {"evidence_id": evidence.id})


# --- Verification (worker) ------------------------------------------------------------------


def _problems(evidence: EvidenceFile, data: bytes) -> tuple[list[str], str]:
    problems = []
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != evidence.size:
        problems.append(f"size {len(data)} differs from declared {evidence.size}")
    if digest != evidence.sha256_client:
        problems.append("sha256 differs from the device's")
    sniffed = sniff_mime(data[:16])
    if sniffed != evidence.mime:
        problems.append(f"content is {sniffed or 'not an allowed image'}, declared {evidence.mime}")
    scanner = import_string(settings.VTRS_MALWARE_SCANNER)()
    if threat := scanner.scan(data):
        problems.append(f"malware: {threat}")
    return problems, digest


def verify(evidence_id: UUID) -> EvidenceFile | None:
    """Worker step: verify an UPLOADED object, then VERIFIED or QUARANTINED. Idempotent."""
    storage = get_storage()
    with transaction.atomic(), system_context():
        evidence = EvidenceFile.objects.select_for_update().filter(id=evidence_id).first()
        if evidence is None or evidence.status != EvidenceStatus.UPLOADED:
            return evidence
        data = storage.read(evidence.object_key)
        problems, digest = _problems(evidence, data)
        derived = None
        if not problems:
            try:
                derived = processing.derive(data)
            except processing.ImageRejected as exc:
                problems.append(str(exc))
        evidence.sha256_server = digest
        if problems or derived is None:
            quarantine_key = f"quarantine/{evidence.object_key}"
            storage.move(evidence.object_key, quarantine_key)
            evidence.status = EvidenceStatus.QUARANTINED
            evidence.quarantine_reason = "; ".join(problems)[:200]
            evidence.metadata = {**evidence.metadata, "quarantine_key": quarantine_key}
            evidence.save(
                update_fields=["status", "quarantine_reason", "metadata", "sha256_server"]
            )
            append_custody(evidence, "quarantined", details={"problems": problems})
            return evidence
        thumb_key = f"derived/{evidence.object_key}.thumb.jpg"
        preview_key = f"derived/{evidence.object_key}.preview.jpg"
        storage.write(thumb_key, derived.thumbnail, mime="image/jpeg")
        storage.write(preview_key, derived.preview, mime="image/jpeg")
        evidence.status = EvidenceStatus.VERIFIED
        evidence.verified_at = timezone.now()
        evidence.metadata = {
            **evidence.metadata,
            **derived.metadata,
            "width": derived.width,
            "height": derived.height,
            "thumbnail_key": thumb_key,
            "preview_key": preview_key,
        }
        evidence.save(update_fields=["status", "verified_at", "metadata", "sha256_server"])
        append_custody(evidence, "verified", details={"sha256_server": digest})
        core.emit("evidence.verified", {"evidence_id": evidence.id})
    return evidence


def reconcile_pending_uploads(older_than: timedelta = timedelta(minutes=10)) -> int:
    """Backup path: a stub still PENDING_UPLOAD whose object exists was uploaded but never
    confirmed (app killed, network dropped). Treat the object's presence as the confirmation."""
    storage = get_storage()
    completed = 0
    with transaction.atomic(), system_context():
        stale = EvidenceFile.objects.select_for_update(skip_locked=True).filter(
            status=EvidenceStatus.PENDING_UPLOAD,
            created_at__lte=timezone.now() - older_than,
        )[:500]
        for evidence in stale:
            if storage.size_of(evidence.object_key) is not None:
                _mark_uploaded(evidence, actor_id=None, via="storage_reconciliation")
                completed += 1
    return completed


# --- Access ---------------------------------------------------------------------------------


def download_url(actor: Actor, evidence: EvidenceFile) -> dict[str, Any]:
    """A 60-second link, issued only after the evidence.view check, logged as custody."""
    authorize(actor, Perm.EVIDENCE_VIEW)
    if evidence.status == EvidenceStatus.QUARANTINED:
        raise EvidenceQuarantined()
    if evidence.status == EvidenceStatus.PENDING_UPLOAD:
        raise EvidenceNotReady()
    with transaction.atomic():
        locked = EvidenceFile.objects.select_for_update().get(id=evidence.id)
        append_custody(locked, "download_url_issued", actor_id=actor.user_id)
    filename = f"{evidence.kind}-{evidence.id}.{ALLOWED_TYPES[evidence.mime]}"
    return {
        "url": get_storage().presign_download(evidence.object_key, filename=filename),
        "expires_in": settings.VTRS_EVIDENCE_DOWNLOAD_URL_SECONDS,
    }


def ensure_partitions(months_ahead: int = 3) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT vtrs_ensure_partitions('custody_event', %s)", [months_ahead])
