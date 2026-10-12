"""Authorization matrix (spec sections 8 and 20; AC-04, AC-14, DD-03).

Every protected endpoint x every role x four targets: in scope, a sibling ward in the same LGA,
a ward in another LGA, and another organization. Expected outcome:
  - the role lacks the permission          -> 403
  - the target belongs to another tenant   -> 404 (never 403: existence is not revealed)
  - otherwise                              -> the endpoint's success status
`test_every_protected_route_is_in_the_matrix` fails when a protected route+method has no row.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.models import Device, Invitation
from apps.anomalies.models import AnomalyFlag
from apps.assignments.models import AgentAssignment
from apps.core.api.permissions import required_permission_for
from apps.core.authz import AUTHENTICATED
from apps.core.domain.actor import ScopeKind
from apps.core.domain.permissions import Perm, Role, effective_permissions
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election
from apps.evidence.models import EvidenceFile
from apps.geography.domain.synthetic import synthetic_master_data
from apps.geography.models import Lga, PollingUnit, State, Ward
from apps.geography.services import import_master_data
from apps.notifications.models import Notification
from apps.organizations.models import Organization
from apps.reports.models import ExportJob
from apps.results.models import PuResult, ResultVersion

pytestmark = pytest.mark.django_db

RELATIONS = ("in_scope", "sibling_ward", "other_lga", "other_org")


@dataclass
class World:
    org: Any
    other_org: Any
    state: State
    lga_a: Lga
    # ward per relation, from the point of view of the scoped actors (LGA A / ward A1)
    wards: dict[str, Ward]
    make_member: Callable[..., Any]

    def org_for(self, relation: str) -> Any:
        return self.other_org if relation == "other_org" else self.org

    def pu(self, relation: str) -> PollingUnit:
        return PollingUnit.objects.filter(ward=self.wards[relation]).order_by("inec_code").first()


@pytest.fixture
def world(make_org, make_member) -> World:
    import_master_data(synthetic_master_data(lgas=2, wards=4, polling_units=8, seed=3))
    lga_a, lga_b = Lga.objects.order_by("inec_code")
    a1, a2 = Ward.objects.filter(lga=lga_a).order_by("inec_code")
    b1 = Ward.objects.filter(lga=lga_b).order_by("inec_code").first()
    return World(
        org=make_org("Our Party"),
        other_org=make_org("Their Party"),
        state=State.objects.get(),
        lga_a=lga_a,
        wards={"in_scope": a1, "sibling_ward": a2, "other_lga": b1, "other_org": a1},
        make_member=make_member,
    )


def _actor(w: World, role: Role):
    scope = {
        Role.PARTY_ADMIN: [],
        Role.LGA_OFFICER: [w.lga_a.id],
        Role.WARD_OFFICER: [w.wards["in_scope"].id],
        Role.PU_AGENT: [w.pu("in_scope").id],
        Role.PLATFORM_ADMIN: [],
    }[role]
    return w.make_member(role, scope_ids=scope, organization=w.org)


# --- Targets: objects placed in a given relation to the actor ------------------------------


def _member(w: World, relation: str):
    return w.make_member(
        Role.WARD_OFFICER, scope_ids=[w.wards[relation].id], organization=w.org_for(relation)
    )


def _invitation(w: World, relation: str):
    member = _member(w, relation)
    with system_context():
        return Invitation.objects.create(
            organization=member.organization,
            role=Role.WARD_OFFICER,
            scope_type=ScopeKind.WARD,
            scope_ids=[w.wards[relation].id],
            email="invitee@example.org",
            token_hash=uuid7().hex * 2,
            expires_at="2999-01-01T00:00:00Z",
            created_by_id=member.user.id,
        )


def _device(w: World, relation: str):
    agent = w.make_member(
        Role.PU_AGENT, scope_ids=[w.pu(relation).id], organization=w.org_for(relation)
    )
    return Device.objects.create(user=agent.user, platform="ANDROID", app_version="1.0.0")


def _election(w: World, relation: str, status: str = "DRAFT") -> Election:
    with system_context():
        election = Election.objects.create(
            organization=w.org_for(relation),
            name=f"Election {uuid7().hex[-12:]}",
            state=w.state,
            election_date="2027-03-01",
            status=status,
            created_by_id=uuid7(),
        )
        contest = Contest.objects.create(
            organization=w.org_for(relation),
            election=election,
            office="GOVERNORSHIP",
            title="Governor",
            jurisdiction_level="STATE",
            jurisdiction_ids=[w.state.id],
        )
        for order, acronym in ((1, "AAA"), (2, "BBB")):
            Candidate.objects.create(
                organization=w.org_for(relation),
                contest=contest,
                name=f"Candidate {acronym}",
                party_name=f"Party {acronym}",
                party_acronym=acronym,
                ballot_order=order,
                config_version=1,
            )
    return election


def _configured_election(w: World, relation: str) -> Election:
    return _election(w, relation, status="CONFIGURED")


def _contest(w: World, relation: str) -> Contest:
    election = _election(w, relation)
    with system_context():
        return election.contests.get()


def _candidate(w: World, relation: str) -> Candidate:
    contest = _contest(w, relation)
    with system_context():
        return Candidate.objects.filter(contest=contest).order_by("ballot_order").first()


def _assignment(w: World, relation: str) -> AgentAssignment:
    pu = w.pu(relation)
    agent = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=w.org_for(relation))
    election = _election(w, relation)
    with system_context():
        return AgentAssignment.objects.create(
            organization=w.org_for(relation),
            election=election,
            agent=agent.user,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            assigned_by_id=uuid7(),
        )


def _new_assignment_body(t: Any, w: World) -> dict:
    pu = w.pu("in_scope")
    agent = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=w.org)
    return {
        "election_id": str(_election(w, "in_scope").id),
        "agent_id": str(agent.user.id),
        "polling_unit_id": str(pu.id),
    }


def _if_match(t: Any) -> dict:
    return {"HTTP_IF_MATCH": f'"{t.row_version}"'}


def _evidence(w: World, relation: str) -> EvidenceFile:
    """A verified photo uploaded by *another* agent at the relation's polling unit."""
    pu = w.pu(relation)
    org = w.org_for(relation)
    uploader = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=org)
    election = _election(w, relation)
    with system_context():
        contest = election.contests.get()
        pu_result = PuResult.objects.create(
            organization=org,
            election=election,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            state=w.state,
        )
        version = ResultVersion.objects.create(
            id=uuid7(),
            organization=org,
            pu_result=pu_result,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            version_no=1,
            valid=10,
            device_captured_at=timezone.now(),
            server_received_at=timezone.now(),
            submitted_by=uploader.user,
            app_version="1.0.0",
            config_version=1,
            payload_hash="0" * 64,
            state="SUBMITTED",
        )
        evidence_id = uuid7()
        return EvidenceFile.objects.create(
            id=evidence_id,
            organization=org,
            result_version=version,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            uploaded_by=uploader.user,
            kind="EC8A",
            object_key=f"org/{org.id}/{evidence_id}.jpg",
            size=10,
            mime="image/jpeg",
            sha256_client="0" * 64,
            status="VERIFIED",
        )


