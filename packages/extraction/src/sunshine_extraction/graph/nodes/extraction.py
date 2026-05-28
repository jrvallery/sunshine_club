"""Extraction provider selection and content extraction nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.model_usage import _ocr_model_usage_rows
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.providers.extraction.factory import extraction_provider_from_name
from sunshine_extraction.providers.extraction.router import select_extraction_provider
from sunshine_extraction.services.extraction import (
    OcrArtifacts,
)
from sunshine_extraction.services.raw_provider_artifacts import write_raw_provider_artifact


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
    raw_artifact = write_raw_provider_artifact(state["output_dir"], extraction, provider_attempt_row)
    if raw_artifact:
        extraction = _with_raw_provider_artifact(extraction, raw_artifact)
        provider_attempt_row = {
            **provider_attempt_row,
            "metadata": {**provider_attempt_row.get("metadata", {}), "raw_provider_artifact": raw_artifact},
        }
    updates: dict[str, Any] = {
        "extraction_result": extraction,
        "provider_attempts": [*state.get("provider_attempts", []), provider_attempt_row],
        "raw_provider_artifacts": [*state.get("raw_provider_artifacts", []), raw_artifact] if raw_artifact else state.get("raw_provider_artifacts", []),
        "ocr_pages": ocr_artifacts.pages,
        "warnings": [*state.get("warnings", []), *extraction.warnings],
    }
    if ocr_artifacts.documents:
        updates["ocr_document"] = ocr_artifacts.documents[0]
    usage_rows = _ocr_model_usage_rows(state, ocr_artifacts.pages, node="extract_content")
    if usage_rows:
        updates["model_usage"] = [*state.get("model_usage", []), *usage_rows]
    return updates


def _with_raw_provider_artifact(extraction: Any, raw_artifact: dict[str, Any]) -> Any:
    return type(extraction)(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata={**extraction.metadata, "raw_provider_artifact": raw_artifact},
        page_count=extraction.page_count,
        warnings=extraction.warnings,
    )


def _provider_for_selection(selection: dict[str, Any], deps: DocumentPipelineDeps) -> Any:
    selected = str(selection.get("selected_provider") or "").lower()
    configured = deps["extraction_provider"]
    configured_name = str(getattr(configured, "provider_name", "")).lower()
    if not selected or selected == configured_name:
        return configured
    return extraction_provider_from_name(selected)
