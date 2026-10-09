"""Organization lifecycle (FR-6.1.1). Callers own the RLS context: these run pre-tenant."""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit

from .models import Organization, OrganizationStatus


def create_organization(*, name: str, legal_name: str = "") -> Organization:
    return Organization.objects.create(name=name, legal_name=legal_name)


def mark_verified(organization_id: UUID) -> Organization:
    """The signer verified their OTP; the organization now waits for operator approval."""
    org = Organization.objects.select_for_update().get(id=organization_id)
    if org.status == OrganizationStatus.PENDING_VERIFICATION:
        org.status = OrganizationStatus.PENDING_APPROVAL
        org.verified_at = timezone.now()
        org.save(update_fields=["status", "verified_at"])
    return org


def approve(organization_id: UUID, *, operator: str) -> Organization:
    """Platform-operator approval. Operators sit outside the tenant model (no actor)."""
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(id=organization_id)
        if org.status != OrganizationStatus.PENDING_APPROVAL:
            raise ValueError(f"Organization is {org.status}, not pending approval")
        org.status = OrganizationStatus.ACTIVE
        org.approved_at = timezone.now()
        org.save(update_fields=["status", "approved_at"])
        audit.record(
            action="organization.approved",
            object_type="organization",
            object_id=org.id,
            organization_id=org.id,
            diff={"operator": operator},
        )
    return org
