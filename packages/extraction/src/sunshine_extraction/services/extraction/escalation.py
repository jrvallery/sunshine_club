"""Extraction validation repair and OCR escalation services."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.domain.extraction import ExtractionResult, OcrArtifacts, OcrExecutor
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SampleFile
from sunshine_extraction.services.extraction.core import extract_ocr_page_level
from sunshine_extraction.services.quality.text_validation import validate_extracted_text, with_text_validation


def validate_and_repair_extraction(
    sample: SampleFile,
    plan: dict[str, Any],
    extraction: ExtractionResult,
    *,
    ocr_executor: OcrExecutor | None = None,
    ocr_artifacts: OcrArtifacts | None = None,
) -> ExtractionResult:
    validation = validate_extracted_text(extraction)
    if validation["status"] != "failed":
        return with_text_validation(extraction, validation)

    failed_extraction = with_text_validation(
        _with_added_warnings(extraction, [f"text_validation_failed:{validation['reason']}"]),
        validation,
    )
    if plan.get("strategy") == "ocr_page_level" or not _can_try_ocr(sample):
        return failed_extraction

    fallback_plan = {
        **plan,
        "strategy": "ocr_page_level",
        "document_subtype": "scanned_or_image_pdf",
        "ocr_required": True,
        "original_strategy": plan.get("strategy"),
    }
    original_extraction = {
        "strategy": plan.get("strategy"),
        "status": extraction.extraction_status,
        "text_length": len(extraction.text),
        "text_snippet": _shorten(extraction.text, 360),
        "warnings": extraction.warnings,
    }
    if ocr_executor is None:
        fallback_metadata = {
            "ocr_required": True,
            "document_subtype": fallback_plan.get("document_subtype"),
            "text_validation": {
                "status": "failed",
                "reason": validation["reason"],
                "repair_strategy": "ocr_page_level",
            },
            "original_extraction": original_extraction,
        }
        return ExtractionResult(
            sample=sample,
            plan=fallback_plan,
            extraction_status="deferred_extractor",
            text="",
            metadata=fallback_metadata,
            page_count=extraction.page_count,
            warnings=[
                *extraction.warnings,
                f"text_validation_failed:{validation['reason']}",
                f"text_extraction_fallback_to_ocr:{plan.get('strategy')}",
                "ocr_executor_not_provided",
            ],
        )

    fallback = extract_ocr_page_level(
        sample,
        fallback_plan,
        ocr_executor=ocr_executor,
        ocr_artifacts=ocr_artifacts,
    )
    fallback_metadata = {
        **fallback.metadata,
        "text_validation": {"status": "repaired", "reason": validation["reason"], "repair_strategy": "ocr_page_level"},
        "original_extraction": original_extraction,
    }
    return ExtractionResult(
        sample=sample,
        plan=fallback_plan,
        extraction_status=fallback.extraction_status,
        text=fallback.text,
        metadata=fallback_metadata,
        page_count=fallback.page_count,
        warnings=[
            *extraction.warnings,
            f"text_validation_failed:{validation['reason']}",
            f"text_extraction_fallback_to_ocr:{plan.get('strategy')}",
            *fallback.warnings,
        ],
    )


def _with_added_warnings(extraction: ExtractionResult, warnings: list[str]) -> ExtractionResult:
    return ExtractionResult(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata=extraction.metadata,
        page_count=extraction.page_count,
        warnings=[*extraction.warnings, *warnings],
    )


def _can_try_ocr(sample: SampleFile) -> bool:
    return sample.sample_path.suffix.lower() in IMAGE_EXTENSIONS or sample.sample_path.suffix.lower() == ".pdf"


def _shorten(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."
