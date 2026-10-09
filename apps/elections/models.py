from collections.abc import Iterable
from enum import StrEnum

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.models import UUIDv7Model
from apps.core.scope import ScopedQuerySet

from .domain.rules import SHEET_FIELDS, ElectionStatus, JurisdictionLevel


def _choices(members: Iterable[StrEnum]) -> list[tuple[str, str]]:
    return [(member.value, member.value) for member in members]


def default_sheet_fields() -> list[str]:
    return list(SHEET_FIELDS)


class CountPolicy(models.TextChoices):
    # Both measures are always stored; the policy only picks the default shown (section 11).
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"


class Election(UUIDv7Model):
    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="elections"
    )
    name = models.CharField(max_length=200)
    state = models.ForeignKey("geography.State", on_delete=models.PROTECT, related_name="+")
    election_date = models.DateField()
    status = models.CharField(
        max_length=12, choices=_choices(ElectionStatus), default=ElectionStatus.DRAFT
    )
    count_policy = models.CharField(
        max_length=10, choices=CountPolicy.choices, default=CountPolicy.REPORTED
    )
    # Open decision #5: count on submission, review optional per election.
    review_enabled = models.BooleanField(default=False)
    polls_open_at = models.DateTimeField(null=True, blank=True)
    polls_close_at = models.DateTimeField(null=True, blank=True)
    # Bumped on every contest or candidate change; agents sync against it.
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


class Office(models.TextChoices):
    PRESIDENTIAL = "PRESIDENTIAL"
    GOVERNORSHIP = "GOVERNORSHIP"
    SENATORIAL = "SENATORIAL"
    HOUSE_OF_REPRESENTATIVES = "HOUSE_OF_REPRESENTATIVES"
    STATE_ASSEMBLY = "STATE_ASSEMBLY"
    LGA_CHAIRMAN = "LGA_CHAIRMAN"
    COUNCILLOR = "COUNCILLOR"
    OTHER = "OTHER"


class Contest(UUIDv7Model):
    """One race. Its jurisdiction is a set of states, LGAs or wards (a senatorial district is
    the list of its LGAs), so any constituency can be described from master data."""

    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="contests")
    office = models.CharField(max_length=32, choices=Office.choices)
    title = models.CharField(max_length=200)
    jurisdiction_level = models.CharField(max_length=8, choices=_choices(JurisdictionLevel))
    jurisdiction_ids = ArrayField(models.UUIDField())
    sheet_fields = ArrayField(models.CharField(max_length=20), default=default_sheet_fields)
    row_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "contest"
        constraints = [
            models.UniqueConstraint(fields=["election", "title"], name="contest_unique_title")
        ]

    def __str__(self) -> str:
        return self.title


class Candidate(UUIDv7Model):
    SCOPE_LOOKUPS = {"org": "organization_id"}

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    contest = models.ForeignKey(Contest, on_delete=models.PROTECT, related_name="candidates")
    name = models.CharField(max_length=200)
    party_name = models.CharField(max_length=200)
    party_acronym = models.CharField(max_length=20)
    ballot_order = models.PositiveSmallIntegerField()
    # The organization's own candidate, for "our margin" on dashboards.
    is_own_party = models.BooleanField(default=False)
    # The election config version this candidate entry was written at.
    config_version = models.PositiveIntegerField()
    row_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "candidate"
        constraints = [
            models.UniqueConstraint(
                fields=["contest", "ballot_order"], name="candidate_unique_ballot_order"
            ),
            models.UniqueConstraint(
                fields=["contest", "party_acronym"], name="candidate_unique_party"
            ),
            models.UniqueConstraint(
                fields=["contest"], condition=Q(is_own_party=True), name="candidate_one_own_party"
            ),
            models.CheckConstraint(condition=Q(ballot_order__gte=1), name="candidate_ballot_order"),
        ]

    def __str__(self) -> str:
        return self.name
