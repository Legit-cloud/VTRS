"""AC-02: an authorized admin configures an election and its candidate list; FR-6.3.3 lock."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.services.sessions import start_session
from apps.audit.models import AuditEvent
from apps.core.domain.permissions import Role
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, State
from apps.geography.services import import_master_data

pytestmark = pytest.mark.django_db
KEY = iter(range(1, 10_000))


@pytest.fixture
def state():
    import_master_data(synthetic_master_data(lgas=3, wards=6, polling_units=12))
    return State.objects.get()


@pytest.fixture
def admin(make_member):
    return make_member(Role.PARTY_ADMIN)


@pytest.fixture
def client(admin, client_as):
    return client_as(admin)


def _post(client, url, body=None):
    return client.post(url, body or {}, format="json", HTTP_IDEMPOTENCY_KEY=f"k-{next(KEY)}")


def _election(client, state, **extra):
    body = {
        "name": "Oyo Governorship 2027",
        "state_id": str(state.id),
        "election_date": "2027-03-11",
    }
    response = _post(client, "/api/v1/elections", {**body, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def _contest(client, election_id, state, title="Governor"):
    response = _post(
        client,
        f"/api/v1/elections/{election_id}/contests",
        {
            "office": "GOVERNORSHIP",
            "title": title,
            "jurisdiction_level": "STATE",
            "jurisdiction_ids": [str(state.id)],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _candidate(client, contest_id, order, acronym, own=False):
    response = _post(
        client,
        f"/api/v1/contests/{contest_id}/candidates",
        {
            "name": f"Candidate {acronym}",
            "party_name": f"Party {acronym}",
            "party_acronym": acronym,
            "ballot_order": order,
            "is_own_party": own,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _ready(client, state):
    election = _election(client, state)
    contest = _contest(client, election["id"], state)
    _candidate(client, contest["id"], 1, "aaa", own=True)
    _candidate(client, contest["id"], 2, "BBB")
    return election, contest


def test_configure_lock_and_run_an_election(admin, client, state, make_member, client_as):
    election, contest = _ready(client, state)
    eid = election["id"]
    detail = client.get(f"/api/v1/elections/{eid}")
    assert detail.json()["config_version"] == 4  # contest + two candidates
    assert detail["ETag"] == f'"{detail.json()["row_version"]}"'

    candidates = client.get(f"/api/v1/contests/{contest['id']}/candidates").json()
    assert [(c["ballot_order"], c["party_acronym"]) for c in candidates] == [(1, "AAA"), (2, "BBB")]

    configured = _post(client, f"/api/v1/elections/{eid}/transition", {"to": "CONFIGURED"})
    assert configured.json()["status"] == "CONFIGURED"
    locked = _post(client, f"/api/v1/elections/{eid}/lock")
    assert locked.status_code == 200, locked.json()
    assert locked.json()["status"] == "LOCKED"
    assert len(locked.json()["config_hash"]) == 64

    # Locked: no more contest or candidate changes (FR-6.3.3).
    blocked = _post(
        client,
        f"/api/v1/contests/{contest['id']}/candidates",
        {"name": "Late", "party_name": "Late Party", "party_acronym": "LTE", "ballot_order": 3},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "election_locked"
    assert client.delete(f"/api/v1/contests/{contest['id']}").json()["code"] == "election_locked"

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
    election = _election(client, state)
    contest = _contest(client, election["id"], state)
    _candidate(client, contest["id"], 1, "AAA")
    response = _post(client, f"/api/v1/elections/{election['id']}/transition", {"to": "CONFIGURED"})
    assert response.status_code == 409
    assert response.json()["code"] == "configuration_incomplete"
    assert any("at least two candidates" in p for p in response.json()["errors"]["problems"])
    direct = _post(client, f"/api/v1/elections/{election['id']}/lock")
    assert direct.json()["code"] == "invalid_transition"  # DRAFT cannot jump to LOCKED


def test_lock_needs_a_fresh_second_factor(admin, client_as, state, client):
    election, _ = _ready(client, state)
    _post(client, f"/api/v1/elections/{election['id']}/transition", {"to": "CONFIGURED"})
    stale = start_session(
        user=admin.user,
        membership=admin.membership,
        client="WEB",
        device=None,
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
    # The old ETag is now stale: a second admin editing from the same read loses.
    again = client.patch(
        url, {"name": "Other"}, format="json", HTTP_IF_MATCH=f'"{election["row_version"]}"'
    )
    assert again.status_code == 412


def test_candidate_rules(client, state):
    election = _election(client, state)
    contest = _contest(client, election["id"], state)
    _candidate(client, contest["id"], 1, "AAA", own=True)
    url = f"/api/v1/contests/{contest['id']}/candidates"
    same_order = _post(
        client, url, {"name": "X", "party_name": "X", "party_acronym": "XXX", "ballot_order": 1}
    )
    same_party = _post(
        client, url, {"name": "X", "party_name": "X", "party_acronym": "aaa", "ballot_order": 5}
    )
    second_own = _post(
        client,
        url,
        {
            "name": "X",
            "party_name": "X",
            "party_acronym": "YYY",
            "ballot_order": 6,
            "is_own_party": True,
        },
    )
    for response in (same_order, same_party, second_own):
        assert response.status_code == 400
        assert response.json()["errors"]["ballot_order"]


def test_contest_jurisdiction_must_be_inside_the_state(client, state, make_org):
    election = _election(client, state)
    lgas = list(Lga.objects.values_list("id", flat=True))
    url = f"/api/v1/elections/{election['id']}/contests"
    senatorial = _post(
        client,
        url,
        {
            "office": "SENATORIAL",
            "title": "Oyo Central",
            "jurisdiction_level": "LGA",
            "jurisdiction_ids": [str(i) for i in lgas[:2]],
        },
    )
    assert senatorial.status_code == 201
    unknown = _post(
        client,
        url,
        {
            "office": "SENATORIAL",
            "title": "Nowhere",
            "jurisdiction_level": "LGA",
            "jurisdiction_ids": ["0190a6a0-0000-7000-8000-000000000000"],
        },
    )
    assert "jurisdiction_ids" in unknown.json()["errors"]
    bad_sheet = _post(
        client,
        url,
        {
            "office": "OTHER",
            "title": "Sheet",
            "jurisdiction_level": "STATE",
            "jurisdiction_ids": [str(state.id)],
            "sheet_fields": ["accredited"],
        },
    )
    assert "sheet_fields" in bad_sheet.json()["errors"]


def test_config_changes_are_versioned_and_audited(client, state):
    election, contest = _ready(client, state)
    version = client.get(f"/api/v1/elections/{election['id']}").json()["config_version"]
    url = f"/api/v1/candidates/{_first_candidate(client, contest)['id']}"
    etag = client.get(url)["ETag"]
    changed = client.patch(url, {"name": "New Name"}, format="json", HTTP_IF_MATCH=etag)
    assert changed.json()["config_version"] == version + 1
    assert client.get(f"/api/v1/elections/{election['id']}").json()["config_version"] == version + 1
    event = AuditEvent.objects.get(action="candidate.updated")
    assert event.diff["before"]["name"] == "Candidate aaa"
    assert event.diff["after"]["name"] == "New Name"

    assert client.delete(url).status_code == 204
    assert AuditEvent.objects.filter(action="candidate.deleted").exists()


def _first_candidate(client, contest):
    return client.get(f"/api/v1/contests/{contest['id']}/candidates").json()[0]


def test_creates_are_idempotent(client, state):
    body = {"name": "Once", "state_id": str(state.id), "election_date": "2027-03-11"}
    first = client.post("/api/v1/elections", body, format="json", HTTP_IDEMPOTENCY_KEY="same")
    again = client.post("/api/v1/elections", body, format="json", HTTP_IDEMPOTENCY_KEY="same")
    assert first.json() == again.json()
    assert len(client.get("/api/v1/elections").json()["results"]) == 1
    duplicate = client.post(
        "/api/v1/elections", body, format="json", HTTP_IDEMPOTENCY_KEY="different"
    )
    assert duplicate.json()["errors"]["name"]
