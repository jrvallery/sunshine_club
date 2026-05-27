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

def _resolve_deps(
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_index_path: str | Path | None = None,
) -> DocumentPipelineDeps:
    if embedding_provider is None:
        try:
            embedding_provider = provider_from_env()
        except EmbeddingConfigurationError:
            embedding_provider = PlaceholderEmbeddingProvider()
    return {
        "embedding_provider": embedding_provider,
        "llm_tag_inspector": llm_tag_inspector or llm_tag_inspector_from_env(),
        "ocr_executor": ocr_executor or ocr_executor_from_env(),
        "semantic_index_path": str(semantic_index_path) if semantic_index_path is not None else _semantic_index_path_from_env(),
    }


def _semantic_index_path_from_env() -> str | None:
    configured = os.environ.get("SUNSHINE_SEMANTIC_INDEX_PATH", DEFAULT_INDEX_DB).strip()
    if not configured:
        return None
    return configured

