"""Evidence reads. Admins see all of the organization's evidence; officers need an explicit
evidence.view grant and stay inside their geography; agents see only what they uploaded."""

from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import authorize
from apps.core.domain.actor import Actor, ScopeKind
from apps.core.domain.permissions import Perm

from .models import EvidenceFile


def _scoped(actor: Actor) -> QuerySet[EvidenceFile]:
    qs = EvidenceFile.objects.for_actor(actor)
    if actor.scope.kind is ScopeKind.PU:
        qs = qs.filter(uploaded_by_id=actor.user_id)
    return qs


def viewable(actor: Actor, evidence_id: UUID) -> EvidenceFile:
    authorize(actor, Perm.EVIDENCE_VIEW)
    evidence = _scoped(actor).filter(id=evidence_id).first()
    if evidence is None:
        raise NotFound()
    return evidence


def own_upload(actor: Actor, evidence_id: UUID) -> EvidenceFile:
    """For the uploading agent's own follow-up calls (confirm upload)."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    evidence = (
        EvidenceFile.objects.for_actor(actor)
        .filter(id=evidence_id, uploaded_by_id=actor.user_id)
        .first()
    )
    if evidence is None:
        raise NotFound()
    return evidence


def for_versions(actor: Actor, version_ids: list[UUID]) -> QuerySet[EvidenceFile]:
    authorize(actor, Perm.RESULTS_SUBMIT)
    return _scoped(actor).filter(result_version_id__in=version_ids).order_by("created_at")
