"""Building export files. Every builder works as the requester (their role, scope and grants,
snapshotted on the job), through the same selectors the API uses, so an export can never show
what the person could not have seen on screen."""

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from apps.aggregation import selectors as aggregation
from apps.aggregation.domain.tally import PROVISIONAL_NOTICE
from apps.anomalies import selectors as anomalies
from apps.anomalies.routing import RULE_TITLES
from apps.audit.models import AuditEvent
from apps.core.domain.actor import Actor
from apps.elections import selectors as elections
from apps.evidence.domain.rules import ALLOWED_TYPES, EvidenceStatus
from apps.evidence.models import CustodyEvent, EvidenceFile
from apps.evidence.storage import get_storage
from apps.results.models import ResultVersion

from .domain import pack as pack_rules
from .domain.formats import ExportFormat, columns_for_candidates, safe_row
from .errors import PackTooLarge
from .models import ExportJob

CHUNK = 500


@dataclass(frozen=True)
class Built:
    label: str
    row_count: int | None = None
    file_count: int | None = None
    manifest_sha256: str = ""


# --- Tabular writers ------------------------------------------------------------------------


class CsvTable:
    def __init__(self, path: str) -> None:
        # A byte-order mark makes Excel read UTF-8 names correctly.
        self._file = open(path, "w", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._file)

    def header(self, columns: Sequence[str]) -> None:
        self._writer.writerow(columns)

    def row(self, values: Iterable[Any]) -> None:
        self._writer.writerow(safe_row(values))

    def close(self, about: dict[str, Any]) -> None:
        self._file.close()


class XlsxTable:
    def __init__(self, path: str, title: str) -> None:
        from openpyxl import Workbook

        self._path = path
        self._wb = Workbook(write_only=True)
        self._sheet = self._wb.create_sheet(title[:31])

    def header(self, columns: Sequence[str]) -> None:
        self._sheet.append(list(columns))

    def row(self, values: Iterable[Any]) -> None:
        self._sheet.append(safe_row(values))

    def close(self, about: dict[str, Any]) -> None:
        sheet = self._wb.create_sheet("About")
        sheet.append(["Field", "Value"])
        for key, value in about.items():
            sheet.append(safe_row([key, value if isinstance(value, int | float) else str(value)]))
        self._wb.save(self._path)


def _table(job: ExportJob, path: str, title: str) -> CsvTable | XlsxTable:
    return XlsxTable(path, title) if job.format == ExportFormat.XLSX else CsvTable(path)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


# --- Results --------------------------------------------------------------------------------


def _walk(
    actor: Actor, election: Any, measure: Any, level: str, parent_id: UUID | None
) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]]:
    """Yield (lga_row, ward_row, row) for every area at `level` inside the actor's scope."""

    def fetch(lvl: str | None, parent: UUID | None) -> list[dict[str, Any]]:
        return aggregation.results(actor, election, level=lvl, parent_id=parent, measure=measure)[
            "rows"
        ]

    top = fetch(None, None)
    if not top:
        return
    lgas: list[dict[str, Any]]
    if top[0]["level"] == "STATE":
        lgas = fetch("lga", None)
    elif top[0]["level"] == "LGA":
        lgas = top
    else:
        lgas = []
    if parent_id is not None:
        lgas = [r for r in lgas if r["area_id"] == parent_id] or lgas
    if level == "lga":
        for lga in lgas:
            yield lga, None, lga
        return
    ward_rows: list[tuple[dict[str, Any] | None, dict[str, Any]]] = []
    if top[0]["level"] == "WARD":
        ward_rows = [(None, w) for w in top]
    else:
        for lga in lgas:
            ward_rows.extend((lga, w) for w in fetch("ward", lga["area_id"]))
    for parent_lga, ward in ward_rows:
        if ward is None:
            continue
        if level == "ward":
            yield parent_lga or {}, ward, ward
            continue
        for unit in fetch("pu", ward["area_id"]):
            yield parent_lga or {}, ward, unit


