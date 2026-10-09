"""Master-data reads. Geography is shared reference data: any authenticated role may read it."""

from uuid import UUID

from django.db.models import QuerySet

from apps.core.authz import authorize
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm

from .models import Lga, PollingUnit, Ward


def lgas_for(actor: Actor, *, state_code: str | None = None) -> QuerySet[Lga]:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    qs = Lga.objects.select_related("state")
    if state_code:
        qs = qs.filter(state__inec_code=state_code)
    return qs


def wards_for(actor: Actor, *, lga_id: UUID | None = None) -> QuerySet[Ward]:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    qs = Ward.objects.all()
    if lga_id:
        qs = qs.filter(lga_id=lga_id)
    return qs


def polling_units_for(
    actor: Actor, *, ward_id: UUID | None = None, lga_id: UUID | None = None
) -> QuerySet[PollingUnit]:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    qs = PollingUnit.objects.all()
    if ward_id:
        qs = qs.filter(ward_id=ward_id)
    if lga_id:
        qs = qs.filter(lga_id=lga_id)
    return qs
