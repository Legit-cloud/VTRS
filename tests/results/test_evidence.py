"""AC-12 / DD-04: evidence is stored privately, verified, hashed, quarantined when bad, and
every access is recorded in a tamper-evident chain of custody (FR-6.10.x)."""

import hashlib
import io
from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from PIL import Image

from apps.core.domain.permissions import Role
from apps.core.ids import uuid7
from apps.core.rls import system_context
from apps.evidence import services
from apps.evidence.models import CustodyEvent, EvidenceFile
from apps.evidence.scanning import EICAR
from apps.evidence.storage import get_storage

from .conftest import PDF_BYTES, jpeg_bytes, manifest_entry

pytestmark = pytest.mark.django_db


def _request_uploads(scenario, item, entries):
    uploads = []
    for entry in entries:
        response = scenario.agent.client.post(
            "/api/v1/evidence/uploads", {**entry, "version_id": item["version_id"]}, format="json"
        )
        assert response.status_code == 200, response.content
        uploads.append(response.json())
    return uploads


def _submit_with(scenario, *payloads, **manifest_kwargs):
    """The web flow: send the numbers, then ask to upload the result sheet(s)."""
    entries = [manifest_entry(p, **manifest_kwargs) for p in payloads]
    item = scenario.item()
    [outcome] = scenario.submit(item)
    outcome["evidence_uploads"] = _request_uploads(scenario, item, entries)
    return item, entries, outcome


def _evidence(evidence_id):
    with system_context():
        return EvidenceFile.objects.get(id=evidence_id)


def _upload(evidence_id, data):
    """What the browser's PUT to the presigned URL does."""
    get_storage().write(_evidence(evidence_id).object_key, data, mime="image/jpeg")


def _complete(scenario, evidence_id):
    return scenario.agent.client.post(f"/api/v1/evidence/{evidence_id}/complete")


def _chain(evidence_id):
    with system_context():
        return list(
            CustodyEvent.objects.filter(evidence_file_id=evidence_id)
            .order_by("seq")
            .values_list("event_type", flat=True)
        )


def test_happy_path_upload_verify_and_custody(scenario):
    photo = jpeg_bytes()
    _, [entry], outcome = _submit_with(scenario, photo)
    [upload] = outcome["evidence_uploads"]
    assert upload["status"] == "PENDING_UPLOAD"
    assert upload["upload"]["method"] == "PUT"
    # The store is told the checksum, so it can reject a corrupted upload by itself.
    assert upload["upload"]["headers"]["x-amz-checksum-sha256"]
    assert upload["upload"]["headers"]["Content-Length"] == str(len(photo))

    _upload(entry["evidence_id"], photo)
    response = _complete(scenario, entry["evidence_id"])
    assert response.status_code == 200
    evidence = _evidence(entry["evidence_id"])
    assert evidence.status == "VERIFIED"  # the verify task ran via the outbox
    assert evidence.sha256_server == hashlib.sha256(photo).hexdigest()
    assert evidence.metadata["width"] == 240 and len(evidence.metadata["dhash"]) == 16
    storage = get_storage()
    assert storage.size_of(evidence.metadata["thumbnail_key"])
    assert storage.size_of(evidence.metadata["preview_key"])
    assert storage.read(evidence.object_key) == photo  # originals are never touched

    assert _chain(entry["evidence_id"]) == ["upload_requested", "uploaded", "verified"]
    with system_context():
        assert services.verify_custody(evidence.id) == []

    # Confirming twice is harmless.
    assert _complete(scenario, entry["evidence_id"]).json()["status"] == "VERIFIED"


def test_numbers_first_sheet_follows(scenario):
    """A result is accepted and visible before its sheet exists, and says it is incomplete."""
    _, [entry], outcome = _submit_with(scenario, jpeg_bytes())
    assert (outcome["status"], outcome["completion"]) == ("ACCEPTED", "NUMBERS_SUBMITTED")
    assert _evidence(entry["evidence_id"]).status == "PENDING_UPLOAD"


def test_pdf_sheets_are_verified_without_derivatives(scenario):
    _, [entry], _ = _submit_with(scenario, PDF_BYTES, mime="application/pdf")
    _upload(entry["evidence_id"], PDF_BYTES)
    response = _complete(scenario, entry["evidence_id"])
    assert response.json()["completion"] == "COMPLETE"
    evidence = _evidence(entry["evidence_id"])
    assert evidence.status == "VERIFIED", evidence.quarantine_reason
    assert evidence.object_key.endswith(".pdf")
    assert "thumbnail_key" not in evidence.metadata and "dhash" not in evidence.metadata
    assert _chain(entry["evidence_id"]) == ["upload_requested", "uploaded", "verified"]


