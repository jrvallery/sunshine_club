"""Command-line interface for the Sunshine LangGraph pipeline."""

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

from sunshine_extraction.graph.batch import run_document_batch
from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.graph.utils import _json_safe

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sunshine LangGraph pipeline.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-file")
    input_group.add_argument("--input-root")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--source-path")
    parser.add_argument("--relative-path")
    parser.add_argument("--corrected", default=str(DEFAULT_CORRECTED_PATH))
    parser.add_argument("--plan", default=str(DEFAULT_PLAN_PATH))
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY_PATH))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--embedding-provider", choices=["cortex", "openai", "disabled"])
    parser.add_argument("--enable-llm-tags", action="store_true")
    parser.add_argument("--llm-tag-provider", choices=["auto", "gemini", "cortex", "openai", "disabled"])
    parser.add_argument("--ocr-fallback-provider", choices=["openai", "cortex", "openai-compatible", "local", "disabled"])
    parser.add_argument("--semantic-index-path")
    parser.add_argument("--checkpoint-path")
    parser.add_argument("--thread-id")
    parser.add_argument("--retry-attempts", type=int, default=1)
    parser.add_argument("--retry-delay-seconds", type=float, default=0)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--rate-limit-seconds", type=float, default=0)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_pipeline_env()
    if args.embedding_provider:
        os.environ["SUNSHINE_EMBEDDING_PROVIDER"] = "placeholder" if args.embedding_provider == "disabled" else args.embedding_provider
    inspector = llm_tag_inspector_from_env(
        enabled=args.enable_llm_tags,
        provider_override=args.llm_tag_provider or "auto",
    )
    ocr_executor = ocr_executor_from_env(fallback_provider_override=args.ocr_fallback_provider)
    if args.input_root:
        summary = run_document_batch(
            args.input_root,
            output_dir=args.output_dir,
            corrected_path=args.corrected,
            plan_path=args.plan,
            taxonomy_path=args.taxonomy,
            limit=args.limit,
            llm_tag_inspector=inspector,
            ocr_executor=ocr_executor,
            progress=not args.quiet,
            checkpoint_path=args.checkpoint_path,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            max_concurrency=args.max_concurrency,
            rate_limit_seconds=args.rate_limit_seconds,
            semantic_index_path=args.semantic_index_path,
        )
        print(json.dumps(_json_safe(summary), indent=2, sort_keys=True))
    else:
        result = run_document_graph(
            args.input_file,
            output_dir=args.output_dir,
            source_path=args.source_path,
            relative_path=args.relative_path,
            taxonomy_path=args.taxonomy,
            llm_tag_inspector=inspector,
            ocr_executor=ocr_executor,
            checkpoint_path=args.checkpoint_path,
            thread_id=args.thread_id,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            semantic_index_path=args.semantic_index_path,
        )
        print(json.dumps(_json_safe(result.get("final_result", result)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
