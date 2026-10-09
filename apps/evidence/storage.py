"""Evidence storage behind one interface (spec section 12): S3-compatible in development and
production, the local filesystem for tests. The API never touches image bytes on upload:
devices PUT straight to storage with a presigned URL that pins the key, content type and
SHA-256 checksum, so the store itself rejects corrupted uploads.
"""

import base64
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from django.conf import settings


@dataclass(frozen=True)
class PresignedUpload:
    method: str
    url: str
    headers: dict[str, str]
    expires_in: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "expires_in": self.expires_in,
        }


class EvidenceStorage(Protocol):
    def presign_upload(
        self, key: str, *, mime: str, sha256_hex: str, size: int
    ) -> PresignedUpload: ...
    def presign_download(self, key: str, *, filename: str) -> str: ...
    def size_of(self, key: str) -> int | None: ...
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, data: bytes, *, mime: str) -> None: ...
    def move(self, key: str, new_key: str) -> None: ...


def _b64(sha256_hex: str) -> str:
    return base64.b64encode(bytes.fromhex(sha256_hex)).decode()


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.VTRS_S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.VTRS_S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.VTRS_S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.VTRS_S3_SECRET_KEY or None,
            region_name=settings.VTRS_S3_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_upload(self, key: str, *, mime: str, sha256_hex: str, size: int) -> PresignedUpload:
        checksum = _b64(sha256_hex)
        expires = settings.VTRS_EVIDENCE_UPLOAD_URL_SECONDS
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": mime,
                "ContentLength": size,
                "ChecksumSHA256": checksum,
            },
            ExpiresIn=expires,
        )
        headers = {
            "Content-Type": mime,
            "Content-Length": str(size),
            "x-amz-checksum-sha256": checksum,
        }
        return PresignedUpload("PUT", url, headers, expires)

    def presign_download(self, key: str, *, filename: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=settings.VTRS_EVIDENCE_DOWNLOAD_URL_SECONDS,
        )

    def size_of(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except ClientError:
            return None

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def write(self, key: str, data: bytes, *, mime: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime)

    def move(self, key: str, new_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket, Key=new_key, CopySource={"Bucket": self.bucket, "Key": key}
        )
        self.client.delete_object(Bucket=self.bucket, Key=key)


class LocalStorage:
    """Filesystem storage for tests. 'Presigned' URLs are placeholders; tests write directly."""

    def __init__(self) -> None:
        self.root = Path(settings.VTRS_EVIDENCE_LOCAL_ROOT)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Key escapes the storage root")
        return path

    def presign_upload(self, key: str, *, mime: str, sha256_hex: str, size: int) -> PresignedUpload:
        headers = {
            "Content-Type": mime,
            "Content-Length": str(size),
            "x-amz-checksum-sha256": _b64(sha256_hex),
        }
        return PresignedUpload("PUT", f"local://{key}", headers, 900)

    def presign_download(self, key: str, *, filename: str) -> str:
        return f"local://{key}?filename={filename}"

    def size_of(self, key: str) -> int | None:
        path = self._path(key)
        return path.stat().st_size if path.exists() else None

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def write(self, key: str, data: bytes, *, mime: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def move(self, key: str, new_key: str) -> None:
        target = self._path(new_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._path(key).rename(target)


@lru_cache(maxsize=4)
def _build(kind: str, marker: str) -> EvidenceStorage:
    return S3Storage() if kind == "s3" else LocalStorage()


def get_storage() -> EvidenceStorage:
    kind = settings.VTRS_EVIDENCE_STORAGE
    marker = settings.VTRS_EVIDENCE_LOCAL_ROOT if kind == "local" else settings.VTRS_S3_ENDPOINT_URL
    return _build(kind, str(marker))
