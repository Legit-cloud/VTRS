from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.evidence.storage import S3Storage


class Command(BaseCommand):
    help = (
        "Create the private evidence bucket (development). Versioning and object lock are "
        "enabled when the store supports them; retention periods wait for PB-09. Browsers "
        "upload result sheets straight to the bucket, so it also allows PUT from the web app's "
        "own origins (VTRS_CORS_ALLOWED_ORIGINS) and nothing else."
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
            (
                "browser uploads (CORS)",
                lambda: _allow_browser_uploads(client, bucket),
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


def _allow_browser_uploads(client: Any, bucket: str) -> None:
    """A presigned PUT from the web app is cross-origin: exact origins only, PUT only, and only
    the headers the presigned request pins (spec section 10.1, step 5)."""
    origins = list(settings.VTRS_CORS_ALLOWED_ORIGINS)
    if not origins:
        raise CommandError("VTRS_CORS_ALLOWED_ORIGINS is empty; browsers could not upload")
    client.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": origins,
                    "AllowedMethods": ["PUT"],
                    "AllowedHeaders": ["content-type", "x-amz-checksum-sha256"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )
