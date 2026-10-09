"""Role/permission matrix from spec section 8."""

import pytest

from apps.core.domain.actor import Actor, Scope, ScopeKind
from apps.core.domain.permissions import (
    Perm,
    Role,
    can_assign_role,
    effective_permissions,
)
from apps.core.ids import uuid7

EXPECTED = {
    # permission: roles that hold it without an explicit grant
    Perm.ELECTIONS_CONFIGURE: {Role.PARTY_ADMIN},
    Perm.CANDIDATES_MANAGE: {Role.PARTY_ADMIN},
    Perm.USERS_MANAGE: {Role.PARTY_ADMIN},
    Perm.ASSIGNMENTS_MANAGE: {Role.PARTY_ADMIN},
    Perm.RESULTS_SUBMIT: {Role.PU_AGENT},
    Perm.RESULTS_VIEW: set(Role),
    Perm.RESULTS_REVIEW: {Role.PARTY_ADMIN, Role.WARD_OFFICER},
    Perm.ANOMALIES_VIEW: {Role.PARTY_ADMIN, Role.LGA_OFFICER, Role.WARD_OFFICER},
    Perm.ANOMALIES_RESOLVE: {Role.PARTY_ADMIN, Role.LGA_OFFICER},
    Perm.EVIDENCE_VIEW: {Role.PARTY_ADMIN, Role.PU_AGENT},
    Perm.EVIDENCE_EXPORT: {Role.PARTY_ADMIN},
    Perm.REPORTS_EXPORT: {Role.PARTY_ADMIN},
    Perm.AUDIT_VIEW: {Role.PARTY_ADMIN},
    Perm.DASHBOARD_VIEW: {Role.PARTY_ADMIN, Role.LGA_OFFICER, Role.WARD_OFFICER},
    Perm.GEOGRAPHY_VIEW: set(Role),
}


@pytest.mark.parametrize("perm", list(Perm))
def test_role_matrix(perm):
    holders = {role for role in Role if perm in effective_permissions(role)}
    assert holders == EXPECTED[perm]


def test_grants_only_apply_where_the_role_allows_them():
    assert Perm.EVIDENCE_VIEW in effective_permissions(Role.LGA_OFFICER, {Perm.EVIDENCE_VIEW})
    assert Perm.RESULTS_REVIEW in effective_permissions(Role.LGA_OFFICER, {Perm.RESULTS_REVIEW})
    # A ward officer can never be granted exports, nor an agent the audit log.
    assert Perm.EVIDENCE_EXPORT not in effective_permissions(
        Role.WARD_OFFICER, {Perm.EVIDENCE_EXPORT}
    )
    assert Perm.AUDIT_VIEW not in effective_permissions(Role.PU_AGENT, {Perm.AUDIT_VIEW})


def test_roles_can_only_be_granted_at_or_below_your_own():
    assert can_assign_role(Role.PARTY_ADMIN, Role.LGA_OFFICER)
    assert can_assign_role(Role.LGA_OFFICER, Role.LGA_OFFICER)
    assert not can_assign_role(Role.WARD_OFFICER, Role.LGA_OFFICER)
    assert not can_assign_role(Role.LGA_OFFICER, Role.PARTY_ADMIN)


def test_actor_rejects_a_scope_that_does_not_match_its_role():
    with pytest.raises(ValueError):
        Actor(uuid7(), uuid7(), Role.WARD_OFFICER, Scope(ScopeKind.ORG))
    with pytest.raises(ValueError):
        Scope(ScopeKind.ORG, frozenset({uuid7()}))