def _leader(position: dict[str, Any], abbreviations: dict[Any, str]) -> str:
    if position["status"] == "TIED":
        return "TIED: " + ", ".join(abbreviations.get(p, "") for p in position["leading_party_ids"])
    return position["leader_abbreviation"] or ""


def build_results(job: ExportJob, actor: Actor, path: str) -> Built:
    """One row per area (or polling unit) with one vote column per contesting party, in the
    election's party order. Votes are summed by party id, never by name."""
    params = job.params
    election = elections.election_for(actor, UUID(params["election_id"]))
    parties = list(elections.election_parties(actor, election))
    abbreviations = {p.party_id: p.party.abbreviation for p in parties}
    level = params.get("level", "pu")
    measure = aggregation.parse_measure(params.get("measure"), election)
    table = _table(job, path, "Results")
    base = ["lga_code", "lga_name", "ward_code", "ward_name"]
    if level == "pu":
        base += ["pu_code", "pu_name", "registered_voters", "status", "verification"]
    else:
        base += ["expected_pus", "reported_pus", "verified_pus", "review_pus", "reported_pct"]
    base += ["accredited", "valid", "rejected", "total_cast"]
    table.header(
        columns_for_candidates(
            [*base, "leader_status", "leader", "margin", "open_flags", "updated_at"],
            [p.party.abbreviation for p in parties],
        )
    )
    count = 0
    for lga, ward, row in _walk(actor, election, measure, level, _uuid(params.get("parent_id"))):
        by_party = {v["party_id"]: v["votes"] for v in row["votes"]}
        totals = row["totals"]
        values: list[Any] = [
            lga.get("area_code", ""),
            lga.get("area_name", ""),
            (ward or {}).get("area_code", ""),
            (ward or {}).get("area_name", ""),
        ]
        if level == "pu":
            values += [
                row["area_code"],
                row["area_name"],
                row["registered_voters"],
                row.get("status", ""),
                "VERIFIED" if row.get("verified") else "UNVERIFIED",
            ]
        else:
            values += [
                row["expected_pus"],
                row["reported_pus"],
                row["verified_pus"],
                row["review_pus"],
                row["reported_pct"],
            ]
        values += [totals.get(k) for k in ("accredited", "valid", "rejected", "total_cast")]
        values += [
            row["position"]["status"],
            _leader(row["position"], abbreviations),
            row["position"]["margin"],
            row["open_flags"],
            _iso(row["updated_at"]),
            *(by_party.get(p.party_id, 0) for p in parties),
        ]
        table.row(values)
        count += 1
    table.close(
        {
            "notice": PROVISIONAL_NOTICE,
            "election": election.name,
            "parties": [
                {"party_id": str(p.party_id), "abbreviation": p.party.abbreviation} for p in parties
            ],
            "level": level,
            "measure": measure.value,
            "generated_at": timezone.now().isoformat(),
            "rows": count,
        }
    )
    return Built(label=election.name, row_count=count)


# --- Flags ----------------------------------------------------------------------------------


def build_flags(job: ExportJob, actor: Actor, path: str) -> Built:
    params = job.params
    election = elections.election_for(actor, UUID(params["election_id"]))
    qs = anomalies.flags_for(actor).filter(election_id=election.id)
    for name in ("status", "severity", "rule_code"):
        if params.get(name):
            qs = qs.filter(**{name: params[name]})
    table = _table(job, path, "Flags")
    table.header(
        [
            "raised_at", "severity", "status", "rule_code", "title", "lga_code", "lga_name",
            "ward_code", "ward_name", "pu_code", "pu_name", "result_version_id",
            "escalation_level", "acknowledged_at", "resolved_at", "resolution_note", "flag_id",
        ]
    )  # fmt: skip
    count = 0
    for flag in qs.order_by("created_at", "id").iterator(chunk_size=CHUNK):
        table.row(
            [
                _iso(flag.created_at), flag.severity, flag.status, flag.rule_code,
                RULE_TITLES.get(flag.rule_code, flag.rule_code), flag.lga.inec_code,
                flag.lga.name, flag.ward.inec_code, flag.ward.name,
                flag.polling_unit.inec_code, flag.polling_unit.name,
                flag.result_version_id or "", flag.escalation_level, _iso(flag.acknowledged_at),
                _iso(flag.resolved_at), flag.resolution_note, flag.id,
            ]
        )  # fmt: skip
        count += 1
    table.close(
        {
            "election": election.name,
            "generated_at": timezone.now().isoformat(),
            "rows": count,
            "filters": json.dumps({k: v for k, v in params.items() if k != "election_id"}),
        }
    )
    return Built(label=election.name, row_count=count)


