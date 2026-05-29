"""Command-line interface for the Sunshine LangGraph pipeline."""

from __future__ import annotations

import argparse
import json
import os

from sunshine_extraction.config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_CORRECTED_PATH,
    DEFAULT_PLAN_PATH,
    DEFAULT_TAXONOMY_PATH,
)

from sunshine_extraction.graph.batch import run_document_batch
from sunshine_extraction.graph.deps import parse_semantic_retrieval_filter
from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.graph.utils import _json_safe
from sunshine_extraction.providers.extraction import extraction_provider_from_env
from sunshine_extraction.services.env import load_pipeline_env
from sunshine_extraction.services.extraction import ocr_executor_from_env
from sunshine_extraction.services.tagging import llm_tag_inspector_from_env

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
    parser.add_argument("--extraction-provider", choices=["current", "docling", "mineru", "ragflow_deepdoc", "unstructured"])
    parser.add_argument("--embedding-provider", choices=["cortex", "placeholder", "disabled"])
    parser.add_argument("--enable-llm-tags", action="store_true")
    parser.add_argument("--llm-tag-provider", choices=["auto", "cortex", "disabled"])
    parser.add_argument("--ocr-fallback-provider", choices=["openai", "cortex", "disabled"])
    parser.add_argument("--semantic-index-path")
    parser.add_argument("--semantic-retrieval-filter-json")
    parser.add_argument("--rerank-provider", choices=["cortex", "disabled"])
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
    if args.rerank_provider:
        os.environ["SUNSHINE_RERANK_PROVIDER"] = args.rerank_provider
    extraction_provider = extraction_provider_from_env(args.extraction_provider)
    inspector = llm_tag_inspector_from_env(
        enabled=args.enable_llm_tags,
        provider_override=args.llm_tag_provider or "auto",
    )
    ocr_executor = ocr_executor_from_env(fallback_provider_override=args.ocr_fallback_provider)
    semantic_retrieval_filter = parse_semantic_retrieval_filter(args.semantic_retrieval_filter_json)
    if args.input_root:
        summary = run_document_batch(
            args.input_root,
            output_dir=args.output_dir,
            corrected_path=args.corrected,
            plan_path=args.plan,
            taxonomy_path=args.taxonomy,
            limit=args.limit,
            extraction_provider=extraction_provider,
            llm_tag_inspector=inspector,
            ocr_executor=ocr_executor,
            progress=not args.quiet,
            checkpoint_path=args.checkpoint_path,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            max_concurrency=args.max_concurrency,
            rate_limit_seconds=args.rate_limit_seconds,
            semantic_index_path=args.semantic_index_path,
            semantic_retrieval_filter=semantic_retrieval_filter,
        )
        print(json.dumps(_json_safe(summary), indent=2, sort_keys=True))
    else:
        result = run_document_graph(
            args.input_file,
            output_dir=args.output_dir,
            source_path=args.source_path,
            relative_path=args.relative_path,
            taxonomy_path=args.taxonomy,
            extraction_provider=extraction_provider,
            llm_tag_inspector=inspector,
            ocr_executor=ocr_executor,
            checkpoint_path=args.checkpoint_path,
            thread_id=args.thread_id,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            semantic_index_path=args.semantic_index_path,
            semantic_retrieval_filter=semantic_retrieval_filter,
        )
        print(json.dumps(_json_safe(result.get("final_result", result)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
