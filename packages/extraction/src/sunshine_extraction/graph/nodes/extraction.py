"""Extraction provider selection and content extraction nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.model_usage import _ocr_model_usage_rows
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.providers.extraction.current import CurrentExtractionProvider
from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider
from sunshine_extraction.providers.extraction.router import select_extraction_provider
from sunshine_extraction.services.extraction import (
    OcrArtifacts,
)


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
