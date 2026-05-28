"""Semantic index and evaluation routes."""

from __future__ import annotations

from pathlib import Path
import csv
import io
import json
import os
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from sunshine_api.dependencies import review_store
from sunshine_api.schemas import (
    DocumentPipelineRunRequest,
    DocumentPipelineRunResponse,
    FileReviewRequest,
    FileRunRequest,
    GoldenLabelUpdateRequest,
    ReviewAssignRequest,
    ReviewDecisionRequest,
    ReviewImportRequest,
    RunStartRequest,
    PipelineEvalImportRequest,
    PipelineEvalRequest,
    ProviderBenchmarkRequest,
    QdrantRebuildRequest,
    SemanticEvalRequest,
    SemanticIndexBuildRequest,
)

router = APIRouter()


from sunshine_api.services.semantic import _semantic_index_status
from sunshine_api.services.vector_index import rebuild_qdrant_from_postgres
from sunshine_extraction.evaluate_pipeline import DEFAULT_EVAL_OUTPUT_DIR, run_golden_pipeline_evaluation
from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers
from sunshine_extraction.semantic_eval import evaluate_review_db
from sunshine_extraction.semantic_index import DEFAULT_INDEX_DB, build_semantic_index
from sunshine_extraction.services.env import load_pipeline_env
from sunshine_extraction.services.extraction import ocr_executor_from_env
from sunshine_extraction.services.tagging import LLMTagInspector, llm_tag_inspector_from_env


@router.get("/admin/semantic-index/status")
def semantic_index_status(index_db: str | None = None) -> dict[str, Any]:
    return _semantic_index_status(index_db or DEFAULT_INDEX_DB)


@router.post("/admin/semantic-index/build")
def semantic_index_build(request: SemanticIndexBuildRequest) -> dict[str, Any]:
    load_pipeline_env()
    labels_db = request.labels_db or str(review_store().db_path)
    output_db = request.output_db or DEFAULT_INDEX_DB
    summary = build_semantic_index(labels_db, output_db, limit=request.limit)
    return {"ok": True, "status": _semantic_index_status(output_db), **summary}


@router.post("/admin/vector-index/qdrant/rebuild")
def qdrant_rebuild(request: QdrantRebuildRequest) -> dict[str, Any]:
    try:
        return rebuild_qdrant_from_postgres(run_key=request.run_key, limit=request.limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/admin/semantic-eval/latest")
def semantic_eval_latest(output_dir: str | None = None) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir or ".local/semantic-eval")
    summary_path = resolved_output_dir / "semantic-eval-summary.json"
    if not summary_path.exists():
        return {"ok": False, "exists": False, "output_dir": str(resolved_output_dir)}
    try:
        report = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Invalid semantic eval report: {error}") from error
    return {"ok": True, "exists": True, "output_dir": str(resolved_output_dir), "report": report}


@router.post("/admin/semantic-eval/run")
def semantic_eval_run(request: SemanticEvalRequest) -> dict[str, Any]:
    labels_db = request.labels_db or str(review_store().db_path)
    output_dir = request.output_dir or ".local/semantic-eval"
    report = evaluate_review_db(labels_db, output_dir=output_dir)
    return {"ok": True, "output_dir": output_dir, "report": report}


@router.get("/admin/pipeline-eval/latest")
def pipeline_eval_latest(output_dir: str | None = None) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir or DEFAULT_EVAL_OUTPUT_DIR)
    summary_path = resolved_output_dir / "eval-summary.json"
    if not summary_path.exists():
        return {"ok": False, "exists": False, "output_dir": str(resolved_output_dir)}
    try:
        report = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Invalid pipeline eval report: {error}") from error
    return {"ok": True, "exists": True, "output_dir": str(resolved_output_dir), "report": report}


@router.get("/admin/pipeline-eval/runs")
def pipeline_eval_runs(limit: int = 100) -> list[dict[str, Any]]:
    return review_store().list_pipeline_eval_runs(limit=limit)


