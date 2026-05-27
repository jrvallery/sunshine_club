"""Graph construction for the Sunshine document pipeline."""

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

from sunshine_extraction.graph.deps import _resolve_deps
from sunshine_extraction.graph.nodes import (
    _after_load_file_context,
    _after_quality_gate,
    _assign_deterministic_tags,
    _chunk_content_node,
    _classify_content_type,
    _combine_tag_evidence,
    _embed_chunks_node,
    _extract_content_node,
    _inspect_tags_with_llm,
    _load_file_context,
    _persist_outputs,
    _plan_extraction,
    _quality_gate,
    _resolve_route_or_review_node,
    _retrieve_labeled_examples_node,
    _run_node,
    _validate_text_extraction_node,
)

def build_document_graph(deps: DocumentPipelineDeps | None = None, *, checkpointer: Any | None = None) -> Any:
    active_deps = deps or _resolve_deps()
    builder = StateGraph(DocumentPipelineState)
    builder.add_node("load_file_context", lambda state: _run_node("load_file_context", state, _load_file_context))
    builder.add_node("classify_content_type", lambda state: _run_node("classify_content_type", state, _classify_content_type))
    builder.add_node("plan_extraction", lambda state: _run_node("plan_extraction", state, _plan_extraction))
    builder.add_node("extract_content", lambda state: _run_node("extract_content", state, lambda active: _extract_content_node(active, active_deps)))
    builder.add_node("validate_text_extraction", lambda state: _run_node("validate_text_extraction", state, lambda active: _validate_text_extraction_node(active, active_deps)))
    builder.add_node("quality_gate", lambda state: _run_node("quality_gate", state, _quality_gate))
    builder.add_node("chunk_content", lambda state: _run_node("chunk_content", state, _chunk_content_node))
    builder.add_node("embed_chunks", lambda state: _run_node("embed_chunks", state, lambda active: _embed_chunks_node(active, active_deps)))
    builder.add_node("retrieve_labeled_examples", lambda state: _run_node("retrieve_labeled_examples", state, lambda active: _retrieve_labeled_examples_node(active, active_deps)))
    builder.add_node("assign_deterministic_tags", lambda state: _run_node("assign_deterministic_tags", state, _assign_deterministic_tags))
    builder.add_node("inspect_tags_with_llm", lambda state: _run_node("inspect_tags_with_llm", state, lambda active: _inspect_tags_with_llm(active, active_deps)))
    builder.add_node("combine_tag_evidence", lambda state: _run_node("combine_tag_evidence", state, _combine_tag_evidence))
    builder.add_node("resolve_route_or_review", lambda state: _run_node("resolve_route_or_review", state, _resolve_route_or_review_node))
    builder.add_node("persist_outputs", lambda state: _run_node("persist_outputs", state, _persist_outputs))

    builder.add_edge(START, "load_file_context")
    builder.add_conditional_edges(
        "load_file_context",
        _after_load_file_context,
        {"continue": "classify_content_type", "persist": "persist_outputs"},
    )
    builder.add_edge("classify_content_type", "plan_extraction")
    builder.add_edge("plan_extraction", "extract_content")
    builder.add_edge("extract_content", "validate_text_extraction")
    builder.add_edge("validate_text_extraction", "quality_gate")
    builder.add_conditional_edges(
        "quality_gate",
        _after_quality_gate,
        {"chunk": "chunk_content", "route": "assign_deterministic_tags"},
    )
    builder.add_edge("chunk_content", "embed_chunks")
    builder.add_edge("embed_chunks", "retrieve_labeled_examples")
    builder.add_edge("retrieve_labeled_examples", "assign_deterministic_tags")
    builder.add_edge("assign_deterministic_tags", "inspect_tags_with_llm")
    builder.add_edge("inspect_tags_with_llm", "combine_tag_evidence")
    builder.add_edge("combine_tag_evidence", "resolve_route_or_review")
    builder.add_edge("resolve_route_or_review", "persist_outputs")
    builder.add_edge("persist_outputs", END)
    return builder.compile(checkpointer=checkpointer)

