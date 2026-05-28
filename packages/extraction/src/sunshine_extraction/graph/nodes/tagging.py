"""Tag assignment, LLM inspection, and confidence calibration nodes."""

from __future__ import annotations

import time
from typing import Any

from sunshine_extraction.graph.model_usage import _llm_tag_model_usage_row
from sunshine_extraction.graph.node_utils import _empty_extraction, _llm_inspection_warnings, _unique_strings
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.tagging import (
    DEFAULT_TAXONOMY_PATH,
    assign_tag_candidates,
    calibrate_tag_confidence,
    combine_tag_candidates,
    load_taxonomy_options,
)


def _assign_deterministic_tags(state: DocumentPipelineState) -> dict[str, Any]:
    extraction = state.get("extraction_result") or _empty_extraction(state)
    candidates = assign_tag_candidates(state["sample"], state["content_class"], state["extraction_plan"], extraction)
    return {"deterministic_tag_candidates": candidates}

def _inspect_tags_with_llm(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    taxonomy = load_taxonomy_options(state.get("taxonomy_path", DEFAULT_TAXONOMY_PATH))
    extraction = state.get("extraction_result") or _empty_extraction(state)
    started = time.monotonic()
    inspection = deps["llm_tag_inspector"].inspect(
        sample=state["sample"],
        corrected=state["content_class"],
        plan=state["extraction_plan"],
        extraction=extraction,
        taxonomy=taxonomy,
        deterministic_candidates=state.get("deterministic_tag_candidates", []),
        semantic_examples=state.get("semantic_examples", []),
    )
    warnings = _unique_strings([*state.get("warnings", []), *_llm_inspection_warnings(inspection)])
    usage_row = _llm_tag_model_usage_row(state, inspection, started=started)
    return {
        "llm_tag_inspection": inspection,
        "warnings": warnings,
        "model_usage": [*state.get("model_usage", []), usage_row] if usage_row else state.get("model_usage", []),
    }

def _combine_tag_evidence(state: DocumentPipelineState) -> dict[str, Any]:
    return {
        "tag_candidates": combine_tag_candidates(
            state.get("deterministic_tag_candidates", []),
            state.get("llm_tag_inspection", {}),
            state.get("semantic_examples", []),
        )
    }

def _calibrate_tag_confidence_node(state: DocumentPipelineState) -> dict[str, Any]:
    tag_candidates, calibration = calibrate_tag_confidence(
        state.get("tag_candidates", []),
        state.get("extraction_quality", {"quality": "failed", "requires_review": True}),
        state["extraction_plan"],
        llm_inspection=state.get("llm_tag_inspection", {}),
        semantic_examples=state.get("semantic_examples", []),
        embeddings=state.get("embeddings", []),
    )
    return {"tag_candidates": tag_candidates, "confidence_calibration": calibration}