def _closed_election(w: World, relation: str) -> Election:
    return _election(w, relation, status="CLOSED")


def _result_version(w: World, relation: str) -> ResultVersion:
    """The counting version of a polling unit in the relation, in an election with review on."""
    pu = w.pu(relation)
    org = w.org_for(relation)
    submitter = w.make_member(Role.PU_AGENT, scope_ids=[pu.id], organization=org)
    election = _election(w, relation, status="LIVE")
    with system_context():
        Election.objects.filter(id=election.id).update(review_enabled=True)
        contest = election.contests.get()
        pu_result = PuResult.objects.create(
            organization=org,
            election=election,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            state=w.state,
            status="SUBMITTED",
            version_count=1,
        )
        version = ResultVersion.objects.create(
            id=uuid7(),
            organization=org,
            pu_result=pu_result,
            contest=contest,
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            version_no=1,
            valid=10,
            device_captured_at=timezone.now(),
            server_received_at=timezone.now(),
            submitted_by=submitter.user,
            app_version="1.0.0",
            config_version=1,
            payload_hash="0" * 64,
            state="SUBMITTED",
        )
        PuResult.objects.filter(id=pu_result.id).update(head_version=version)
        return version


def _flag(w: World, relation: str, status: str = "OPEN") -> AnomalyFlag:
    pu = w.pu(relation)
    org = w.org_for(relation)
    election = _election(w, relation, status="LIVE")
    with system_context():
        return AnomalyFlag.objects.create(
            organization=org,
            election=election,
            contest=election.contests.get(),
            polling_unit=pu,
            ward=pu.ward,
            lga=pu.lga,
            rule_code="GPS_OUT_OF_GEOFENCE",
            severity="HIGH",
            status=status,
        )


