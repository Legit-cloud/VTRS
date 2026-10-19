"""Requesting, building and handing over exports (FR-6.10.5, spec sections 14 and 15).

The rules, in order: the caller needs the permission for the kind of export, a fresh second
factor, and fewer than N exports already running. The worker then builds the file as the
caller, uploads it to private storage, and records a digest. A link is issued only to the
requester (or an admin), after another fresh second factor, lives 60 seconds, and every issue
is audited. Files are purged after the retention window; the job record stays.
"""

import hashlib
import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.core import rls
from apps.core import services as core
from apps.core.authz import authorize, require_recent_mfa
from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import Perm, Role
from apps.core.rls import system_context
from apps.elections import selectors as elections
from apps.evidence import services as evidence
from apps.evidence.models import EvidenceFile
from apps.evidence.storage import get_storage

from . import builders
from .domain.formats import (
    ALLOWED_FORMATS,
    CONTENT_TYPES,
    ExportFormat,
    ExportKind,
    export_filename,
)
from .errors import (
    ExportExpired,
    ExportNotReady,
    InvalidExport,
    PackTooLarge,
    TooManyExports,
)
from .models import ExportJob, JobStatus

logger = logging.getLogger("vtrs.reports")

KIND_PERMISSIONS: dict[ExportKind, tuple[Perm, ...]] = {
    ExportKind.RESULTS: (Perm.REPORTS_EXPORT, Perm.DASHBOARD_VIEW),
    ExportKind.FLAGS: (Perm.REPORTS_EXPORT, Perm.ANOMALIES_VIEW),
    ExportKind.AUDIT: (Perm.REPORTS_EXPORT, Perm.AUDIT_VIEW),
    ExportKind.EVIDENCE_PACK: (Perm.EVIDENCE_EXPORT, Perm.EVIDENCE_VIEW),
}
MAX_AUDIT_WINDOW = timedelta(days=31)


def _actor_of(job: ExportJob) -> Actor:
    return Actor(
        user_id=job.requested_by_id,
        organization_id=job.organization_id,
        role=Role(job.actor_role),
        scope=Scope(ScopeKind(job.scope_kind), frozenset(job.scope_ids)),
        granted=frozenset(Perm(p) for p in job.granted if p in Perm._value2member_map_),
    )


