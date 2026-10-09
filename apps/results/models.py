"""Result ledger (spec section 6). PostgreSQL is the single system of record for results.

pu_result is the aggregate root: one per (contest, polling unit), locked FOR UPDATE whenever a
version is added. result_version and vote_line are immutable: a trigger rejects UPDATE and
DELETE (only result_version.state may change, for review decisions), and the app role has
no DELETE on them.
"""

from django.db import models
from django.db.models import Q

from apps.core.ids import uuid7
from apps.core.scope import ScopedQuerySet

from .domain.versions import VersionState

_GEO_SCOPE = {"org": "organization_id", "lga": "lga_id", "ward": "ward_id", "pu": "polling_unit_id"}


class PuResultStatus(models.TextChoices):
    NO_RESULT = "NO_RESULT"  # every version rejected
    SUBMITTED = "SUBMITTED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    APPROVED = "APPROVED"


class PuResult(models.Model):
    SCOPE_LOOKUPS = _GEO_SCOPE

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    election = models.ForeignKey("elections.Election", on_delete=models.PROTECT, related_name="+")
    contest = models.ForeignKey("elections.Contest", on_delete=models.PROTECT, related_name="+")
    polling_unit = models.ForeignKey(
        "geography.PollingUnit", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey("geography.Ward", on_delete=models.PROTECT, related_name="+")
    lga = models.ForeignKey("geography.Lga", on_delete=models.PROTECT, related_name="+")
    state = models.ForeignKey("geography.State", on_delete=models.PROTECT, related_name="+")
    head_version = models.ForeignKey(
        "ResultVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    version_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=PuResultStatus.choices, default=PuResultStatus.NO_RESULT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "pu_result"
        constraints = [
            models.UniqueConstraint(
                fields=["contest", "polling_unit"], name="pu_result_one_per_contest_pu"
            )
        ]
        indexes = [
            models.Index(fields=["contest", "lga"], name="pu_result_contest_lga_idx"),
            models.Index(fields=["contest", "ward"], name="pu_result_contest_ward_idx"),
            models.Index(fields=["contest", "status"], name="pu_result_contest_status_idx"),
        ]


class ResultVersion(models.Model):
    SCOPE_LOOKUPS = _GEO_SCOPE

    # The client-generated version UUID: primary key and idempotency key in one.
    id = models.UUIDField(primary_key=True, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    pu_result = models.ForeignKey(PuResult, on_delete=models.PROTECT, related_name="versions")
    contest = models.ForeignKey("elections.Contest", on_delete=models.PROTECT, related_name="+")
    polling_unit = models.ForeignKey(
        "geography.PollingUnit", on_delete=models.PROTECT, related_name="+"
    )
    ward = models.ForeignKey("geography.Ward", on_delete=models.PROTECT, related_name="+")
    lga = models.ForeignKey("geography.Lga", on_delete=models.PROTECT, related_name="+")
    version_no = models.PositiveIntegerField()
    accredited = models.PositiveIntegerField(null=True, blank=True)
    valid = models.PositiveIntegerField()
    rejected = models.PositiveIntegerField(null=True, blank=True)
    total_cast = models.PositiveIntegerField(null=True, blank=True)
    # Device time is recorded but untrusted; server_received_at is authoritative.
    device_captured_at = models.DateTimeField()
    server_received_at = models.DateTimeField()
    gps_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    gps_accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    submitted_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    app_version = models.CharField(max_length=32)
    config_version = models.PositiveIntegerField()
    payload_hash = models.CharField(max_length=64)
    parent_version_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=[(s.value, s.value) for s in VersionState])

    objects = ScopedQuerySet.as_manager()

    class Meta:
        db_table = "result_version"
        constraints = [
            models.UniqueConstraint(fields=["pu_result", "version_no"], name="version_unique_no"),
            models.CheckConstraint(
                condition=(Q(gps_lat__isnull=True) & Q(gps_lng__isnull=True))
                | (Q(gps_lat__gte=-90) & Q(gps_lat__lte=90))
                & (Q(gps_lng__gte=-180) & Q(gps_lng__lte=180)),
                name="version_gps_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["submitted_by", "server_received_at"], name="version_agent_idx"),
            models.Index(fields=["contest", "lga"], name="version_contest_lga_idx"),
        ]


class VoteLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    result_version = models.ForeignKey(
        ResultVersion, on_delete=models.PROTECT, related_name="vote_lines"
    )
    candidate = models.ForeignKey("elections.Candidate", on_delete=models.PROTECT, related_name="+")
    votes = models.PositiveIntegerField()

    class Meta:
        db_table = "vote_line"
        constraints = [
            models.UniqueConstraint(
                fields=["result_version", "candidate"], name="vote_line_one_per_candidate"
            )
        ]