def _closed_flag(w: World, relation: str) -> AnomalyFlag:
    return _flag(w, relation, status="RESOLVED")


def _notification(w: World, relation: str) -> Notification:
    """Somebody else's notification: nobody may read it through their own inbox."""
    owner = w.make_member(
        Role.WARD_OFFICER, scope_ids=[w.wards[relation].id], organization=w.org_for(relation)
    )
    with system_context():
        return Notification.objects.create(
            organization=w.org_for(relation),
            user=owner.user,
            kind="SYSTEM",
            title="Private",
            body="Private",
        )


def _export_job(w: World, relation: str) -> ExportJob:
    """An export somebody else in the relation's organization asked for."""
    owner = w.make_member(
        Role.WARD_OFFICER, scope_ids=[w.wards[relation].id], organization=w.org_for(relation)
    )
    with system_context():
        return ExportJob.objects.create(
            organization=w.org_for(relation),
            requested_by=owner.user,
            kind="RESULTS",
            format="CSV",
            actor_role="WARD_OFFICER",
            scope_kind="WARD",
            scope_ids=[w.wards[relation].id],
            status="READY",
        )


def _fresh_org(status: str):
    def make(w: World, relation: str):
        with system_context():
            return Organization.objects.create(name=f"Org {uuid7().hex[-8:]}", status=status)

    return make


def _every_org(role: Role, relation: str) -> bool:
    """Platform operators see every party; the permission is the only gate."""
    return True


def _admin_in_org(role: Role, relation: str) -> bool:
    return role is Role.PARTY_ADMIN and relation != "other_org"


def _never(role: Role, relation: str) -> bool:
    return False


def _review_visible(role: Role, relation: str) -> bool:
    """Admins review anywhere in the organization; ward officers only in their own ward."""
    if role is Role.PARTY_ADMIN:
        return relation != "other_org"
    return role is Role.WARD_OFFICER and relation == "in_scope"


def _oversight_visible(role: Role, relation: str) -> bool:
    """Dashboard reads narrow to the actor's geography (LGA A, ward A1)."""
    if relation == "other_org":
        return False
    if role is Role.PARTY_ADMIN:
        return True
    if role is Role.LGA_OFFICER:
        return relation in {"in_scope", "sibling_ward"}
    return relation == "in_scope"


@dataclass(frozen=True)
class Endpoint:
    route: str
    method: str
    perm: Perm | str
    target: Callable[[World, str], Any] | None = None
    kwargs: Callable[[Any], dict] = lambda t: {}
    body: Callable[[Any, World], dict] = lambda t, w: {}
    headers: Callable[[Any], dict] = lambda t: {}
    query: dict = None  # type: ignore[assignment]
    ok: int = 200
    # For endpoints with their own visibility rules (e.g. agents see only their own uploads):
    # (role, relation) -> visible. Roles that hold the permission but can't see get 404.
    visible: Callable[[Role, str], bool] | None = None


_user = {"kwargs": lambda t: {"user_id": t.user.id}}
_election_kw = {"kwargs": lambda t: {"election_id": t.id}}
_contest_kw = {"kwargs": lambda t: {"contest_id": t.id}}
_candidate_kw = {"kwargs": lambda t: {"candidate_id": t.id}}
_flag_kw = {"kwargs": lambda t: {"flag_id": t.id}}

