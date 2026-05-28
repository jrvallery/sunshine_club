"""Extraction validation, repair, and quality gate nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.model_usage import _ocr_model_usage_rows
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.extraction import OcrArtifacts, validate_and_repair_extraction
from sunshine_extraction.services.quality import (
    extraction_quality_gate,
    quality_gate_row,
    validate_extracted_text,
    validation_row,
    with_text_validation,
)


def _validate_extraction_node(state: DocumentPipelineState) -> dict[str, Any]:
    original = state["extraction_result"]
    validation = validate_extracted_text(original)
    return {
        "extraction_validation": validation_row(state["sample"], original, validation),
        "extraction_result": with_text_validation(original, validation),
    }


def _repair_or_escalate_extraction_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    original = state["extraction_result"]
    validation = state.get("extraction_validation", {})
    if validation.get("status") != "failed":
        return {
            "extraction_repair": {
                "source_path": state["sample"].source_path,
                "relative_path": state["sample"].relative_path,
                "sample_path": str(state["sample"].sample_path),
                "status": "not_needed",
                "reason": validation.get("reason"),
                "repair_strategy": None,
            }
        }
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
        "extraction_repair": {
            "source_path": state["sample"].source_path,
            "relative_path": state["sample"].relative_path,
            "sample_path": str(state["sample"].sample_path),
            "status": "attempted",
            "reason": validation.get("reason"),
            "repair_strategy": repaired.plan.get("strategy"),
            "original_strategy": original.plan.get("strategy"),
            "result_status": repaired.extraction_status,
            "text_length": len(repaired.text or ""),
        },
        "warnings": [*state.get("warnings", []), *new_warnings],
    }
    if ocr_artifacts.pages:
        updates["ocr_pages"] = [*state.get("ocr_pages", []), *ocr_artifacts.pages]
    if ocr_artifacts.documents:
        updates["ocr_document"] = ocr_artifacts.documents[-1]
    usage_rows = _ocr_model_usage_rows(state, ocr_artifacts.pages, node="repair_or_escalate_extraction")
    if usage_rows:
        updates["model_usage"] = [*state.get("model_usage", []), *usage_rows]
    return updates


def _quality_gate(state: DocumentPipelineState) -> dict[str, Any]:
    quality = extraction_quality_gate(state["extraction_result"])
    row = quality_gate_row(
        state["sample"],
        state["extraction_result"],
        quality,
        extraction_provider_selection=state.get("extraction_provider_selection"),
        extraction_validation=state.get("extraction_validation"),
        extraction_repair=state.get("extraction_repair"),
    )
    return {"extraction_quality": quality, "quality_gate_result": row}


def _after_quality_gate(state: DocumentPipelineState) -> str:
    return "chunk" if state.get("extraction_quality", {}).get("can_chunk") else "route"
