"""Batch orchestration for running the graph over QA samples."""

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

from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.graph.utils import _progress, _write_jsonl
from sunshine_extraction.providers.extraction import ExtractionProvider

def run_document_batch(
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    corrected_path: str | Path = DEFAULT_CORRECTED_PATH,
    plan_path: str | Path = DEFAULT_PLAN_PATH,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY_PATH,
    limit: int | None = None,
    extraction_provider: ExtractionProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_index_path: str | Path | None = None,
    progress: bool = False,
    checkpoint_path: str | Path | None = None,
    retry_attempts: int = 1,
    retry_delay_seconds: float = 0,
    max_concurrency: int = 1,
    rate_limit_seconds: float = 0,
) -> dict[str, Any]:
    """Run the single-file graph over a QA sample batch and aggregate artifacts."""

    input_root_path = Path(input_root)
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    graph_runs_dir = output_dir_path / "graph-runs"
    graph_runs_dir.mkdir(parents=True, exist_ok=True)

    corrected_by_key = _rows_by_key(corrected_path)
    plan_by_key = _rows_by_key(plan_path)
    samples = select_sample_files(input_root_path)
    if limit is not None:
        samples = samples[:limit]
    _progress(progress, f"langgraph-batch: input_root={input_root_path}")
    _progress(progress, f"langgraph-batch: output_dir={output_dir_path}")
    _progress(progress, f"langgraph-batch: selected_samples={len(samples)}")

    artifact_rows: dict[str, list[dict[str, Any]]] = {
        "sample-source-identity.jsonl": [],
        "sample-file-probes.jsonl": [],
        "sample-provider-selections.jsonl": [],
        "sample-inputs.jsonl": [],
        "sample-extraction-results.jsonl": [],
        "sample-provider-attempts.jsonl": [],
        "sample-ocr-pages.jsonl": [],
        "sample-ocr-documents.jsonl": [],
        "sample-structure.jsonl": [],
        "sample-document-segments.jsonl": [],
        "sample-chunks.jsonl": [],
        "sample-embeddings.jsonl": [],
        "sample-indexing.jsonl": [],
        "sample-semantic-examples.jsonl": [],
        "sample-llm-tag-inspections.jsonl": [],
        "sample-tag-candidates.jsonl": [],
        "sample-model-usage.jsonl": [],
        "sample-pipeline-results.jsonl": [],
        "sample-review-queue.jsonl": [],
        "graph-audit-events.jsonl": [],
    }
    graph_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    summary_counter: dict[str, Counter[str]] = _empty_summary_counters()

    run_specs = []
    for index, sample in enumerate(samples, start=1):
        run_specs.append(
            {
                "index": index,
                "sample": sample,
                "corrected": load_existing_content_class(sample, corrected_by_key),
                "plan": load_existing_extraction_plan(sample, plan_by_key),
                "per_file_output": graph_runs_dir / f"{index:05d}",
            }
        )

    active_concurrency = max(1, int(max_concurrency))
    active_rate_limit = max(0.0, float(rate_limit_seconds))
    if active_concurrency == 1:
        indexed_results = []
        for spec in run_specs:
            indexed_results.append(
                (
                    spec["index"],
                    _run_batch_item(
                        spec,
                        len(samples),
                        taxonomy_path,
                        checkpoint_path,
                        retry_attempts,
                        retry_delay_seconds,
                        progress,
                        extraction_provider,
                        embedding_provider,
                        llm_tag_inspector,
                        ocr_executor,
                        semantic_index_path,
                    ),
                )
            )
            if active_rate_limit:
                time.sleep(active_rate_limit)
    else:
        indexed_results = []
        with ThreadPoolExecutor(max_workers=active_concurrency) as executor:
            futures = {}
            for spec in run_specs:
                futures[
                    executor.submit(
                        _run_batch_item,
                        spec,
                        len(samples),
                        taxonomy_path,
                        checkpoint_path,
                        retry_attempts,
                        retry_delay_seconds,
                        progress,
                        extraction_provider,
                        embedding_provider,
                        llm_tag_inspector,
                        ocr_executor,
                        semantic_index_path,
                    )
                ] = spec["index"]
                if active_rate_limit:
                    time.sleep(active_rate_limit)
            for future in as_completed(futures):
                indexed_results.append((futures[future], future.result()))

    for result_index, result in sorted(indexed_results, key=lambda item: item[0]):
        graph_results.append(result)
        errors.extend(result.get("errors", []))
        _append_batch_rows(artifact_rows, result)
        if result.get("final_result"):
            _update_batch_summary_counters(summary_counter, result["final_result"])
            _progress(
                progress,
                f"[{result_index}/{len(samples)}] graph route={result['final_result'].get('route_status')} tag={result['final_result'].get('top_tag_candidate') or 'none'}",
            )

    for filename, rows in artifact_rows.items():
        _write_jsonl(output_dir_path / filename, rows)

    covered_strategies = set(summary_counter["by_extraction_strategy"])
    summary = {
        "input_root": str(input_root_path),
        "output_dir": str(output_dir_path),
        "selected_sample_count": len(samples),
        "artifact_counts": {filename: len(rows) for filename, rows in artifact_rows.items()},
        "missing_expected_strategies": sorted(EXPECTED_STRATEGIES - covered_strategies),
        "graph_run_count": len(graph_results),
        "error_count": len(errors),
        "max_concurrency": active_concurrency,
        "rate_limit_seconds": active_rate_limit,
        **{name: dict(sorted(counter.items())) for name, counter in summary_counter.items()},
    }
    (output_dir_path / "sample-pipeline-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir_path / "sample-ocr-summary.json").write_text(
        json.dumps(build_ocr_summary(artifact_rows["sample-ocr-pages.jsonl"], artifact_rows["sample-ocr-documents.jsonl"]), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir_path / "graph-batch-summary.json").write_text(
        json.dumps(
            {
                "input_root": str(input_root_path),
                "output_dir": str(output_dir_path),
                "graph_run_count": len(graph_results),
                "error_count": len(errors),
                "errors": errors,
                "checkpoint_path": str(checkpoint_path) if checkpoint_path is not None else None,
                "max_concurrency": active_concurrency,
                "rate_limit_seconds": active_rate_limit,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _progress(progress, "langgraph-batch: complete")
    return summary


def _run_batch_item(
    spec: dict[str, Any],
    total_count: int,
    taxonomy_path: str | Path,
    checkpoint_path: str | Path | None,
    retry_attempts: int,
    retry_delay_seconds: float,
    progress: bool,
    extraction_provider: ExtractionProvider | None,
    embedding_provider: EmbeddingProvider | None,
    llm_tag_inspector: LLMTagInspector | None,
    ocr_executor: OcrExecutor | None,
    semantic_index_path: str | Path | None,
) -> dict[str, Any]:
    sample = spec["sample"]
    index = spec["index"]
    _progress(progress, f"[{index}/{total_count}] graph start {sample.sample_group} :: {sample.sample_path.name}")
    return run_document_graph(
        sample.sample_path,
        output_dir=spec["per_file_output"],
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        content_class=spec["corrected"],
        extraction_plan=spec["plan"],
        taxonomy_path=taxonomy_path,
        sample_group=sample.sample_group,
        sample_number=sample.sample_number or index,
        index_metadata=sample.index_row.get("metadata", {}),
        extraction_provider=extraction_provider,
        embedding_provider=embedding_provider,
        llm_tag_inspector=llm_tag_inspector,
        ocr_executor=ocr_executor,
        semantic_index_path=semantic_index_path,
        checkpoint_path=checkpoint_path,
        thread_id=f"batch:{sample.source_path}",
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )


def _rows_by_key(path: str | Path) -> dict[str, dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            row = json.loads(line)
            rows_by_key[row["source_path"]] = row
            rows_by_key[row["relative_path"]] = row
    return rows_by_key


def _append_batch_rows(artifact_rows: dict[str, list[dict[str, Any]]], result: dict[str, Any]) -> None:
    sample = result.get("sample")
    content_class = result.get("content_class")
    extraction_plan = result.get("extraction_plan")
    extraction_result = result.get("extraction_result")
    extraction_quality = result.get("extraction_quality")
    llm_tag_inspection = result.get("llm_tag_inspection")
    if sample and content_class and extraction_plan:
        artifact_rows["sample-inputs.jsonl"].append(sample_input_row(sample, content_class, extraction_plan))
    if result.get("source_identity"):
        artifact_rows["sample-source-identity.jsonl"].append(result["source_identity"])
    if result.get("file_probe"):
        artifact_rows["sample-file-probes.jsonl"].append(result["file_probe"])
    if result.get("extraction_provider_selection"):
        artifact_rows["sample-provider-selections.jsonl"].append(result["extraction_provider_selection"])
    if extraction_result and extraction_quality:
        artifact_rows["sample-extraction-results.jsonl"].append(extraction_result_row(extraction_result, extraction_quality))
    artifact_rows["sample-provider-attempts.jsonl"].extend(result.get("provider_attempts", []))
    artifact_rows["sample-ocr-pages.jsonl"].extend(result.get("ocr_pages", []))
    if result.get("ocr_document"):
        artifact_rows["sample-ocr-documents.jsonl"].append(result["ocr_document"])
    if result.get("document_structure"):
        artifact_rows["sample-structure.jsonl"].append(result["document_structure"])
    artifact_rows["sample-document-segments.jsonl"].extend(result.get("document_segments", []))
    artifact_rows["sample-chunks.jsonl"].extend(result.get("chunks", []))
    artifact_rows["sample-embeddings.jsonl"].extend(result.get("embeddings", []))
    if result.get("indexing_result"):
        artifact_rows["sample-indexing.jsonl"].append(result["indexing_result"])
    artifact_rows["sample-semantic-examples.jsonl"].extend(result.get("semantic_examples", []))
    if sample and llm_tag_inspection:
        artifact_rows["sample-llm-tag-inspections.jsonl"].append(llm_inspection_row(sample, llm_tag_inspection))
    artifact_rows["sample-tag-candidates.jsonl"].extend(result.get("tag_candidates", []))
    artifact_rows["sample-model-usage.jsonl"].extend(result.get("model_usage", []))
    if result.get("final_result"):
        artifact_rows["sample-pipeline-results.jsonl"].append(result["final_result"])
        review_row = _review_queue_row(result["final_result"])
        if review_row:
            artifact_rows["sample-review-queue.jsonl"].append(review_row)
    for event in result.get("audit_events", []):
        artifact_rows["graph-audit-events.jsonl"].append(
            {
                "run_id": result.get("run_id"),
                "source_path": result.get("source_path"),
                "relative_path": result.get("relative_path"),
                **event,
            }
        )


def _empty_summary_counters() -> dict[str, Counter[str]]:
    return {
        "by_sample_group": Counter(),
        "by_final_class": Counter(),
        "by_extraction_strategy": Counter(),
        "by_extraction_status": Counter(),
        "by_quality": Counter(),
        "by_ocr_status": Counter(),
        "by_ocr_quality": Counter(),
        "by_chunk_count_bucket": Counter(),
        "by_embedding_status": Counter(),
        "by_llm_status": Counter(),
        "by_top_tag_candidate": Counter(),
        "by_secondary_tag": Counter(),
        "by_route_status": Counter(),
        "by_warning": Counter(),
    }


def _update_batch_summary_counters(counters: dict[str, Counter[str]], result: dict[str, Any]) -> None:
    counters["by_sample_group"][str(result.get("sample_group") or "unknown")] += 1
    counters["by_final_class"][str(result.get("final_class") or "unknown")] += 1
    counters["by_extraction_strategy"][str(result.get("extraction_strategy") or "unknown")] += 1
    counters["by_extraction_status"][str(result.get("extraction_status") or "unknown")] += 1
    counters["by_quality"][str(result.get("quality") or "unknown")] += 1
    if result.get("ocr_status"):
        counters["by_ocr_status"][str(result["ocr_status"])] += 1
        counters["by_ocr_quality"][str(result.get("quality") or "unknown")] += 1
    counters["by_chunk_count_bucket"][_chunk_count_bucket(int(result.get("chunk_count") or 0))] += 1
    counters["by_embedding_status"][str(result.get("embedding_status") or "none")] += 1
    counters["by_llm_status"][str(result.get("llm_status") or "unknown")] += 1
    counters["by_top_tag_candidate"][str(result.get("top_tag_candidate") or "none")] += 1
    for secondary_tag in result.get("secondary_tags", []):
        counters["by_secondary_tag"][str(secondary_tag)] += 1
    counters["by_route_status"][str(result.get("route_status") or "unknown")] += 1
    for warning in result.get("warnings", []):
        counters["by_warning"][str(warning)] += 1


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


def _chunk_count_bucket(chunk_count: int) -> str:
    if chunk_count == 0:
        return "0"
    if chunk_count == 1:
        return "1"
    if chunk_count <= 5:
        return "2-5"
    return "6+"
