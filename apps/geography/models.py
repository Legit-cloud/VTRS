"""Shared geographic reference data (FR-6.4.x). Read-only outside the master-data import."""

from django.db import models
from django.db.models import Q

from apps.core.models import UUIDv7Model


class State(UUIDv7Model):
    inec_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "geo_state"

    def __str__(self) -> str:
        return self.name


class Lga(UUIDv7Model):
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="lgas")
    inec_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "geo_lga"

    def __str__(self) -> str:
        return self.name


class Ward(UUIDv7Model):
    lga = models.ForeignKey(Lga, on_delete=models.PROTECT, related_name="wards")
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="+")
    inec_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "geo_ward"

    def __str__(self) -> str:
        return self.name


class PollingUnit(UUIDv7Model):
    # lga and state are denormalized so scoping and aggregation filter on one column.
    ward = models.ForeignKey(Ward, on_delete=models.PROTECT, related_name="polling_units")
    lga = models.ForeignKey(Lga, on_delete=models.PROTECT, related_name="+")
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="+")
    inec_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    registered_voters = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "geo_polling_unit"
        constraints = [
            models.CheckConstraint(
                condition=(Q(latitude__isnull=True) & Q(longitude__isnull=True))
                | (
                    Q(latitude__gte=-90)
                    & Q(latitude__lte=90)
                    & Q(longitude__gte=-180)
                    & Q(longitude__lte=180)
                ),
                name="pu_coordinates_valid",
            )
        ]

    def __str__(self) -> str:
        return self.name


class ElectionType(UUIDv7Model):
    """A kind of election and the constituency kind its races are held in (FR-6.3.1, FR-6.3.6).

    Configuration, not code: loaded from `data/election_types.json` by `load_election_types`.
    """

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    constituency_kind = models.CharField(max_length=40)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "election_type"

    def __str__(self) -> str:
        return self.name


class Constituency(UUIDv7Model):
    """An area one race is held in: a state, senatorial district, federal or state constituency,
    LGA or ward. Kinds are configuration; codes are unique within a kind."""

    kind = models.CharField(max_length=40)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "constituency"
        constraints = [
            models.UniqueConstraint(fields=["kind", "code"], name="constituency_unique_code")
        ]
        indexes = [models.Index(fields=["state", "kind"], name="constituency_state_kind_idx")]

    def __str__(self) -> str:
        return self.name


class PollingUnitConstituency(UUIDv7Model):
    """Which constituency of each kind a polling unit belongs to. Exactly one per kind, so a
    polling unit resolves to exactly one constituency per election type (FR-6.3.6)."""

    polling_unit = models.ForeignKey(
        PollingUnit, on_delete=models.CASCADE, related_name="constituencies"
    )
    kind = models.CharField(max_length=40)
    constituency = models.ForeignKey(
        Constituency, on_delete=models.CASCADE, related_name="polling_units"
    )

    class Meta:
        db_table = "polling_unit_constituency"
        constraints = [
            models.UniqueConstraint(
                fields=["polling_unit", "kind"], name="pu_constituency_one_per_kind"
            )
        ]
        indexes = [models.Index(fields=["constituency"], name="pu_constituency_idx")]
