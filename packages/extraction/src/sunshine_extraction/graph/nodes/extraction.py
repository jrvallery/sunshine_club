"""Extraction, validation, quality gate, and chunking nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.model_usage import _ocr_model_usage_rows
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.extraction import (
    OcrArtifacts,
    chunk_content,
    extraction_quality_gate,
    validate_and_repair_extraction,
)
from sunshine_extraction.services.segmentation.page_grouping import attach_segment_ids_to_chunks, propose_document_segments


def _extract_content_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    ocr_artifacts = OcrArtifacts(pages=[], documents=[])
    extraction, provider_attempt = deps["extraction_provider"].extract(
        state["sample"],
        state["extraction_plan"],
        ocr_executor=deps["ocr_executor"],
        ocr_artifacts=ocr_artifacts,
    )
    provider_attempt_row = {
        "source_path": state["sample"].source_path,
        "relative_path": state["sample"].relative_path,
        "sample_path": str(state["sample"].sample_path),
        **provider_attempt.as_row(),
    }
    updates: dict[str, Any] = {
        "extraction_result": extraction,
        "provider_attempts": [*state.get("provider_attempts", []), provider_attempt_row],
        "ocr_pages": ocr_artifacts.pages,
        "warnings": [*state.get("warnings", []), *extraction.warnings],
    }
    if ocr_artifacts.documents:
        updates["ocr_document"] = ocr_artifacts.documents[0]
    usage_rows = _ocr_model_usage_rows(state, ocr_artifacts.pages, node="extract_content")
    if usage_rows:
        updates["model_usage"] = [*state.get("model_usage", []), *usage_rows]
    return updates

def _validate_text_extraction_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    original = state["extraction_result"]
    ocr_artifacts = OcrArtifacts(pages=[], documents=[])
    repaired = validate_and_repair_extraction(
        state["sample"],
        state["extraction_plan"],
        original,
        ocr_executor=deps["ocr_executor"],
        ocr_artifacts=ocr_artifacts,
    )
    new_warnings = [warning for warning in repaired.warnings if warning not in original.warnings]
    updates: dict[str, Any] = {
        "extraction_result": repaired,
        "extraction_plan": repaired.plan,
        "warnings": [*state.get("warnings", []), *new_warnings],
    }
    if ocr_artifacts.pages:
        updates["ocr_pages"] = [*state.get("ocr_pages", []), *ocr_artifacts.pages]
    if ocr_artifacts.documents:
        updates["ocr_document"] = ocr_artifacts.documents[-1]
    usage_rows = _ocr_model_usage_rows(state, ocr_artifacts.pages, node="validate_text_extraction")
    if usage_rows:
        updates["model_usage"] = [*state.get("model_usage", []), *usage_rows]
    return updates

def _quality_gate(state: DocumentPipelineState) -> dict[str, Any]:
    return {"extraction_quality": extraction_quality_gate(state["extraction_result"])}

def _propose_document_segments_node(state: DocumentPipelineState) -> dict[str, Any]:
    segments = propose_document_segments(
        state["extraction_result"],
        file_id=state.get("file_id"),
        content_class=state.get("content_class"),
        ocr_pages=state.get("ocr_pages", []),
    )
    warnings = list(state.get("warnings", []))
    if any(segment.get("requires_segment_review") for segment in segments):
        warnings.append("document_segmentation_review_recommended")
    return {"document_segments": segments, "warnings": warnings}

def _chunk_content_node(state: DocumentPipelineState) -> dict[str, Any]:
    chunks = chunk_content(state["extraction_result"], state["extraction_quality"])
    return {"chunks": attach_segment_ids_to_chunks(chunks, state.get("document_segments", []))}

def _after_quality_gate(state: DocumentPipelineState) -> str:
    return "chunk" if state.get("extraction_quality", {}).get("can_chunk") else "route"
