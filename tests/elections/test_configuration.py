"""AC-02, AC-16: an authorized admin configures the party master list, an election with a type,
its contesting parties in a fixed order and one contestant per party and constituency
(FR-6.3.1 - FR-6.3.7); FR-6.3.3 lock."""

import hashlib
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.services.sessions import start_session
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role
from apps.core.rls import system_context
from apps.elections.models import Party
from apps.evidence.storage import get_storage
from apps.geography.models import Constituency, Lga, State

from ..factories import load_reference_data
from ..results.conftest import jpeg_bytes

pytestmark = pytest.mark.django_db
KEY = iter(range(1, 10_000))


@pytest.fixture
def state():
    load_reference_data(lgas=3, wards=6, polling_units=12, seed=3)
    return State.objects.get()


@pytest.fixture
def admin(make_member):
    return make_member(Role.PARTY_ADMIN)


@pytest.fixture
def client(admin, client_as):
    return client_as(admin)


def _post(client, url, body=None):
    return client.post(url, body or {}, format="json", HTTP_IDEMPOTENCY_KEY=f"k-{next(KEY)}")


def _party(client, abbreviation, own=False):
    response = _post(
        client,
        "/api/v1/parties",
        {"full_name": f"{abbreviation} Party", "abbreviation": abbreviation, "is_own": own},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _election(client, state, election_type="GOVERNORSHIP", **extra):
    body = {
        "name": f"Oyo {election_type.title()} 2027",
        "election_type": election_type,
        "state_id": str(state.id),
        "election_date": "2027-03-11",
    }
    response = _post(client, "/api/v1/elections", {**body, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def _contesting(client, election_id, parties):
    response = client.put(
        f"/api/v1/elections/{election_id}/parties",
        {"party_ids": [p["id"] for p in parties]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _state_constituency(state):
    return Constituency.objects.get(kind="STATE", state=state)


def _contestant(client, election_id, constituency, party, name=None):
    return _post(
        client,
        f"/api/v1/elections/{election_id}/contestants",
        {
            "constituency_id": str(constituency.id),
            "party_id": party["id"],
            "name": name or f"Candidate {party['abbreviation']}",
        },
    )


def _ready(client, state):
    aaa, bbb = _party(client, "aaa", own=True), _party(client, "BBB")
    election = _election(client, state)
    _contesting(client, election["id"], [aaa, bbb])
    constituency = _state_constituency(state)
    for party in (aaa, bbb):
        assert _contestant(client, election["id"], constituency, party).status_code == 201
    return election, [aaa, bbb]


def test_party_master_list(client):
    party = _party(client, " apc ")
    assert (party["abbreviation"], party["full_name"], party["logo_url"]) == (
        "APC",
        "apc  Party",
        None,
    )
    duplicate = _post(client, "/api/v1/parties", {"full_name": "Other", "abbreviation": "Apc"})
    assert duplicate.status_code == 400 and duplicate.json()["errors"]["abbreviation"]
    _party(client, "PDP", own=True)
    second_own = _post(
        client, "/api/v1/parties", {"full_name": "LP", "abbreviation": "LP", "is_own": True}
    )
    assert second_own.status_code == 400  # one own party per organization
    listed = client.get("/api/v1/parties").json()
    assert [p["abbreviation"] for p in listed] == ["APC", "PDP"]
    assert AuditEvent.objects.filter(action="party.created").count() == 2


def test_only_admins_manage_parties(client, admin, make_member, client_as):
    party = _party(client, "ADC")
    for role, _scope in (
        (Role.LGA_OFFICER, None),
        (Role.WARD_OFFICER, None),
        (Role.PU_AGENT, None),
    ):
        other = client_as(make_member(role, organization=admin.organization))
        assert other.get("/api/v1/parties").status_code == 200  # everyone may read the list
        assert (
            _post(other, "/api/v1/parties", {"full_name": "X", "abbreviation": "X"}).status_code
            == 403
        )
        assert other.delete(f"/api/v1/parties/{party['id']}").status_code == 403
    # Another organization's list is separate and invisible.
    outsider = client_as(make_member(Role.PARTY_ADMIN))
    assert outsider.get("/api/v1/parties").json() == []
    assert outsider.get(f"/api/v1/parties/{party['id']}").status_code == 404


def test_party_logo_upload(client):
    party = _party(client, "LP")
    logo = jpeg_bytes(size=(64, 64))
    digest = hashlib.sha256(logo).hexdigest()
    requested = client.post(
        f"/api/v1/parties/{party['id']}/logo",
        {"mime": "image/jpeg", "size": len(logo), "sha256": digest},
        format="json",
    )
    assert requested.status_code == 200, requested.json()
    key = requested.json()["upload"]["url"].removeprefix("local://")
    get_storage().write(key, logo, mime="image/jpeg")
    done = client.post(
        f"/api/v1/parties/{party['id']}/logo/complete",
        {"mime": "image/jpeg", "sha256": digest},
        format="json",
    )
    assert done.status_code == 200, done.json()
    assert done.json()["logo_url"]
    # A file that is not what it claims is refused.
    bad = client.post(
        f"/api/v1/parties/{party['id']}/logo",
        {"mime": "image/svg+xml", "size": 10, "sha256": digest},
        format="json",
    )
    assert bad.status_code == 400
    removed = client.delete(f"/api/v1/parties/{party['id']}/logo")
    assert removed.json()["logo_url"] is None


def test_configure_lock_and_run_an_election(admin, client, state, make_member, client_as):
    election, (aaa, bbb) = _ready(client, state)
    eid = election["id"]
    detail = client.get(f"/api/v1/elections/{eid}")
    assert detail.json()["election_type"] == "GOVERNORSHIP"
    assert detail.json()["constituency_kind"] == "STATE"
    assert detail.json()["config_version"] == 4  # contesting list + two contestants
    assert detail["ETag"] == f'"{detail.json()["row_version"]}"'

    contesting = client.get(f"/api/v1/elections/{eid}/parties").json()
    assert [(p["ballot_order"], p["abbreviation"]) for p in contesting] == [(1, "AAA"), (2, "BBB")]
    contestants = client.get(f"/api/v1/elections/{eid}/contestants").json()
    assert [(c["party_abbreviation"], c["name"]) for c in contestants] == [
        ("AAA", "Candidate AAA"),
        ("BBB", "Candidate BBB"),
    ]

    configured = _post(client, f"/api/v1/elections/{eid}/transition", {"to": "CONFIGURED"})
    assert configured.json()["status"] == "CONFIGURED"
    locked = _post(client, f"/api/v1/elections/{eid}/lock")
    assert locked.status_code == 200, locked.json()
    assert locked.json()["status"] == "LOCKED"
    assert len(locked.json()["config_hash"]) == 64

    # Locked: no more party or contestant changes (FR-6.3.3).
    ccc = _party(client, "CCC")
    blocked = client.put(
        f"/api/v1/elections/{eid}/parties",
        {"party_ids": [aaa["id"], bbb["id"], ccc["id"]]},
        format="json",
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "election_locked"
    contestant_id = contestants[0]["id"]
    assert client.delete(f"/api/v1/contestants/{contestant_id}").json()["code"] == "election_locked"
    # A party a locked election uses keeps its name.
    url = f"/api/v1/parties/{aaa['id']}"
    renamed = client.patch(
        url, {"abbreviation": "ZZZ"}, format="json", HTTP_IF_MATCH=client.get(url)["ETag"]
    )
    assert renamed.json()["code"] == "party_locked"
    assert client.delete(url).json()["code"] == "party_in_use"

    live = _post(client, f"/api/v1/elections/{eid}/transition", {"to": "LIVE"})
    assert live.json()["status"] == "LIVE" and live.json()["opened_at"]
    closed = _post(client, f"/api/v1/elections/{eid}/transition", {"to": "CLOSED"})
    assert closed.json()["status"] == "CLOSED"
    reopen = _post(client, f"/api/v1/elections/{eid}/transition", {"to": "LIVE"})
    assert reopen.json()["code"] == "invalid_transition"

    actions = list(
        AuditEvent.objects.filter(object_id=eid, action="election.status_changed")
        .order_by("id")
        .values_list("diff", flat=True)
    )
    assert [a["to"] for a in actions] == ["CONFIGURED", "LOCKED", "LIVE", "CLOSED"]
    assert actions[1]["config_hash"] == locked.json()["config_hash"]

    # Every member of the organization can read the configuration; nobody else can.
    officer = client_as(make_member(Role.WARD_OFFICER, organization=make_member().organization))
    assert officer.get(f"/api/v1/elections/{eid}").status_code == 404
    same_org_officer = client_as(make_member(Role.WARD_OFFICER, organization=admin.organization))
    assert same_org_officer.get(f"/api/v1/elections/{eid}").status_code == 200


def test_lock_needs_a_complete_configuration(client, state):
    aaa = _party(client, "AAA")
    election = _election(client, state)
    _contesting(client, election["id"], [aaa])
    _contestant(client, election["id"], _state_constituency(state), aaa)
    response = _post(client, f"/api/v1/elections/{election['id']}/transition", {"to": "CONFIGURED"})
    assert response.status_code == 409
    assert response.json()["code"] == "configuration_incomplete"
    problems = response.json()["errors"]["problems"]
    assert any("at least two contesting parties" in p for p in problems)
    assert any("at least two parties" in p for p in problems)
    direct = _post(client, f"/api/v1/elections/{election['id']}/lock")
    assert direct.json()["code"] == "invalid_transition"  # DRAFT cannot jump to LOCKED


def test_lock_needs_a_fresh_second_factor(admin, client_as, state, client):
    election, _ = _ready(client, state)
    _post(client, f"/api/v1/elections/{election['id']}/transition", {"to": "CONFIGURED"})
    stale = start_session(
        user=admin.user,
        membership=admin.membership,
        mfa_at=timezone.now() - timedelta(hours=1),
        ip=None,
    )
    stale_client = client_as(admin)
    stale_client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale.access_token}")
    response = _post(stale_client, f"/api/v1/elections/{election['id']}/lock")
    assert response.json()["code"] == "mfa_step_up_required"


def test_edits_need_the_current_etag(client, state):
    election = _election(client, state)
    url = f"/api/v1/elections/{election['id']}"
    missing = client.patch(url, {"name": "Renamed"}, format="json")
    assert missing.status_code == 428
    stale = client.patch(url, {"name": "Renamed"}, format="json", HTTP_IF_MATCH='"999"')
    assert stale.status_code == 412
    ok = client.patch(
        url, {"name": "Renamed"}, format="json", HTTP_IF_MATCH=client.get(url)["ETag"]
    )
    assert ok.status_code == 200 and ok.json()["name"] == "Renamed"
    again = client.patch(
        url, {"name": "Other"}, format="json", HTTP_IF_MATCH=f'"{election["row_version"]}"'
    )
    assert again.status_code == 412


def test_election_type_is_configuration(client, state):
    types = client.get("/api/v1/geography/election-types").json()
    assert {t["code"]: t["constituency_kind"] for t in types} == {
        "PRESIDENTIAL": "STATE",
        "GOVERNORSHIP": "STATE",
        "SENATORIAL": "SENATORIAL_DISTRICT",
        "HOUSE_OF_REPRESENTATIVES": "FEDERAL_CONSTITUENCY",
        "STATE_ASSEMBLY": "STATE_CONSTITUENCY",
        "LGA_CHAIRMANSHIP": "LGA",
        "COUNCILLORSHIP": "WARD",
    }
    unknown = _post(
        client,
        "/api/v1/elections",
        {
            "name": "Nope",
            "election_type": "MAYORAL",
            "state_id": str(state.id),
            "election_date": "2027-03-11",
        },
    )
    assert unknown.status_code == 400 and unknown.json()["errors"]["election_type"]


def test_contestant_rules(client, state):
    """One contestant per party and constituency; the party must be contesting; the
    constituency must be of the election type's kind and in its state."""
    aaa, bbb, idle = _party(client, "AAA"), _party(client, "BBB"), _party(client, "IDL")
    election = _election(client, state, election_type="LGA_CHAIRMANSHIP")
    eid = election["id"]
    _contesting(client, eid, [aaa, bbb])
    lga = Lga.objects.order_by("inec_code").first()
    lga_seat = Constituency.objects.get(kind="LGA", code=lga.inec_code)

    assert _contestant(client, eid, lga_seat, aaa).status_code == 201
    twice = _contestant(client, eid, lga_seat, aaa, name="Someone else")
    assert twice.status_code == 400 and twice.json()["errors"]["party_id"]
    not_contesting = _contestant(client, eid, lga_seat, idle)
    assert not_contesting.status_code == 400 and not_contesting.json()["errors"]["party_id"]
    wrong_kind = _contestant(client, eid, _state_constituency(state), bbb)
    assert wrong_kind.status_code == 400 and wrong_kind.json()["errors"]["constituency_id"]

    # The same party may stand in another LGA with another candidate.
    other_lga = Lga.objects.order_by("inec_code").last()
    other_seat = Constituency.objects.get(kind="LGA", code=other_lga.inec_code)
    assert _contestant(client, eid, other_seat, aaa, name="Second AAA").status_code == 201
    per_seat = client.get(f"/api/v1/elections/{eid}/contestants?constituency_id={lga_seat.id}")
    assert [c["name"] for c in per_seat.json()] == ["Candidate AAA"]


def test_taking_a_party_off_the_election_removes_its_contestants(client, state):
    election, (_aaa, bbb) = _ready(client, state)
    eid = election["id"]
    remaining = _contesting(client, eid, [bbb])
    assert [p["abbreviation"] for p in remaining] == ["BBB"]
    contestants = client.get(f"/api/v1/elections/{eid}/contestants").json()
    assert [c["party_abbreviation"] for c in contestants] == ["BBB"]
    assert AuditEvent.objects.get(action="election.parties_set", diff__after=[bbb["id"]])


def test_reordering_contesting_parties(client, state):
    election, (aaa, bbb) = _ready(client, state)
    reordered = _contesting(client, election["id"], [bbb, aaa])
    assert [(p["ballot_order"], p["abbreviation"]) for p in reordered] == [(1, "BBB"), (2, "AAA")]
    duplicate = client.put(
        f"/api/v1/elections/{election['id']}/parties",
        {"party_ids": [aaa["id"], aaa["id"]]},
        format="json",
    )
    assert duplicate.status_code == 400


def test_contestant_changes_are_versioned_and_audited(client, state):
    election, _ = _ready(client, state)
    version = client.get(f"/api/v1/elections/{election['id']}").json()["config_version"]
    contestant = client.get(f"/api/v1/elections/{election['id']}/contestants").json()[0]
    url = f"/api/v1/contestants/{contestant['id']}"
    etag = client.get(url)["ETag"]
    changed = client.patch(url, {"name": "New Name"}, format="json", HTTP_IF_MATCH=etag)
    assert changed.status_code == 200, changed.json()
    assert changed.json()["config_version"] == version + 1
    assert client.get(f"/api/v1/elections/{election['id']}").json()["config_version"] == version + 1
    event = AuditEvent.objects.get(action="contestant.updated")
    assert (event.diff["before"]["name"], event.diff["after"]["name"]) == (
        "Candidate AAA",
        "New Name",
    )
    assert client.delete(url).status_code == 204
    assert AuditEvent.objects.filter(action="contestant.deleted").exists()


def test_creates_are_idempotent(client, state):
    body = {
        "name": "Once",
        "election_type": "GOVERNORSHIP",
        "state_id": str(state.id),
        "election_date": "2027-03-11",
    }
    first = client.post("/api/v1/elections", body, format="json", HTTP_IDEMPOTENCY_KEY="same")
    again = client.post("/api/v1/elections", body, format="json", HTTP_IDEMPOTENCY_KEY="same")
    assert first.json() == again.json()
    assert len(client.get("/api/v1/elections").json()["results"]) == 1
    duplicate = client.post(
        "/api/v1/elections", body, format="json", HTTP_IDEMPOTENCY_KEY="different"
    )
    assert duplicate.json()["errors"]["name"]


def test_a_draft_election_can_be_deleted_with_what_was_set_up_under_it(client, state):
    election, _ = _ready(client, state)
    url = f"/api/v1/elections/{election['id']}"
    response = client.delete(url)
    assert response.status_code == 204
    assert client.get(url).status_code == 404
    event = AuditEvent.objects.filter(action="election.deleted").get()
    assert event.diff["contests_removed"] == 1
    # Parties are master data: they outlive the election.
    with system_context():
        assert Party.objects.count() == 2
    assert _election(client, state)["name"] == election["name"]


def test_a_locked_election_cannot_be_deleted(client, state):
    election, _ = _ready(client, state)
    _post(client, f"/api/v1/elections/{election['id']}/transition", {"to": "CONFIGURED"})
    assert _post(client, f"/api/v1/elections/{election['id']}/lock").status_code == 200
    response = client.delete(f"/api/v1/elections/{election['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "election_not_deletable"
    assert client.get(f"/api/v1/elections/{election['id']}").status_code == 200


def test_deleting_an_election_needs_a_fresh_second_factor(admin, client_as, state, client):
    election = _election(client, state)
    stale = start_session(
        user=admin.user,
        membership=admin.membership,
        mfa_at=timezone.now() - timedelta(hours=1),
        ip=None,
    )
    stale_client = client_as(admin)
    stale_client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale.access_token}")
    response = stale_client.delete(f"/api/v1/elections/{election['id']}")
    assert response.json()["code"] == "mfa_step_up_required"
    assert client.get(f"/api/v1/elections/{election['id']}").status_code == 200
