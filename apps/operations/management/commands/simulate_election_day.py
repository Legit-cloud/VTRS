"""Election-Day simulation and load test (PB-13, AC-15, DD-02, DD-06).

Creates a throwaway organization, election, officers and agents on the polling-unit directory
already in the database, then drives the real API the way the field does: agents submit in
offline batches, retry, correct and occasionally send suspicious results, while dashboard users
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

from apps.accounts.models import Device, Membership, User, UserStatus
from apps.accounts.services.sessions import start_session
from apps.aggregation import services as aggregation
from apps.aggregation.models import Rollup, RollupDirty
from apps.assignments.models import AgentAssignment
from apps.audit import services as audit
from apps.core.crypto import blind_index
from apps.core.ids import uuid7
from apps.core.models import OutboxEvent
from apps.core.rls import system_context
from apps.elections.models import Candidate, Contest, Election
from apps.geography.models import PollingUnit, State
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
        parser.add_argument("--batch", type=int, default=1, help="Results per sync request (1-10)")
        parser.add_argument("--readers", type=int, default=20, help="Concurrent dashboard users")
        parser.add_argument("--correction-rate", type=float, default=0.05)
        parser.add_argument("--replay-rate", type=float, default=0.05)
        parser.add_argument("--anomaly-rate", type=float, default=0.03)
        parser.add_argument("--seed", type=int, default=None)
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
        world = self._setup(total)
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
        batches = [
            world["agents"][i : i + options["batch"]]
            for i in range(0, len(world["agents"]), options["batch"])
        ]
        lock = threading.Lock()

        def drive(batch: list[dict[str, Any]]) -> None:
            nonlocal accepted, replays, corrections, flagged_expected
            client = Client(SERVER_NAME="localhost")
            try:
                items, kinds = [], []
                for agent in batch:
                    anomalous = self.rng.random() < options["anomaly_rate"]
                    item = self._item(world, agent, anomalous=anomalous)
                    items.append(item)
                    kinds.append(anomalous)
                outcomes = self._post(client, batch[0], items, write_latencies, errors, lock)
                with lock:
                    accepted += sum(
                        1 for o in outcomes if o["status"] in {"SYNCED", "REQUIRES_REVIEW"}
                    )
                    flagged_expected += sum(kinds)
                if self.rng.random() < options["replay_rate"]:
                    again = self._post(client, batch[0], items, write_latencies, errors, lock)
                    with lock:
                        replays += sum(1 for o in again if o.get("replayed"))
                if self.rng.random() < options["correction_rate"]:
                    fixed = [
                        self._item(world, a, parent=i["version_id"], bump=3)
                        for a, i in zip(batch, items, strict=True)
                    ]
                    self._post(client, batch[0], fixed, write_latencies, errors, lock)
                    with lock:
                        corrections += len(fixed)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=options["workers"]) as pool:
            list(pool.map(drive, batches))
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

    def _setup(self, total: int) -> dict[str, Any]:
        started = time.perf_counter()
        state = State.objects.order_by("inec_code").first()
        if state is None:
            raise CommandError("Import master data first (import_master_data).")
        units = list(
            PollingUnit.objects.filter(state=state, latitude__isnull=False).order_by("inec_code")[
                :total
            ]
        )
        if len(units) < total:
            raise CommandError(f"Only {len(units)} polling units with coordinates; need {total}.")
        run = secrets.token_hex(3)
        now = timezone.now()
        with transaction.atomic(), system_context():
            org = Organization.objects.create(name=f"Sim {run}", status="ACTIVE")
            admin = User.objects.create_user(
                password=None,
                full_name="Sim Admin",
                email=f"sim-admin-{run}@sim.example",
                email_index=blind_index("email", f"sim-admin-{run}@sim.example"),
                status=UserStatus.ACTIVE,
                mfa_enabled=True,
            )
            admin_m = Membership.objects.create(
                user=admin, organization=org, role="PARTY_ADMIN", scope_type="ORG"
            )
            election = Election.objects.create(
                organization=org,
                name=f"Simulation {run}",
                state=state,
                election_date=now.date(),
                status="LIVE",
                created_by_id=admin.id,
                config_hash="simulation",
            )
            contest = Contest.objects.create(
                organization=org,
                election=election,
                office="GOVERNORSHIP",
                title="Governor",
                jurisdiction_level="STATE",
                jurisdiction_ids=[state.id],
            )
            candidates = [
                Candidate.objects.create(
                    organization=org,
                    contest=contest,
                    name=f"Candidate {a}",
                    party_name=a,
                    party_acronym=a,
                    ballot_order=i,
                    is_own_party=(i == 1),
                    config_version=1,
                )
                for i, a in enumerate(("AAA", "BBB", "CCC"), start=1)
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
            devices = Device.objects.bulk_create(
                Device(user=u, platform="ANDROID", app_version="1.0.0") for u in users
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
                user=admin, membership=admin_m, client="WEB", device=None, mfa_at=now, ip=None
            ).access_token
            agents = []
            for u, m, d, unit in zip(users, memberships, devices, units, strict=True):
                token = start_session(
                    user=u, membership=m, client="MOBILE", device=d, mfa_at=None, ip=None
                ).access_token
                agents.append({"token": token, "device": str(d.id), "pu": unit, "user_id": u.id})
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
        accredited = valid + rejected + 3
        if anomalous:
            accredited = max(1, valid // 2)  # more cast than accredited: over-voting
        item = {
            "version_id": str(uuid7()),
            "contest_id": str(world["contest"].id),
            "polling_unit_id": str(pu.id),
            "config_version": world["election"].config_version,
            "parent_version_id": parent,
            "totals": {
                "accredited": accredited,
                "valid": valid,
                "rejected": rejected,
                "total_cast": valid + rejected,
            },
            "votes": [
                {"candidate_id": str(c.id), "votes": v}
                for c, v in zip(world["candidates"], votes, strict=True)
            ],
            "device_captured_at": (
                timezone.now() - timedelta(seconds=self.rng.randint(0, 900))
            ).isoformat(),
            "gps": {"lat": float(pu.latitude), "lng": float(pu.longitude), "accuracy_m": 9},
            "device_id": agent["device"],
            "app_version": "1.0.0",
            "evidence": [],
        }
        item = json.loads(json.dumps(item))
        item["payload_hash"] = submission_hash(item)
        return item

    def _post(
        self,
        client: Client,
        agent: dict[str, Any],
        items: list[dict[str, Any]],
        latencies: list[float],
        errors: list[str],
        lock: threading.Lock,
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        response = client.post(
            "/api/v1/sync/submissions",
            data=json.dumps({"items": items}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {agent['token']}",
        )
        took = time.perf_counter() - started
        with lock:
            latencies.append(took)
            if response.status_code != 200:
                errors.append(f"{response.status_code}: {response.content[:120]!r}")
                return []
        return list(response.json()["items"])

    def _reader(
        self,
        world: dict[str, Any],
        stop: threading.Event,
        latencies: list[float],
        errors: list[str],
    ) -> None:
        client = Client(SERVER_NAME="localhost")
        election = world["election"].id
        contest = world["contest"].id
        urls = [
            f"/api/v1/elections/{election}/dashboard",
            f"/api/v1/contests/{contest}/results?level=lga",
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
