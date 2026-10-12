"""Export job reads: people see their own jobs; an organization admin sees the organization's."""

from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import NotFound

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Role

from .models import ExportJob


def exports_for(actor: Actor) -> QuerySet[ExportJob]:
    authorize(actor, AUTHENTICATED)
    qs = ExportJob.objects.filter(organization_id=actor.organization_id)
    if actor.role is not Role.PARTY_ADMIN:
        qs = qs.filter(requested_by_id=actor.user_id)
    return qs.select_related("requested_by")


def export_for(actor: Actor, job_id: UUID) -> ExportJob:
    job = exports_for(actor).filter(id=job_id).first()
    if job is None:
        raise NotFound()
    return job
