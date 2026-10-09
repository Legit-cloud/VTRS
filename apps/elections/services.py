"""Election, contest and candidate configuration (FR-6.3.1 - FR-6.3.3, AC-02).

Every change is audited, bumps the election's config_version, and is refused once the
election is LOCKED. Edits carry the row version the admin last read (If-Match).
"""

from datetime import date, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.core.api.concurrency import check_version
from apps.core.authz import authorize, require_recent_mfa
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.geography import selectors as geography

from . import selectors
from .domain.rules import (
    EDITABLE,
    ElectionStatus,
    can_transition,
    configuration_problems,
    fingerprint,
    sheet_field_problems,
)
from .errors import ConfigurationIncomplete, ElectionNotEditable, InvalidTransition
from .models import Candidate, Contest, Election

ELECTION_FIELDS = (
    "name",
    "election_date",
    "count_policy",
    "review_enabled",
    "polls_open_at",
    "polls_close_at",
)


def _snapshot(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in fields}


def _check_polls_window(opens: datetime | None, closes: datetime | None) -> None:
    if opens and closes and closes <= opens:
        raise ValidationError({"polls_close_at": ["Polls must close after they open."]})


def _locked_election(election_id: Any) -> Election:
    return Election.objects.select_for_update().get(id=election_id)


def _require_editable(election: Election) -> None:
    if election.status not in EDITABLE:
        raise ElectionNotEditable()


def _bump_config(election: Election) -> None:
    election.config_version += 1
    election.row_version += 1
    election.save(update_fields=["config_version", "row_version", "updated_at"])


def _unique_violation(field: str, message: str) -> ValidationError:
    return ValidationError({field: [message]}, code="duplicate")


# --- Elections ------------------------------------------------------------------------------


