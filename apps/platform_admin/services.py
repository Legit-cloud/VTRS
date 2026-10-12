"""Platform operator actions: deciding on organizations and importing master data.

Operators work across tenants, so these run in the system RLS context, and every decision
needs a fresh second factor and writes to the target organization's audit trail.
"""

import csv
import io
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit import services as audit
from apps.core.authz import authorize, require_recent_mfa
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.core.rls import system_context
from apps.geography import services as geography
from apps.organizations.models import Organization, OrganizationStatus

MAX_REASON = 500
MAX_FILE_BYTES = 8 * 1024 * 1024


class WrongState(ValidationError):
    default_code = "wrong_state"


def _decide(
    actor: Actor,
    organization_id: UUID,
    *,
    allowed_from: set[str],
    to: str,
    action: str,
    reason: str = "",
    reason_required: bool = False,
) -> Organization:
    authorize(actor, Perm.PLATFORM_MANAGE)
    require_recent_mfa(actor)
    reason = reason.strip()
    if reason_required and not reason:
        raise ValidationError({"reason": ["Say why. The organization is shown this reason."]})
    if len(reason) > MAX_REASON:
        raise ValidationError({"reason": [f"Use at most {MAX_REASON} characters."]})
    with transaction.atomic(), system_context():
        org = (
            Organization.objects.select_for_update()
            .filter(id=organization_id, is_platform=False)
            .first()
        )
        if org is None:
            raise NotFound()
        if org.status not in allowed_from:
            raise WrongState({"status": [f"This organization is {org.status.lower()}."]})
        before = org.status
        org.status = to
        org.status_reason = reason
        fields = ["status", "status_reason"]
        if to == OrganizationStatus.ACTIVE and before == OrganizationStatus.PENDING_APPROVAL:
            org.approved_at = timezone.now()
            fields.append("approved_at")
        org.save(update_fields=fields)
        audit.record(
            action=action,
            object_type="organization",
            object_id=org.id,
            organization_id=org.id,
            actor=actor,
            diff={"from": before, "to": to, "reason": reason},
        )
    return org


def approve(actor: Actor, organization_id: UUID) -> Organization:
    return _decide(
        actor,
        organization_id,
        allowed_from={OrganizationStatus.PENDING_APPROVAL},
        to=OrganizationStatus.ACTIVE,
        action="organization.approved",
    )


def reject(actor: Actor, organization_id: UUID, reason: str) -> Organization:
    return _decide(
        actor,
        organization_id,
        allowed_from={OrganizationStatus.PENDING_APPROVAL},
        to=OrganizationStatus.REJECTED,
        action="organization.rejected",
        reason=reason,
        reason_required=True,
    )


def suspend(actor: Actor, organization_id: UUID, reason: str) -> Organization:
    return _decide(
        actor,
        organization_id,
        allowed_from={OrganizationStatus.ACTIVE},
        to=OrganizationStatus.SUSPENDED,
        action="organization.suspended",
        reason=reason,
        reason_required=True,
    )


def reinstate(actor: Actor, organization_id: UUID) -> Organization:
    return _decide(
        actor,
        organization_id,
        allowed_from={OrganizationStatus.SUSPENDED},
        to=OrganizationStatus.ACTIVE,
        action="organization.reinstated",
    )


# ---- master data ------------------------------------------------------------------------


def _records(content: bytes) -> list[dict[str, str]]:
    if len(content) > MAX_FILE_BYTES:
        raise ValidationError({"file": ["The file is larger than 8 MB."]})
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError({"file": ["The file must be UTF-8 CSV."]}) from None
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError({"file": ["The file is empty."]})
    return [{(k or "").strip(): (v or "") for k, v in row.items()} for row in reader]


def preview_master_data(actor: Actor, content: bytes) -> dict[str, Any]:
    authorize(actor, Perm.PLATFORM_MANAGE)
    with transaction.atomic():
        outcome = geography.preview_master_data(_records(content))
    return outcome.as_dict()


def import_master_data(actor: Actor, content: bytes) -> dict[str, Any]:
    authorize(actor, Perm.PLATFORM_MANAGE)
    require_recent_mfa(actor)
    records = _records(content)
    with transaction.atomic():
        outcome = geography.import_master_data(records, actor=actor)
    return outcome.as_dict()
