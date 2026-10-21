"""Cross-organization reads for platform operators.

Everything here runs in the system RLS context and shows operators what they need to run the
service: who is on it, whether it is healthy, whether messages arrive. It never returns a
party's results, evidence or voter-level data; those stay behind that party's own roles.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.accounts.models import Membership, MembershipStatus
from apps.anomalies.models import AnomalyFlag, FlagStatus
from apps.audit.models import AuditEvent
from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.core.models import OutboxEvent
from apps.elections.models import Election
from apps.evidence.domain.rules import EvidenceStatus
from apps.evidence.models import EvidenceFile
from apps.geography.models import PollingUnit, State
from apps.notifications.models import Delivery, DeliveryStatus
from apps.organizations.models import Organization, OrganizationStatus
from apps.results.models import ResultVersion

SUBMISSIONS_PER_HOUR_TARGET = 10_000


def _guard(actor: Actor) -> None:
    authorize(actor, Perm.PLATFORM_MANAGE)


def organizations(actor: Actor, *, status: str | None = None) -> QuerySet[Organization]:
    _guard(actor)
    active = Q(memberships__status=MembershipStatus.ACTIVE)
    qs = (
        Organization.objects.filter(is_platform=False)
        .annotate(
            people=Count("memberships", filter=active, distinct=True),
            agents=Count(
                "memberships", filter=active & Q(memberships__role="PU_AGENT"), distinct=True
            ),
            election_count=Count("elections", distinct=True),
        )
        .order_by("-id")
    )
    if status:
        qs = qs.filter(status=status)
    return qs


def organization_detail(actor: Actor, organization_id: UUID) -> dict[str, Any]:
    _guard(actor)
    org = organizations(actor).filter(id=organization_id).first()
    if org is None:
        raise NotFound()
    admins = [
        {
            "user_id": m.user_id,
            "full_name": m.user.full_name,
            "status": m.user.status,
            "email": _mask_email(m.user.email),
            "phone": _mask_phone(m.user.phone),
        }
        for m in Membership.objects.filter(organization=org, role="PARTY_ADMIN")
        .select_related("user")
        .order_by("created_at")
    ]
    elections = list(
        Election.objects.filter(organization=org)
        .order_by("-election_date")
        .values("id", "name", "status", "election_date", "locked_at", "opened_at", "closed_at")[:20]
    )
    activity = list(
        AuditEvent.objects.filter(organization_id=org.id)
        .order_by("-at")
        .values("id", "at", "action", "actor_role", "object_type", "object_id")[:15]
    )
    return {"organization": org, "admins": admins, "elections": elections, "activity": activity}


def _mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    return f"{local[:1]}***@{domain}" if domain else ""


def _mask_phone(value: str) -> str:
    return "*" * max(len(value) - 3, 0) + value[-3:] if value else ""


def verification_queue(actor: Actor) -> QuerySet[Organization]:
    _guard(actor)
    return organizations(actor).filter(status=OrganizationStatus.PENDING_APPROVAL).order_by("id")


def elections(actor: Actor, *, status: str | None = None) -> QuerySet[Election]:
    _guard(actor)
    qs = Election.objects.select_related("organization").order_by("-election_date", "-id")
    if status:
        qs = qs.filter(status=status)
    return qs


def overview(actor: Actor) -> dict[str, Any]:
    _guard(actor)
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)
    orgs = dict(
        Organization.objects.filter(is_platform=False)
        .values_list("status")
        .annotate(n=Count("id"))
        .order_by()
    )
    election_status = dict(
        Election.objects.values_list("status").annotate(n=Count("id")).order_by()
    )
    last_hour = ResultVersion.objects.filter(server_received_at__gte=hour_ago).count()
    failed = Delivery.objects.filter(
        status=DeliveryStatus.FAILED, last_attempt_at__gte=hour_ago
    ).count()
    unpublished = OutboxEvent.objects.filter(published_at__isnull=True)
    oldest = unpublished.order_by("created_at").values_list("created_at", flat=True).first()
    quarantined = EvidenceFile.objects.filter(status=EvidenceStatus.QUARANTINED).count()
    open_flags = AnomalyFlag.objects.filter(
        status__in=[FlagStatus.OPEN, FlagStatus.ACKNOWLEDGED]
    ).count()
    agents = Membership.objects.filter(
        status=MembershipStatus.ACTIVE, role="PU_AGENT", organization__is_platform=False
    ).count()

    attention: list[dict[str, Any]] = []
    pending = orgs.get(OrganizationStatus.PENDING_APPROVAL, 0)
    if pending:
        attention.append(
            {"kind": "verification", "count": pending, "text": "organisations waiting for approval"}
        )
    if failed:
        attention.append(
            {"kind": "messaging", "count": failed, "text": "messages failed in the last hour"}
        )
    if oldest and (now - oldest).total_seconds() > 60:
        attention.append(
            {
                "kind": "queue",
                "count": unpublished.count(),
                "text": "events not yet processed; the oldest is over a minute old",
            }
        )
    if quarantined:
        attention.append(
            {"kind": "evidence", "count": quarantined, "text": "result-sheet photos in quarantine"}
        )

    return {
        "organizations": {
            "active": orgs.get(OrganizationStatus.ACTIVE, 0),
            "pending_verification": orgs.get(OrganizationStatus.PENDING_VERIFICATION, 0),
            "pending_approval": pending,
            "suspended": orgs.get(OrganizationStatus.SUSPENDED, 0),
            "rejected": orgs.get(OrganizationStatus.REJECTED, 0),
        },
        "elections": {
            "live": election_status.get("LIVE", 0),
            "total": sum(election_status.values()),
            "by_status": election_status,
        },
        "agents": agents,
        "submissions": {
            "last_hour": last_hour,
            "target_per_hour": SUBMISSIONS_PER_HOUR_TARGET,
        },
        "open_flags": open_flags,
        "messaging_failed_last_hour": failed,
        "needs_attention": attention,
        "as_of": now,
    }


def master_data(actor: Actor) -> dict[str, Any]:
    _guard(actor)
    states = []
    for state in State.objects.order_by("inec_code"):
        units = PollingUnit.objects.filter(state=state)
        totals = units.aggregate(
            polling_units=Count("id"),
            located=Count("id", filter=Q(latitude__isnull=False, longitude__isnull=False)),
            with_voters=Count("id", filter=Q(registered_voters__isnull=False)),
        )
        total = totals["polling_units"]
        states.append(
            {
                "state_id": state.id,
                "code": state.inec_code,
                "name": state.name,
                "lgas": state.lgas.count(),
                "wards": units.values("ward_id").distinct().count(),
                "polling_units": total,
                "located": totals["located"],
                "with_registered_voters": totals["with_voters"],
                "located_pct": round(100 * totals["located"] / total, 1) if total else None,
                "voters_pct": round(100 * totals["with_voters"] / total, 1) if total else None,
            }
        )
    return {"states": states}


def master_data_search(actor: Actor, query: str, limit: int = 25) -> list[dict[str, Any]]:
    _guard(actor)
    text = query.strip()
    if len(text) < 2:
        return []
    rows = (
        PollingUnit.objects.filter(Q(name__icontains=text) | Q(inec_code__icontains=text))
        .select_related("ward", "lga", "state")
        .order_by("inec_code")[:limit]
    )
    return [
        {
            "id": r.id,
            "code": r.inec_code,
            "name": r.name,
            "ward": r.ward.name,
            "lga": r.lga.name,
            "state": r.state.name,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "registered_voters": r.registered_voters,
        }
        for r in rows
    ]


def _provider_name(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1] if dotted else "not set"


def messaging(actor: Actor, *, hours: int = 24) -> dict[str, Any]:
    _guard(actor)
    since = timezone.now() - timedelta(hours=hours)
    rows = (
        Delivery.objects.filter(created_at__gte=since)
        .values("channel", "status")
        .annotate(n=Count("id"))
        .order_by()
    )
    by_channel: dict[str, dict[str, int]] = {}
    for row in rows:
        by_channel.setdefault(row["channel"], {})[row["status"]] = row["n"]

    providers = {
        "SMS": _provider_name(getattr(settings, "VTRS_SMS_PROVIDER", "")),
        "WHATSAPP": _provider_name(getattr(settings, "VTRS_WHATSAPP_PROVIDER", "")),
        "EMAIL": _provider_name(getattr(settings, "EMAIL_BACKEND", "")),
    }
    channels = []
    for channel in ("SMS", "EMAIL", "WHATSAPP", "IN_APP"):
        counts = by_channel.get(channel, {})
        attempted = sum(
            counts.get(s, 0)
            for s in (DeliveryStatus.SENT, DeliveryStatus.DELIVERED, DeliveryStatus.FAILED)
        )
        ok = counts.get(DeliveryStatus.SENT, 0) + counts.get(DeliveryStatus.DELIVERED, 0)
        channels.append(
            {
                "channel": channel,
                "provider": providers.get(channel, "in-app store"),
                "attempted": attempted,
                "sent": ok,
                "delivered": counts.get(DeliveryStatus.DELIVERED, 0),
                "failed": counts.get(DeliveryStatus.FAILED, 0),
                "pending": counts.get(DeliveryStatus.PENDING, 0),
                "skipped": counts.get(DeliveryStatus.SKIPPED, 0),
                "success_pct": round(100 * ok / attempted, 1) if attempted else None,
            }
        )
    return {"hours": hours, "channels": channels}


def audit_events(
    actor: Actor,
    *,
    organization_id: UUID | None = None,
    action: str | None = None,
    since: Any = None,
    until: Any = None,
) -> QuerySet[AuditEvent]:
    _guard(actor)
    qs = AuditEvent.objects.all()
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    if action:
        qs = qs.filter(action__icontains=action)
    if since:
        qs = qs.filter(at__gte=since)
    if until:
        qs = qs.filter(at__lte=until)
    return qs.order_by("-at", "-id")
