"""Content classification and extraction planning nodes."""

from __future__ import annotations

import mimetypes
from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SPREADSHEET_EXTENSIONS, TEXT_EXTENSIONS


def _classify_content_type(state: DocumentPipelineState) -> dict[str, Any]:
    if state.get("content_class"):
        return {}

    sample = state["sample"]
    suffix = sample.sample_path.suffix.lower()
    mime_type = mimetypes.guess_type(sample.sample_path.name)[0]
    file_probe = state.get("file_probe", {})
    signals = {"suffix": suffix, "mime_type": mime_type, "file_probe": file_probe}
    if file_probe.get("media_type") == "pdf" and file_probe.get("image_only_pdf_likelihood", 0) >= 0.8:
        final_class = "scanned_document"
        confidence = 0.88
    elif file_probe.get("media_type") == "pdf" and file_probe.get("warnings"):
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
        "content_class": {
            "source_path": sample.source_path,
            "relative_path": sample.relative_path,
            "final_class": final_class,
            "final_status": "classified",
            "confidence": confidence,
            "signals": signals,
            "probe_status": file_probe.get("status"),
            "needs_review": confidence < 0.7,
        }
    }

def _plan_extraction(state: DocumentPipelineState) -> dict[str, Any]:
    if state.get("extraction_plan"):
        return {}

    sample = state["sample"]
    final_class = state["content_class"]["final_class"]
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

    return {
        "extraction_plan": {
            "source_path": sample.source_path,
            "relative_path": sample.relative_path,
            "strategy": strategy,
            "document_subtype": document_subtype,
            "ocr_required": strategy == "ocr_page_level",
            "defer_reason": defer_reason,
            "probe_status": state.get("file_probe", {}).get("status"),
            "provider_hints": _provider_hints(state.get("file_probe", {}), strategy),
        }
    }


def _provider_hints(file_probe: dict[str, Any], strategy: str) -> dict[str, Any]:
    if strategy == "ocr_page_level":
        return {
            "preferred_parser": "docling",
            "fallback_ocr": "cortex",
            "reason": "ocr_required_or_image_only_pdf",
            "image_only_pdf_likelihood": file_probe.get("image_only_pdf_likelihood"),
        }
    if strategy == "text_extraction":
        return {
            "preferred_parser": "current",
            "fallback_parser": "docling",
            "reason": "embedded_text_or_native_text_expected",
            "embedded_text_chars": file_probe.get("embedded_text_chars"),
        }
    return {"preferred_parser": "current", "reason": "strategy_default"}