def test_a_pdf_that_is_not_a_pdf_is_quarantined(scenario):
    fake = jpeg_bytes()
    _, [entry], _ = _submit_with(scenario, fake, mime="application/pdf")
    _upload(entry["evidence_id"], fake)
    _complete(scenario, entry["evidence_id"])
    evidence = _evidence(entry["evidence_id"])
    assert evidence.status == "QUARANTINED"
    assert "content is image/jpeg" in evidence.quarantine_reason


def test_confirm_before_upload(scenario):
    _, [entry], _ = _submit_with(scenario, jpeg_bytes())
    response = _complete(scenario, entry["evidence_id"])
    assert (response.status_code, response.json()["code"]) == (409, "upload_not_found")


@pytest.mark.parametrize(
    ("uploaded", "declared_mime", "reason"),
    [
        (b"tampered" + jpeg_bytes()[8:], "image/jpeg", "sha256 differs"),
        (lambda: _png(), "image/jpeg", "content is image/png"),
        (lambda: jpeg_bytes()[:-40] + EICAR, "image/jpeg", "malware: EICAR"),
        (lambda: _bomb(), "image/png", "decompression_bomb"),
        (lambda: b"\xff\xd8\xff" + b"\x00" * 500, "image/jpeg", "undecodable_image"),
    ],
)
def test_bad_files_are_quarantined(scenario, uploaded, declared_mime, reason):
    data = uploaded() if callable(uploaded) else uploaded
    # Declare exactly what will arrive (size and hash), except where the test is about a mismatch.
    declared = data if reason != "sha256 differs" else jpeg_bytes()[: len(data)]
    _, [entry], _ = _submit_with(scenario, declared, mime=declared_mime)
    _upload(entry["evidence_id"], data)
    _complete(scenario, entry["evidence_id"])
    evidence = _evidence(entry["evidence_id"])
    assert evidence.status == "QUARANTINED", evidence.quarantine_reason
    assert reason in evidence.quarantine_reason
    storage = get_storage()
    assert storage.size_of(evidence.object_key) is None  # moved out of the live area
    assert storage.size_of(evidence.metadata["quarantine_key"]) == len(data)
    assert _chain(entry["evidence_id"])[-1] == "quarantined"


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def _bomb():
    buffer = io.BytesIO()
    Image.new("1", (9000, 9000)).save(buffer, format="PNG", optimize=True)  # 81 Mpx, tiny file
    return buffer.getvalue()


def test_exif_capture_time_is_extracted(scenario):
    exif = Image.Exif()
    exif[0x0132] = "2027:03:11 14:55:02"  # DateTime
    photo = jpeg_bytes(exif=exif.tobytes())
    _, [entry], _ = _submit_with(scenario, photo)
    _upload(entry["evidence_id"], photo)
    _complete(scenario, entry["evidence_id"])
    assert _evidence(entry["evidence_id"]).metadata["exif_taken_at"] == "2027-03-11T14:55:02"


def test_extra_photo_and_fresh_url(scenario):
    item, [entry], _ = _submit_with(scenario, jpeg_bytes())
    second = manifest_entry(jpeg_bytes(color=(10, 200, 10)), kind="EC8B")
    response = scenario.agent.client.post(
        "/api/v1/evidence/uploads", {**second, "version_id": item["version_id"]}, format="json"
    )
    assert response.status_code == 200 and response.json()["upload"]["method"] == "PUT"
    again = scenario.agent.client.post(
        "/api/v1/evidence/uploads", {**entry, "version_id": item["version_id"]}, format="json"
    )
    assert again.json()["evidence_id"] == entry["evidence_id"]  # same stub, fresh URL
    clash = scenario.agent.client.post(
        "/api/v1/evidence/uploads",
        {**entry, "size": 99, "version_id": item["version_id"]},
        format="json",
    )
    assert clash.json()["code"] == "evidence_conflict"


