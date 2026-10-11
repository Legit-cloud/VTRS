"""Who hears about a rollup change (FR-6.8.5, spec section 8).

A change is announced to the groups that cover the polling unit's geography, and a viewer joins
only the groups its scope covers. So the notice (ids and a revision, never figures) reaches
exactly the people whose dashboards the change can alter; the figures themselves are fetched
over REST, where authorization is enforced again.
"""

from collections.abc import Iterable
from uuid import UUID


def org_group(election_id: UUID) -> str:
    return f"dash.{election_id}.org"


def lga_group(election_id: UUID, lga_id: UUID) -> str:
    return f"dash.{election_id}.lga.{lga_id}"


def ward_group(election_id: UUID, ward_id: UUID) -> str:
    return f"dash.{election_id}.ward.{ward_id}"


def groups_for_update(election_id: UUID, lga_id: UUID, ward_id: UUID) -> list[str]:
    """Every group a change in this ward must be announced to."""
    return [
        org_group(election_id),
        lga_group(election_id, lga_id),
        ward_group(election_id, ward_id),
    ]


def groups_for_viewer(election_id: UUID, scope_kind: str, scope_ids: Iterable[UUID]) -> list[str]:
    """The groups a viewer with this scope subscribes to."""
    if scope_kind == "ORG":
        return [org_group(election_id)]
    if scope_kind == "LGA":
        return [lga_group(election_id, i) for i in scope_ids]
    if scope_kind == "WARD":
        return [ward_group(election_id, i) for i in scope_ids]
    return []  # agents have no dashboard
