"""Single-document graph runtime entry points."""

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

from sunshine_extraction.graph.build import build_document_graph
from sunshine_extraction.graph.deps import SEMANTIC_INDEX_FROM_ENV, _resolve_deps
from sunshine_extraction.graph.utils import _json_safe, _write_jsonl
from sunshine_extraction.providers.chunking import ChunkingProvider
from sunshine_extraction.providers.extraction import ExtractionProvider
from sunshine_extraction.providers.vectorstores import VectorStoreProvider
from sunshine_extraction.services.imports import RunResultsImporter

def run_document_graph(
    input_file: str | Path,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    source_path: str | None = None,
    relative_path: str | None = None,
    content_class: dict[str, Any] | None = None,
    extraction_plan: dict[str, Any] | None = None,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY_PATH,
    sample_group: str = "single-file",
    sample_number: int = 1,
    index_metadata: dict[str, Any] | None = None,
    extraction_provider: ExtractionProvider | None = None,
    chunking_provider: ChunkingProvider | None = None,
    vector_store: VectorStoreProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_failure_mode: str | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    run_results_importer: RunResultsImporter | None = None,
    dashboard_run_id: int | None = None,
    semantic_index_path: str | Path | None | object = SEMANTIC_INDEX_FROM_ENV,
    progress: bool = False,
    checkpoint_path: str | Path | None = None,
    thread_id: str | None = None,
    retry_attempts: int = 1,
    retry_delay_seconds: float = 0,
) -> dict[str, Any]:
    """Run the single-file LangGraph pipeline and persist graph artifacts."""

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    active_thread_id = thread_id or str(uuid.uuid5(uuid.NAMESPACE_URL, str(Path(input_file).resolve())))
    state: DocumentPipelineState = {
        "run_id": str(uuid.uuid4()),
        "file_id": active_thread_id,
        "input_path": str(input_file),
        "source_path": source_path or str(input_file),
        "relative_path": relative_path or Path(input_file).name,
        "filename": Path(input_file).name,
        "output_dir": str(output_dir_path),
        "taxonomy_path": str(taxonomy_path),
        "sample_group": sample_group,
        "sample_number": sample_number,
        "warnings": [],
        "errors": [],
        "audit_events": [],
        "retry_attempts": max(1, retry_attempts),
        "retry_delay_seconds": max(0, retry_delay_seconds),
        "thread_id": active_thread_id,
    }
    if checkpoint_path is not None:
        state["checkpoint_path"] = str(checkpoint_path)
    if index_metadata is not None:
        state["index_metadata"] = index_metadata
    if content_class is not None:
        state["content_class"] = content_class
    if extraction_plan is not None:
        state["extraction_plan"] = extraction_plan
    if dashboard_run_id is not None:
        state["dashboard_run_id"] = dashboard_run_id

    deps = _resolve_deps(
        extraction_provider=extraction_provider,
        chunking_provider=chunking_provider,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        embedding_failure_mode=embedding_failure_mode,
        llm_tag_inspector=llm_tag_inspector,
        ocr_executor=ocr_executor,
        run_results_importer=run_results_importer,
        semantic_index_path=semantic_index_path,
    )
    config = {"configurable": {"thread_id": active_thread_id}}
    if checkpoint_path is not None:
        Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
        from langgraph.checkpoint.sqlite import SqliteSaver

        with SqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
            graph = build_document_graph(deps, checkpointer=checkpointer)
            result = graph.invoke(state, config=config)
    else:
        graph = build_document_graph(deps)
        result = graph.invoke(state)
    _write_jsonl(output_dir_path / "graph-audit-events.jsonl", result.get("audit_events", []))
    (output_dir_path / "graph-result.json").write_text(
        json.dumps(_json_safe(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
