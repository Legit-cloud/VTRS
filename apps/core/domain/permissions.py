"""Role -> permission map (spec section 8.1). Scope is resolved separately, from memberships.

One web app serves every role; what a user can see and do depends only on these permissions
and their assigned scope. Coordinators (LGA_OFFICER, WARD_OFFICER) review and verify results
and see the uploaded sheets for their own area.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum


class Role(StrEnum):
    PARTY_ADMIN = "PARTY_ADMIN"
    LGA_OFFICER = "LGA_OFFICER"
    WARD_OFFICER = "WARD_OFFICER"
    PU_AGENT = "PU_AGENT"
    # Runs VTRS itself across all parties. Sits in the platform organization, outside any party.
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


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
    SYSTEM_VIEW = "system.view"
    ALERTS_CONFIGURE = "alerts.configure"
    PLATFORM_MANAGE = "platform.manage"


ROLE_PERMISSIONS: Mapping[Role, frozenset[Perm]] = {
    Role.PARTY_ADMIN: frozenset(Perm) - {Perm.RESULTS_SUBMIT, Perm.PLATFORM_MANAGE},
    # LGA coordinator.
    Role.LGA_OFFICER: frozenset(
        {
            Perm.RESULTS_VIEW,
            Perm.RESULTS_REVIEW,
            Perm.ANOMALIES_VIEW,
            Perm.ANOMALIES_RESOLVE,
            Perm.EVIDENCE_VIEW,
            Perm.DASHBOARD_VIEW,
            Perm.GEOGRAPHY_VIEW,
        }
    ),
    # Ward coordinator.
    Role.WARD_OFFICER: frozenset(
        {
            Perm.RESULTS_VIEW,
            Perm.RESULTS_REVIEW,
            Perm.ANOMALIES_VIEW,
            Perm.EVIDENCE_VIEW,
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
    # No party data at all: organizations, master data, health and the platform's own audit.
    Role.PLATFORM_ADMIN: frozenset({Perm.PLATFORM_MANAGE, Perm.GEOGRAPHY_VIEW, Perm.SYSTEM_VIEW}),
}

# Permissions an admin may grant explicitly on top of a role ("Optional" / "Granted explicitly").
GRANTABLE_PERMISSIONS: Mapping[Role, frozenset[Perm]] = {
    Role.PARTY_ADMIN: frozenset(),
    Role.LGA_OFFICER: frozenset({Perm.EVIDENCE_EXPORT, Perm.REPORTS_EXPORT}),
    Role.WARD_OFFICER: frozenset(),
    Role.PU_AGENT: frozenset(),
    Role.PLATFORM_ADMIN: frozenset(),
}

ROLE_RANK: Mapping[Role, int] = {
    # Above every party role, so no party admin can grant it. Operators are created by command.
    Role.PLATFORM_ADMIN: 5,
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
    return role in {Role.PARTY_ADMIN, Role.PLATFORM_ADMIN} or bool(
        permissions & {Perm.EVIDENCE_EXPORT, Perm.REPORTS_EXPORT}
    )


def can_assign_role(granter: Role, target: Role) -> bool:
    """Users may only grant roles at or below their own."""
    return ROLE_RANK[target] <= ROLE_RANK[granter]
