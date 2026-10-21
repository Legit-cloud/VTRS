"""Election-Day simulation and load test (PB-13, AC-15, DD-02, DD-06).

Creates a throwaway organization, election, officers and agents on the polling-unit directory
already in the database, then drives the real API the way the field does: agents submit from
the web app, retry, correct and occasionally send suspicious results, while dashboard users
read at the same time. Afterwards it waits for the workers to catch up, proves the rollups and
the audit chain, and prints a report.

It talks to the application in-process (Django's test client over the real WSGI stack, real
PostgreSQL, real broker and workers), so it measures the application, not the network. Run it
only against a development or staging database: it creates data and refuses otherwise.
"""

import json
import os
import random
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Membership, User, UserStatus
from apps.accounts.services.sessions import start_session
from apps.aggregation import services as aggregation
from apps.aggregation.models import Rollup, RollupDirty
from apps.assignments.models import AgentAssignment
from apps.audit import services as audit
from apps.core.crypto import blind_index
from apps.core.ids import uuid7
from apps.core.models import OutboxEvent
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election, ElectionParty, Party
from apps.geography import services as geography
from apps.geography.models import Constituency, ElectionType, PollingUnit, State
from apps.organizations.models import Organization
from apps.results.domain.versions import submission_hash
from apps.results.models import ResultVersion

# Django's marker for "no password can match": simulated agents sign in with minted tokens.
UNUSABLE = make_password(None)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * p))] * 1000, 1)


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": round(max(values) * 1000, 1) if values else 0.0,
    }