# --- Audit ----------------------------------------------------------------------------------


def build_audit(job: ExportJob, actor: Actor, path: str) -> Built:
    params = job.params
    since = datetime.fromisoformat(params["since"])
    until = datetime.fromisoformat(params["until"])
    qs = AuditEvent.objects.filter(
        organization_id=actor.organization_id, at__gte=since, at__lt=until
    )
    if params.get("action"):
        qs = qs.filter(action__startswith=params["action"])
    table = CsvTable(path)
    table.header(
        ["at", "action", "object_type", "object_id", "actor_id", "actor_role", "ip",
         "request_id", "event_id", "details"]
    )  # fmt: skip
    count = 0
    for event in qs.order_by("at", "id").iterator(chunk_size=CHUNK):
        table.row(
            [
                _iso(event.at), event.action, event.object_type, event.object_id,
                event.actor_id or "", event.actor_role, event.ip or "", event.request_id,
                event.id, json.dumps(event.diff, sort_keys=True, ensure_ascii=False),
            ]
        )  # fmt: skip
        count += 1
    table.close({})
    return Built(label=f"{since:%Y%m%d}-{until:%Y%m%d}", row_count=count)


# --- Evidence pack ----------------------------------------------------------------------------


def pack_selection(actor: Actor, params: dict[str, Any]) -> Any:
    qs = (
        EvidenceFile.objects.for_actor(actor)
        .filter(
            status=EvidenceStatus.VERIFIED,
            result_version__pu_result__election_id=UUID(params["election_id"]),
        )
        .select_related("polling_unit", "ward", "lga", "result_version", "result_version__contest")
        .order_by("polling_unit__inec_code", "result_version__version_no", "created_at", "id")
    )
    for name, lookup in (
        ("contest_id", "result_version__contest_id"),
        ("lga_id", "lga_id"),
        ("ward_id", "ward_id"),
        ("polling_unit_id", "polling_unit_id"),
    ):
        if params.get(name):
            qs = qs.filter(**{lookup: UUID(params[name])})
    return qs


