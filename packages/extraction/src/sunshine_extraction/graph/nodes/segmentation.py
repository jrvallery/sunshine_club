"""Document structure normalization and logical segment proposal nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.segmentation.page_grouping import propose_document_segments
from sunshine_extraction.services.structure import normalize_document_structure


def _normalize_document_structure_node(state: DocumentPipelineState) -> dict[str, Any]:
    return {
        "document_structure": normalize_document_structure(
            state["extraction_result"],
            ocr_pages=state.get("ocr_pages", []),
            provider_attempts=state.get("provider_attempts", []),
        )
    }


def _propose_document_segments_node(state: DocumentPipelineState) -> dict[str, Any]:
    segments = propose_document_segments(
        state["extraction_result"],
        file_id=state.get("file_id"),
        source_identity=state.get("source_identity"),
        content_class=state.get("content_class"),
        ocr_pages=state.get("ocr_pages", []),
        document_structure=state.get("document_structure"),
    )
    warnings = list(state.get("warnings", []))
    if any(segment.get("requires_segment_review") for segment in segments):
        warnings.append("document_segmentation_review_recommended")
    return {"document_segments": segments, "warnings": warnings}