class Command(BaseCommand):
    help = "Simulate an election day against a development database and report what held."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--agents", type=int, default=300)
        parser.add_argument("--workers", type=int, default=12, help="Concurrent agents")
        parser.add_argument("--readers", type=int, default=20, help="Concurrent dashboard users")
        parser.add_argument("--correction-rate", type=float, default=0.05)
        parser.add_argument("--replay-rate", type=float, default=0.05)
        parser.add_argument("--anomaly-rate", type=float, default=0.03)
        parser.add_argument("--seed", type=int, default=None)
        parser.add_argument("--state", default=None, help="State code to simulate in")
        parser.add_argument("--json", action="store_true")

    # --- Setup ---------------------------------------------------------------------------------

    def handle(self, *args: Any, **options: Any) -> None:
        if not (settings.DEBUG or os.environ.get("VTRS_ALLOW_SIMULATION") == "1"):
            raise CommandError(
                "Refusing to run: this creates data. Use a development database, or set "
                "VTRS_ALLOW_SIMULATION=1 on a staging stack."
            )
        self.rng = random.Random(options["seed"])  # noqa: S311 - simulation data
        total = options["agents"]
        report: dict[str, Any] = {"agents": total, "workers": options["workers"]}
        world = self._setup(total, options["state"])
        report["setup_seconds"] = world["setup_seconds"]
        self.stderr.write(f"Setup done in {world['setup_seconds']}s; submitting...")

        stop_readers = threading.Event()
        read_latencies: list[float] = []
        read_errors: list[str] = []
        readers = [
            threading.Thread(
                target=self._reader, args=(world, stop_readers, read_latencies, read_errors)
            )
            for _ in range(options["readers"])
        ]
        for thread in readers:
            thread.start()

        write_latencies: list[float] = []
        errors: list[str] = []
        accepted = replays = corrections = flagged_expected = 0
        started = time.perf_counter()
        lock = threading.Lock()

        def drive(agent: dict[str, Any]) -> None:
            nonlocal accepted, replays, corrections, flagged_expected
            client = Client(SERVER_NAME="localhost")
            try:
                anomalous = self.rng.random() < options["anomaly_rate"]
                item = self._item(world, agent, anomalous=anomalous)
                outcome = self._post(client, agent, item, write_latencies, errors, lock)
                with lock:
                    accepted += int(outcome.get("status") in {"ACCEPTED", "REQUIRES_REVIEW"})
                    flagged_expected += int(anomalous)
                if self.rng.random() < options["replay_rate"]:
                    # A double tap or a retry after a dropped connection: same submission id.
                    again = self._post(client, agent, item, write_latencies, errors, lock)
                    with lock:
                        replays += int(bool(again.get("replayed")))
                if self.rng.random() < options["correction_rate"]:
                    fixed = self._item(world, agent, parent=item["version_id"], bump=3)
                    self._post(client, agent, fixed, write_latencies, errors, lock)
                    with lock:
                        corrections += 1
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=options["workers"]) as pool:
            list(pool.map(drive, world["agents"]))
        elapsed = time.perf_counter() - started
        stop_readers.set()
        for thread in readers:
            thread.join()

        report["submit"] = {
            "seconds": round(elapsed, 1),
            "accepted_results": accepted,
            "per_second": round(accepted / elapsed, 2),
            "per_hour": round(accepted / elapsed * 3600),
            "replays_sent": replays,
            "corrections_sent": corrections,
            "request_latency": _summary(write_latencies),
            "errors": errors[:5],
            "error_count": len(errors),
        }
        report["dashboard"] = {
            "readers": options["readers"],
            "latency": _summary(read_latencies),
            "error_count": len(read_errors),
            "errors": read_errors[:5],
        }

        report["consistency"] = self._settle_and_verify(world, accepted, replays)
        report["anomalies_injected"] = flagged_expected
        self._print(report, options["json"])
        failed = errors or read_errors or not report["consistency"]["ok"]
        if failed:
            raise CommandError("The simulation found problems; see the report above.")

    def _setup(self, total: int, state_code: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        # Name-only directories have no coordinates, so take the first state that can seat every
        # simulated agent at a located polling unit (or the one asked for).
        states = State.objects.order_by("inec_code")
        if state_code:
            states = states.filter(inec_code=state_code)
        if not states.exists():
            raise CommandError("Import master data first (import_master_data).")
        state, units = None, []
        for candidate in states:
            units = list(
                PollingUnit.objects.filter(state=candidate, latitude__isnull=False).order_by(
                    "inec_code"
                )[:total]
            )
            if len(units) >= total:
                state = candidate
                break
        if state is None:
            raise CommandError(
                f"No state has {total} polling units with coordinates "
                f"(the best has {len(units)}). Import a located directory or lower --agents."
            )
        run = secrets.token_hex(3)
        now = timezone.now()
        if not ElectionType.objects.filter(code="GOVERNORSHIP").exists():
            geography.load_election_types(
                json.loads((settings.BASE_DIR / "data" / "election_types.json").read_text())
            )
        if not Constituency.objects.filter(kind="STATE", state=state).exists():
            geography.derive_constituencies()
        with transaction.atomic(), system_context():
            org = Organization.objects.create(name=f"Sim {run}", status="ACTIVE")
            admin = User.objects.create_user(
                password=None,
                full_name="Sim Admin",
                email=f"sim-admin-{run}@sim.example",
                email_index=blind_index("email", f"sim-admin-{run}@sim.example"),
                status=UserStatus.ACTIVE,
            )
            admin_m = Membership.objects.create(
                user=admin, organization=org, role="PARTY_ADMIN", scope_type="ORG"
            )
            election = Election.objects.create(
                organization=org,
                name=f"Simulation {run}",
                election_type=ElectionType.objects.get(code="GOVERNORSHIP"),
                state=state,
                election_date=now.date(),
                status="LIVE",
                created_by_id=admin.id,
                config_hash="simulation",
            )
            contest = Contest.objects.create(
                organization=org,
                election=election,
                constituency=Constituency.objects.get(kind="STATE", state=state),
            )
            parties = [
                Party.objects.create(
                    organization=org, full_name=f"{a} Party", abbreviation=a, is_own=(i == 1)
                )
                for i, a in enumerate(("AAA", "BBB", "CCC"), start=1)
            ]
            ElectionParty.objects.bulk_create(
                ElectionParty(organization=org, election=election, party=p, ballot_order=i)
                for i, p in enumerate(parties, start=1)
            )
            candidates = [
                Candidate.objects.create(
                    organization=org,
                    contest=contest,
                    party=p,
                    name=f"Candidate {p.abbreviation}",
                    config_version=1,
                )
                for p in parties
            ]
            users = User.objects.bulk_create(
                User(
                    id=uuid7(),
                    password=UNUSABLE,
                    full_name=f"Agent {i}",
                    email=f"agent{i}-{run}@sim.example",
                    email_index=blind_index("email", f"agent{i}-{run}@sim.example"),
                    status=UserStatus.ACTIVE,
                )
                for i in range(total)
            )
            memberships = Membership.objects.bulk_create(
                Membership(
                    user=u,
                    organization=org,
                    role="PU_AGENT",
                    scope_type="PU",
                    scope_ids=[unit.id],
                )
                for u, unit in zip(users, units, strict=True)
            )
            AgentAssignment.objects.bulk_create(
                AgentAssignment(
                    organization=org,
                    election=election,
                    agent=u,
                    polling_unit=unit,
                    ward_id=unit.ward_id,
                    lga_id=unit.lga_id,
                    assigned_by_id=admin.id,
                )
                for u, unit in zip(users, units, strict=True)
            )
            admin_token = start_session(
                user=admin, membership=admin_m, mfa_at=now, ip=None
            ).access_token
            agents = []
            for u, m, unit in zip(users, memberships, units, strict=True):
                # As if each agent had entered their emailed sign-in code.
                token = start_session(user=u, membership=m, mfa_at=now, ip=None).access_token
                agents.append({"token": token, "pu": unit, "user_id": u.id})
        aggregation.rebuild_contest(organization_id=org.id, contest_id=contest.id)
        return {
            "org": org,
            "election": election,
            "contest": contest,
            "candidates": candidates,
            "admin_token": admin_token,
            "agents": agents,
            "setup_seconds": round(time.perf_counter() - started, 1),
        }

    # --- Traffic -----------------------------------------------------------------------------

    def _item(
        self,
        world: dict[str, Any],
        agent: dict[str, Any],
        *,
        anomalous: bool = False,
        parent: str | None = None,
        bump: int = 0,
    ) -> dict[str, Any]:
        pu = agent["pu"]
        registered = pu.registered_voters or 600
        cast = int(registered * self.rng.uniform(0.45, 0.75))
        shares = [self.rng.random() for _ in world["candidates"]]
        total_share = sum(shares)
        votes = [int(cast * s / total_share) for s in shares]
        votes[0] += cast - sum(votes) + bump
        valid = sum(votes)
        rejected = int(valid * 0.02)
        total_cast = valid + rejected
        if anomalous:
            total_cast += 25  # the sheet's totals do not reconcile: flagged, still counted
        item = {
            "version_id": str(uuid7()),
            "election_id": str(world["election"].id),
            "polling_unit_id": str(pu.id),
            "config_version": world["election"].config_version,
            "parent_version_id": parent,
            "totals": {
                "accredited": total_cast + 3,
                "rejected": rejected,
                "total_cast": total_cast,
            },
            "votes": [
                {"candidate_id": str(c.id), "votes": v}
                for c, v in zip(world["candidates"], votes, strict=True)
            ],
            "device_captured_at": (
                timezone.now() - timedelta(seconds=self.rng.randint(0, 900))
            ).isoformat(),
            "gps": {"lat": float(pu.latitude), "lng": float(pu.longitude), "accuracy_m": 9},
        }
        item = json.loads(json.dumps(item))
        item["payload_hash"] = submission_hash(item)
        return item

    def _post(
        self,
        client: Client,
        agent: dict[str, Any],
        item: dict[str, Any],
        latencies: list[float],
        errors: list[str],
        lock: threading.Lock,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        response = client.post(
            "/api/v1/submissions",
            data=json.dumps(item),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {agent['token']}",
        )
        took = time.perf_counter() - started
        with lock:
            latencies.append(took)
            if response.status_code != 200:
                errors.append(f"{response.status_code}: {response.content[:120]!r}")
                return {}
        return dict(response.json())

    def _reader(
        self,
        world: dict[str, Any],
        stop: threading.Event,
        latencies: list[float],
        errors: list[str],
    ) -> None:
        client = Client(SERVER_NAME="localhost")
        election = world["election"].id
        urls = [
            f"/api/v1/elections/{election}/dashboard",
            f"/api/v1/elections/{election}/results?level=lga",
            f"/api/v1/elections/{election}/flags/summary",
            f"/api/v1/elections/{election}/review-queue?limit=20",
        ]
        try:
            while not stop.is_set():
                for url in urls:
                    started = time.perf_counter()
                    response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {world['admin_token']}")
                    latencies.append(time.perf_counter() - started)
                    if response.status_code != 200:
                        errors.append(f"{url}: {response.status_code}")
                time.sleep(self.rng.uniform(0.05, 0.25))
        finally:
            connection.close()

    # --- Aftermath ----------------------------------------------------------------------------

    def _settle_and_verify(
        self, world: dict[str, Any], accepted: int, replays: int
    ) -> dict[str, Any]:
        contest = world["contest"]
        org = world["org"]
        started = time.perf_counter()
        deadline = started + 600
        reported = 0
        quiet_since: float | None = None
        while time.perf_counter() < deadline:
            with transaction.atomic(), system_context():
                state_row = Rollup.objects.filter(contest=contest, level="STATE").first()
                reported = state_row.reported_pus if state_row else 0
                marks = RollupDirty.objects.filter(contest=contest).count()
                backlog = OutboxEvent.objects.filter(published_at__isnull=True).count()
            self.stderr.write(
                f"  t+{time.perf_counter() - started:5.1f}s reported={reported} "
                f"marks={marks} unpublished_events={backlog}"
            ) if int(time.perf_counter() - started) % 10 == 0 else None
            idle = reported >= len(world["agents"]) and marks == 0 and backlog == 0
            if idle:
                quiet_since = quiet_since or time.perf_counter()
                if time.perf_counter() - quiet_since >= 4:  # nothing moved for a while
                    break
            else:
                quiet_since = None
            time.sleep(1)
        catch_up = round(time.perf_counter() - started, 1)

        with transaction.atomic(), system_context():
            heads = ResultVersion.objects.filter(contest=contest).count()
            distinct = (
                ResultVersion.objects.filter(contest=contest)
                .values("polling_unit_id")
                .distinct()
                .count()
            )
            contest_obj = Contest.objects.select_related("election").get(id=contest.id)
            differences = aggregation.verify_contest(contest_obj)
            while audit.seal_pending(lag_seconds=0):
                pass
            chain = audit.verify_chain()
        return {
            "ok": reported >= len(world["agents"]) and not differences and not chain,
            "worker_catch_up_seconds": catch_up,
            "polling_units_reported": reported,
            "versions_stored": heads,
            "polling_units_with_a_version": distinct,
            "accepted_results_seen_by_client": accepted,
            "rollup_differences": differences[:5],
            "audit_chain_problems": chain[:5] if chain else [],
            "organization_id": str(org.id),
        }

    def _print(self, report: dict[str, Any], as_json: bool) -> None:
        if as_json:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return
        submit, dash, cons = report["submit"], report["dashboard"], report["consistency"]
        self.stdout.write(
            f"\nSubmit: {submit['accepted_results']} results in {submit['seconds']} s = "
            f"{submit['per_second']}/s ({submit['per_hour']}/hour)\n"
            f"  request latency p50 {submit['request_latency']['p50_ms']} ms, "
            f"p95 {submit['request_latency']['p95_ms']} ms, "
            f"p99 {submit['request_latency']['p99_ms']} ms, "
            f"errors {submit['error_count']}\n"
            f"Dashboard ({dash['readers']} readers): {dash['latency']['count']} reads, "
            f"p50 {dash['latency']['p50_ms']} ms, p95 {dash['latency']['p95_ms']} ms, "
            f"p99 {dash['latency']['p99_ms']} ms, errors {dash['error_count']}\n"
            f"Consistency: workers caught up in {cons['worker_catch_up_seconds']} s; "
            f"{cons['polling_units_reported']} units reported; rollup differences "
            f"{len(cons['rollup_differences'])}; audit chain problems "
            f"{len(cons['audit_chain_problems'])}; ok={cons['ok']}"
        )
