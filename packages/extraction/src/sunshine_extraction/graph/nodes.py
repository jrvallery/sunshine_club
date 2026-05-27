"""LangGraph node implementations for document classification and extraction.

Nodes are kept together because they share the same state vocabulary and make
the graph's dataflow easier to inspect than scattered small modules.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    PlaceholderEmbeddingProvider,
    provider_from_env,
)
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.semantic_index import DEFAULT_INDEX_DB, search_semantic_index
from sunshine_extraction.sample_pipeline import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_CORRECTED_PATH,
    DEFAULT_INPUT_ROOT,
    DEFAULT_PLAN_PATH,
    DEFAULT_TAXONOMY_PATH,
    EXPECTED_STRATEGIES,
    IMAGE_EXTENSIONS,
    SPREADSHEET_EXTENSIONS,
    TEXT_EXTENSIONS,
    ExtractionResult,
    LLMTagInspector,
    OcrArtifacts,
    OcrExecutor,
    SampleFile,
    assign_tag_candidates,
    build_ocr_summary,
    chunk_content,
    combine_tag_candidates,
    embed_chunks_with_fallback,
    extract_content,
    extraction_quality_gate,
    extraction_result_row,
    llm_inspection_row,
    llm_tag_inspector_from_env,
    load_pipeline_env,
    load_existing_content_class,
    load_existing_extraction_plan,
    load_taxonomy_options,
    ocr_executor_from_env,
    resolve_route_or_review,
    sample_input_row,
    select_sample_files,
    validate_and_repair_extraction,
    write_pipeline_result,
)

from sunshine_extraction.graph.utils import _json_safe, _write_jsonl

def _run_node(name: str, state: DocumentPipelineState, func: Any) -> DocumentPipelineState:
    started = time.monotonic()
    before_warning_count = len(state.get("warnings", []))
    before_error_count = len(state.get("errors", []))
    max_attempts = max(1, int(state.get("retry_attempts", 1)))
    delay_seconds = max(0.0, float(state.get("retry_delay_seconds", 0)))
    attempts = 0
    last_error: Exception | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            updates = func(state)
            status = "ok"
            summary = _node_summary(name, updates)
            last_error = None
            break
        except Exception as error:  # noqa: BLE001 - graph failures need durable state.
            last_error = error
            if attempts < max_attempts and delay_seconds:
                time.sleep(delay_seconds)
    else:
        assert last_error is not None
        updates = {
            "errors": [
                *state.get("errors", []),
                {"node": name, "error_type": type(last_error).__name__, "message": str(last_error), "attempts": attempts},
            ]
        }
        status = "failed"
        summary = f"{type(last_error).__name__}: {last_error}"
    merged = _merge_state(state, updates)
    event = {
        "node": name,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": state.get("run_id"),
        "source_path": state.get("source_path"),
        "relative_path": state.get("relative_path"),
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "attempts": attempts,
        "warnings": merged.get("warnings", [])[before_warning_count:],
        "errors": merged.get("errors", [])[before_error_count:],
        "summary": summary,
    }
    merged["audit_events"] = [*state.get("audit_events", []), event]
    return merged


def _merge_state(state: DocumentPipelineState, updates: dict[str, Any]) -> DocumentPipelineState:
    merged: DocumentPipelineState = dict(state)
    for key, value in updates.items():
        if key in {"warnings", "errors"}:
            merged[key] = value
        else:
            merged[key] = value
    return merged


def _load_file_context(state: DocumentPipelineState) -> dict[str, Any]:
    input_path = Path(state["input_path"])
    if not input_path.exists():
        return {
            "errors": [
                *state.get("errors", []),
                {"node": "load_file_context", "error_type": "file_missing", "message": str(input_path)},
            ],
            "warnings": [*state.get("warnings", []), "file_missing"],
            "route": {"route_status": "review_failed_extraction", "review_reason": "file_missing"},
        }
    sample = SampleFile(
        sample_path=input_path,
        source_path=state.get("source_path") or str(input_path),
        relative_path=state.get("relative_path") or input_path.name,
        sample_group=state.get("sample_group", "single-file"),
        sample_number=state.get("sample_number", 1),
        index_row={"metadata": {"size_bytes": input_path.stat().st_size, **state.get("index_metadata", {})}},
    )
    return {
        "sample": sample,
        "filename": input_path.name,
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
    }


def _classify_content_type(state: DocumentPipelineState) -> dict[str, Any]:
    if state.get("content_class"):
        return {}

    sample = state["sample"]
    suffix = sample.sample_path.suffix.lower()
    mime_type = mimetypes.guess_type(sample.sample_path.name)[0]
    signals = {"suffix": suffix, "mime_type": mime_type}
    if suffix in IMAGE_EXTENSIONS:
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
        }
    }


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
    return updates


def _quality_gate(state: DocumentPipelineState) -> dict[str, Any]:
    return {"extraction_quality": extraction_quality_gate(state["extraction_result"])}


def _chunk_content_node(state: DocumentPipelineState) -> dict[str, Any]:
    return {"chunks": chunk_content(state["extraction_result"], state["extraction_quality"])}


def _embed_chunks_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    chunks = state.get("chunks", [])
    embeddings, embedding_warnings = embed_chunks_with_fallback(chunks, deps["embedding_provider"])
    return {"embeddings": embeddings, "warnings": [*state.get("warnings", []), *embedding_warnings]}


def _retrieve_labeled_examples_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    index_path = deps.get("semantic_index_path")
    if not index_path or not Path(index_path).exists():
        return {"semantic_examples": []}
    extraction = state.get("extraction_result") or _empty_extraction(state)
    query_text = "\n".join(
        [
            f"relative_path: {state.get('relative_path', '')}",
            f"filename: {state.get('filename', '')}",
            f"content_class: {state.get('content_class', {}).get('final_class', '')}",
            f"document_subtype: {state.get('extraction_plan', {}).get('document_subtype', '')}",
            f"text: {extraction.text[:2500]}",
        ]
    )
    warnings = [*state.get("warnings", [])]
    try:
        examples = search_semantic_index(index_path, query_text, embedding_provider=deps["embedding_provider"], limit=5)
    except Exception as error:  # noqa: BLE001 - retrieval failure should not block extraction.
        warnings.append(f"semantic_example_retrieval_failed:{type(error).__name__}")
        return {"semantic_examples": [], "warnings": warnings}
    return {"semantic_examples": examples, "warnings": warnings}


def _assign_deterministic_tags(state: DocumentPipelineState) -> dict[str, Any]:
    extraction = state.get("extraction_result") or _empty_extraction(state)
    candidates = assign_tag_candidates(state["sample"], state["content_class"], state["extraction_plan"], extraction)
    return {"deterministic_tag_candidates": candidates}


def _inspect_tags_with_llm(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    taxonomy = load_taxonomy_options(state.get("taxonomy_path", DEFAULT_TAXONOMY_PATH))
    extraction = state.get("extraction_result") or _empty_extraction(state)
    inspection = deps["llm_tag_inspector"].inspect(
        sample=state["sample"],
        corrected=state["content_class"],
        plan=state["extraction_plan"],
        extraction=extraction,
        taxonomy=taxonomy,
        deterministic_candidates=state.get("deterministic_tag_candidates", []),
        semantic_examples=state.get("semantic_examples", []),
    )
    warning = inspection.get("warning")
    warnings = [*state.get("warnings", [])]
    if warning:
        warnings.append(str(warning))
    return {"llm_tag_inspection": inspection, "warnings": warnings}


def _combine_tag_evidence(state: DocumentPipelineState) -> dict[str, Any]:
    return {
        "tag_candidates": combine_tag_candidates(
            state.get("deterministic_tag_candidates", []),
            state.get("llm_tag_inspection", {}),
            state.get("semantic_examples", []),
        )
    }


def _resolve_route_or_review_node(state: DocumentPipelineState) -> dict[str, Any]:
    return {
        "route": resolve_route_or_review(
            state.get("tag_candidates", []),
            state.get("extraction_quality", {"quality": "failed"}),
            state["extraction_plan"],
        )
    }


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
    if state.get("sample") and state.get("content_class") and state.get("extraction_plan"):
        artifacts["sample-inputs.jsonl"] = [sample_input_row(state["sample"], state["content_class"], state["extraction_plan"])]
    if state.get("extraction_result") and state.get("extraction_quality"):
        artifacts["sample-extraction-results.jsonl"] = [extraction_result_row(state["extraction_result"], state["extraction_quality"])]
    artifacts["sample-ocr-pages.jsonl"] = state.get("ocr_pages", [])
    artifacts["sample-ocr-documents.jsonl"] = [state["ocr_document"]] if state.get("ocr_document") else []
    artifacts["sample-chunks.jsonl"] = state.get("chunks", [])
    artifacts["sample-embeddings.jsonl"] = state.get("embeddings", [])
    artifacts["sample-semantic-examples.jsonl"] = state.get("semantic_examples", [])
    if state.get("sample") and state.get("llm_tag_inspection"):
        artifacts["sample-llm-tag-inspections.jsonl"] = [llm_inspection_row(state["sample"], state["llm_tag_inspection"])]
    artifacts["sample-tag-candidates.jsonl"] = state.get("tag_candidates", [])

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
        )
        result["semantic_example_count"] = len(state.get("semantic_examples", []))
        result["semantic_examples"] = state.get("semantic_examples", [])[:5]
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
        "confidence_inputs": {
            "candidate_count": len(state.get("tag_candidates", [])),
            "llm_confidence": state.get("llm_tag_inspection", {}).get("confidence"),
            "llm_needs_review": state.get("llm_tag_inspection", {}).get("needs_review"),
        },
        "semantic_example_count": len(state.get("semantic_examples", [])),
        "semantic_examples": state.get("semantic_examples", [])[:5],
        "route_status": state.get("route", {}).get("route_status", "review_failed_extraction"),
        "review_reason": state.get("route", {}).get("review_reason", "graph_failed_before_extraction"),
        "warnings": state.get("warnings", []),
        "errors": state.get("errors", []),
    }


def _empty_extraction(state: DocumentPipelineState) -> ExtractionResult:
    return ExtractionResult(
        sample=state["sample"],
        plan=state["extraction_plan"],
        extraction_status="failed",
        text="",
        metadata={},
        page_count=None,
        warnings=state.get("warnings", []),
    )


def _after_load_file_context(state: DocumentPipelineState) -> str:
    return "persist" if state.get("errors") and "sample" not in state else "continue"


def _after_quality_gate(state: DocumentPipelineState) -> str:
    return "chunk" if state.get("extraction_quality", {}).get("can_chunk") else "route"


def _node_summary(name: str, updates: dict[str, Any]) -> str:
    if name == "load_file_context" and updates.get("sample"):
        return f"loaded {updates['sample'].relative_path}"
    if name == "classify_content_type" and updates.get("content_class"):
        return f"classified {updates['content_class'].get('final_class')}"
    if name == "plan_extraction" and updates.get("extraction_plan"):
        return f"planned {updates['extraction_plan'].get('strategy')}"
    if name == "extract_content" and updates.get("extraction_result"):
        return f"extracted {updates['extraction_result'].extraction_status}"
    if name == "validate_text_extraction" and updates.get("extraction_result"):
        return f"validated {updates['extraction_result'].plan.get('strategy')}"
    if name == "quality_gate" and updates.get("extraction_quality"):
        return f"quality {updates['extraction_quality'].get('quality')}"
    if name == "chunk_content":
        return f"chunks {len(updates.get('chunks', []))}"
    if name == "embed_chunks":
        return f"embeddings {len(updates.get('embeddings', []))}"
    if name == "retrieve_labeled_examples":
        return f"semantic examples {len(updates.get('semantic_examples', []))}"
    if name == "assign_deterministic_tags":
        return f"deterministic candidates {len(updates.get('deterministic_tag_candidates', []))}"
    if name == "inspect_tags_with_llm" and updates.get("llm_tag_inspection"):
        return f"llm {updates['llm_tag_inspection'].get('llm_status')}"
    if name == "combine_tag_evidence":
        return f"tag candidates {len(updates.get('tag_candidates', []))}"
    if name == "resolve_route_or_review" and updates.get("route"):
        return f"route {updates['route'].get('route_status')}"
    if name == "persist_outputs":
        return "persisted graph outputs"
    return "completed"
