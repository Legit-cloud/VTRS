"""Party, election and contestant configuration (FR-6.3.1 - FR-6.3.7, AC-02).

Every change is audited, bumps the election's config_version where it touches an election,
and is refused once the election is LOCKED. Edits carry the row version the admin last read
(If-Match). Agents never reach these services: they can only report a missing party or
contestant (`record_issue`), which never changes the configuration.
"""

import hashlib
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.core import services as core
from apps.core.api.concurrency import check_version
from apps.core.authz import authorize, require_recent_mfa
from apps.core.domain.actor import Actor
from apps.core.domain.permissions import Perm
from apps.evidence.domain.rules import sniff_mime
from apps.evidence.storage import get_storage
from apps.geography import selectors as geography

from . import selectors
from .domain.rules import (
    EDITABLE,
    ElectionStatus,
    IssueKind,
    IssueStatus,
    can_transition,
    configuration_problems,
    fingerprint,
    normalize_abbreviation,
)
from .errors import (
    ConfigurationIncomplete,
    ElectionNotDeletable,
    ElectionNotEditable,
    InvalidTransition,
    IssueAlreadyResolved,
    LogoRejected,
    PartyInUse,
    PartyLocked,
)
from .models import Candidate, ConfigIssue, Contest, Election, ElectionParty, Party

ELECTION_FIELDS = (
    "name",
    "election_date",
    "count_policy",
    "polls_open_at",
    "polls_close_at",
)
PARTY_FIELDS = ("full_name", "abbreviation", "is_own")
# Logos are small raster images only: no SVG, which can carry script.
LOGO_TYPES = selectors.LOGO_EXTENSIONS
LOGO_MAX_BYTES = 256 * 1024


def _snapshot(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in fields}


def _check_polls_window(opens: datetime | None, closes: datetime | None) -> None:
    if opens and closes and closes <= opens:
        raise ValidationError({"polls_close_at": ["Polls must close after they open."]})


def _locked_election(election_id: Any) -> Election:
    return Election.objects.select_related("election_type").select_for_update().get(id=election_id)


def _require_editable(election: Election) -> None:
    if election.status not in EDITABLE:
        raise ElectionNotEditable()


def _bump_config(election: Election) -> None:
    election.config_version += 1
    election.row_version += 1
    election.save(update_fields=["config_version", "row_version", "updated_at"])


def _unique_violation(field: str, message: str) -> ValidationError:
    return ValidationError({field: [message]}, code="duplicate")


# --- Parties (FR-6.3.4) ----------------------------------------------------------------------


def _party_locked(party: Party) -> bool:
    """A party a locked (or later) election uses keeps its name: results were captured under it."""
    return (
        ElectionParty.objects.filter(party=party)
        .exclude(election__status__in=[s.value for s in EDITABLE])
        .exists()
    )


