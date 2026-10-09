import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core.authz import AUTHENTICATED, authorize
from apps.core.domain.actor import Scope, ScopeKind
from apps.core.domain.permissions import Perm, Role
from apps.core.errors import Forbidden
from apps.core.scope import ScopedQuerySet, scope_q
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import PollingUnit
from apps.geography.services import import_master_data

# Polling units have no organization, so they exercise only the geographic half of scoping.
PU_LOOKUPS = {"lga": "lga_id", "ward": "ward_id", "pu": "id"}


@pytest.fixture
def geography(db):
    import_master_data(synthetic_master_data(lgas=3, wards=6, polling_units=24))
    return PollingUnit.objects.all()


def _visible(scope):
    return set(PollingUnit.objects.filter(scope_q(scope, None, PU_LOOKUPS)))


def test_org_scope_sees_everything(geography):
    assert _visible(Scope(ScopeKind.ORG)) == set(geography)


def test_lga_scope_sees_only_its_lga(geography):
    pu = geography.first()
    visible = _visible(Scope(ScopeKind.LGA, frozenset({pu.lga_id})))
    assert visible == set(geography.filter(lga_id=pu.lga_id))
    assert 0 < len(visible) < geography.count()


def test_ward_and_pu_scopes(geography):
    pu = geography.first()
    assert _visible(Scope(ScopeKind.WARD, frozenset({pu.ward_id}))) == set(
        geography.filter(ward_id=pu.ward_id)
    )
    assert _visible(Scope(ScopeKind.PU, frozenset({pu.id}))) == {pu}


def test_scope_with_no_ids_sees_nothing(geography):
    assert _visible(Scope(ScopeKind.WARD)) == set()


def test_missing_lookup_fails_closed():
    with pytest.raises(ImproperlyConfigured):
        scope_q(Scope(ScopeKind.WARD, frozenset()), None, {"org": "organization_id"})


def test_scoped_queryset_requires_an_org_lookup(make_actor):
    qs = ScopedQuerySet(model=PollingUnit)
    with pytest.raises(ImproperlyConfigured):
        qs.for_actor(make_actor())


def test_authorize(make_actor):
    agent = make_actor(Role.PU_AGENT)
    assert authorize(agent, Perm.RESULTS_SUBMIT) is agent
    assert authorize(agent, AUTHENTICATED) is agent
    with pytest.raises(Forbidden):
        authorize(agent, Perm.AUDIT_VIEW)
