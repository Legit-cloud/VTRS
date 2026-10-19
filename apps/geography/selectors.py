"""Master-data reads. Geography is shared reference data: any authenticated role may read it."""

from collections.abc import Iterable
from uuid import UUID

from django.db.models import QuerySet

from apps.core.authz import authorize
from apps.core.domain.actor import Actor, ScopeKind
from apps.core.domain.permissions import Perm

from .models import Constituency, ElectionType, Lga, PollingUnit, State, Ward


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


def missing_ids(actor: Actor, kind: ScopeKind, ids: Iterable[UUID]) -> set[UUID]:
    """Ids of the given scope kind that do not exist in master data."""
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    models: dict[ScopeKind, type[Lga] | type[Ward] | type[PollingUnit]] = {
        ScopeKind.LGA: Lga,
        ScopeKind.WARD: Ward,
        ScopeKind.PU: PollingUnit,
    }
    model = models[kind]
    wanted = set(ids)
    found = set(model.objects.filter(id__in=wanted).values_list("id", flat=True))
    return wanted - found


def state_exists(actor: Actor, state_id: UUID) -> bool:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    return State.objects.filter(id=state_id).exists()


def not_in_state(actor: Actor, kind: str, ids: Iterable[UUID], state_id: UUID) -> set[UUID]:
    """Ids (STATE, LGA or WARD) that are unknown or lie outside the given state."""
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    wanted = set(ids)
    if kind == "STATE":
        return wanted - {state_id}
    model: type[Lga] | type[Ward] = Lga if kind == "LGA" else Ward
    found = set(model.objects.filter(id__in=wanted, state_id=state_id).values_list("id", flat=True))
    return wanted - found


def polling_unit(actor: Actor, polling_unit_id: UUID) -> PollingUnit | None:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    return PollingUnit.objects.select_related("ward", "lga").filter(id=polling_unit_id).first()


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


# --- Election types and constituencies (FR-6.3.6) ---------------------------------------------


def election_types_for(actor: Actor) -> QuerySet[ElectionType]:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    return ElectionType.objects.filter(is_active=True).order_by("sort_order", "code")


def election_type(actor: Actor, code: str) -> ElectionType | None:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    return ElectionType.objects.filter(code=code.upper(), is_active=True).first()


def constituencies_for(
    actor: Actor, *, kind: str | None = None, state_id: UUID | None = None, search: str = ""
) -> QuerySet[Constituency]:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    qs = Constituency.objects.all()
    if kind:
        qs = qs.filter(kind=kind.upper())
    if state_id:
        qs = qs.filter(state_id=state_id)
    if search:
        qs = qs.filter(name__icontains=search)
    return qs


def constituency(actor: Actor, constituency_id: UUID) -> Constituency | None:
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    return Constituency.objects.filter(id=constituency_id).first()


def constituency_of(actor: Actor, polling_unit_id: UUID, kind: str) -> Constituency | None:
    """The one constituency of `kind` a polling unit belongs to, if the mapping has it."""
    authorize(actor, Perm.GEOGRAPHY_VIEW)
    return Constituency.objects.filter(
        polling_units__polling_unit_id=polling_unit_id, polling_units__kind=kind
    ).first()
