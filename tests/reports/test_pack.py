"""Evidence packs (FR-6.10.2, FR-6.10.3, FR-6.10.5, FR-6.10.6, AC-12)."""

import hashlib
import io
import json
import subprocess
import sys
import zipfile

import pytest

from apps.core.domain.permissions import Perm, Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.evidence import services as evidence_services
from apps.evidence.models import CustodyEvent, EvidenceFile
from apps.reports.models import ExportJob

from ..anomalies.helpers import noise_photo, submit_with_photo

pytestmark = pytest.mark.django_db


def _request(client, field, **extra):
    body = {
        "kind": "EVIDENCE_PACK",
        "format": "ZIP",
        "election_id": str(field.election.id),
        **extra,
    }
    response = client.post(
        "/api/v1/exports", body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid7())
    )
    assert response.status_code == 202, response.content
    with system_context():
        return ExportJob.objects.get(id=response.json()["id"])


@pytest.fixture
def photographed(field_):
    f = field_
    f.photos = {
        "a": noise_photo(11),
        "b": noise_photo(12),
        "c": noise_photo(13),
    }
    f.out_a = submit_with_photo(f, f.pus_of(f.wards[0])[0], f.photos["a"])
    f.out_b = submit_with_photo(f, f.pus_of(f.wards[1])[0], f.photos["b"])
    f.out_c = submit_with_photo(f, f.pus_of(f.wards[2])[0], f.photos["c"])  # the other LGA
    return f


def _zip(storage, job) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(storage.read(job.object_key)))


def test_a_pack_carries_the_photos_a_manifest_and_a_verifier(photographed, storage):
    f = photographed
    job = _request(f.admin_client(), f)
    assert job.status == "READY", job.error
    assert job.file_count == 3 and job.row_count == 3
    archive = _zip(storage, job)
    names = set(archive.namelist())
    assert {"manifest.json", "results.csv", "verify.py", "README.txt"} <= names
    assert len([n for n in names if n.startswith("evidence/")]) == 3

    manifest = json.loads(archive.read("manifest.json"))
    assert "does not guarantee legal admissibility" in manifest["disclaimer"]
    assert "not an official" in manifest["notice"]
    assert len(manifest["files"]) == 3
    for entry in manifest["files"]:
        data = archive.read(entry["path"])
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert [e["event_type"] for e in entry["custody"]][:3] == [
            "upload_requested",
            "uploaded",
            "verified",
        ]
    assert job.manifest_sha256 == hashlib.sha256(archive.read("manifest.json")).hexdigest()
    assert "AAA=120; BBB=80" in archive.read("results.csv").decode()


def test_the_verifier_passes_an_untouched_pack_and_catches_tampering(
    photographed, storage, tmp_path
):
    f = photographed
    job = _request(f.admin_client(), f)
    archive = _zip(storage, job)
    archive.extractall(tmp_path)

    def run():
        return subprocess.run(  # noqa: S603 - our own verifier, run with this interpreter
            [sys.executable, "-I", str(tmp_path / "verify.py")],
            capture_output=True,
            text=True,
            check=False,
        )

    ok = run()
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "OK: every file and every custody chain verifies" in ok.stdout
    assert job.manifest_sha256 in ok.stdout  # the recipient can compare with the platform's record

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    victim = tmp_path / manifest["files"][0]["path"]
    victim.write_bytes(victim.read_bytes() + b"x")
    assert run().returncode == 1
    victim.write_bytes(archive.read(manifest["files"][0]["path"]))
    assert run().returncode == 0

    manifest["files"][1]["custody"][0]["details"] = {"edited": True}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    broken = run()
    assert broken.returncode == 1
    assert "does not chain" in broken.stdout


def test_exporting_is_part_of_each_photos_custody_chain(photographed, storage):
    f = photographed
    job = _request(f.admin_client(), f)
    with system_context():
        ids = list(EvidenceFile.objects.values_list("id", flat=True))
        for evidence_id in ids:
            events = list(CustodyEvent.objects.filter(evidence_file_id=evidence_id).order_by("seq"))
            assert events[-1].event_type == "exported"
            assert events[-1].details["export_job_id"] == str(job.id)
            assert evidence_services.verify_custody(evidence_id) == []


def test_a_pack_only_holds_what_the_requester_may_see(photographed, storage):
    f = photographed
    member = f.make_member(
        Role.LGA_OFFICER,
        scope_ids=[f.lgas[0].id],
        organization=f.org,
        granted=[Perm.EVIDENCE_VIEW, Perm.EVIDENCE_EXPORT],
        mfa_enabled=True,
    )
    job = _request(f.client_as(member), f)
    manifest = json.loads(_zip(storage, job).read("manifest.json"))
    assert len(manifest["files"]) == 2
    assert {e["polling_unit"]["lga"] for e in manifest["files"]} == {"Synthetic LGA 01"}


def test_a_pack_can_be_narrowed(photographed, storage):
    f = photographed
    job = _request(f.admin_client(), f, ward_id=str(f.wards[1].id))
    assert job.file_count == 1
    job = _request(f.admin_client(), f, polling_unit_id=str(f.out_c["item"]["polling_unit_id"]))
    assert job.file_count == 1


def test_only_verified_photos_go_in(photographed, storage):
    f = photographed
    with system_context():
        EvidenceFile.objects.filter(id=f.out_b["evidence_id"]).update(status="QUARANTINED")
    job = _request(f.admin_client(), f)
    assert job.file_count == 2


def test_an_object_that_no_longer_matches_its_hash_is_left_out_and_reported(photographed, storage):
    f = photographed
    with system_context():
        key = EvidenceFile.objects.get(id=f.out_a["evidence_id"]).object_key
    storage.write(key, b"replaced after verification", mime="image/jpeg")
    job = _request(f.admin_client(), f)
    manifest = json.loads(_zip(storage, job).read("manifest.json"))
    assert len(manifest["files"]) == 2
    assert [x["evidence_id"] for x in manifest["excluded"]] == [f.out_a["evidence_id"]]


def test_a_pack_that_is_too_big_asks_to_be_narrowed(photographed, settings):
    f = photographed
    settings.VTRS_EVIDENCE_PACK_MAX_FILES = 2
    job = _request(f.admin_client(), f)
    assert job.status == "FAILED"
    assert "limit is 2" in job.error


def test_packs_need_the_evidence_export_permission(photographed):
    f = photographed
    lga = f.client_as(f.officer(Role.LGA_OFFICER, f.lgas[0]))
    body = {"kind": "EVIDENCE_PACK", "format": "ZIP", "election_id": str(f.election.id)}
    response = lga.post("/api/v1/exports", body, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    assert response.status_code == 403
    agent = f.agents[f.pus[0].id].client
    assert (
        agent.post("/api/v1/exports", body, format="json", HTTP_IDEMPOTENCY_KEY="k-2").status_code
        == 403
    )
