"""Image checks and derivatives (spec section 12, step 4-5).

Decoding is bounded (decompression-bomb limit). Originals are never modified; previews are
re-encoded without metadata. EXIF capture time and GPS and a perceptual hash are extracted for
the evidence anomaly rules (M5).
"""

import io
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.conf import settings
from PIL import ExifTags, Image, UnidentifiedImageError

THUMBNAIL_PX = 320
PREVIEW_PX = 1600


class ImageRejected(Exception):
    pass


@dataclass
class Derived:
    thumbnail: bytes
    preview: bytes
    width: int
    height: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _open(data: bytes) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = settings.VTRS_EVIDENCE_MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            probe = Image.open(io.BytesIO(data))
            probe.verify()  # structural check; the image must be reopened afterwards
            image = Image.open(io.BytesIO(data))
            image.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageRejected("decompression_bomb") from exc
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            raise ImageRejected("undecodable_image") from exc
    return image


def _exif(image: Image.Image) -> dict[str, Any]:
    exif = image.getexif()
    out: dict[str, Any] = {}
    taken = exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal) or exif.get(
        ExifTags.Base.DateTime
    )
    if isinstance(taken, str):
        try:
            out["exif_taken_at"] = datetime.strptime(taken.strip(), "%Y:%m:%d %H:%M:%S").isoformat()
        except ValueError:
            pass
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    if gps:
        try:
            out["exif_gps"] = {"lat": _degrees(gps[2], gps[1]), "lng": _degrees(gps[4], gps[3])}
        except (KeyError, TypeError, ZeroDivisionError):
            pass
    return out


def _degrees(dms: Any, ref: str) -> float:
    degrees = float(dms[0]) + float(dms[1]) / 60 + float(dms[2]) / 3600
    return round(-degrees if ref in {"S", "W"} else degrees, 6)


def dhash(image: Image.Image, size: int = 8) -> str:
    """Difference hash: near-identical photos (re-used sheets) give near-identical hashes."""
    small = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return f"{bits:0{size * size // 4}x}"


def _encode_jpeg(image: Image.Image, max_px: int) -> bytes:
    copy = image.convert("RGB")
    copy.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=85)  # fresh encode: no EXIF, no GPS
    return buffer.getvalue()


def derive(data: bytes) -> Derived:
    image = _open(data)
    metadata = _exif(image)
    metadata["dhash"] = dhash(image)
    return Derived(
        thumbnail=_encode_jpeg(image, THUMBNAIL_PX),
        preview=_encode_jpeg(image, PREVIEW_PX),
        width=image.width,
        height=image.height,
        metadata=metadata,
    )
