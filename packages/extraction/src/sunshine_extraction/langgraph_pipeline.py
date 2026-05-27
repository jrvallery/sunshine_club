"""Single-file LangGraph pipeline for Sunshine Club documents."""

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
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    PlaceholderEmbeddingProvider,
    provider_from_env,
)
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


class DocumentPipelineState(TypedDict, total=False):
    run_id: str
    file_id: str
    input_path: str
    source_path: str
    relative_path: str
    filename: str
    output_dir: str
    taxonomy_path: str
    sample_group: str
    sample_number: int
    index_metadata: dict[str, Any]
    retry_attempts: int
    retry_delay_seconds: float
    checkpoint_path: str
    thread_id: str

    sample: SampleFile
    content_class: dict[str, Any]
    extraction_plan: dict[str, Any]
    extraction_result: ExtractionResult
    extraction_quality: dict[str, Any]
    ocr_pages: list[dict[str, Any]]
    ocr_document: dict[str, Any]
    chunks: list[dict[str, Any]]
    embeddings: list[dict[str, Any]]
    semantic_examples: list[dict[str, Any]]
    deterministic_tag_candidates: list[dict[str, Any]]
    llm_tag_inspection: dict[str, Any]
    tag_candidates: list[dict[str, Any]]
    route: dict[str, Any]
    final_result: dict[str, Any]

    warnings: list[str]
    errors: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]


class DocumentPipelineDeps(TypedDict, total=False):
    embedding_provider: EmbeddingProvider
    llm_tag_inspector: LLMTagInspector
    ocr_executor: OcrExecutor
    semantic_index_path: str | None


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
    embedding_provider: EmbeddingProvider | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_index_path: str | Path | None = None,
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

    deps = _resolve_deps(
        embedding_provider=embedding_provider,
        llm_tag_inspector=llm_tag_inspector,
        ocr_executor=ocr_executor,
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


def run_document_batch(
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    corrected_path: str | Path = DEFAULT_CORRECTED_PATH,
    plan_path: str | Path = DEFAULT_PLAN_PATH,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY_PATH,
    limit: int | None = None,
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
        "sample-inputs.jsonl": [],
        "sample-extraction-results.jsonl": [],
        "sample-ocr-pages.jsonl": [],
        "sample-ocr-documents.jsonl": [],
        "sample-chunks.jsonl": [],
        "sample-embeddings.jsonl": [],
        "sample-semantic-examples.jsonl": [],
        "sample-llm-tag-inspections.jsonl": [],
        "sample-tag-candidates.jsonl": [],
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


def _run_batch_item(
    spec: dict[str, Any],
    total_count: int,
    taxonomy_path: str | Path,
    checkpoint_path: str | Path | None,
    retry_attempts: int,
    retry_delay_seconds: float,
    progress: bool,
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
    if extraction_result and extraction_quality:
        artifact_rows["sample-extraction-results.jsonl"].append(extraction_result_row(extraction_result, extraction_quality))
    artifact_rows["sample-ocr-pages.jsonl"].extend(result.get("ocr_pages", []))
    if result.get("ocr_document"):
        artifact_rows["sample-ocr-documents.jsonl"].append(result["ocr_document"])
    artifact_rows["sample-chunks.jsonl"].extend(result.get("chunks", []))
    artifact_rows["sample-embeddings.jsonl"].extend(result.get("embeddings", []))
    artifact_rows["sample-semantic-examples.jsonl"].extend(result.get("semantic_examples", []))
    if sample and llm_tag_inspection:
        artifact_rows["sample-llm-tag-inspections.jsonl"].append(llm_inspection_row(sample, llm_tag_inspection))
    artifact_rows["sample-tag-candidates.jsonl"].extend(result.get("tag_candidates", []))
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dict__"):
        return _json_safe(value.__dict__)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output_file:
        for row in rows:
            output_file.write(json.dumps(_json_safe(row), sort_keys=True) + "\n")


def _progress(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr, flush=True)


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
