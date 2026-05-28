"""Extraction strategy planning policy."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.services.content import TEXT_EXTENSIONS, SampleFile
from sunshine_extraction.services.provider_policy import parser_provider_for_strategy


def plan_extraction(sample: SampleFile, content_class: dict[str, Any], *, file_probe: dict[str, Any] | None = None) -> dict[str, Any]:
    final_class = content_class["final_class"]
    suffix = sample.sample_path.suffix.lower()
    if final_class == "image":
        strategy = "photo_metadata"
        document_subtype = "photo"
        defer_reason = None
    elif final_class == "scanned_document":
        strategy = "ocr_page_level"
        document_subtype = "scanned_or_photographed_document"
        defer_reason = None
    elif final_class == "document":
        strategy = "text_extraction" if suffix == ".pdf" or suffix in TEXT_EXTENSIONS else "deferred_technical"
        document_subtype = "text_document"
        defer_reason = None if strategy == "text_extraction" else "document_parser_required"
    elif final_class == "spreadsheet":
        strategy = "spreadsheet_table_extraction"
        document_subtype = "spreadsheet"
        defer_reason = None
    elif final_class == "deferred_technical":
        strategy = "deferred_technical"
        document_subtype = "technical"
        defer_reason = "technical_conversion_required"
    else:
        strategy = "deferred_technical"
        document_subtype = "unknown"
        defer_reason = "unknown_file_type"

    probe = file_probe or {}
    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "strategy": strategy,
        "document_subtype": document_subtype,
        "ocr_required": strategy == "ocr_page_level",
        "defer_reason": defer_reason,
        "probe_status": probe.get("status"),
        "provider_hints": provider_hints(probe, strategy),
    }


def provider_hints(file_probe: dict[str, Any], strategy: str) -> dict[str, Any]:
    if strategy == "ocr_page_level":
        preferred = parser_provider_for_strategy(strategy, default="docling")
        return {
            "preferred_parser": preferred,
            "fallback_ocr": "cortex",
            "reason": "ocr_required_or_image_only_pdf",
            "image_only_pdf_likelihood": file_probe.get("image_only_pdf_likelihood"),
        }
    if strategy == "text_extraction":
        fallback = parser_provider_for_strategy(strategy, default="docling")
        return {
            "preferred_parser": "current",
            "fallback_parser": fallback,
            "reason": "embedded_text_or_native_text_expected",
            "embedded_text_chars": file_probe.get("embedded_text_chars"),
        }
    return {"preferred_parser": "current", "reason": "strategy_default"}
