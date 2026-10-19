"""Test setup for the party / constituency / contestant model (FR-6.3.x).

Imports a synthetic directory, loads the configured election types, derives the STATE, LGA and
WARD constituencies, and builds an election with contesting parties and one contestant per
party in a constituency.
"""

import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election, ElectionParty, Party
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Constituency, ElectionType, State
from apps.geography.services import (
    derive_constituencies,
    import_master_data,
    load_election_types,
)


def load_reference_data(*, lgas: int, wards: int, polling_units: int, seed: int) -> None:
    import_master_data(
        synthetic_master_data(lgas=lgas, wards=wards, polling_units=polling_units, seed=seed)
    )
    load_election_types(
        json.loads((settings.BASE_DIR / "data" / "election_types.json").read_text("utf-8"))
    )
    derive_constituencies()


def election_type(code: str = "GOVERNORSHIP") -> ElectionType:
    return ElectionType.objects.get(code=code)


@dataclass
class Ballot:
    parties: list[Party]
    contest: Contest
    candidates: list[Candidate]


def make_election(org: Any, admin: Any, **fields: Any) -> Election:
    values: dict[str, Any] = {
        "name": "Governorship",
        "election_type": election_type(fields.pop("type_code", "GOVERNORSHIP")),
        "state": State.objects.get(),
        "election_date": "2027-03-11",
        "status": "LIVE",
        "config_version": 3,
        "created_by_id": admin.user.id,
        **fields,
    }
    with transaction.atomic(), system_context():
        return Election.objects.create(organization=org, **values)


def make_parties(org: Any, abbreviations: tuple[str, ...], own: str | None = None) -> list[Party]:
    with transaction.atomic(), system_context():
        return [
            Party.objects.create(
                organization=org,
                full_name=f"{a} Party",
                abbreviation=a,
                is_own=(a == own),
            )
            for a in abbreviations
        ]


def make_ballot(
    org: Any,
    election: Election,
    abbreviations: tuple[str, ...] = ("AAA", "BBB"),
    *,
    own: str | None = "AAA",
    constituency: Constituency | None = None,
    parties: list[Party] | None = None,
) -> Ballot:
    """Contesting parties in this order, a contest for the constituency (the state by default)
    and one contestant per party."""
    with transaction.atomic(), system_context():
        if parties is None:
            parties = make_parties(org, abbreviations, own)
        order = ElectionParty.objects.filter(election=election).count()
        for offset, party in enumerate(parties, start=1):
            ElectionParty.objects.get_or_create(
                organization=org,
                election=election,
                party=party,
                defaults={"ballot_order": order + offset},
            )
        constituency = constituency or Constituency.objects.get(
            kind=election.election_type.constituency_kind, state_id=election.state_id
        )
        contest, _ = Contest.objects.get_or_create(
            organization=org, election=election, constituency=constituency
        )
        candidates = [
            Candidate.objects.create(
                organization=org,
                contest=contest,
                party=party,
                name=f"Candidate {party.abbreviation}",
                config_version=1,
            )
            for party in parties
        ]
    return Ballot(parties, contest, candidates)