def test_limits_on_declared_files(scenario):
    item = scenario.item()
    scenario.submit(item)
    big = {**manifest_entry(jpeg_bytes()), "size": 9 * 1024 * 1024}
    gif = {**manifest_entry(jpeg_bytes()), "mime": "image/gif"}
    for entry, field_name in ((big, "size"), (gif, "mime")):
        response = scenario.agent.client.post(
            "/api/v1/evidence/uploads", {**entry, "version_id": item["version_id"]}, format="json"
        )
        assert response.status_code == 400
        assert field_name in response.json()["errors"]


def test_reconciliation_completes_unconfirmed_uploads(scenario):
    photo = jpeg_bytes()
    _, [entry], _ = _submit_with(scenario, photo)
    _upload(entry["evidence_id"], photo)  # uploaded, but the tab closed before confirming
    with system_context():
        EvidenceFile.objects.filter(id=entry["evidence_id"]).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
    with transaction.atomic():
        assert services.reconcile_pending_uploads() == 1
    with system_context():
        services.verify(entry["evidence_id"])
    assert _evidence(entry["evidence_id"]).status == "VERIFIED"
    with system_context():
        uploaded = CustodyEvent.objects.get(
            evidence_file_id=entry["evidence_id"], event_type="uploaded"
        )
    assert uploaded.details["via"] == "storage_reconciliation"


def _verified(scenario):
    photo = jpeg_bytes()
    _, [entry], _ = _submit_with(scenario, photo)
    _upload(entry["evidence_id"], photo)
    _complete(scenario, entry["evidence_id"])
    return entry["evidence_id"]


def test_download_links_are_scoped_short_lived_and_logged(scenario, make_member, client_as):
    evidence_id = _verified(scenario)
    url = f"/api/v1/evidence/{evidence_id}/download-url"

    admin = client_as(scenario.admin)
    response = admin.post(url)
    assert response.status_code == 200 and response.json()["expires_in"] == 60
    assert _chain(evidence_id)[-1] == "download_url_issued"

    # The uploading agent may fetch their own photo; another agent may not even see it.
    assert scenario.agent.client.post(url).status_code == 200
    other_agent = scenario.make_agent()
    assert other_agent.client.post(url).status_code == 404

    # Coordinators see the sheets of their own area, and nothing outside it.
    pu = scenario.pu
    ward_coordinator = make_member(
        Role.WARD_OFFICER, scope_ids=[pu.ward_id], organization=scenario.org
    )
    assert client_as(ward_coordinator).post(url).status_code == 200
    lga_coordinator = make_member(
        Role.LGA_OFFICER, scope_ids=[pu.lga_id], organization=scenario.org
    )
    assert client_as(lga_coordinator).post(url).status_code == 200
    elsewhere = make_member(
        Role.LGA_OFFICER, scope_ids=[scenario.other_pu.lga_id], organization=scenario.org
    )
    assert client_as(elsewhere).post(url).status_code == 404
    outsider = make_member(Role.PARTY_ADMIN)
    assert client_as(outsider).post(url).status_code == 404


def test_quarantined_evidence_cannot_be_downloaded(scenario, client_as):
    _, [entry], _ = _submit_with(scenario, jpeg_bytes())
    _upload(entry["evidence_id"], b"not an image at all")
    _complete(scenario, entry["evidence_id"])
    response = client_as(scenario.admin).post(
        f"/api/v1/evidence/{entry['evidence_id']}/download-url"
    )
    assert response.json()["code"] == "evidence_quarantined"


def test_custody_is_append_only_and_tampering_is_detected(scenario, as_superuser):
    evidence_id = _verified(scenario)
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE custody_event SET event_type = 'x' WHERE evidence_file_id = %s", [evidence_id]
        )
    as_superuser()
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        cursor.execute(
            "UPDATE custody_event SET details = '{\"forged\": true}' "
            "WHERE evidence_file_id = %s AND seq = 2",
            [evidence_id],
        )
    problems = services.verify_custody(evidence_id)
    assert any("event 2: hash mismatch" in p for p in problems)


def test_evidence_ids_cannot_be_reused_across_versions(scenario):
    photo = jpeg_bytes()
    _, [entry], _ = _submit_with(scenario, photo)
    correction = scenario.item(votes=[121, 80])
    scenario.submit(correction)
    response = scenario.agent.client.post(
        "/api/v1/evidence/uploads", {**entry, "version_id": correction["version_id"]}, format="json"
    )
    assert response.json()["code"] == "evidence_conflict"


def test_unknown_evidence_is_not_found(scenario):
    response = scenario.agent.client.post(f"/api/v1/evidence/{uuid7()}/complete")
    assert response.status_code == 404
