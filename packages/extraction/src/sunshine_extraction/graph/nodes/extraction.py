"""Extraction, validation, quality gate, and chunking nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.model_usage import _ocr_model_usage_rows
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.extraction import (
    OcrArtifacts,
    chunk_content,
    extract_content,
    extraction_quality_gate,
    validate_and_repair_extraction,
)


def _extract_content_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    ocr_artifacts = OcrArtifacts(pages=[], documents=[])
    extraction = extract_content(
        state["sample"],
        state["extraction_plan"],
        ocr_executor=deps["ocr_executor"],
        ocr_artifacts=ocr_artifacts,
    )
    updates: dict[str, Any] = {
        "extraction_result": extraction,
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

def _chunk_content_node(state: DocumentPipelineState) -> dict[str, Any]:
    return {"chunks": chunk_content(state["extraction_result"], state["extraction_quality"])}

def _after_quality_gate(state: DocumentPipelineState) -> str:
    return "chunk" if state.get("extraction_quality", {}).get("can_chunk") else "route"
