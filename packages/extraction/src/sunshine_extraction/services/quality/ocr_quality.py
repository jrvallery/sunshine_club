"""OCR quality thresholds and document-level OCR quality classification."""

from __future__ import annotations

from typing import Any

OCR_OK_CONFIDENCE_THRESHOLD = 75.0
OCR_MIN_TEXT_LENGTH = 100
OCR_MAX_FAILED_PAGE_RATE = 0.2


def classify_ocr_document_quality(
    *,
    page_count: int,
    pages_failed: int,
    total_text_length: int,
    mean_confidence: float | None,
    warnings: list[str],
) -> tuple[str, str, list[str]]:
    failed_page_rate = pages_failed / page_count if page_count else 1
    active_warnings = list(warnings)

    if pages_failed == page_count:
        return "failed", "failed", active_warnings
    if total_text_length == 0:
        return "empty", "metadata_only", active_warnings
    if (
        mean_confidence is not None
        and mean_confidence >= OCR_OK_CONFIDENCE_THRESHOLD
        and total_text_length >= OCR_MIN_TEXT_LENGTH
        and failed_page_rate <= OCR_MAX_FAILED_PAGE_RATE
    ):
        return "ok", "ok", active_warnings

    active_warnings.append("ocr_confidence_below_threshold") if mean_confidence is None or mean_confidence < OCR_OK_CONFIDENCE_THRESHOLD else None
    active_warnings.append("ocr_sparse_text_below_threshold") if total_text_length < OCR_MIN_TEXT_LENGTH else None
    active_warnings.append("ocr_failed_page_rate_above_threshold") if failed_page_rate > OCR_MAX_FAILED_PAGE_RATE else None
    return "poor", "poor", active_warnings


def ocr_quality_from_document_row(ocr_document: dict[str, Any]) -> str | None:
    quality = ocr_document.get("quality")
    return str(quality) if isinstance(quality, str) else None
