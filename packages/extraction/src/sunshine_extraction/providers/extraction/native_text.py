"""Native text/PDF extraction provider helpers."""

from __future__ import annotations

import mimetypes
from typing import Any

from pypdf import PdfReader

from sunshine_extraction.domain.extraction import ExtractionResult
from sunshine_extraction.services.content import TEXT_EXTENSIONS, SampleFile


def extract_text(sample: SampleFile, plan: dict[str, Any]) -> ExtractionResult:
    suffix = sample.sample_path.suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(str(sample.sample_path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return ExtractionResult(
                sample,
                plan,
                "extracted",
                text,
                {"mime_type": "application/pdf"},
                len(reader.pages),
                [] if text.strip() else ["pdf_text_empty"],
            )
        if suffix in TEXT_EXTENSIONS:
            return ExtractionResult(
                sample,
                plan,
                "extracted",
                sample.sample_path.read_text(encoding="utf-8", errors="replace"),
                {"mime_type": mimetypes.guess_type(sample.sample_path.name)[0]},
                None,
                [],
            )
    except Exception as error:  # noqa: BLE001 - artifact must capture failures per file.
        return ExtractionResult(sample, plan, "failed", "", {"error": str(error)}, None, ["text_extraction_failed"])

    return ExtractionResult(sample, plan, "deferred_extractor", "", {"suffix": suffix}, None, ["document_executor_not_installed"])
