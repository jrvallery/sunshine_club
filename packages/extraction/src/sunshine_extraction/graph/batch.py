"""Batch orchestration for running the graph over QA samples."""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from sunshine_extraction.embeddings import EmbeddingProvider
from sunshine_extraction.config import (
    DEFAULT_CORRECTED_PATH,
    DEFAULT_INPUT_ROOT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PLAN_PATH,
    DEFAULT_TAXONOMY_PATH,
    EXPECTED_STRATEGIES,
)

from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.graph.utils import _progress, _write_jsonl
from sunshine_extraction.providers.chunking import ChunkingProvider
from sunshine_extraction.providers.extraction import ExtractionProvider
from sunshine_extraction.providers.reranking import RerankProvider
from sunshine_extraction.providers.retrieval import SemanticRetrievalProvider
from sunshine_extraction.services.artifacts import extraction_result_row, parser_result_row, sample_input_row
from sunshine_extraction.services.artifacts.review_queue import build_review_queue_rows
from sunshine_extraction.services.artifact_manifest import write_artifact_manifest
from sunshine_extraction.services.extraction import OcrExecutor
from sunshine_extraction.services.ocr_summary import build_ocr_summary
from sunshine_extraction.services.samples import load_existing_content_class, load_existing_extraction_plan, rows_by_key, select_sample_files
from sunshine_extraction.services.tagging import LLMTagInspector, llm_inspection_row