def create_election(
    actor: Actor,
    *,
    name: str,
    state_id: Any,
    election_date: date,
    count_policy: str = "REPORTED",
    review_enabled: bool = False,
    polls_open_at: datetime | None = None,
    polls_close_at: datetime | None = None,
) -> Election:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    if not geography.state_exists(actor, state_id):
        raise ValidationError({"state_id": ["Unknown state."]})
    _check_polls_window(polls_open_at, polls_close_at)
    try:
        with transaction.atomic():
            election = Election.objects.create(
                organization_id=actor.organization_id,
                name=name,
                state_id=state_id,
                election_date=election_date,
                count_policy=count_policy,
                review_enabled=review_enabled,
                polls_open_at=polls_open_at,
                polls_close_at=polls_close_at,
                created_by_id=actor.user_id,
            )
            audit.record(
                action="election.created",
                object_type="election",
                object_id=election.id,
                actor=actor,
                diff={"after": _snapshot(election, ELECTION_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation("name", "An election with this name already exists.") from None
    return election


def update_election(
    actor: Actor, election: Election, *, expected_version: int, changes: dict[str, Any]
) -> Election:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    try:
        with transaction.atomic():
            election = _locked_election(election.id)
            check_version(expected_version, election.row_version)
            _require_editable(election)
            before = _snapshot(election, ELECTION_FIELDS)
            for name, value in changes.items():
                setattr(election, name, value)
            _check_polls_window(election.polls_open_at, election.polls_close_at)
            election.row_version += 1
            election.save()
            audit.record(
                action="election.updated",
                object_type="election",
                object_id=election.id,
                actor=actor,
                diff={"before": before, "after": _snapshot(election, ELECTION_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation("name", "An election with this name already exists.") from None
    return election


def transition(actor: Actor, election: Election, target: str) -> Election:
    """Move an election through its lifecycle. Locking needs a fresh second factor."""
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    target_status = ElectionStatus(target)
    if target_status is ElectionStatus.LOCKED:
        require_recent_mfa(actor)
    with transaction.atomic():
        election = _locked_election(election.id)
        current = ElectionStatus(election.status)
        if not can_transition(current, target_status):
            raise InvalidTransition(f"An election cannot move from {current} to {target_status}.")
        specs = selectors.contest_specs(actor, election)
        now = timezone.now()
        if target_status in {ElectionStatus.CONFIGURED, ElectionStatus.LOCKED}:
            problems = configuration_problems(specs)
            if problems:
                raise ConfigurationIncomplete({"problems": problems})
        if target_status is ElectionStatus.LOCKED:
            election.config_hash = fingerprint(election.id, specs)
            election.locked_at = now
        elif target_status is ElectionStatus.LIVE:
            election.opened_at = now
        elif target_status is ElectionStatus.CLOSED:
            election.closed_at = now
        election.status = target_status
        election.row_version += 1
        election.save()
        audit.record(
            action="election.status_changed",
            object_type="election",
            object_id=election.id,
            actor=actor,
            diff={
                "from": current,
                "to": target_status,
                "config_version": election.config_version,
                "config_hash": election.config_hash,
            },
        )
    return election


# --- Contests -------------------------------------------------------------------------------


def _validate_contest(
    actor: Actor, election: Election, level: str, jurisdiction_ids: list[Any], sheet: list[str]
) -> None:
    errors: dict[str, list[str]] = {}
    if not jurisdiction_ids:
        errors["jurisdiction_ids"] = ["Give at least one area."]
    elif bad := geography.not_in_state(actor, level, jurisdiction_ids, election.state_id):
        errors["jurisdiction_ids"] = [
            f"Unknown or outside the election's state: {sorted(map(str, bad))}"
        ]
    if problems := sheet_field_problems(sheet):
        errors["sheet_fields"] = problems
    if errors:
        raise ValidationError(errors)


CONTEST_FIELDS = ("office", "title", "jurisdiction_level", "jurisdiction_ids", "sheet_fields")


def create_contest(
    actor: Actor,
    election: Election,
    *,
    office: str,
    title: str,
    jurisdiction_level: str,
    jurisdiction_ids: list[Any],
    sheet_fields: list[str],
) -> Contest:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    _validate_contest(actor, election, jurisdiction_level, jurisdiction_ids, sheet_fields)
    try:
        with transaction.atomic():
            election = _locked_election(election.id)
            _require_editable(election)
            contest = Contest.objects.create(
                organization_id=actor.organization_id,
                election=election,
                office=office,
                title=title,
                jurisdiction_level=jurisdiction_level,
                jurisdiction_ids=sorted(set(jurisdiction_ids)),
                sheet_fields=sheet_fields,
            )
            _bump_config(election)
            audit.record(
                action="contest.created",
                object_type="contest",
                object_id=contest.id,
                actor=actor,
                diff={"election_id": election.id, "after": _snapshot(contest, CONTEST_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation(
            "title", "This election already has a contest with that title."
        ) from None
    return contest


def update_contest(
    actor: Actor, contest: Contest, *, expected_version: int, changes: dict[str, Any]
) -> Contest:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    try:
        with transaction.atomic():
            election = _locked_election(contest.election_id)
            _require_editable(election)
            contest = Contest.objects.select_for_update().get(id=contest.id)
            check_version(expected_version, contest.row_version)
            before = _snapshot(contest, CONTEST_FIELDS)
            for name, value in changes.items():
                setattr(contest, name, value)
            _validate_contest(
                actor,
                election,
                contest.jurisdiction_level,
                contest.jurisdiction_ids,
                contest.sheet_fields,
            )
            contest.jurisdiction_ids = sorted(set(contest.jurisdiction_ids))
            contest.row_version += 1
            contest.save()
            _bump_config(election)
            audit.record(
                action="contest.updated",
                object_type="contest",
                object_id=contest.id,
                actor=actor,
                diff={"before": before, "after": _snapshot(contest, CONTEST_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation(
            "title", "This election already has a contest with that title."
        ) from None
    return contest


def delete_contest(actor: Actor, contest: Contest) -> None:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    with transaction.atomic():
        election = _locked_election(contest.election_id)
        _require_editable(election)
        removed = list(contest.candidates.values_list("id", flat=True))
        Candidate.objects.filter(contest=contest).delete()
        contest.delete()
        _bump_config(election)
        audit.record(
            action="contest.deleted",
            object_type="contest",
            object_id=contest.id,
            actor=actor,
            diff={"title": contest.title, "candidates_removed": removed},
        )


# --- Candidates -----------------------------------------------------------------------------

CANDIDATE_FIELDS = ("name", "party_name", "party_acronym", "ballot_order", "is_own_party")
_CANDIDATE_DUPLICATE = (
    "A candidate in this contest already has that ballot position, party, or the own-party flag."
)


def create_candidate(
    actor: Actor,
    contest: Contest,
    *,
    name: str,
    party_name: str,
    party_acronym: str,
    ballot_order: int,
    is_own_party: bool = False,
) -> Candidate:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    try:
        with transaction.atomic():
            election = _locked_election(contest.election_id)
            _require_editable(election)
            candidate = Candidate.objects.create(
                organization_id=actor.organization_id,
                contest=contest,
                name=name,
                party_name=party_name,
                party_acronym=party_acronym.upper(),
                ballot_order=ballot_order,
                is_own_party=is_own_party,
                config_version=election.config_version + 1,
            )
            _bump_config(election)
            audit.record(
                action="candidate.created",
                object_type="candidate",
                object_id=candidate.id,
                actor=actor,
                diff={"contest_id": contest.id, "after": _snapshot(candidate, CANDIDATE_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation("ballot_order", _CANDIDATE_DUPLICATE) from None
    return candidate


def update_candidate(
    actor: Actor, candidate: Candidate, *, expected_version: int, changes: dict[str, Any]
) -> Candidate:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    try:
        with transaction.atomic():
            election = _locked_election(candidate.contest.election_id)
            _require_editable(election)
            candidate = Candidate.objects.select_for_update().get(id=candidate.id)
            check_version(expected_version, candidate.row_version)
            before = _snapshot(candidate, CANDIDATE_FIELDS)
            for name, value in changes.items():
                setattr(candidate, name, value.upper() if name == "party_acronym" else value)
            candidate.config_version = election.config_version + 1
            candidate.row_version += 1
            candidate.save()
            _bump_config(election)
            audit.record(
                action="candidate.updated",
                object_type="candidate",
                object_id=candidate.id,
                actor=actor,
                diff={"before": before, "after": _snapshot(candidate, CANDIDATE_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation("ballot_order", _CANDIDATE_DUPLICATE) from None
    return candidate


def delete_candidate(actor: Actor, candidate: Candidate) -> None:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    with transaction.atomic():
        election = _locked_election(candidate.contest.election_id)
        _require_editable(election)
        before = _snapshot(candidate, CANDIDATE_FIELDS)
        candidate.delete()
        _bump_config(election)
        audit.record(
            action="candidate.deleted",
            object_type="candidate",
            object_id=candidate.id,
            actor=actor,
            diff={"before": before},
        )
