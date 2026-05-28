"""Pipeline run lifecycle, progress, reports, and artifacts routes."""

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
    SemanticEvalRequest,
    SemanticIndexBuildRequest,
)

router = APIRouter()


from sunshine_api.services.model_usage import _count_list_values, _count_values, _model_usage_report, _read_model_usage_artifact
from sunshine_api.services.imports import (
    delete_postgres_pipeline_run_if_configured,
    import_langgraph_output_to_postgres_if_configured,
    list_postgres_pipeline_runs,
    record_postgres_pipeline_run_state_if_configured,
)
from sunshine_api.services.run_commands import _batch_command, _batch_input_sample_count
from sunshine_api.services.run_execution import _RUN_PROCESSES, _RUN_PROCESS_LOCK, _execute_run, _execute_temporal_batch_run
from sunshine_api.services.run_reports import (
    _load_run_results_by_source,
    _progress_ratio,
    _progress_total,
    _read_live_run_summary,
    _read_run_jsonl_with_live_fallback,
    _read_run_summary,
    _result_file_rows,
    _run_artifacts,
    _training_cycle_metrics,
)


@router.get("/admin/runs/presets")
def run_presets() -> list[dict[str, Any]]:
    return review_store().run_presets()


@router.post("/admin/runs")
def start_run(request: RunStartRequest) -> dict[str, Any]:
    store = review_store()
    presets = {preset["preset_key"]: preset for preset in store.run_presets()}
    preset = presets.get(request.preset_key)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Unknown run preset {request.preset_key!r}")
    input_root = request.input_root or preset["input_root"]
    output_dir = request.output_dir or preset["output_dir"]
    embedding_provider = request.embedding_provider or preset.get("embedding_provider") or "cortex"
    enable_llm_tags = preset["enable_llm_tags"] if request.enable_llm_tags is None else request.enable_llm_tags
    llm_tag_provider = request.llm_tag_provider or preset["llm_tag_provider"]
    ocr_fallback_provider = request.ocr_fallback_provider or preset["ocr_fallback_provider"]
    command = _batch_command(
        input_root=input_root,
        output_dir=output_dir,
        embedding_provider=embedding_provider,
        enable_llm_tags=enable_llm_tags,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        semantic_index_path=request.semantic_index_path,
    )
    execution_backend = request.execution_backend or os.environ.get("SUNSHINE_RUN_EXECUTION_BACKEND", "subprocess").strip().lower()
    if execution_backend not in {"subprocess", "temporal"}:
        raise HTTPException(status_code=400, detail="execution_backend must be subprocess or temporal")
    run = store.create_pipeline_run(
        preset_key=request.preset_key,
        run_role=request.run_role,
        input_root=input_root,
        output_dir=output_dir,
        command=command,
        embedding_provider=embedding_provider,
        enable_llm_tags=enable_llm_tags,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        semantic_index_path=request.semantic_index_path,
        execution_backend=execution_backend,
    )
    postgres_record = record_postgres_pipeline_run_state_if_configured(
        run=run,
        status="queued",
        summary={**(run.get("summary") or {}), "execution_backend": execution_backend},
    )
    if request.start:
        sample_count = _batch_input_sample_count(input_root)
        if sample_count == 0:
            store.mark_pipeline_run_finished(
                run["id"],
                status="failed",
                summary={"selected_sample_count": 0, "processed_count": 0, "error_count": 1, "execution_backend": execution_backend},
                error="No runnable QA sample indexes found in input_root. Batch runs require grouped index.jsonl files; use the file browser for single-file runs.",
            )
            failed_run = store.get_pipeline_run(run["id"])
            record_postgres_pipeline_run_state_if_configured(
                run=failed_run,
                status="failed",
                summary={**(failed_run.get("summary") or {}), "execution_backend": execution_backend},
                error=failed_run.get("error"),
            )
            return {**failed_run, "postgres_record": postgres_record}
        store.update_pipeline_run_progress(run["id"], {"selected_sample_count": sample_count, "processed_count": 0})
        if execution_backend == "temporal":
            payload = _temporal_batch_payload(
                input_root=input_root,
                output_dir=output_dir,
                semantic_index_path=request.semantic_index_path,
            )
            thread = threading.Thread(target=_execute_temporal_batch_run, args=(run["id"], payload, request.import_on_success), daemon=True)
        else:
            thread = threading.Thread(target=_execute_run, args=(run["id"], command, output_dir, request.import_on_success), daemon=True)
        thread.start()
    return {**run, "postgres_record": postgres_record}