def run_document_batch(
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    corrected_path: str | Path = DEFAULT_CORRECTED_PATH,
    plan_path: str | Path = DEFAULT_PLAN_PATH,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY_PATH,
    limit: int | None = None,
    extraction_provider: ExtractionProvider | None = None,
    chunking_provider: ChunkingProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_retrieval_provider: SemanticRetrievalProvider | None = None,
    rerank_provider: RerankProvider | None = None,
    semantic_index_path: str | Path | None = None,
    semantic_retrieval_filter: dict[str, Any] | None = None,
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

    corrected_by_key = rows_by_key(corrected_path)
    plan_by_key = rows_by_key(plan_path)
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
        "sample-extraction-validations.jsonl": [],
        "sample-extraction-repairs.jsonl": [],
        "sample-quality-gates.jsonl": [],
        "sample-provider-attempts.jsonl": [],
        "sample-raw-provider-artifacts.jsonl": [],
        "sample-parser-results.jsonl": [],
        "sample-ocr-pages.jsonl": [],
        "sample-ocr-documents.jsonl": [],
        "sample-structure.jsonl": [],
        "sample-document-segments.jsonl": [],
        "sample-chunking-results.jsonl": [],
        "sample-chunks.jsonl": [],
        "sample-embedding-results.jsonl": [],
        "sample-embeddings.jsonl": [],
        "sample-indexing.jsonl": [],
        "sample-retrieval-results.jsonl": [],
        "sample-semantic-examples.jsonl": [],
        "sample-placement-proposals.jsonl": [],
        "sample-route-decisions.jsonl": [],
        "sample-llm-tag-inspection-results.jsonl": [],
        "sample-llm-tag-inspections.jsonl": [],
        "sample-tag-candidates.jsonl": [],
        "sample-confidence-calibrations.jsonl": [],
        "sample-model-usage.jsonl": [],
        "sample-import-results.jsonl": [],
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
                        chunking_provider,
                        embedding_provider,
                        llm_tag_inspector,
                        ocr_executor,
                        semantic_retrieval_provider,
                        rerank_provider,
                        semantic_index_path,
                        semantic_retrieval_filter,
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
                        chunking_provider,
                        embedding_provider,
                        llm_tag_inspector,
                        ocr_executor,
                        semantic_retrieval_provider,
                        rerank_provider,
                        semantic_index_path,
                        semantic_retrieval_filter,
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
    write_artifact_manifest(
        output_dir_path,
        expected_names=[
            *artifact_rows.keys(),
            "sample-pipeline-summary.json",
            "sample-ocr-summary.json",
            "graph-batch-summary.json",
        ],
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
    chunking_provider: ChunkingProvider | None,
    embedding_provider: EmbeddingProvider | None,
    llm_tag_inspector: LLMTagInspector | None,
    ocr_executor: OcrExecutor | None,
    semantic_retrieval_provider: SemanticRetrievalProvider | None,
    rerank_provider: RerankProvider | None,
    semantic_index_path: str | Path | None,
    semantic_retrieval_filter: dict[str, Any] | None,
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
        chunking_provider=chunking_provider,
        embedding_provider=embedding_provider,
        llm_tag_inspector=llm_tag_inspector,
        ocr_executor=ocr_executor,
        semantic_retrieval_provider=semantic_retrieval_provider,
        rerank_provider=rerank_provider,
        semantic_index_path=semantic_index_path,
        semantic_retrieval_filter=semantic_retrieval_filter,
        checkpoint_path=checkpoint_path,
        thread_id=f"batch:{sample.source_path}",
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )


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
    if result.get("extraction_validation"):
        artifact_rows["sample-extraction-validations.jsonl"].append(result["extraction_validation"])
    if result.get("extraction_repair"):
        artifact_rows["sample-extraction-repairs.jsonl"].append(result["extraction_repair"])
    if result.get("quality_gate_result"):
        artifact_rows["sample-quality-gates.jsonl"].append(result["quality_gate_result"])
    artifact_rows["sample-provider-attempts.jsonl"].extend(result.get("provider_attempts", []))
    artifact_rows["sample-raw-provider-artifacts.jsonl"].extend(result.get("raw_provider_artifacts", []))
    if extraction_result and extraction_quality:
        artifact_rows["sample-parser-results.jsonl"].append(
            parser_result_row(
                extraction_result,
                extraction_quality,
                provider_selection=result.get("extraction_provider_selection"),
                provider_attempts=result.get("provider_attempts", []),
                document_structure=result.get("document_structure"),
            )
        )
    artifact_rows["sample-ocr-pages.jsonl"].extend(result.get("ocr_pages", []))
    if result.get("ocr_document"):
        artifact_rows["sample-ocr-documents.jsonl"].append(result["ocr_document"])
    if result.get("document_structure"):
        artifact_rows["sample-structure.jsonl"].append(result["document_structure"])
    artifact_rows["sample-document-segments.jsonl"].extend(result.get("document_segments", []))
    if result.get("chunking_result"):
        artifact_rows["sample-chunking-results.jsonl"].append(result["chunking_result"])
    artifact_rows["sample-chunks.jsonl"].extend(result.get("chunks", []))
    if result.get("embedding_result"):
        artifact_rows["sample-embedding-results.jsonl"].append(result["embedding_result"])
    artifact_rows["sample-embeddings.jsonl"].extend(result.get("embeddings", []))
    if result.get("indexing_result"):
        artifact_rows["sample-indexing.jsonl"].append(result["indexing_result"])
    if result.get("retrieval_result"):
        artifact_rows["sample-retrieval-results.jsonl"].append(result["retrieval_result"])
    artifact_rows["sample-semantic-examples.jsonl"].extend(result.get("semantic_examples", []))
    if result.get("placement_proposal"):
        artifact_rows["sample-placement-proposals.jsonl"].append(result["placement_proposal"])
    if result.get("route_decision"):
        artifact_rows["sample-route-decisions.jsonl"].append(result["route_decision"])
    if result.get("llm_tag_inspection_result"):
        artifact_rows["sample-llm-tag-inspection-results.jsonl"].append(result["llm_tag_inspection_result"])
    if sample and llm_tag_inspection:
        artifact_rows["sample-llm-tag-inspections.jsonl"].append(llm_inspection_row(sample, llm_tag_inspection))
    artifact_rows["sample-tag-candidates.jsonl"].extend(result.get("tag_candidates", []))
    if result.get("confidence_calibration_result"):
        artifact_rows["sample-confidence-calibrations.jsonl"].append(result["confidence_calibration_result"])
    artifact_rows["sample-model-usage.jsonl"].extend(result.get("model_usage", []))
    if result.get("import_result"):
        artifact_rows["sample-import-results.jsonl"].append(result["import_result"])
    if result.get("final_result"):
        artifact_rows["sample-pipeline-results.jsonl"].append(result["final_result"])
        artifact_rows["sample-review-queue.jsonl"].extend(
            build_review_queue_rows(result["final_result"], result.get("document_segments", []))
        )
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


def _chunk_count_bucket(chunk_count: int) -> str:
    if chunk_count == 0:
        return "0"
    if chunk_count == 1:
        return "1"
    if chunk_count <= 5:
        return "2-5"
    return "6+"