ENDPOINTS = [
    # accounts
    Endpoint("me", "get", AUTHENTICATED),
    Endpoint("users", "get", Perm.USERS_MANAGE),
    Endpoint("invitations", "get", Perm.USERS_MANAGE),
    Endpoint(
        "invitations",
        "post",
        Perm.USERS_MANAGE,
        body=lambda t, w: {
            "role": "WARD_OFFICER",
            "scope_ids": [str(w.wards["in_scope"].id)],
            "email": f"new-{uuid7().hex[-12:]}@example.org",
        },
        ok=201,
    ),
    Endpoint("user-detail", "get", Perm.USERS_MANAGE, _member, **_user),
    Endpoint("user-deactivate", "post", Perm.USERS_MANAGE, _member, **_user),
    Endpoint(
        "user-membership",
        "put",
        Perm.USERS_MANAGE,
        _member,
        body=lambda t, w: {
            "role": "WARD_OFFICER",
            "scope_ids": [str(i) for i in t.membership.scope_ids],
        },
        **_user,
    ),
    Endpoint(
        "user-device-revoke",
        "post",
        Perm.USERS_MANAGE,
        _device,
        kwargs=lambda t: {"user_id": t.user_id, "device_id": t.id},
    ),
    Endpoint(
        "invitation-revoke",
        "post",
        Perm.USERS_MANAGE,
        _invitation,
        kwargs=lambda t: {"invitation_id": t.id},
    ),
    # geography
    Endpoint("geography-lgas", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("geography-wards", "get", Perm.GEOGRAPHY_VIEW),
    Endpoint("geography-polling-units", "get", Perm.GEOGRAPHY_VIEW),
    # elections
    Endpoint("elections", "get", AUTHENTICATED),
    Endpoint(
        "elections",
        "post",
        Perm.ELECTIONS_CONFIGURE,
        body=lambda t, w: {
            "name": f"New {uuid7().hex[-12:]}",
            "state_id": str(w.state.id),
            "election_date": "2027-03-01",
        },
        ok=201,
    ),
    Endpoint("election-detail", "get", AUTHENTICATED, _election, **_election_kw),
    Endpoint(
        "election-detail",
        "patch",
        Perm.ELECTIONS_CONFIGURE,
        _election,
        body=lambda t, w: {"name": f"Renamed {uuid7().hex[-12:]}"},
        headers=_if_match,
        **_election_kw,
    ),
    Endpoint(
        "election-detail", "delete", Perm.ELECTIONS_CONFIGURE, _election, ok=204, **_election_kw
    ),
    Endpoint(
        "election-transition",
        "post",
        Perm.ELECTIONS_CONFIGURE,
        _election,
        body=lambda t, w: {"to": "CONFIGURED"},
        **_election_kw,
    ),
    Endpoint(
        "election-lock", "post", Perm.ELECTIONS_CONFIGURE, _configured_election, **_election_kw
    ),
    Endpoint("election-contests", "get", AUTHENTICATED, _election, **_election_kw),
    Endpoint(
        "election-contests",
        "post",
        Perm.ELECTIONS_CONFIGURE,
        _election,
        body=lambda t, w: {
            "office": "STATE_ASSEMBLY",
            "title": "Assembly",
            "jurisdiction_level": "LGA",
            "jurisdiction_ids": [str(w.lga_a.id)],
        },
        ok=201,
        **_election_kw,
    ),
    Endpoint("contest-detail", "get", AUTHENTICATED, _contest, **_contest_kw),
    Endpoint(
        "contest-detail",
        "patch",
        Perm.ELECTIONS_CONFIGURE,
        _contest,
        body=lambda t, w: {"title": "Governor (renamed)"},
        headers=_if_match,
        **_contest_kw,
    ),
    Endpoint("contest-detail", "delete", Perm.ELECTIONS_CONFIGURE, _contest, ok=204, **_contest_kw),
    Endpoint("contest-candidates", "get", AUTHENTICATED, _contest, **_contest_kw),
    Endpoint(
        "contest-candidates",
        "post",
        Perm.CANDIDATES_MANAGE,
        _contest,
        body=lambda t, w: {
            "name": "Third",
            "party_name": "Party C",
            "party_acronym": "CCC",
            "ballot_order": 3,
        },
        ok=201,
        **_contest_kw,
    ),
    Endpoint("candidate-detail", "get", AUTHENTICATED, _candidate, **_candidate_kw),
    Endpoint(
        "candidate-detail",
        "patch",
        Perm.CANDIDATES_MANAGE,
        _candidate,
        body=lambda t, w: {"name": "Renamed Candidate"},
        headers=_if_match,
        **_candidate_kw,
    ),
    Endpoint(
        "candidate-detail", "delete", Perm.CANDIDATES_MANAGE, _candidate, ok=204, **_candidate_kw
    ),
    # assignments
    Endpoint("assignments", "get", Perm.ASSIGNMENTS_MANAGE),
    Endpoint("assignments", "post", Perm.ASSIGNMENTS_MANAGE, body=_new_assignment_body, ok=201),
    Endpoint(
        "assignment-revoke",
        "post",
        Perm.ASSIGNMENTS_MANAGE,
        _assignment,
        kwargs=lambda t: {"assignment_id": t.id},
    ),
    Endpoint("my-assignments", "get", Perm.RESULTS_SUBMIT),
    # results and evidence
    Endpoint("sync-submissions", "post", Perm.RESULTS_SUBMIT, body=lambda t, w: {"items": [{}]}),
    Endpoint("sync-status", "get", Perm.RESULTS_SUBMIT, query={"ids": str(uuid7())}),
    Endpoint(
        "evidence-uploads",
        "post",
        Perm.RESULTS_SUBMIT,
        _evidence,
        body=lambda t, w: {
            "version_id": str(t.result_version_id),
            "evidence_id": str(uuid7()),
            "kind": "EC8A",
            "size": 10,
            "mime": "image/jpeg",
            "sha256": "0" * 64,
        },
        visible=_never,  # someone else's submission
    ),
    Endpoint(
        "evidence-complete",
        "post",
        Perm.RESULTS_SUBMIT,
        _evidence,
        kwargs=lambda t: {"evidence_id": t.id},
        visible=_never,  # someone else's upload
    ),
    Endpoint(
        "evidence-download-url",
        "post",
        Perm.EVIDENCE_VIEW,
        _evidence,
        kwargs=lambda t: {"evidence_id": t.id},
        visible=_admin_in_org,  # agents hold evidence.view only for their own uploads
    ),
    # aggregation, review and history
    Endpoint(
        "result-review",
        "post",
        Perm.RESULTS_REVIEW,
        _result_version,
        body=lambda t, w: {"decision": "APPROVED"},
        kwargs=lambda t: {"version_id": t.id},
        visible=_review_visible,
    ),
    Endpoint("review-queue", "get", Perm.RESULTS_REVIEW, _election, **_election_kw),
    Endpoint(
        "pu-history",
        "get",
        Perm.DASHBOARD_VIEW,
        _result_version,
        kwargs=lambda t: {"contest_id": t.contest_id, "polling_unit_id": t.polling_unit_id},
        visible=_oversight_visible,
    ),
    Endpoint("election-dashboard", "get", Perm.DASHBOARD_VIEW, _election, **_election_kw),
    Endpoint("contest-results", "get", Perm.DASHBOARD_VIEW, _contest, **_contest_kw),
    Endpoint("contest-coverage-timeline", "get", Perm.DASHBOARD_VIEW, _contest, **_contest_kw),
    Endpoint("election-reconciliation", "get", Perm.ELECTIONS_CONFIGURE, _election, **_election_kw),
    Endpoint(
        "election-reconcile", "post", Perm.ELECTIONS_CONFIGURE, _closed_election, **_election_kw
    ),
    # anomalies: triage and notifications
    Endpoint("election-flags", "get", Perm.ANOMALIES_VIEW, _election, **_election_kw),
    Endpoint("election-flags-summary", "get", Perm.ANOMALIES_VIEW, _election, **_election_kw),
    Endpoint(
        "flag-detail", "get", Perm.ANOMALIES_VIEW, _flag, visible=_oversight_visible, **_flag_kw
    ),
    Endpoint(
        "flag-acknowledge",
        "post",
        Perm.ANOMALIES_VIEW,
        _flag,
        visible=_oversight_visible,
        **_flag_kw,
    ),
    Endpoint(
        "flag-comment",
        "post",
        Perm.ANOMALIES_VIEW,
        _flag,
        body=lambda t, w: {"note": "Looking into it"},
        visible=_oversight_visible,
        **_flag_kw,
    ),
    Endpoint(
        "flag-assign",
        "post",
        Perm.ANOMALIES_RESOLVE,
        _flag,
        body=lambda t, w: {"assignee_id": None},
        visible=_oversight_visible,
        **_flag_kw,
    ),
    Endpoint(
        "flag-resolve",
        "post",
        Perm.ANOMALIES_RESOLVE,
        _flag,
        body=lambda t, w: {"outcome": "RESOLVED", "note": "Checked on site"},
        visible=_oversight_visible,
        **_flag_kw,
    ),
    Endpoint(
        "flag-reopen",
        "post",
        Perm.ANOMALIES_RESOLVE,
        _closed_flag,
        body=lambda t, w: {"note": "New information"},
        visible=_oversight_visible,
        **_flag_kw,
    ),
    # reports, audit, operations
    Endpoint("exports", "get", AUTHENTICATED),
    Endpoint(
        "export-detail",
        "get",
        AUTHENTICATED,
        _export_job,
        kwargs=lambda t: {"job_id": t.id},
        visible=_admin_in_org,  # your own jobs, or everyone's if you are the admin
    ),
    Endpoint("audit-events", "get", Perm.AUDIT_VIEW),
    Endpoint("admin-health", "get", Perm.SYSTEM_VIEW),
    Endpoint("admin-data-quality", "get", Perm.SYSTEM_VIEW),
    Endpoint("election-analytics", "get", Perm.DASHBOARD_VIEW, _election, **_election_kw),
    Endpoint("alert-policy", "get", Perm.ALERTS_CONFIGURE),
    Endpoint(
        "alert-policy",
        "put",
        Perm.ALERTS_CONFIGURE,
        body=lambda t, w: {"matrix": {"HIGH": {"ack_minutes": 25}}},
    ),
    Endpoint("alert-policy", "delete", Perm.ALERTS_CONFIGURE),
    # platform operators
    Endpoint("platform-overview", "get", Perm.PLATFORM_MANAGE),
    Endpoint("platform-orgs", "get", Perm.PLATFORM_MANAGE),
    Endpoint("platform-verification-queue", "get", Perm.PLATFORM_MANAGE),
    Endpoint("platform-elections", "get", Perm.PLATFORM_MANAGE),
    Endpoint("platform-master-data", "get", Perm.PLATFORM_MANAGE),
    Endpoint("platform-master-data-search", "get", Perm.PLATFORM_MANAGE, query={"q": "ab"}),
    Endpoint("platform-messaging", "get", Perm.PLATFORM_MANAGE),
    Endpoint("platform-audit", "get", Perm.PLATFORM_MANAGE),
    Endpoint(
        "platform-messaging-test",
        "post",
        Perm.PLATFORM_MANAGE,
        body=lambda t, w: {"channel": "EMAIL"},
    ),
    Endpoint(
        "platform-org-detail",
        "get",
        Perm.PLATFORM_MANAGE,
        lambda w, rel: w.org_for(rel),
        kwargs=lambda t: {"organization_id": t.id},
        visible=_every_org,
    ),
    Endpoint(
        "platform-org-approve",
        "post",
        Perm.PLATFORM_MANAGE,
        _fresh_org("PENDING_APPROVAL"),
        kwargs=lambda t: {"organization_id": t.id},
        visible=_every_org,
    ),
    Endpoint(
        "platform-org-reject",
        "post",
        Perm.PLATFORM_MANAGE,
        _fresh_org("PENDING_APPROVAL"),
        body=lambda t, w: {"reason": "Documents do not match"},
        kwargs=lambda t: {"organization_id": t.id},
        visible=_every_org,
    ),
    Endpoint(
        "platform-org-suspend",
        "post",
        Perm.PLATFORM_MANAGE,
        _fresh_org("ACTIVE"),
        body=lambda t, w: {"reason": "Misuse of agent accounts"},
        kwargs=lambda t: {"organization_id": t.id},
        visible=_every_org,
    ),
    Endpoint(
        "platform-org-reinstate",
        "post",
        Perm.PLATFORM_MANAGE,
        _fresh_org("SUSPENDED"),
        kwargs=lambda t: {"organization_id": t.id},
        visible=_every_org,
    ),
    Endpoint("my-notifications", "get", AUTHENTICATED),
    Endpoint("my-notifications-unread", "get", AUTHENTICATED),
    Endpoint("my-notifications-read-all", "post", AUTHENTICATED),
    Endpoint(
        "my-notification-read",
        "post",
        AUTHENTICATED,
        _notification,
        kwargs=lambda t: {"notification_id": t.id},
        visible=_never,  # one's own inbox only
    ),
]

# Self-service routes that act only on the caller's own session; covered by their own tests.
SELF_SERVICE = {
    ("auth-logout", "POST"),
    ("auth-totp-setup", "POST"),
    ("auth-totp-confirm", "POST"),
    ("auth-step-up", "POST"),
    # Needs a session opened on a registered device; covered in tests/anomalies.
    ("my-push-token", "PUT"),
    # Each kind of export has its own permissions, checked in the service; covered in
    # tests/reports.
    ("exports", "POST"),
    ("export-download-url", "POST"),
    # Multipart uploads; covered in tests/platform_admin.
    ("platform-master-data-preview", "POST"),
    ("platform-master-data-import", "POST"),
}


def _has(role: Role, perm: Perm | str) -> bool:
    return perm == AUTHENTICATED or Perm(perm) in effective_permissions(role)


def _expected(endpoint: Endpoint, role: Role, relation: str) -> int:
    if not _has(role, endpoint.perm):
        return 403
    if endpoint.visible is not None:
        return endpoint.ok if endpoint.visible(role, relation) else 404
    if relation == "other_org":
        return 404
    return endpoint.ok


CASES = [
    pytest.param(e, role, rel, id=f"{e.method}:{e.route}:{role.value}:{rel}")
    for e in ENDPOINTS
    for role in Role
    for rel in (RELATIONS if e.target else ("collection",))
]


@pytest.mark.parametrize(("endpoint", "role", "relation"), CASES)
def test_matrix(world, client_as, endpoint, role, relation):
    actor = _actor(world, role)
    target = endpoint.target(world, relation) if endpoint.target else None
    url = reverse(endpoint.route, kwargs=endpoint.kwargs(target))
    client = client_as(actor)
    call = getattr(client, endpoint.method)
    headers = endpoint.headers(target) if target is not None else {}
    if endpoint.method in {"get", "delete"}:
        response = call(url, endpoint.query or {}, **headers)
    else:
        body = endpoint.body(target, world) if _has(role, endpoint.perm) else {}
        response = call(url, body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid7()), **headers)
    expected = _expected(endpoint, role, relation)
    detail = response.json() if response.content else None
    assert response.status_code == expected, detail


