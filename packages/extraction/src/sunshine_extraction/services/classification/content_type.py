"""Broad Sunshine content-class policy."""

from __future__ import annotations

import mimetypes
from typing import Any

from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SPREADSHEET_EXTENSIONS, TEXT_EXTENSIONS, SampleFile


def classify_content_type(sample: SampleFile, *, file_probe: dict[str, Any] | None = None) -> dict[str, Any]:
    suffix = sample.sample_path.suffix.lower()
    mime_type = mimetypes.guess_type(sample.sample_path.name)[0]
    probe = file_probe or {}
    signals = {"suffix": suffix, "mime_type": mime_type, "file_probe": probe}
    if probe.get("media_type") == "pdf" and probe.get("image_only_pdf_likelihood", 0) >= 0.8:
        final_class = "scanned_document"
        confidence = 0.88
    elif probe.get("media_type") == "pdf" and probe.get("warnings"):
        final_class = "document"
        confidence = 0.64
    elif suffix in IMAGE_EXTENSIONS:
        final_class = "image"
        confidence = 0.9
    elif suffix in SPREADSHEET_EXTENSIONS:
        final_class = "spreadsheet"
        confidence = 0.9
    elif suffix in TEXT_EXTENSIONS or suffix == ".pdf":
        final_class = "document"
        confidence = 0.75
    elif suffix in {".mov", ".mp4", ".m4v", ".avi"}:
        final_class = "video"
        confidence = 0.9
    elif suffix in {".pub"}:
        final_class = "deferred_technical"
        confidence = 0.95
    else:
        final_class = "binary_or_unknown"
        confidence = 0.4

    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "final_class": final_class,
        "final_status": "classified",
        "confidence": confidence,
        "signals": signals,
        "probe_status": probe.get("status"),
        "needs_review": confidence < 0.7,
    }