def create_party(actor: Actor, *, full_name: str, abbreviation: str, is_own: bool = False) -> Party:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    try:
        with transaction.atomic():
            party = Party.objects.create(
                organization_id=actor.organization_id,
                full_name=full_name.strip(),
                abbreviation=normalize_abbreviation(abbreviation),
                is_own=is_own,
            )
            audit.record(
                action="party.created",
                object_type="party",
                object_id=party.id,
                actor=actor,
                diff={"after": _snapshot(party, PARTY_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation(
            "abbreviation", "A party with this abbreviation exists, or another is marked as yours."
        ) from None
    return party


def update_party(
    actor: Actor, party: Party, *, expected_version: int, changes: dict[str, Any]
) -> Party:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    if "abbreviation" in changes:
        changes["abbreviation"] = normalize_abbreviation(changes["abbreviation"])
    if "full_name" in changes:
        changes["full_name"] = changes["full_name"].strip()
    try:
        with transaction.atomic():
            party = Party.objects.select_for_update().get(id=party.id)
            check_version(expected_version, party.row_version)
            renamed = any(
                name in changes and changes[name] != getattr(party, name)
                for name in ("full_name", "abbreviation")
            )
            if renamed and _party_locked(party):
                raise PartyLocked()
            before = _snapshot(party, PARTY_FIELDS)
            for name, value in changes.items():
                setattr(party, name, value)
            party.row_version += 1
            party.save()
            audit.record(
                action="party.updated",
                object_type="party",
                object_id=party.id,
                actor=actor,
                diff={"before": before, "after": _snapshot(party, PARTY_FIELDS)},
            )
    except IntegrityError:
        raise _unique_violation(
            "abbreviation", "A party with this abbreviation exists, or another is marked as yours."
        ) from None
    return party


def delete_party(actor: Actor, party: Party) -> None:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    with transaction.atomic():
        party = Party.objects.select_for_update().get(id=party.id)
        if ElectionParty.objects.filter(party=party).exists():
            raise PartyInUse()
        before = _snapshot(party, PARTY_FIELDS)
        logo = party.logo_key
        party.delete()
        audit.record(
            action="party.deleted",
            object_type="party",
            object_id=party.id,
            actor=actor,
            diff={"before": before},
        )
    if logo:
        get_storage().delete(logo)


def _logo_key(party: Party, mime: str) -> str:
    return f"org/{party.organization_id}/parties/{party.id}/logo.{LOGO_TYPES[mime]}"


def request_logo_upload(
    actor: Actor, party: Party, *, mime: str, size: int, sha256: str
) -> dict[str, Any]:
    """A presigned upload for the party's logo. The logo changes only when it is confirmed."""
    authorize(actor, Perm.CANDIDATES_MANAGE)
    if mime not in LOGO_TYPES or not 0 < size <= LOGO_MAX_BYTES:
        raise LogoRejected()
    upload = get_storage().presign_upload(
        _logo_key(party, mime) + ".pending", mime=mime, sha256_hex=sha256.lower(), size=size
    )
    return {"mime": mime, "sha256": sha256.lower(), "upload": upload.as_dict()}


def complete_logo_upload(actor: Actor, party: Party, *, mime: str, sha256: str) -> Party:
    """Check the uploaded bytes (size, real image type, checksum), then make them the logo."""
    authorize(actor, Perm.CANDIDATES_MANAGE)
    if mime not in LOGO_TYPES:
        raise LogoRejected()
    storage = get_storage()
    pending = _logo_key(party, mime) + ".pending"
    try:
        data = storage.read(pending)
    except Exception:
        raise LogoRejected("No uploaded logo was found. Upload it again.") from None
    if (
        len(data) > LOGO_MAX_BYTES
        or sniff_mime(data[:16]) != mime
        or hashlib.sha256(data).hexdigest() != sha256.lower()
    ):
        storage.delete(pending)
        raise LogoRejected()
    key = _logo_key(party, mime)
    with transaction.atomic():
        party = Party.objects.select_for_update().get(id=party.id)
        old = party.logo_key
        storage.move(pending, key)
        party.logo_key, party.logo_mime = key, mime
        party.row_version += 1
        party.save(update_fields=["logo_key", "logo_mime", "row_version", "updated_at"])
        audit.record(
            action="party.logo_set",
            object_type="party",
            object_id=party.id,
            actor=actor,
            diff={"sha256": sha256.lower(), "mime": mime},
        )
    if old and old != key:
        storage.delete(old)
    return party


def remove_logo(actor: Actor, party: Party) -> Party:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    with transaction.atomic():
        party = Party.objects.select_for_update().get(id=party.id)
        old = party.logo_key
        party.logo_key, party.logo_mime = "", ""
        party.row_version += 1
        party.save(update_fields=["logo_key", "logo_mime", "row_version", "updated_at"])
        audit.record(
            action="party.logo_removed", object_type="party", object_id=party.id, actor=actor
        )
    if old:
        get_storage().delete(old)
    return party


# --- Elections --------------------------------------------------------------------------------


def _election_type(actor: Actor, code: str) -> Any:
    election_type = geography.election_type(actor, code)
    if election_type is None:
        raise ValidationError({"election_type": ["Unknown election type."]})
    return election_type


def create_election(
    actor: Actor,
    *,
    name: str,
    election_type: str,
    state_id: Any,
    election_date: date,
    count_policy: str = "REPORTED",
    polls_open_at: datetime | None = None,
    polls_close_at: datetime | None = None,
) -> Election:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    if not geography.state_exists(actor, state_id):
        raise ValidationError({"state_id": ["Unknown state."]})
    kind = _election_type(actor, election_type)
    _check_polls_window(polls_open_at, polls_close_at)
    try:
        with transaction.atomic():
            election = Election.objects.create(
                organization_id=actor.organization_id,
                name=name,
                election_type=kind,
                state_id=state_id,
                election_date=election_date,
                count_policy=count_policy,
                polls_open_at=polls_open_at,
                polls_close_at=polls_close_at,
                created_by_id=actor.user_id,
            )
            audit.record(
                action="election.created",
                object_type="election",
                object_id=election.id,
                actor=actor,
                diff={
                    "after": {**_snapshot(election, ELECTION_FIELDS), "election_type": kind.code}
                },
            )
    except IntegrityError:
        raise _unique_violation("name", "An election with this name already exists.") from None
    return election


def update_election(
    actor: Actor, election: Election, *, expected_version: int, changes: dict[str, Any]
) -> Election:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    new_type = changes.pop("election_type", None)
    try:
        with transaction.atomic():
            election = _locked_election(election.id)
            check_version(expected_version, election.row_version)
            _require_editable(election)
            before = {**_snapshot(election, ELECTION_FIELDS), "type": election.election_type.code}
            if new_type is not None and new_type.upper() != election.election_type.code:
                if Contest.objects.filter(election=election).exists():
                    raise ValidationError(
                        {"election_type": ["Remove the contestants before changing the type."]}
                    )
                election.election_type = _election_type(actor, new_type)
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
                diff={
                    "before": before,
                    "after": {
                        **_snapshot(election, ELECTION_FIELDS),
                        "type": election.election_type.code,
                    },
                },
            )
    except IntegrityError:
        raise _unique_violation("name", "An election with this name already exists.") from None
    return election


def transition(
    actor: Actor,
    election: Election,
    target: str,
    *,
    reconcile: Callable[[Actor, Election], Any] | None = None,
) -> Election:
    """Move an election through its lifecycle.

    Locking and reconciling need a fresh second factor. Reconciling also needs `reconcile`,
    the callable that freezes the rollups (it runs in this transaction, before the status
    changes, so a refusal leaves the election CLOSED).
    """
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    target_status = ElectionStatus(target)
    if target_status in {ElectionStatus.LOCKED, ElectionStatus.RECONCILED}:
        require_recent_mfa(actor)
    if (target_status is ElectionStatus.RECONCILED) != (reconcile is not None):
        raise InvalidTransition("Use the reconcile endpoint to reconcile an election.")
    with transaction.atomic():
        election = _locked_election(election.id)
        current = ElectionStatus(election.status)
        if not can_transition(current, target_status):
            raise InvalidTransition(f"An election cannot move from {current} to {target_status}.")
        parties = selectors.party_specs(actor, election)
        contests = selectors.contest_specs(actor, election)
        now = timezone.now()
        if target_status in {ElectionStatus.CONFIGURED, ElectionStatus.LOCKED}:
            problems = configuration_problems(parties, contests)
            if problems:
                raise ConfigurationIncomplete({"problems": problems})
        if target_status is ElectionStatus.LOCKED:
            election.config_hash = fingerprint(election.id, parties, contests)
            election.locked_at = now
        elif target_status is ElectionStatus.LIVE:
            election.opened_at = now
        elif target_status is ElectionStatus.CLOSED:
            election.closed_at = now
        elif target_status is ElectionStatus.RECONCILED and reconcile is not None:
            reconcile(actor, election)
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
        if target_status is ElectionStatus.LIVE:
            # Rollup rows for every covered ward are built by a worker, not in this request.
            core.emit(
                "election.opened",
                {"organization_id": election.organization_id, "election_id": election.id},
            )
    return election


def delete_election(actor: Actor, election: Election) -> None:
    """Remove an election that is still being set up (DRAFT or CONFIGURED).

    Once an election is locked it is part of the record and can no longer be deleted. A fresh
    second factor is required. Assignments, contesting parties, contestants and configuration
    issues made while setting up go with it; the removal is audited.
    """
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    require_recent_mfa(actor)
    with transaction.atomic():
        election = _locked_election(election.id)
        if election.status not in EDITABLE:
            raise ElectionNotDeletable()
        contests = list(Contest.objects.filter(election=election).values_list("id", flat=True))
        assignments = list(election.assignments.values_list("id", flat=True))
        election.assignments.all().delete()
        ConfigIssue.objects.filter(election=election).delete()
        Candidate.objects.filter(contest_id__in=contests).delete()
        Contest.objects.filter(election=election).delete()
        ElectionParty.objects.filter(election=election).delete()
        election.delete()
        audit.record(
            action="election.deleted",
            object_type="election",
            object_id=election.id,
            actor=actor,
            diff={
                "name": election.name,
                "status": election.status,
                "contests_removed": len(contests),
                "assignments_removed": len(assignments),
            },
        )


# --- Contesting parties (FR-6.3.5) -----------------------------------------------------------


def set_election_parties(actor: Actor, election: Election, party_ids: Sequence[UUID]) -> None:
    """Replace the contesting parties with `party_ids`, in that order (1, 2, 3, ...).

    A party taken off the list loses its contestants in this election, so the result form can
    never show a party that is not contesting.
    """
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    if len(set(party_ids)) != len(party_ids):
        raise ValidationError({"party_ids": ["A party can appear only once."]})
    known = set(
        Party.objects.in_organization(actor)
        .filter(id__in=list(party_ids))
        .values_list("id", flat=True)
    )
    if unknown := [str(p) for p in party_ids if p not in known]:
        raise ValidationError({"party_ids": [f"Unknown parties: {', '.join(unknown)}"]})
    with transaction.atomic():
        election = _locked_election(election.id)
        _require_editable(election)
        before = list(
            ElectionParty.objects.filter(election=election)
            .order_by("ballot_order")
            .values_list("party_id", flat=True)
        )
        if before == list(party_ids):
            return
        dropped = set(before) - set(party_ids)
        removed = list(
            Candidate.objects.filter(contest__election=election, party_id__in=dropped).values_list(
                "id", flat=True
            )
        )
        Candidate.objects.filter(id__in=removed).delete()
        Contest.objects.filter(election=election, candidates__isnull=True).delete()
        ElectionParty.objects.filter(election=election).delete()
        ElectionParty.objects.bulk_create(
            ElectionParty(
                organization_id=election.organization_id,
                election=election,
                party_id=party_id,
                ballot_order=order,
            )
            for order, party_id in enumerate(party_ids, start=1)
        )
        _bump_config(election)
        audit.record(
            action="election.parties_set",
            object_type="election",
            object_id=election.id,
            actor=actor,
            diff={
                "before": [str(p) for p in before],
                "after": [str(p) for p in party_ids],
                "contestants_removed": [str(c) for c in removed],
            },
        )


# --- Contestants (FR-6.3.2, FR-6.3.5) --------------------------------------------------------

CONTESTANT_FIELDS = ("name", "party_id", "contest_id")


def create_contestant(
    actor: Actor, election: Election, *, constituency_id: UUID, party_id: UUID, name: str
) -> Candidate:
    """Link one contesting party's candidate to a constituency. The constituency's contest is
    created with its first contestant."""
    authorize(actor, Perm.CANDIDATES_MANAGE)
    constituency = geography.constituency(actor, constituency_id)
    if (
        constituency is None
        or constituency.kind != election.election_type.constituency_kind
        or constituency.state_id != election.state_id
    ):
        raise ValidationError(
            {"constituency_id": ["Not a constituency of this election's type and state."]}
        )
    try:
        with transaction.atomic():
            election = _locked_election(election.id)
            _require_editable(election)
            if not ElectionParty.objects.filter(election=election, party_id=party_id).exists():
                raise ValidationError({"party_id": ["This party is not contesting the election."]})
            contest, _ = Contest.objects.get_or_create(
                election=election,
                constituency=constituency,
                defaults={"organization_id": election.organization_id},
            )
            candidate = Candidate.objects.create(
                organization_id=election.organization_id,
                contest=contest,
                party_id=party_id,
                name=name.strip(),
                config_version=election.config_version + 1,
            )
            _bump_config(election)
            audit.record(
                action="contestant.created",
                object_type="candidate",
                object_id=candidate.id,
                actor=actor,
                diff={
                    "election_id": election.id,
                    "constituency_id": constituency.id,
                    "after": _snapshot(candidate, CONTESTANT_FIELDS),
                },
            )
    except IntegrityError:
        raise _unique_violation(
            "party_id", "This party already has a contestant in this constituency."
        ) from None
    return selectors.candidate_for(actor, candidate.id)


def update_contestant(
    actor: Actor, candidate: Candidate, *, expected_version: int, name: str
) -> Candidate:
    """Only the name can change; a different party or constituency is a new contestant."""
    authorize(actor, Perm.CANDIDATES_MANAGE)
    with transaction.atomic():
        election = _locked_election(candidate.contest.election_id)
        _require_editable(election)
        candidate = Candidate.objects.select_for_update().get(id=candidate.id)
        check_version(expected_version, candidate.row_version)
        before = candidate.name
        candidate.name = name.strip()
        candidate.config_version = election.config_version + 1
        candidate.row_version += 1
        candidate.save()
        _bump_config(election)
        audit.record(
            action="contestant.updated",
            object_type="candidate",
            object_id=candidate.id,
            actor=actor,
            diff={"before": {"name": before}, "after": {"name": candidate.name}},
        )
    return selectors.candidate_for(actor, candidate.id)


def delete_contestant(actor: Actor, candidate: Candidate) -> None:
    authorize(actor, Perm.CANDIDATES_MANAGE)
    with transaction.atomic():
        election = _locked_election(candidate.contest.election_id)
        _require_editable(election)
        before = _snapshot(candidate, CONTESTANT_FIELDS)
        contest_id = candidate.contest_id
        candidate.delete()
        Contest.objects.filter(id=contest_id, candidates__isnull=True).delete()
        _bump_config(election)
        audit.record(
            action="contestant.deleted",
            object_type="candidate",
            object_id=candidate.id,
            actor=actor,
            diff={"before": before},
        )


# --- Configuration issues (FR-6.3.7) ---------------------------------------------------------


def record_issue(
    actor: Actor, election: Election, polling_unit: Any, *, kind: str, note: str
) -> ConfigIssue:
    """Store an agent's "party missing" / "contestant missing" report as a task for an admin.

    The caller (the results service) has already checked that the agent is assigned to the
    unit. Nothing in the configuration changes."""
    authorize(actor, Perm.RESULTS_SUBMIT)
    with transaction.atomic():
        issue = ConfigIssue.objects.create(
            organization_id=actor.organization_id,
            election=election,
            polling_unit=polling_unit,
            ward_id=polling_unit.ward_id,
            lga_id=polling_unit.lga_id,
            kind=IssueKind(kind),
            note=note.strip(),
            raised_by_id=actor.user_id,
        )
        audit.record(
            action="config_issue.raised",
            object_type="config_issue",
            object_id=issue.id,
            actor=actor,
            diff={"election_id": election.id, "polling_unit_id": polling_unit.id, "kind": kind},
        )
    return issue


def resolve_issue(actor: Actor, issue: ConfigIssue, *, note: str) -> ConfigIssue:
    authorize(actor, Perm.ELECTIONS_CONFIGURE)
    if len(note.strip()) < 3:
        raise ValidationError({"note": ["Say what was done about it."]})
    with transaction.atomic():
        issue = ConfigIssue.objects.select_for_update().get(id=issue.id)
        if issue.status != IssueStatus.OPEN:
            raise IssueAlreadyResolved()
        issue.status = IssueStatus.RESOLVED
        issue.resolution_note = note.strip()
        issue.resolved_by_id = actor.user_id
        issue.resolved_at = timezone.now()
        issue.save(update_fields=["status", "resolution_note", "resolved_by", "resolved_at"])
        audit.record(
            action="config_issue.resolved",
            object_type="config_issue",
            object_id=issue.id,
            actor=actor,
            diff={"note": issue.resolution_note},
        )
    return issue
