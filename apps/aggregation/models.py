"""Materialized rollups (spec section 6, FR-6.7.1, FR-6.7.2).

A rollup row holds one contest's figures for one area (state, LGA or ward). Polling-unit
figures are never copied: they are read from the head version, which is the single source of
truth. Rows are derived data: they are rebuilt from head versions, never edited by hand, and
`verify` proves they still equal a fresh calculation.
"""

from django.db import models

from apps.core.ids import uuid7
from apps.core.scope import ScopedQuerySet

from .domain.tally import RollupLevel

_LEVELS = [
    (level.value, level.value) for level in (RollupLevel.STATE, RollupLevel.LGA, RollupLevel.WARD)
]


class Rollup(models.Model):
    # State rows carry neither lga_id nor ward_id, so an LGA- or ward-scoped actor can never
    # read them: a scoped officer's top level is their own area, not the state total.
    SCOPE_LOOKUPS = {"org": "organization_id", "lga": "lga_id", "ward": "ward_id"}

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey("elections.Election", on_delete=models.PROTECT, related_name="+")
    contest = models.ForeignKey("elections.Contest", on_delete=models.PROTECT, related_name="+")
    level = models.CharField(max_length=5, choices=_LEVELS)
    # The state, LGA or ward this row describes, and the area one level up.
    area_id = models.UUIDField()
    parent_id = models.UUIDField(null=True, blank=True)
    lga = models.ForeignKey(
        "geography.Lga", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey(
        "geography.Ward", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    expected_pus = models.PositiveIntegerField(default=0)
    registered_voters = models.PositiveBigIntegerField(default=0)
    # Polling units whose counting head is in a reported state / approved / awaiting a decision.
    reported_pus = models.PositiveIntegerField(default=0)
    verified_pus = models.PositiveIntegerField(default=0)
    review_pus = models.PositiveIntegerField(default=0)
    open_flags = models.PositiveIntegerField(default=0)

    reported_accredited = models.PositiveBigIntegerField(default=0)
    reported_valid = models.PositiveBigIntegerField(default=0)
    reported_rejected = models.PositiveBigIntegerField(default=0)
    reported_total_cast = models.PositiveBigIntegerField(default=0)
    verified_accredited = models.PositiveBigIntegerField(default=0)
    verified_valid = models.PositiveBigIntegerField(default=0)
    verified_rejected = models.PositiveBigIntegerField(default=0)
    verified_total_cast = models.PositiveBigIntegerField(default=0)

    # Bumped on every recompute, so clients can tell a newer figure from an older one.
    revision = models.PositiveIntegerField(default=0)
    computed_at = models.DateTimeField()

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "rollup"
        constraints = [
            models.UniqueConstraint(
                fields=["contest", "level", "area_id"], name="rollup_one_per_area"
            )
        ]
        indexes = [
            models.Index(fields=["contest", "level", "parent_id"], name="rollup_children_idx"),
            models.Index(fields=["election", "level"], name="rollup_election_idx"),
        ]


class RollupVote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    rollup = models.ForeignKey(Rollup, on_delete=models.CASCADE, related_name="votes")
    candidate = models.ForeignKey("elections.Candidate", on_delete=models.PROTECT, related_name="+")
    reported_votes = models.PositiveBigIntegerField(default=0)
    verified_votes = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "rollup_vote"
        constraints = [
            models.UniqueConstraint(fields=["rollup", "candidate"], name="rollup_vote_one_each")
        ]


class ReconciliationSnapshot(models.Model):
    """The rollups at the moment an election was reconciled (FR-6.7.x, spec section 11).

    Immutable. `sha256` is a digest of `data`, so any later difference is detectable."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.OneToOneField(
        "elections.Election", on_delete=models.PROTECT, related_name="reconciliation"
    )
    config_hash = models.CharField(max_length=64)
    data = models.JSONField()
    sha256 = models.CharField(max_length=64)
    reported_pus = models.PositiveIntegerField()
    verified_pus = models.PositiveIntegerField()
    reconciled_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    reconciled_at = models.DateTimeField()

    class Meta:
        db_table = "reconciliation_snapshot"


class RollupDirty(models.Model):
    """A ward whose figures changed and whose rollups have not been refreshed yet.

    Events only mark; whichever worker holds the contest's lock drains every mark that has piled
    up and refreshes each affected ward, LGA and the state once. Under a burst the number of
    refreshes follows the number of drains, not the number of results."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    contest = models.ForeignKey("elections.Contest", on_delete=models.CASCADE, related_name="+")
    ward = models.ForeignKey("geography.Ward", on_delete=models.CASCADE, related_name="+")
    marked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rollup_dirty"
        constraints = [
            models.UniqueConstraint(fields=["contest", "ward"], name="rollup_dirty_one_per_ward")
        ]
        indexes = [models.Index(fields=["marked_at"], name="rollup_dirty_age_idx")]
