"""Text validation service for extracted content."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.sample_pipeline import validate_extracted_text


def validation_row(sample: SampleFile, extraction: ExtractionResult, validation: dict[str, Any]) -> dict[str, Any]:
    """Normalize validation output for `sample-extraction-validations.jsonl`."""

    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
        "status": validation.get("status"),
        "reason": validation.get("reason"),
        "strategy": extraction.plan.get("strategy"),
        "extraction_status": extraction.extraction_status,
        "text_length": len(extraction.text or ""),
    }


def with_text_validation(extraction: ExtractionResult, validation: dict[str, Any]) -> ExtractionResult:
    """Attach validation metadata to an extraction result without changing text."""

    return type(extraction)(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata={**extraction.metadata, "text_validation": validation},
        page_count=extraction.page_count,
        warnings=extraction.warnings,
    )
