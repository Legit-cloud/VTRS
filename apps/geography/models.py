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