def test_collections_never_leak_other_tenants(world, client_as):
    admin = _actor(world, Role.PARTY_ADMIN)
    theirs = _member(world, "other_org")
    _invitation(world, "other_org")
    _election(world, "other_org")
    _assignment(world, "other_org")
    client = client_as(admin)
    users = {r["user_id"] for r in client.get(reverse("users")).json()["results"]}
    assert str(theirs.user.id) not in users
    assert client.get(reverse("invitations")).json()["results"] == []
    assert client.get(reverse("elections")).json()["results"] == []
    assert client.get(reverse("assignments")).json()["results"] == []


def _protected(patterns):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _protected(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            view = getattr(pattern.callback, "cls", None)
            if view is None or getattr(view, "public", False):
                continue
            for method in view.http_method_names:
                if method in {"options", "head"} or not hasattr(view, method):
                    continue
                if required_permission_for(view, method.upper()):
                    yield pattern.name, method.upper()


def test_every_protected_route_is_in_the_matrix():
    covered = {(e.route, e.method.upper()) for e in ENDPOINTS} | SELF_SERVICE
    missing = set(_protected(get_resolver().url_patterns)) - covered
    assert not missing, f"Add these routes to the authorization matrix: {sorted(missing)}"


def test_matrix_permissions_match_the_views():
    """The matrix's expectations must agree with what each view actually declares."""
    resolver = get_resolver()
    for endpoint in ENDPOINTS:
        match = resolver.resolve(reverse(endpoint.route, kwargs=_dummy_kwargs(endpoint)))
        declared = required_permission_for(match.func.cls, endpoint.method.upper())
        assert declared == endpoint.perm, (endpoint.route, endpoint.method, declared)


def _dummy_kwargs(endpoint: Endpoint) -> dict:
    pattern_kwargs = {
        "user_id",
        "device_id",
        "invitation_id",
        "election_id",
        "contest_id",
        "candidate_id",
        "assignment_id",
        "evidence_id",
        "version_id",
        "polling_unit_id",
        "flag_id",
        "notification_id",
        "job_id",
        "organization_id",
    }
    route = next(
        p for p in _flatten(get_resolver().url_patterns) if p.name == endpoint.route
    ).pattern.converters
    return {name: uuid7() for name in route if name in pattern_kwargs}


def _flatten(patterns):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _flatten(pattern.url_patterns)
        else:
            yield pattern
