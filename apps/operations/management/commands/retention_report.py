import json
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.aggregation.models import ReconciliationSnapshot
from apps.core.rls import system_context
from apps.evidence.models import EvidenceFile
from apps.results.models import ResultVersion


class Command(BaseCommand):
    help = (
        "List reconciled elections whose records have passed their retention period "
        "(VTRS_RETENTION_YEARS). Read-only: nothing is deleted. Deleting election evidence "
        "needs legal sign-off and is a separate, deliberate operator action (PB-09, DG-04)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--json", action="store_true", help="Machine-readable output")

    def handle(self, *args: Any, **options: Any) -> None:
        years = settings.VTRS_RETENTION_YEARS
        now = timezone.now()
        rows: list[dict[str, Any]] = []
        with transaction.atomic(), system_context():
            for snap in ReconciliationSnapshot.objects.select_related("election").order_by(
                "reconciled_at"
            ):
                row: dict[str, Any] = {
                    "election_id": str(snap.election_id),
                    "election": snap.election.name,
                    "organization_id": str(snap.organization_id),
                    "reconciled_at": snap.reconciled_at.isoformat(),
                }
                for kind in ("evidence", "results"):
                    due = snap.reconciled_at + timedelta(days=365 * years[kind])
                    row[f"{kind}_eligible_after"] = due.date().isoformat()
                    row[f"{kind}_past_retention"] = due <= now
                row["evidence_files"] = EvidenceFile.objects.filter(
                    result_version__pu_result__election_id=snap.election_id
                ).count()
                row["result_versions"] = ResultVersion.objects.filter(
                    pu_result__election_id=snap.election_id
                ).count()
                rows.append(row)
        if options["json"]:
            self.stdout.write(json.dumps({"retention_years": years, "elections": rows}, indent=2))
            return
        self.stdout.write(f"Retention (years after reconciliation): {years}")
        if not rows:
            self.stdout.write("No reconciled elections.")
        for row in rows:
            flag = "PAST RETENTION" if row["evidence_past_retention"] else "within retention"
            self.stdout.write(
                f"{row['election']} ({row['election_id']}): "
                f"reconciled {row['reconciled_at'][:10]}, "
                f"{row['evidence_files']} photos, {row['result_versions']} versions, {flag}"
            )
