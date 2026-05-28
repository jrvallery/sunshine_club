"""Output persistence and final-result assembly nodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sunshine_extraction.graph.node_utils import _unique_strings
from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.graph.utils import _json_safe, _write_jsonl
from sunshine_extraction.services.artifacts import extraction_result_row, sample_input_row, write_pipeline_result
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.tagging import llm_inspection_row


def _persist_outputs(state: DocumentPipelineState) -> dict[str, Any]:
    output_dir = Path(state["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    final_result = state.get("final_result")
    if not final_result:
        final_result = _final_result_from_state(state)

    artifacts: dict[str, list[dict[str, Any]]] = {
        "graph-audit-events.jsonl": state.get("audit_events", []),
        "sample-pipeline-results.jsonl": [final_result],
        "sample-review-queue.jsonl": [_review_queue_row(final_result)] if _review_queue_row(final_result) else [],
    }
    artifacts["sample-source-identity.jsonl"] = [state["source_identity"]] if state.get("source_identity") else []
    if state.get("sample") and state.get("content_class") and state.get("extraction_plan"):
        artifacts["sample-inputs.jsonl"] = [sample_input_row(state["sample"], state["content_class"], state["extraction_plan"])]
    if state.get("extraction_result") and state.get("extraction_quality"):
        artifacts["sample-extraction-results.jsonl"] = [extraction_result_row(state["extraction_result"], state["extraction_quality"])]
    artifacts["sample-provider-attempts.jsonl"] = state.get("provider_attempts", [])
    artifacts["sample-ocr-pages.jsonl"] = state.get("ocr_pages", [])
    artifacts["sample-ocr-documents.jsonl"] = [state["ocr_document"]] if state.get("ocr_document") else []
    artifacts["sample-structure.jsonl"] = [state["document_structure"]] if state.get("document_structure") else []
    artifacts["sample-document-segments.jsonl"] = state.get("document_segments", [])
    artifacts["sample-chunks.jsonl"] = state.get("chunks", [])
    artifacts["sample-embeddings.jsonl"] = state.get("embeddings", [])
    artifacts["sample-indexing.jsonl"] = [state["indexing_result"]] if state.get("indexing_result") else []
    artifacts["sample-semantic-examples.jsonl"] = state.get("semantic_examples", [])
    if state.get("sample") and state.get("llm_tag_inspection"):
        artifacts["sample-llm-tag-inspections.jsonl"] = [llm_inspection_row(state["sample"], state["llm_tag_inspection"])]
    artifacts["sample-tag-candidates.jsonl"] = state.get("tag_candidates", [])
    artifacts["sample-model-usage.jsonl"] = state.get("model_usage", [])

    for filename, rows in artifacts.items():
        _write_jsonl(output_dir / filename, rows)

    graph_result = _json_safe({**state, "final_result": final_result})
    (output_dir / "graph-result.json").write_text(json.dumps(graph_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"final_result": final_result}

def _review_queue_row(final_result: dict[str, Any]) -> dict[str, Any] | None:
    route_status = final_result.get("route_status")
    if route_status == "route_candidate":
        return None
    return {
        "sample_path": final_result.get("sample_path"),
        "source_path": final_result.get("source_path"),
        "relative_path": final_result.get("relative_path"),
        "route_status": route_status,
        "review_reason": final_result.get("review_reason"),
        "final_class": final_result.get("final_class"),
        "extraction_strategy": final_result.get("extraction_strategy"),
        "extraction_status": final_result.get("extraction_status"),
        "quality": final_result.get("quality"),
        "top_tag_candidate": final_result.get("top_tag_candidate"),
        "tag_confidence": final_result.get("tag_confidence"),
        "warnings": final_result.get("warnings", []),
    }

def _final_result_from_state(state: DocumentPipelineState) -> dict[str, Any]:
    if state.get("extraction_result") and state.get("extraction_quality"):
        result = write_pipeline_result(
            state["sample"],
            state["content_class"],
            state["extraction_plan"],
            state["extraction_result"],
            state["extraction_quality"],
            state.get("chunks", []),
            state.get("embeddings", []),
            state.get("tag_candidates", []),
            state.get("route", {"route_status": "review_failed_extraction", "review_reason": "unknown"}),
            state.get("llm_tag_inspection", {}),
            state.get("confidence_calibration", {}),
        )
        result["semantic_example_count"] = len(state.get("semantic_examples", []))
        result["semantic_examples"] = state.get("semantic_examples", [])[:5]
        if state.get("source_identity"):
            result["file_id"] = state["source_identity"].get("file_id")
            result["content_sha256"] = state["source_identity"].get("content_sha256")
            result["size_bytes"] = state["source_identity"].get("size_bytes")
        result["warnings"] = _unique_strings([*result.get("warnings", []), *state.get("warnings", [])])
        return result
    return {
        "sample_path": state.get("input_path"),
        "source_path": state.get("source_path"),
        "relative_path": state.get("relative_path"),
        "sample_group": state.get("sample_group", "single-file"),
        "final_class": state.get("content_class", {}).get("final_class", "unknown"),
        "document_subtype": state.get("extraction_plan", {}).get("document_subtype"),
        "extraction_strategy": state.get("extraction_plan", {}).get("strategy"),
        "extraction_status": "failed",
        "quality": "failed",
        "chunk_count": 0,
        "embedding_status": "none",
        "top_tag_candidate": None,
        "tag_confidence": None,
        "tag_evidence": [],
        "competing_tags": [],
        "secondary_tags": [],
        "tag_assignment_source": None,
        "placement": None,
        "destination_path": None,
        "placement_status": "needs_review",
        "placement_rule": None,
        "placement_date_confidence": "missing",
        "default_privacy": "restricted",
        "reviewer_role": None,
        "llm_status": state.get("llm_tag_inspection", {}).get("llm_status"),
        "llm_provider": state.get("llm_tag_inspection", {}).get("provider"),
        "llm_primary_tag": state.get("llm_tag_inspection", {}).get("primary_tag"),
        "llm_confidence": state.get("llm_tag_inspection", {}).get("confidence"),
        "llm_competing_tags": state.get("llm_tag_inspection", {}).get("competing_tags", []),
        "llm_review_reason": state.get("llm_tag_inspection", {}).get("review_reason"),
        "confidence_inputs": {
            "candidate_count": len(state.get("tag_candidates", [])),
            "llm_confidence": state.get("llm_tag_inspection", {}).get("confidence"),
            "llm_needs_review": state.get("llm_tag_inspection", {}).get("needs_review"),
            "llm_competing_tags": state.get("llm_tag_inspection", {}).get("competing_tags", []),
            "llm_review_reason": state.get("llm_tag_inspection", {}).get("review_reason"),
        },
        "semantic_example_count": len(state.get("semantic_examples", [])),
        "semantic_examples": state.get("semantic_examples", [])[:5],
        "route_status": state.get("route", {}).get("route_status", "review_failed_extraction"),
        "review_reason": state.get("route", {}).get("review_reason", "graph_failed_before_extraction"),
        "warnings": state.get("warnings", []),
        "errors": state.get("errors", []),
        "file_id": state.get("source_identity", {}).get("file_id") or state.get("file_id"),
        "content_sha256": state.get("source_identity", {}).get("content_sha256"),
        "size_bytes": state.get("source_identity", {}).get("size_bytes"),
    }
