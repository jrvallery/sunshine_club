"""Extraction, validation, quality gate, and chunking nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.model_usage import _ocr_model_usage_rows
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.providers.extraction.current import CurrentExtractionProvider
from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider
from sunshine_extraction.providers.extraction.router import select_extraction_provider
from sunshine_extraction.services.extraction import (
    OcrArtifacts,
    chunk_content,
    extraction_quality_gate,
    validate_extracted_text,
    validate_and_repair_extraction,
)
from sunshine_extraction.services.segmentation.page_grouping import attach_segment_ids_to_chunks, propose_document_segments
from sunshine_extraction.services.structure import normalize_document_structure


def _select_extraction_provider_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    selection = select_extraction_provider(
        state["sample"],
        state["extraction_plan"],
        state.get("file_probe", {}),
        deps["extraction_provider"],
    )
    return {"extraction_provider_selection": selection}


def _extract_content_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    ocr_artifacts = OcrArtifacts(pages=[], documents=[])
    provider = _provider_for_selection(state.get("extraction_provider_selection", {}), deps)
    extraction_plan = {
        **state["extraction_plan"],
        "selected_provider": state.get("extraction_provider_selection", {}).get("selected_provider"),
        "provider_chain": state.get("extraction_provider_selection", {}).get("provider_chain", []),
    }
    extraction, provider_attempt = provider.extract(
        state["sample"],
        extraction_plan,
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


def _provider_for_selection(selection: dict[str, Any], deps: DocumentPipelineDeps) -> Any:
    selected = str(selection.get("selected_provider") or "").lower()
    configured = deps["extraction_provider"]
    configured_name = str(getattr(configured, "provider_name", "")).lower()
    if not selected or selected == configured_name:
        return configured
    if selected == "docling":
        return DoclingExtractionProvider()
    if selected == "current":
        return CurrentExtractionProvider()
    return configured

def _validate_extraction_node(state: DocumentPipelineState) -> dict[str, Any]:
    original = state["extraction_result"]
    validation = validate_extracted_text(original)
    validation_row = {
        "source_path": state["sample"].source_path,
        "relative_path": state["sample"].relative_path,
        "sample_path": str(state["sample"].sample_path),
        "status": validation.get("status"),
        "reason": validation.get("reason"),
        "strategy": original.plan.get("strategy"),
        "extraction_status": original.extraction_status,
        "text_length": len(original.text or ""),
    }
    return {
        "extraction_validation": validation_row,
        "extraction_result": _with_text_validation(original, validation),
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


def _with_text_validation(extraction: Any, validation: dict[str, Any]) -> Any:
    return type(extraction)(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata={**extraction.metadata, "text_validation": validation},
        page_count=extraction.page_count,
        warnings=extraction.warnings,
    )

def _quality_gate(state: DocumentPipelineState) -> dict[str, Any]:
    quality = extraction_quality_gate(state["extraction_result"])
    row = {
        "source_path": state["sample"].source_path,
        "relative_path": state["sample"].relative_path,
        "sample_path": str(state["sample"].sample_path),
        "quality": quality.get("quality"),
        "can_chunk": quality.get("can_chunk"),
        "can_embed": quality.get("can_embed"),
        "requires_review": quality.get("requires_review"),
        "extraction_status": state["extraction_result"].extraction_status,
        "strategy": state["extraction_result"].plan.get("strategy"),
        "provider": state["extraction_result"].metadata.get("provider")
        or state.get("extraction_provider_selection", {}).get("selected_provider"),
        "text_length": len(state["extraction_result"].text or ""),
        "validation_status": state.get("extraction_validation", {}).get("status"),
        "validation_reason": state.get("extraction_validation", {}).get("reason"),
        "repair_status": state.get("extraction_repair", {}).get("status"),
        "quality_evidence": _quality_evidence(state, quality),
    }
    return {"extraction_quality": quality, "quality_gate_result": row}


def _quality_evidence(state: DocumentPipelineState, quality: dict[str, Any]) -> list[str]:
    evidence = [f"quality:{quality.get('quality')}"]
    extraction = state["extraction_result"]
    evidence.append(f"extraction_status:{extraction.extraction_status}")
    if quality.get("requires_review"):
        evidence.append("requires_review:true")
    validation = state.get("extraction_validation", {})
    if validation.get("status"):
        evidence.append(f"validation:{validation.get('status')}")
    if validation.get("reason"):
        evidence.append(f"validation_reason:{validation.get('reason')}")
    repair = state.get("extraction_repair", {})
    if repair.get("status"):
        evidence.append(f"repair:{repair.get('status')}")
    ocr_document = extraction.metadata.get("ocr_document")
    if isinstance(ocr_document, dict):
        if ocr_document.get("quality"):
            evidence.append(f"ocr_quality:{ocr_document.get('quality')}")
        if ocr_document.get("mean_confidence") is not None:
            evidence.append(f"ocr_mean_confidence:{ocr_document.get('mean_confidence')}")
    if not extraction.text.strip() and extraction.metadata:
        evidence.append("metadata_only_candidate")
    return evidence

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
        content_class=state.get("content_class"),
        ocr_pages=state.get("ocr_pages", []),
        document_structure=state.get("document_structure"),
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