def _clean_params(kind: ExportKind, raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields this kind understands, as plain JSON values."""
    allowed = {
        ExportKind.RESULTS: {"election_id", "level", "measure", "parent_id"},
        ExportKind.FLAGS: {"election_id", "status", "severity", "rule_code"},
        ExportKind.AUDIT: {"since", "until", "action"},
        ExportKind.EVIDENCE_PACK: {
            "election_id",
            "contest_id",
            "lga_id",
            "ward_id",
            "polling_unit_id",
        },
    }[kind]
    return {k: str(v) for k, v in raw.items() if k in allowed and v not in (None, "")}


def _validate(actor: Actor, kind: ExportKind, params: dict[str, Any]) -> None:
    if kind is ExportKind.AUDIT:
        try:
            since = datetime.fromisoformat(params["since"])
            until = datetime.fromisoformat(params["until"])
        except (KeyError, ValueError):
            raise InvalidExport("Give `since` and `until` as ISO timestamps.") from None
        if since.tzinfo is None or until.tzinfo is None:
            raise InvalidExport("`since` and `until` need a time zone offset.")
        if until <= since or until - since > MAX_AUDIT_WINDOW:
            raise InvalidExport("The window must be positive and at most 31 days.")
        return
    if "election_id" not in params:
        raise InvalidExport("`election_id` is required.")
    elections.election_for(actor, UUID(params["election_id"]))  # 404 outside the organization
    if kind is ExportKind.RESULTS:
        if params.get("level", "pu") not in {"pu", "ward", "lga"}:
            raise InvalidExport("`level` must be pu, ward or lga.")
        if params.get("measure", "reported") not in {"reported", "verified"}:
            raise InvalidExport("`measure` must be reported or verified.")


def request_export(actor: Actor, *, kind: str, fmt: str, params: dict[str, Any]) -> ExportJob:
    try:
        export_kind = ExportKind(kind)
        export_format = ExportFormat(fmt)
    except ValueError:
        raise InvalidExport("Unknown export kind or format.") from None
    if export_format not in ALLOWED_FORMATS[export_kind]:
        raise InvalidExport(
            f"{export_kind} exports are available as {ALLOWED_FORMATS[export_kind]}."
        )
    for perm in KIND_PERMISSIONS[export_kind]:
        authorize(actor, perm)
    require_recent_mfa(actor)
    cleaned = _clean_params(export_kind, params)
    _validate(actor, export_kind, cleaned)

    active = ExportJob.objects.filter(
        requested_by_id=actor.user_id, status__in=[JobStatus.PENDING, JobStatus.RUNNING]
    ).count()
    if active >= settings.VTRS_EXPORT_MAX_ACTIVE:
        raise TooManyExports()

    with transaction.atomic():
        job = ExportJob.objects.create(
            organization_id=actor.organization_id,
            requested_by_id=actor.user_id,
            kind=export_kind.value,
            format=export_format.value,
            params=cleaned,
            actor_role=actor.role.value,
            scope_kind=actor.scope.kind.value,
            scope_ids=sorted(actor.scope.ids, key=str),
            granted=sorted(p.value for p in actor.granted),
        )
        audit.record(
            action="export.requested",
            object_type="export_job",
            object_id=job.id,
            actor=actor,
            diff={"kind": job.kind, "format": job.format, "params": cleaned},
        )
        core.emit("export.requested", {"organization_id": job.organization_id, "job_id": job.id})
    return job


# --- The worker -------------------------------------------------------------------------------


def run_export(organization_id: UUID, job_id: UUID) -> str:
    """Build the file for a pending job. Idempotent: only a PENDING job is picked up."""
    with transaction.atomic():
        rls.set_tenant(organization_id)
        job = ExportJob.objects.select_for_update().filter(id=job_id).first()
        if job is None or job.status != JobStatus.PENDING:
            return job.status if job else "MISSING"
        job.status = JobStatus.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])

    handle, path = tempfile.mkstemp(prefix="vtrs-export-", suffix=f".{job.format.lower()}")
    os.close(handle)
    try:
        with transaction.atomic():
            rls.set_tenant(organization_id)
            actor = _actor_of(job)
            included: list[Any] = []
            kind = ExportKind(job.kind)
            if kind is ExportKind.RESULTS:
                built = builders.build_results(job, actor, path)
            elif kind is ExportKind.FLAGS:
                built = builders.build_flags(job, actor, path)
            elif kind is ExportKind.AUDIT:
                built = builders.build_audit(job, actor, path)
            else:
                built, included = builders.build_pack(job, actor, path)
        size = os.path.getsize(path)
        digest = _sha256_file(path)
        now = timezone.now()
        fmt = ExportFormat(job.format)
        filename = export_filename(kind, built.label, now, fmt)
        key = f"exports/{organization_id}/{job.id}/{filename}"
        get_storage().upload_file(key, path, mime=CONTENT_TYPES[fmt])
        with transaction.atomic():
            rls.set_tenant(organization_id)
            job = ExportJob.objects.select_for_update().get(id=job.id)
            job.status = JobStatus.READY
            job.filename = filename
            job.object_key = key
            job.size = size
            job.sha256 = digest
            job.manifest_sha256 = built.manifest_sha256
            job.row_count = built.row_count
            job.file_count = built.file_count
            job.finished_at = now
            job.expires_at = now + timedelta(hours=settings.VTRS_EXPORT_RETENTION_HOURS)
            job.save()
            _record_pack_custody(job, included)
            audit.record(
                action="export.completed",
                object_type="export_job",
                object_id=job.id,
                organization_id=organization_id,
                diff={
                    "kind": job.kind,
                    "sha256": digest,
                    "size": size,
                    "rows": built.row_count,
                    "files": built.file_count,
                    "manifest_sha256": built.manifest_sha256,
                },
            )
        return JobStatus.READY
    except Exception as exc:
        logger.warning("export_failed", exc_info=True, extra={"job_id": str(job_id)})
        message = str(exc) if isinstance(exc, PackTooLarge) else "The export could not be built."
        with transaction.atomic():
            rls.set_tenant(organization_id)
            ExportJob.objects.filter(id=job_id).update(
                status=JobStatus.FAILED, error=message[:300], finished_at=timezone.now()
            )
            audit.record(
                action="export.failed",
                object_type="export_job",
                object_id=job_id,
                organization_id=organization_id,
                diff={"error": message[:300]},
            )
        return JobStatus.FAILED
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_pack_custody(job: ExportJob, files: list[Any]) -> None:
    """Each photo's chain of custody records that it left in this pack."""
    if not files:
        return
    ids = [f.id for f in files]
    for locked in EvidenceFile.objects.select_for_update().filter(id__in=ids).order_by("id"):
        evidence.append_custody(
            locked,
            "exported",
            actor_id=job.requested_by_id,
            details={"export_job_id": str(job.id), "manifest_sha256": job.manifest_sha256},
        )


# --- Handing it over --------------------------------------------------------------------------


def download_url(actor: Actor, job: ExportJob) -> dict[str, Any]:
    for perm in KIND_PERMISSIONS[ExportKind(job.kind)]:
        authorize(actor, perm)
    require_recent_mfa(actor)
    if job.status == JobStatus.EXPIRED or (
        job.expires_at is not None and job.expires_at <= timezone.now()
    ):
        raise ExportExpired()
    if job.status != JobStatus.READY:
        raise ExportNotReady()
    with transaction.atomic():
        locked = ExportJob.objects.select_for_update().get(id=job.id)
        locked.download_count += 1
        locked.last_downloaded_at = timezone.now()
        locked.save(update_fields=["download_count", "last_downloaded_at"])
        audit.record(
            action="export.download_url_issued",
            object_type="export_job",
            object_id=job.id,
            actor=actor,
            diff={"kind": job.kind, "sha256": job.sha256},
        )
    return {
        "url": get_storage().presign_download(job.object_key, filename=job.filename),
        "expires_in": settings.VTRS_EVIDENCE_DOWNLOAD_URL_SECONDS,
        "sha256": job.sha256,
        "size": job.size,
    }


def purge_expired(limit: int = 200) -> int:
    """Beat task: delete files past their retention window; keep the job record."""
    now = timezone.now()
    with transaction.atomic(), system_context():
        due = list(
            ExportJob.objects.filter(status=JobStatus.READY, expires_at__lte=now).order_by(
                "expires_at"
            )[:limit]
        )
        storage = get_storage()
        for job in due:
            try:
                storage.delete(job.object_key)
            except Exception:
                logger.warning("export_purge_failed", exc_info=True, extra={"job": str(job.id)})
                continue
            job.status = JobStatus.EXPIRED
            job.save(update_fields=["status"])
            audit.record(
                action="export.purged",
                object_type="export_job",
                object_id=job.id,
                organization_id=job.organization_id,
                diff={"kind": job.kind, "expired_at": job.expires_at},
            )
    return len(due)