@router.get("/admin/pipeline-eval/runs/{eval_run_id}")
def pipeline_eval_run_detail(eval_run_id: int) -> dict[str, Any]:
    try:
        return review_store().get_pipeline_eval_run(eval_run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/admin/pipeline-eval/runs/{eval_run_id}/results")
def pipeline_eval_run_results(eval_run_id: int, result_type: str = "results", limit: int = 200) -> dict[str, Any]:
    try:
        eval_run = review_store().get_pipeline_eval_run(eval_run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = Path(str(eval_run.get("output_dir") or ""))
    filenames = {
        "results": "eval-results.jsonl",
        "failures": "eval-failures.jsonl",
        "failure_groups": "eval-failure-groups.json",
        "model_usage": "eval-model-usage.jsonl",
        "artifact_manifest": "eval-artifacts-manifest.json",
    }
    filename = filenames.get(result_type)
    if filename is None:
        raise HTTPException(status_code=400, detail="result_type must be results, failures, failure_groups, model_usage, or artifact_manifest")
    path = output_dir / filename
    rows = _read_eval_json(path, limit=max(1, min(limit, 1000))) if result_type in {"failure_groups", "artifact_manifest"} else _read_eval_jsonl(path, limit=max(1, min(limit, 1000)))
    return {
        "eval_run": eval_run,
        "result_type": result_type,
        "path": str(path),
        "count": len(rows),
        "items": rows,
    }


@router.get("/admin/pipeline-eval/runs/{eval_run_id}/compare")
def pipeline_eval_run_compare(eval_run_id: int, baseline_eval_run_id: int) -> dict[str, Any]:
    try:
        current = review_store().get_pipeline_eval_run(eval_run_id)
        baseline = review_store().get_pipeline_eval_run(baseline_eval_run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    current_results = _eval_rows_by_source(Path(str(current.get("output_dir") or "")) / "eval-results.jsonl")
    baseline_results = _eval_rows_by_source(Path(str(baseline.get("output_dir") or "")) / "eval-results.jsonl")
    return _pipeline_eval_comparison(baseline, current, baseline_results, current_results)


@router.post("/admin/provider-benchmarks/run")
def provider_benchmark_run(request: ProviderBenchmarkRequest) -> dict[str, Any]:
    try:
        result = benchmark_extraction_providers(
            request.paths or [],
            provider_names=list(request.providers),
            output_dir=request.output_dir,
            sample_manifest=request.sample_manifest,
            sample_root=request.sample_root,
            sample_categories=request.sample_categories,
            sample_limit=request.sample_limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, **result}


@router.get("/admin/provider-benchmarks/latest")
def provider_benchmark_latest(output_dir: str) -> dict[str, Any]:
    output_path = Path(output_dir)
    summary_path = output_path / "provider-benchmark-summary.json"
    results_path = output_path / "provider-benchmark-results.jsonl"
    parser_results_path = output_path / "sample-parser-results.jsonl"
    recommendations_path = output_path / "provider-benchmark-recommendations.jsonl"
    artifact_exists = summary_path.exists() or results_path.exists() or parser_results_path.exists() or recommendations_path.exists()
    if not artifact_exists:
        return {"ok": False, "exists": False, "output_dir": str(output_path)}
    partial = not summary_path.exists()
    summary: dict[str, Any] = {}
    if partial:
        results = _read_eval_jsonl(results_path, limit=500)
        parser_results = _read_eval_jsonl(parser_results_path, limit=500)
        summary = {
            "result_count": len(results),
            "partial": True,
            "by_provider": _count_rows(results, "provider"),
            "by_status": _count_rows(results, "status"),
            "by_quality": _count_rows(results, "quality"),
            "review_required_count": sum(1 for row in results if row.get("requires_review")),
            "sample_categories": _count_rows(results, "sample_category"),
        }
        return {
            "ok": True,
            "exists": True,
            "partial": True,
            "output_dir": str(output_path),
            "summary": summary,
            "recommendations": _read_eval_jsonl(recommendations_path, limit=100),
            "results": results,
            "parser_results": parser_results,
        }
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Invalid provider benchmark summary: {error}") from error
    return {
        "ok": True,
        "exists": True,
        "partial": False,
        "output_dir": str(output_path),
        "summary": summary,
        "recommendations": _read_eval_jsonl(recommendations_path, limit=100),
        "results": _read_eval_jsonl(results_path, limit=500),
        "parser_results": _read_eval_jsonl(parser_results_path, limit=500),
    }


def _pipeline_eval_comparison(
    baseline: dict[str, Any],
    current: dict[str, Any],
    baseline_results: dict[str, dict[str, Any]],
    current_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    shared_sources = sorted(set(current_results) & set(baseline_results))
    changed_predictions = []
    fixed_failures = []
    regressed_failures = []
    changed_review_routes = []
    changed_secondary_tags = []
    changed_failure_reasons = []
    for source_path in shared_sources:
        current_row = current_results[source_path]
        baseline_row = baseline_results[source_path]
        if current_row.get("predicted_primary_tag") != baseline_row.get("predicted_primary_tag"):
            changed_predictions.append(_comparison_row(source_path, baseline_row, current_row, "primary_tag_changed"))
        if sorted(current_row.get("predicted_secondary_tags") or []) != sorted(baseline_row.get("predicted_secondary_tags") or []):
            changed_secondary_tags.append(_comparison_row(source_path, baseline_row, current_row, "secondary_tags_changed"))
        baseline_failed = bool(baseline_row.get("failure_reasons"))
        current_failed = bool(current_row.get("failure_reasons"))
        if baseline_failed and not current_failed:
            fixed_failures.append(_comparison_row(source_path, baseline_row, current_row, "failure_fixed"))
        elif not baseline_failed and current_failed:
            regressed_failures.append(_comparison_row(source_path, baseline_row, current_row, "failure_regressed"))
        if sorted(baseline_row.get("failure_reasons") or []) != sorted(current_row.get("failure_reasons") or []):
            changed_failure_reasons.append(_comparison_row(source_path, baseline_row, current_row, "failure_reasons_changed"))
        if baseline_row.get("route_status") != current_row.get("route_status"):
            changed_review_routes.append(_comparison_row(source_path, baseline_row, current_row, "route_changed"))

    metric_keys = [
        "primary_accuracy",
        "content_class_accuracy",
        "ocr_quality_accuracy",
        "ocr_acceptable_rate",
        "review_routing_accuracy",
        "placement_destination_accuracy",
        "privacy_accuracy",
        "high_confidence_primary_accuracy",
        "embedding_success_rate",
        "semantic_same_family_top5_rate",
    ]
    metric_deltas = {
        key: {
            "baseline": _summary_metric(baseline, key),
            "current": _summary_metric(current, key),
            "delta": _metric_delta(_summary_metric(baseline, key), _summary_metric(current, key)),
        }
        for key in metric_keys
    }
    return {
        "baseline_eval_run": baseline,
        "current_eval_run": current,
        "shared_file_count": len(shared_sources),
        "baseline_only_count": len(set(baseline_results) - set(current_results)),
        "current_only_count": len(set(current_results) - set(baseline_results)),
        "metric_deltas": metric_deltas,
        "changed_prediction_count": len(changed_predictions),
        "changed_secondary_tag_count": len(changed_secondary_tags),
        "fixed_failure_count": len(fixed_failures),
        "regressed_failure_count": len(regressed_failures),
        "changed_failure_reason_count": len(changed_failure_reasons),
        "changed_review_route_count": len(changed_review_routes),
        "changed_predictions": changed_predictions[:100],
        "changed_secondary_tags": changed_secondary_tags[:100],
        "fixed_failures": fixed_failures[:100],
        "regressed_failures": regressed_failures[:100],
        "changed_failure_reasons": changed_failure_reasons[:100],
        "changed_review_routes": changed_review_routes[:100],
    }


@router.post("/admin/pipeline-eval/run")
def pipeline_eval_run(request: PipelineEvalRequest) -> dict[str, Any]:
    load_pipeline_env()
    labels_db = request.labels_db or str(review_store().db_path)
    output_dir = request.output_dir or DEFAULT_EVAL_OUTPUT_DIR
    report = run_golden_pipeline_evaluation(
        labels_db,
        output_dir=output_dir,
        limit=request.limit,
        embedding_provider_name=request.embedding_provider,
        llm_tag_inspector=llm_tag_inspector_from_env() if request.enable_llm_tags else LLMTagInspector(),
        ocr_executor=ocr_executor_from_env() if request.enable_ocr else None,
        ocr_fallback_provider=request.ocr_fallback_provider,
        semantic_index_path=None if request.disable_semantic_index else (request.semantic_index_path or DEFAULT_INDEX_DB),
    )
    eval_run = review_store().record_pipeline_eval(report)
    return {"ok": True, "output_dir": output_dir, "eval_run": eval_run, "report": report}


@router.post("/admin/pipeline-eval/import")
def pipeline_eval_import(request: PipelineEvalImportRequest) -> dict[str, Any]:
    output_dir = Path(request.output_dir)
    summary_path = output_dir / "eval-summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail=f"Missing eval summary: {summary_path}")
    try:
        report = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail=f"Invalid eval summary JSON: {error}") from error
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="Eval summary must be a JSON object")
    report["output_dir"] = str(output_dir)
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    artifacts.setdefault("summary", str(summary_path))
    report["artifacts"] = artifacts
    eval_run = review_store().record_pipeline_eval(report)
    return {"ok": True, "output_dir": str(output_dir), "eval_run": eval_run, "report": report}


def _eval_rows_by_source(path: Path) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("source_path") or row.get("relative_path") or index): row
        for index, row in enumerate(_read_eval_jsonl(path, limit=100000))
    }