def build_pack(job: ExportJob, actor: Actor, path: str) -> tuple[Built, list[EvidenceFile]]:
    election = elections.election_for(actor, UUID(job.params["election_id"]))
    files = list(pack_selection(actor, job.params))
    max_files = settings.VTRS_EVIDENCE_PACK_MAX_FILES
    max_bytes = settings.VTRS_EVIDENCE_PACK_MAX_BYTES
    if len(files) > max_files:
        raise PackTooLarge(f"{len(files)} files selected; the limit is {max_files}. Narrow it.")
    total = sum(f.size for f in files)
    if total > max_bytes:
        raise PackTooLarge(f"{total} bytes selected; the limit is {max_bytes}. Narrow it.")

    custody: dict[UUID, list[CustodyEvent]] = defaultdict(list)
    for event in CustodyEvent.objects.filter(evidence_file_id__in=[f.id for f in files]).order_by(
        "evidence_file_id", "seq"
    ):
        custody[event.evidence_file_id].append(event)

    storage = get_storage()
    entries: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    included: list[EvidenceFile] = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for evidence in files:
            data = storage.read(evidence.object_key)
            digest = hashlib.sha256(data).hexdigest()
            expected = evidence.sha256_server or evidence.sha256_client
            if digest != expected:
                excluded.append(
                    {
                        "evidence_id": str(evidence.id),
                        "reason": "stored object does not match its hash",
                    }
                )
                continue
            version = evidence.result_version
            member = pack_rules.evidence_path(
                evidence.polling_unit.inec_code,
                version.version_no,
                evidence.kind,
                evidence.id,
                ALLOWED_TYPES[evidence.mime],
            )
            archive.writestr(member, data, compress_type=zipfile.ZIP_STORED)  # photos are packed
            events = [
                {
                    "evidence_file_id": str(e.evidence_file_id),
                    "seq": e.seq,
                    "event_type": e.event_type,
                    "actor_id": str(e.actor_id) if e.actor_id else None,
                    "at": e.at.isoformat(),
                    "ip": e.ip,
                    "details": e.details,
                    "prev_hash": e.prev_hash,
                    "hash": e.hash,
                }
                for e in custody[evidence.id]
            ]
            entries.append(
                {
                    "path": member,
                    "evidence_id": str(evidence.id),
                    "kind": evidence.kind,
                    "mime": evidence.mime,
                    "size": evidence.size,
                    "sha256": digest,
                    "sha256_declared_by_device": evidence.sha256_client,
                    "uploaded_at": _iso(evidence.uploaded_at),
                    "verified_at": _iso(evidence.verified_at),
                    "polling_unit": {
                        "id": str(evidence.polling_unit_id),
                        "code": evidence.polling_unit.inec_code,
                        "name": evidence.polling_unit.name,
                        "ward": evidence.ward.name,
                        "lga": evidence.lga.name,
                    },
                    "version": {
                        "id": str(version.id),
                        "number": version.version_no,
                        "state": version.state,
                        "constituency": version.contest.constituency.name,
                    },
                    "custody": events,
                }
            )
            included.append(evidence)

        version_ids = sorted({UUID(e["version"]["id"]) for e in entries}, key=str)
        archive.writestr("results.csv", _pack_results_csv(version_ids))
        manifest = {
            "pack_id": str(job.id),
            "generated_at": timezone.now().isoformat(),
            "organization_id": str(job.organization_id),
            "election": {"id": str(election.id), "name": election.name},
            "filters": {k: v for k, v in job.params.items() if k != "election_id"},
            "notice": pack_rules.PACK_NOTICE,
            "disclaimer": pack_rules.PACK_DISCLAIMER,
            "files": entries,
            "excluded": excluded,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False).encode(
            "utf-8"
        )
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("verify.py", pack_rules.VERIFY_SCRIPT)
        archive.writestr("README.txt", pack_rules.readme())
    return (
        Built(
            label=election.name,
            row_count=len(version_ids),
            file_count=len(entries),
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        ),
        included,
    )


def _pack_results_csv(version_ids: list[UUID]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        ["pu_code", "pu_name", "constituency", "version_no", "state", "accredited", "valid",
         "rejected", "total_cast", "votes", "server_received_at", "device_captured_at",
         "payload_hash", "version_id"]
    )  # fmt: skip
    versions = (
        ResultVersion.objects.filter(id__in=version_ids)
        .select_related("polling_unit", "contest__constituency")
        .prefetch_related("vote_lines__candidate__party")
        .order_by("polling_unit__inec_code", "version_no")
    )
    for v in versions:
        votes = "; ".join(
            f"{line.candidate.party.abbreviation}={line.votes}"
            for line in sorted(v.vote_lines.all(), key=lambda x: x.candidate.party.abbreviation)
        )
        writer.writerow(
            safe_row(
                [
                    v.polling_unit.inec_code, v.polling_unit.name, v.contest.constituency.name,
                    v.version_no,
                    v.state, v.accredited, v.valid, v.rejected, v.total_cast, votes,
                    _iso(v.server_received_at), _iso(v.device_captured_at), v.payload_hash, v.id,
                ]
            )
        )  # fmt: skip
    return buffer.getvalue()
