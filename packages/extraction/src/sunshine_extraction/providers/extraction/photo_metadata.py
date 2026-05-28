"""Image metadata extraction helpers."""

from __future__ import annotations

from typing import Any

from PIL import ExifTags, Image

from sunshine_extraction.domain.extraction import ExtractionResult
from sunshine_extraction.services.content import SampleFile


def extract_photo_metadata(sample: SampleFile, plan: dict[str, Any]) -> ExtractionResult:
    try:
        with Image.open(sample.sample_path) as image:
            exif = image.getexif()
            captured_at = None
            if exif:
                exif_by_name = {ExifTags.TAGS.get(key, str(key)): value for key, value in exif.items()}
                captured_at = exif_by_name.get("DateTimeOriginal") or exif_by_name.get("DateTime")
            metadata = {
                "image_format": image.format,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "frame_count": getattr(image, "n_frames", 1),
                "captured_at": captured_at,
            }
        return ExtractionResult(sample, plan, "metadata_extracted", "", metadata, None, [])
    except Exception as error:  # noqa: BLE001
        return ExtractionResult(sample, plan, "failed", "", {"error": str(error)}, None, ["photo_metadata_failed"])