def _temporal_batch_payload(*, input_root: str, output_dir: str, semantic_index_path: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "input_root": input_root,
        "output_dir": output_dir,
        "progress": True,
        "retry_attempts": 1,
        "max_concurrency": 1,
    }
    if semantic_index_path:
        payload["semantic_index_path"] = semantic_index_path
    return payload


@router.get("/admin/runs")
def runs(limit: int = 100, source: str = "sqlite") -> list[dict[str, Any]]:
    if source == "postgres":
        try:
            return [_postgres_run_for_dashboard(row) for row in list_postgres_pipeline_runs(limit=limit)]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    return review_store().list_pipeline_runs(limit=limit)


def _postgres_run_for_dashboard(row: dict[str, Any]) -> dict[str, Any]:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    execution_backend = summary.get("execution_backend") or summary.get("graph_runtime", {}).get("execution_backend")
    run_metadata = {
        "source": "postgres",
        "result_count": row.get("result_count"),
        "review_required_count": row.get("review_required_count"),
        "model_usage_count": row.get("model_usage_count"),
        "provider_attempt_count": row.get("provider_attempt_count"),
        "document_segment_count": row.get("document_segment_count"),
        "execution_backend": execution_backend,
    }
    return {
        "id": row.get("run_key") or row.get("id"),
        "postgres_id": row.get("id"),
        "source": "postgres",
        "run_key": row.get("run_key"),
        "preset_key": row.get("preset_key"),
        "run_role": summary.get("run_role") or summary.get("graph_runtime", {}).get("run_role") or "v2",
        "status": row.get("status"),
        "input_root": row.get("input_root"),
        "output_dir": row.get("output_dir"),
        "command": [],
        "embedding_provider": row.get("embedding_provider"),
        "enable_llm_tags": bool(row.get("llm_provider")),
        "llm_tag_provider": row.get("llm_provider"),
        "ocr_fallback_provider": row.get("extraction_provider"),
        "semantic_index_path": None,
        "run_metadata": run_metadata,
        "execution_backend": execution_backend,
        "started_at": row.get("started_at"),
        "completed_at": row.get("finished_at"),
        "processed_count": summary.get("processed_count") or summary.get("total_results") or row.get("result_count"),
        "route_candidate_count": summary.get("route_candidate_count"),
        "review_required_count": row.get("review_required_count"),
        "failed_count": summary.get("failed_count") or summary.get("error_count"),
        "summary": summary,
        "error": summary.get("error"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.get("/admin/runs/{run_id}")
def run_detail(run_id: int) -> dict[str, Any]:
    try:
        return review_store().get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/admin/runs/{run_id}/events")
def run_events(run_id: int, limit: int = 200) -> list[dict[str, Any]]:
    return review_store().list_pipeline_run_events(run_id, limit=limit)


@router.get("/admin/runs/{run_id}/progress")
def run_progress(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = str(run.get("output_dir") or "")
    summary = _read_run_summary(output_dir)
    if run["status"] == "running" or not summary:
        live_summary = _read_live_run_summary(output_dir, run.get("summary") or {})
        if live_summary:
            summary = {**summary, **live_summary}
            store.update_pipeline_run_progress(run_id, summary)
            run = store.get_pipeline_run(run_id)
    return {
        "run_id": run_id,
        "status": run["status"],
        "output_dir": output_dir,
        "processed_count": run.get("processed_count"),
        "total_count": _progress_total(run, summary),
        "progress_ratio": _progress_ratio(run, summary),
        "summary": summary or run.get("summary") or {},
        "error": run.get("error"),
        "updated_at": run.get("updated_at"),
    }


@router.get("/admin/runs/{run_id}/results")
def run_results(run_id: int, limit: int = 200) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = Path(str(run.get("output_dir") or ""))
    sample_results_path = output_dir / "sample-pipeline-results.jsonl"
    graph_result_path = output_dir / "graph-result.json"
    if sample_results_path.exists():
        rows = []
        with sample_results_path.open("r", encoding="utf-8") as input_file:
            for line in input_file:
                if len(rows) >= limit:
                    break
                if line.strip():
                    rows.append(json.loads(line))
        return {"run_id": run_id, "output_dir": str(output_dir), "result_type": "batch", "results": rows}
    if graph_result_path.exists():
        return {
            "run_id": run_id,
            "output_dir": str(output_dir),
            "result_type": "single_file",
            "results": [json.loads(graph_result_path.read_text(encoding="utf-8"))],
        }
    return {"run_id": run_id, "output_dir": str(output_dir), "result_type": "none", "results": []}


@router.get("/admin/runs/{run_id}/artifacts")
def run_artifacts(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = Path(str(run.get("output_dir") or ""))
    return {"run_id": run_id, "output_dir": str(output_dir), "artifacts": _run_artifacts(output_dir)}


@router.get("/admin/runs/{run_id}/model-usage")
def run_model_usage(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    rows = store.list_model_usage(run_id)
    if not rows:
        rows = _read_model_usage_artifact(Path(str(run.get("output_dir") or "")), run_id=run_id)
    return {"run_id": run_id, **_model_usage_report(rows)}


@router.get("/admin/runs/{run_id}/report")
def run_report(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = Path(str(run.get("output_dir") or ""))
    progress = run_progress(run_id)
    results = list(_load_run_results_by_source(str(output_dir)).values())
    review_queue = _read_run_jsonl_with_live_fallback(output_dir, "sample-review-queue.jsonl", limit=200)
    ocr_documents = _read_run_jsonl_with_live_fallback(output_dir, "sample-ocr-documents.jsonl", limit=200)
    ocr_pages = _read_run_jsonl_with_live_fallback(output_dir, "sample-ocr-pages.jsonl", limit=200)
    source_identity = _read_run_jsonl_with_live_fallback(output_dir, "sample-source-identity.jsonl", limit=500)
    file_probes = _read_run_jsonl_with_live_fallback(output_dir, "sample-file-probes.jsonl", limit=500)
    provider_selections = _read_run_jsonl_with_live_fallback(output_dir, "sample-provider-selections.jsonl", limit=500)
    extraction_results = _read_run_jsonl_with_live_fallback(output_dir, "sample-extraction-results.jsonl", limit=200)
    extraction_validations = _read_run_jsonl_with_live_fallback(output_dir, "sample-extraction-validations.jsonl", limit=500)
    extraction_repairs = _read_run_jsonl_with_live_fallback(output_dir, "sample-extraction-repairs.jsonl", limit=500)
    quality_gates = _read_run_jsonl_with_live_fallback(output_dir, "sample-quality-gates.jsonl", limit=500)
    provider_attempts = store.list_provider_attempts(run_id) or _read_run_jsonl_with_live_fallback(output_dir, "sample-provider-attempts.jsonl", limit=500)
    document_segments = store.list_document_segments(run_id) or _read_run_jsonl_with_live_fallback(output_dir, "sample-document-segments.jsonl", limit=500)
    indexing_rows = _read_run_jsonl_with_live_fallback(output_dir, "sample-indexing.jsonl", limit=200)
    placement_proposals = _read_run_jsonl_with_live_fallback(output_dir, "sample-placement-proposals.jsonl", limit=500)
    route_decisions = _read_run_jsonl_with_live_fallback(output_dir, "sample-route-decisions.jsonl", limit=500)
    import_results = _read_run_jsonl_with_live_fallback(output_dir, "sample-import-results.jsonl", limit=100)
    model_usage_rows = store.list_model_usage(run_id) or _read_model_usage_artifact(output_dir, run_id=run_id)
    comparison = run_compare_previous(run_id)
    artifacts = _run_artifacts(output_dir)
    summary = _read_live_run_summary(str(output_dir), _read_run_summary(str(output_dir)) or run.get("summary") or {})
    review_items = store.list_review_items(status="all", run_id=run_id, limit=200)
    training_cycle = _training_cycle_metrics(run, review_items, store.list_golden_labels(limit=10000), comparison)
    status_buckets = _production_status_buckets(results)
    return {
        "run": run,
        "progress": progress,
        "overview": {
            "processed_count": progress.get("processed_count") or run.get("processed_count") or summary.get("processed_count"),
            "total_count": progress.get("total_count"),
            "route_candidate_count": run.get("route_candidate_count") or summary.get("route_candidate_count"),
            "review_required_count": run.get("review_required_count") or summary.get("review_required_count"),
            "failed_count": run.get("failed_count") or summary.get("failed_count"),
            "status_buckets": status_buckets,
            "summary": summary,
        },
        "status_buckets": status_buckets,
        "distributions": {
            "route_status": _count_values(results, "route_status"),
            "quality": _count_values(results, "quality"),
            "final_class": _count_values(results, "final_class"),
            "primary_tag": _count_values(results, "top_tag_candidate"),
            "placement_status": _count_values(results, "placement_status"),
            "extraction_strategy": _count_values(results, "extraction_strategy"),
            "warnings": _count_list_values(results, "warnings"),
            "secondary_tags": _count_list_values(results, "secondary_tags"),
        },
        "files": _result_file_rows(results, limit=200),
        "source_identity": {
            "count": len(source_identity),
            "items": source_identity[:100],
        },
        "file_probes": {
            "count": len(file_probes),
            "by_media_type": _count_values(file_probes, "media_type"),
            "by_status": _count_values(file_probes, "status"),
            "items": file_probes[:100],
        },
        "provider_selections": {
            "count": len(provider_selections),
            "by_selected_provider": _count_values(provider_selections, "selected_provider"),
            "by_reason": _count_values(provider_selections, "provider_selection_reason"),
            "items": provider_selections[:100],
        },
        "review_queue": {
            "count": len(review_items) if review_items else len(review_queue),
            "items": review_items[:100] if review_items else review_queue[:100],
            "by_status": _count_values(review_items, "status") if review_items else {},
            "links": {
                "all": f"/review?run_id={run_id}&status=all",
                "open": f"/review?run_id={run_id}&status=open",
                "ocr": f"/review?run_id={run_id}&status=all&review_reason=ocr_quality_not_trusted",
                "tag_disagreements": f"/review?run_id={run_id}&status=all&review_reason=llm_tag_disagreement",
                "low_confidence": f"/review?run_id={run_id}&status=all&review_reason=tag_confidence_below_threshold",
                "placement": f"/review?run_id={run_id}&status=all&placement_status=needs_review",
            },
        },
        "ocr": {
            "document_count": len(ocr_documents),
            "page_count": len(ocr_pages),
            "documents": ocr_documents[:100],
            "pages": ocr_pages[:100],
        },
        "extraction": {
            "count": len(extraction_results),
            "validation_count": len(extraction_validations),
            "repair_count": len(extraction_repairs),
            "quality_gate_count": len(quality_gates),
            "validation_status": _count_values(extraction_validations, "status"),
            "repair_status": _count_values(extraction_repairs, "status"),
            "quality_gate_quality": _count_values(quality_gates, "quality"),
            "quality_gate_review_required": _count_values(quality_gates, "requires_review"),
            "items": extraction_results[:100],
            "validations": extraction_validations[:100],
            "repairs": extraction_repairs[:100],
            "quality_gates": quality_gates[:100],
        },
        "provider_attempts": {
            "count": len(provider_attempts),
            "by_provider": _count_values(provider_attempts, "provider"),
            "by_status": _count_values(provider_attempts, "status"),
            "items": provider_attempts[:100],
        },
        "segments": {
            "count": len(document_segments),
            "requires_review_count": sum(1 for row in document_segments if row.get("requires_segment_review")),
            "by_type": _count_values(document_segments, "segment_type"),
            "items": document_segments[:100],
        },
        "indexing": {
            "count": len(indexing_rows),
            "by_provider": _count_values(indexing_rows, "provider"),
            "by_status": _count_values(indexing_rows, "status"),
            "indexed_count": sum(int(row.get("indexed_count") or 0) for row in indexing_rows),
            "skipped_count": sum(int(row.get("skipped_count") or 0) for row in indexing_rows),
            "semantic_embedding_count": sum(int(row.get("semantic_embedding_count") or 0) for row in indexing_rows),
            "placeholder_embedding_count": sum(int(row.get("placeholder_embedding_count") or 0) for row in indexing_rows),
            "items": indexing_rows[:100],
        },
        "tags": {
            "primary": _count_values(results, "top_tag_candidate"),
            "secondary": _count_list_values(results, "secondary_tags"),
            "llm_status": _count_values(results, "llm_status"),
        },
        "placement": {
            "status": _count_values(results, "placement_status"),
            "privacy": _count_values(results, "default_privacy"),
            "rule": _count_values(results, "placement_rule"),
            "proposal_count": len(placement_proposals),
            "proposal_status": _count_nested_values(placement_proposals, "proposal", "placement_status"),
            "proposal_items": placement_proposals[:100],
        },
        "routing": {
            "count": len(route_decisions),
            "by_status": _count_values(route_decisions, "route_status"),
            "by_priority": _count_values(route_decisions, "priority"),
            "by_review_stage": _count_values(route_decisions, "review_stage"),
            "items": route_decisions[:100],
        },
        "model_usage": _model_usage_report(model_usage_rows),
        "imports": {
            "count": len(import_results),
            "by_status": _count_values(import_results, "import_status"),
            "items": import_results[:25],
        },
        "artifacts": artifacts,
        "diff": comparison,
        "training_cycle": training_cycle,
    }


def _production_status_buckets(results: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {"accepted": 0, "review_required": 0, "failed": 0, "deferred": 0}
    for result in results:
        route_status = str(result.get("route_status") or "")
        extraction_status = str(result.get("extraction_status") or "")
        extraction_strategy = str(result.get("extraction_strategy") or "")
        quality = str(result.get("quality") or "")
        if route_status == "route_candidate":
            buckets["accepted"] += 1
        elif (
            "failed" in route_status
            or "failed" in extraction_status
            or quality == "failed"
        ):
            buckets["failed"] += 1
        elif (
            "deferred" in route_status
            or route_status == "technical_followup"
            or extraction_strategy == "deferred_technical"
        ):
            buckets["deferred"] += 1
        else:
            buckets["review_required"] += 1
    return buckets


def _count_nested_values(rows: list[dict[str, Any]], parent: str, field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        nested = row.get(parent) if isinstance(row.get(parent), dict) else {}
        value = str(nested.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


@router.get("/admin/runs/{run_id}/compare-previous")
def run_compare_previous(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    prior_runs = [
        candidate
        for candidate in store.list_pipeline_runs(limit=500)
        if candidate["id"] < run_id and candidate["preset_key"] == run["preset_key"] and candidate.get("output_dir")
    ]
    if not prior_runs:
        return {"run_id": run_id, "previous_run_id": None, "changed": [], "added": [], "removed": [], "summary": {}}
    previous = sorted(prior_runs, key=lambda candidate: candidate["id"], reverse=True)[0]
    current_rows = _load_run_results_by_source(str(run.get("output_dir") or ""))
    previous_rows = _load_run_results_by_source(str(previous.get("output_dir") or ""))
    changed = []
    for source_path, current in current_rows.items():
        prior = previous_rows.get(source_path)
        if not prior:
            continue
        changed_fields = {
            field: {"previous": prior.get(field), "current": current.get(field)}
            for field in ["final_class", "top_tag_candidate", "route_status", "quality", "placement_status"]
            if prior.get(field) != current.get(field)
        }
        if changed_fields:
            changed.append(
                {
                    "source_path": source_path,
                    "relative_path": current.get("relative_path") or prior.get("relative_path"),
                    "changed_fields": changed_fields,
                }
            )
    added = [
        {"source_path": source_path, "relative_path": row.get("relative_path")}
        for source_path, row in current_rows.items()
        if source_path not in previous_rows
    ]
    removed = [
        {"source_path": source_path, "relative_path": row.get("relative_path")}
        for source_path, row in previous_rows.items()
        if source_path not in current_rows
    ]
    return {
        "run_id": run_id,
        "previous_run_id": previous["id"],
        "changed": changed,
        "added": added,
        "removed": removed,
        "summary": {"changed": len(changed), "added": len(added), "removed": len(removed)},
    }


@router.post("/admin/runs/{run_id}/cancel")
def cancel_run(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if run["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=400, detail=f"Run is {run['status']}; only queued/running runs can be cancelled")
    with _RUN_PROCESS_LOCK:
        process = _RUN_PROCESSES.get(run_id)
    if process and process.poll() is None:
        try:
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            pass
        except Exception:
            process.terminate()
    store.mark_pipeline_run_finished(run_id, status="cancelled", summary=run.get("summary") or {}, error="Cancelled from dashboard.")
    return store.get_pipeline_run(run_id)


@router.delete("/admin/runs/{run_id}")
def delete_run(run_id: int, delete_artifacts: bool = True, force: bool = False) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    with _RUN_PROCESS_LOCK:
        process = _RUN_PROCESSES.get(run_id)
    if run["status"] == "running" and not force:
        raise HTTPException(status_code=400, detail=f"Run is {run['status']}; cancel it first or pass force=true")
    if process and process.poll() is None:
        if not force:
            raise HTTPException(status_code=400, detail="Run process is still active; cancel it first or pass force=true")
        try:
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            pass
        except Exception:
            process.terminate()
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES.pop(run_id, None)
    postgres_delete = delete_postgres_pipeline_run_if_configured(run_key=str(run["run_key"]))
    legacy_delete = store.delete_pipeline_run(run_id, delete_artifacts=delete_artifacts)
    return {**legacy_delete, "postgres_delete": postgres_delete}


@router.post("/admin/runs/{run_id}/import-results")
def import_run_results(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = run.get("output_dir")
    if not output_dir:
        raise HTTPException(status_code=400, detail="Run has no output_dir")
    legacy_result = store.import_langgraph_output(output_dir, sample_routed_per_bucket=0, run_id=run_id)
    try:
        postgres_result = import_langgraph_output_to_postgres_if_configured(
            output_dir,
            run_key=str(run["run_key"]),
            preset_key=run.get("preset_key"),
        )
    except Exception as error:  # noqa: BLE001 - expose import failure without hiding legacy import result.
        postgres_result = {
            "import_status": "failed",
            "importer": "postgres_runtime",
            "error": f"{type(error).__name__}: {error}",
        }
    return {**legacy_result, "postgres_import": postgres_result}


@router.post("/admin/runs/{run_id}/rerun-failed")
def rerun_failed(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    command = [str(part) for part in run.get("command") or []]
    if not command:
        raise HTTPException(status_code=400, detail="Run has no command to rerun")
    rerun = store.create_pipeline_run(
        preset_key=f"{run['preset_key']}_rerun_failed",
        run_role=run.get("run_role") or "test",
        input_root=str(run.get("input_root") or ""),
        output_dir=str(run.get("output_dir") or ""),
        command=command,
        embedding_provider=run.get("embedding_provider"),
        enable_llm_tags=bool(run.get("enable_llm_tags")),
        llm_tag_provider=run.get("llm_tag_provider"),
        ocr_fallback_provider=run.get("ocr_fallback_provider"),
        semantic_index_path=run.get("semantic_index_path"),
    )
    thread = threading.Thread(target=_execute_run, args=(rerun["id"], command, str(run.get("output_dir") or ""), False), daemon=True)
    thread.start()
    return rerun
