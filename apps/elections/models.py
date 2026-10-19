"""Parties, elections, contests and contestants (FR-6.3.1 - FR-6.3.7).

A party is master data owned by one organization. An election has a type, and the type names
the constituency kind its races are held in; a contest is the race in one constituency, and a
contestant (stored as `candidate`) is one party's candidate in it. Results reference
contestants, and through them parties, by id: nothing is grouped by free text.
"""

from collections.abc import Iterable
from enum import StrEnum

from django.db import models
from django.db.models import Q

from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet

from .domain.rules import ElectionStatus, IssueKind, IssueStatus


def _choices(members: Iterable[StrEnum]) -> list[tuple[str, str]]:
    return [(member.value, member.value) for member in members]


def default_sheet_fields() -> list[str]:
    """Kept for migration 0001, which created the old per-contest sheet field list."""
    return ["accredited", "valid", "rejected", "total_cast"]


class CountPolicy(models.TextChoices):
    # Both measures are always stored; the policy only picks the default shown (section 11).
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"


class Party(UUIDv7Model):
    """One entry in an organization's party master list (FR-6.3.4). Admins manage it; agents
    only ever see it on the result form."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    full_name = models.CharField(max_length=200)
    # Stored upper case, as printed on the result sheet (APC, PDP, LP, ADC).
    abbreviation = models.CharField(max_length=20)
    logo_key = models.CharField(max_length=300, blank=True, default="")
    logo_mime = models.CharField(max_length=40, blank=True, default="")
    # The organization's own party, for "our margin" and series colour 1 on dashboards.
    is_own = models.BooleanField(default=False)
    row_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "party"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "abbreviation"], name="party_unique_abbreviation"
            ),
            models.UniqueConstraint(
                fields=["organization"], condition=Q(is_own=True), name="party_one_own"
            ),
        ]

    def __str__(self) -> str:
        return self.abbreviation


class Election(UUIDv7Model):
    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="elections"
    )
    name = models.CharField(max_length=200)
    election_type = models.ForeignKey(
        "geography.ElectionType", on_delete=models.PROTECT, related_name="+"
    )
    state = models.ForeignKey("geography.State", on_delete=models.PROTECT, related_name="+")
    election_date = models.DateField()
    status = models.CharField(
        max_length=12, choices=_choices(ElectionStatus), default=ElectionStatus.DRAFT
    )
    count_policy = models.CharField(
        max_length=10, choices=CountPolicy.choices, default=CountPolicy.REPORTED
    )
    polls_open_at = models.DateTimeField(null=True, blank=True)
    polls_close_at = models.DateTimeField(null=True, blank=True)
    # Bumped on every party, contest or contestant change; the result form carries it.
    config_version = models.PositiveIntegerField(default=1)
    config_hash = models.CharField(max_length=64, blank=True, default="")
    row_version = models.PositiveIntegerField(default=1)
    locked_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "election"
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="election_unique_name"),
            models.CheckConstraint(
                condition=Q(polls_open_at__isnull=True)
                | Q(polls_close_at__isnull=True)
                | Q(polls_close_at__gt=models.F("polls_open_at")),
                name="election_polls_window",
            ),
        ]
        indexes = [models.Index(fields=["organization", "election_date"], name="election_org_idx")]

    def __str__(self) -> str:
        return self.name


class ElectionParty(UUIDv7Model):
    """A party contesting an election, and where it sits in the admin's fixed order (FR-6.3.5).
    The result form lists parties in this order."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="parties")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="+")
    ballot_order = models.PositiveSmallIntegerField()

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "election_party"
        constraints = [
            models.UniqueConstraint(fields=["election", "party"], name="election_party_once"),
            models.UniqueConstraint(
                fields=["election", "ballot_order"], name="election_party_unique_order"
            ),
            models.CheckConstraint(condition=Q(ballot_order__gte=1), name="election_party_order"),
        ]


class Contest(UUIDv7Model):
    """The race in one constituency of an election. Created when its first contestant is
    linked; its polling units are those the constituency mapping assigns to it."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="contests")
    constituency = models.ForeignKey(
        "geography.Constituency", on_delete=models.PROTECT, related_name="+"
    )
    row_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "contest"
        constraints = [
            models.UniqueConstraint(
                fields=["election", "constituency"], name="contest_one_per_constituency"
            )
        ]

    @property
    def title(self) -> str:
        return self.constituency.name

    def __str__(self) -> str:
        return self.title


class Candidate(UUIDv7Model):
    """A contestant: one party's candidate in one contest, so in one election and constituency
    (FR-6.3.2). One party has at most one contestant per contest."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    contest = models.ForeignKey(Contest, on_delete=models.PROTECT, related_name="candidates")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=200)
    # The election config version this contestant entry was written at.
    config_version = models.PositiveIntegerField()
    row_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    # Not a column: the election's party order, annotated by the selectors that list contestants.
    ballot_order: int

    class Meta:
        db_table = "candidate"
        constraints = [
            models.UniqueConstraint(fields=["contest", "party"], name="candidate_one_per_party")
        ]

    def __str__(self) -> str:
        return self.name


class ConfigIssue(UUIDv7Model):
    """ "Party missing" or "contestant missing", raised by an agent from the result form
    (FR-6.3.7). A task for an admin: it never creates a party or contestant."""

    SCOPE_LOOKUPS = {
        "org": "organization_id",
        "lga": "lga_id",
        "ward": "ward_id",
        "pu": "polling_unit_id",
    }

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name="issues")
    polling_unit = models.ForeignKey(
        "geography.PollingUnit", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey("geography.Ward", on_delete=models.PROTECT, related_name="+")
    lga = models.ForeignKey("geography.Lga", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, choices=_choices(IssueKind))
    note = models.TextField()
    raised_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=_choices(IssueStatus), default="OPEN")
    resolution_note = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "config_issue"
        indexes = [
            models.Index(
                fields=["election", "created_at"],
                condition=Q(status="OPEN"),
                name="config_issue_open_idx",
            )
        ]
