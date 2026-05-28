"""Dependency resolution for graph providers and optional indexes."""

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

SEMANTIC_INDEX_FROM_ENV = object()


def _resolve_deps(
    *,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_failure_mode: str | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_index_path: str | Path | None | object = SEMANTIC_INDEX_FROM_ENV,
) -> DocumentPipelineDeps:
    if embedding_provider is None:
        try:
            embedding_provider = provider_from_env()
        except EmbeddingConfigurationError:
            embedding_provider = PlaceholderEmbeddingProvider()
    return {
        "embedding_provider": embedding_provider,
        "embedding_failure_mode": _embedding_failure_mode(embedding_failure_mode),
        "llm_tag_inspector": llm_tag_inspector or llm_tag_inspector_from_env(),
        "ocr_executor": ocr_executor or ocr_executor_from_env(),
        "semantic_index_path": _resolve_semantic_index_path(semantic_index_path),
    }


def _embedding_failure_mode(configured: str | None) -> str:
    mode = (configured or os.environ.get("SUNSHINE_EMBEDDING_FAILURE_MODE") or "fallback").strip().lower()
    if mode in {"review", "fail_closed", "fail-closed", "strict"}:
        return "review"
    return "fallback"


def _semantic_index_path_from_env() -> str | None:
    configured = os.environ.get("SUNSHINE_SEMANTIC_INDEX_PATH", "").strip()
    if not configured:
        return None
    return configured


def _resolve_semantic_index_path(semantic_index_path: str | Path | None | object) -> str | None:
    if semantic_index_path is SEMANTIC_INDEX_FROM_ENV:
        return _semantic_index_path_from_env()
    if semantic_index_path is None:
        return None
    return str(semantic_index_path)