def _summary_metric(eval_run: dict[str, Any], key: str) -> float | None:
    summary = eval_run.get("summary") if isinstance(eval_run.get("summary"), dict) else {}
    value = summary.get(key) if isinstance(summary, dict) else eval_run.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_delta(baseline: float | None, current: float | None) -> float | None:
    if baseline is None or current is None:
        return None
    return current - baseline


def _comparison_row(source_path: str, baseline: dict[str, Any], current: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "relative_path": current.get("relative_path") or baseline.get("relative_path"),
        "reason": reason,
        "correct_primary_tag": current.get("correct_primary_tag") or baseline.get("correct_primary_tag"),
        "baseline_predicted_primary_tag": baseline.get("predicted_primary_tag"),
        "current_predicted_primary_tag": current.get("predicted_primary_tag"),
        "baseline_predicted_secondary_tags": baseline.get("predicted_secondary_tags") or [],
        "current_predicted_secondary_tags": current.get("predicted_secondary_tags") or [],
        "baseline_route_status": baseline.get("route_status"),
        "current_route_status": current.get("route_status"),
        "baseline_failure_reasons": baseline.get("failure_reasons") or [],
        "current_failure_reasons": current.get("failure_reasons") or [],
    }


def _read_eval_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if len(rows) >= limit:
                break
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _count_rows(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _read_eval_json(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows = payload if isinstance(payload, list) else _json_rows_from_object(payload) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)][:limit]


def _json_rows_from_object(payload: dict[str, Any]) -> list[Any]:
    for key in ("items", "artifacts"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return rows
    return []
