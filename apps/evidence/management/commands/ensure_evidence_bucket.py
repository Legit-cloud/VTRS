from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.evidence.storage import S3Storage


class Command(BaseCommand):
    help = (
        "Create the private evidence bucket (development). Versioning and object lock are "
        "enabled when the store supports them; retention periods wait for PB-09."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.VTRS_EVIDENCE_STORAGE != "s3":
            raise CommandError("VTRS_EVIDENCE_STORAGE is not 's3'")
        storage = S3Storage()
        client, bucket = storage.client, storage.bucket
        existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
        if bucket not in existing:
            try:
                client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
                self.stdout.write(f"Created {bucket} with object lock")
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"Object lock unavailable ({exc}); plain bucket")
                )
                client.create_bucket(Bucket=bucket)
        for label, call in (
            (
                "versioning",
                lambda: client.put_bucket_versioning(
                    Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
                ),
            ),
            (
                "public access block",
                lambda: client.put_public_access_block(
                    Bucket=bucket,
                    PublicAccessBlockConfiguration={
                        "BlockPublicAcls": True,
                        "IgnorePublicAcls": True,
                        "BlockPublicPolicy": True,
                        "RestrictPublicBuckets": True,
                    },
                ),
            ),
        ):
            try:
                call()
                self.stdout.write(f"{label}: on")
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"{label}: not supported by this store ({exc})")
                )
        self.stdout.write(self.style.SUCCESS(f"Bucket {bucket} ready"))
