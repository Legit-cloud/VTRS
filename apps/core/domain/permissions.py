"""Role -> permission map (spec section 8). Scope is resolved separately, from memberships."""

from collections.abc import Iterable, Mapping
from enum import StrEnum


class Role(StrEnum):
    PARTY_ADMIN = "PARTY_ADMIN"
    LGA_OFFICER = "LGA_OFFICER"
    WARD_OFFICER = "WARD_OFFICER"
    PU_AGENT = "PU_AGENT"


class Perm(StrEnum):
    ELECTIONS_CONFIGURE = "elections.configure"
    CANDIDATES_MANAGE = "candidates.manage"
    USERS_MANAGE = "users.manage"
    ASSIGNMENTS_MANAGE = "assignments.manage"
    RESULTS_SUBMIT = "results.submit"
    RESULTS_VIEW = "results.view"
    RESULTS_REVIEW = "results.review"
    ANOMALIES_VIEW = "anomalies.view"
    ANOMALIES_RESOLVE = "anomalies.resolve"
    EVIDENCE_VIEW = "evidence.view"
    EVIDENCE_EXPORT = "evidence.export"
    REPORTS_EXPORT = "reports.export"
    AUDIT_VIEW = "audit.view"
    DASHBOARD_VIEW = "dashboard.view"
    GEOGRAPHY_VIEW = "geography.view"


ROLE_PERMISSIONS: Mapping[Role, frozenset[Perm]] = {
    Role.PARTY_ADMIN: frozenset(Perm) - {Perm.RESULTS_SUBMIT},
    Role.LGA_OFFICER: frozenset(
        {
            Perm.RESULTS_VIEW,
            Perm.ANOMALIES_VIEW,
            Perm.ANOMALIES_RESOLVE,
            Perm.DASHBOARD_VIEW,
            Perm.GEOGRAPHY_VIEW,
        }
    ),
    Role.WARD_OFFICER: frozenset(
        {
            Perm.RESULTS_VIEW,
            Perm.RESULTS_REVIEW,
            Perm.ANOMALIES_VIEW,
            Perm.DASHBOARD_VIEW,
            Perm.GEOGRAPHY_VIEW,
        }
    ),
    # Agents see their own submissions and uploads only; selectors narrow that further.
    Role.PU_AGENT: frozenset(
        {
            Perm.RESULTS_SUBMIT,
            Perm.RESULTS_VIEW,
            Perm.EVIDENCE_VIEW,
            Perm.GEOGRAPHY_VIEW,
        }
    ),
}

# Permissions an admin may grant explicitly on top of a role ("Optional" / "Granted explicitly").
GRANTABLE_PERMISSIONS: Mapping[Role, frozenset[Perm]] = {
    Role.PARTY_ADMIN: frozenset(),
    Role.LGA_OFFICER: frozenset(
        {Perm.RESULTS_REVIEW, Perm.EVIDENCE_VIEW, Perm.EVIDENCE_EXPORT, Perm.REPORTS_EXPORT}
    ),
    Role.WARD_OFFICER: frozenset({Perm.EVIDENCE_VIEW}),
    Role.PU_AGENT: frozenset(),
}

ROLE_RANK: Mapping[Role, int] = {
    Role.PARTY_ADMIN: 4,
    Role.LGA_OFFICER: 3,
    Role.WARD_OFFICER: 2,
    Role.PU_AGENT: 1,
}


def effective_permissions(role: Role, granted: Iterable[Perm] = ()) -> frozenset[Perm]:
    """Role permissions plus explicit grants; grants the role cannot hold are ignored."""
    return ROLE_PERMISSIONS[role] | (frozenset(granted) & GRANTABLE_PERMISSIONS[role])


def requires_mfa(role: Role, permissions: frozenset[Perm]) -> bool:
    """MFA is mandatory for admins and for anyone who can export data or evidence packs."""
    return role is Role.PARTY_ADMIN or bool(
        permissions & {Perm.EVIDENCE_EXPORT, Perm.REPORTS_EXPORT}
    )


def can_assign_role(granter: Role, target: Role) -> bool:
    """Users may only grant roles at or below their own."""
    return ROLE_RANK[target] <= ROLE_RANK[granter]
