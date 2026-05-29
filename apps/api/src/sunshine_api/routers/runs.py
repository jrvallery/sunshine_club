"""Pipeline run lifecycle, progress, reports, and artifacts routes."""

from __future__ import annotations

from pathlib import Path
import csv
import io
import json
import os
import threading
from datetime import UTC, datetime
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from sunshine_api.dependencies import review_store
from sunshine_api.review_store import _delete_run_output_dir
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
from sunshine_extraction.services.tagging import DEFAULT_TAXONOMY_PATH

router = APIRouter()


def _run_presets() -> list[dict[str, Any]]:
    base_manifest = "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25"
    return [
        {
            "preset_key": "qa_samples_full",
            "label": "QA samples full",
            "description": "Full QA sample with LLM tags, OpenAI OCR fallback, and semantic examples.",
            "input_root": f"{base_manifest}/qa samples",
            "output_dir": f"{base_manifest}/dashboard-runs/qa_samples_full",
            "enable_llm_tags": True,
            "embedding_provider": "cortex",
            "llm_tag_provider": "auto",
            "ocr_fallback_provider": "openai",
        },
        {
            "preset_key": "qa_samples_fast",
            "label": "QA samples fast",
            "description": "Fast QA regression pass without LLM tag inspection.",
            "input_root": f"{base_manifest}/qa samples",
            "output_dir": f"{base_manifest}/dashboard-runs/qa_samples_fast",
            "enable_llm_tags": False,
            "embedding_provider": "cortex",
            "llm_tag_provider": "disabled",
            "ocr_fallback_provider": "disabled",
        },
        {
            "preset_key": "ocr_fallback_focus",
            "label": "OCR fallback focus",
            "description": "OCR-heavy QA sample with OpenAI OCR fallback for poor local OCR.",
            "input_root": f"{base_manifest}/qa samples",
            "output_dir": f"{base_manifest}/dashboard-runs/ocr_fallback_focus",
            "enable_llm_tags": False,
            "embedding_provider": "cortex",
            "llm_tag_provider": "disabled",
            "ocr_fallback_provider": "openai",
        },
        {
            "preset_key": "review_required_rerun",
            "label": "Review required rerun",
            "description": "Rerun currently open review files after pipeline changes.",
            "input_root": f"{base_manifest}/review required files",
            "output_dir": f"{base_manifest}/dashboard-runs/review_required_rerun",
            "enable_llm_tags": True,
            "embedding_provider": "cortex",
            "llm_tag_provider": "auto",
            "ocr_fallback_provider": "openai",
        },
        {
            "preset_key": "random_route_candidate_audit",
            "label": "Route candidate audit",
            "description": "Audit a random sample of auto-routed files after a run import.",
            "input_root": f"{base_manifest}/qa samples",
            "output_dir": f"{base_manifest}/dashboard-runs/random_route_candidate_audit",
            "enable_llm_tags": True,
            "embedding_provider": "cortex",
            "llm_tag_provider": "auto",
            "ocr_fallback_provider": "openai",
        },
        {
            "preset_key": "single_file_debug",
            "label": "Single file debug",
            "description": "Debug one file by overriding input root/output parameters or using the file browser Run File action.",
            "input_root": f"{base_manifest}/qa samples",
            "output_dir": f"{base_manifest}/dashboard-runs/single_file_debug",
            "enable_llm_tags": False,
            "embedding_provider": "cortex",
            "llm_tag_provider": "disabled",
            "ocr_fallback_provider": "disabled",
        },
    ]


from sunshine_api.services.model_usage import _count_list_values, _count_values, _model_usage_report, _read_model_usage_artifact
from sunshine_api.services.imports import (
    delete_postgres_pipeline_run_if_configured,
    import_langgraph_output_to_postgres_if_configured,
    list_postgres_pipeline_runs,
    record_postgres_pipeline_run_state_if_configured,
)
from sunshine_api.services.run_commands import _batch_command, _batch_input_sample_count
from sunshine_api.services.run_execution import (
    _RUN_PROCESSES,
    _RUN_PROCESS_LOCK,
    _execute_postgres_run,
    _execute_run,
    _execute_temporal_batch_run,
    cancel_postgres_run_process,
)
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
    return _run_presets()


@router.post("/admin/runs")
def start_run(request: RunStartRequest) -> dict[str, Any]:
    presets = {preset["preset_key"]: preset for preset in _run_presets()}
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
    run_key = f"{request.preset_key}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run = {
        "id": run_key,
        "source": "postgres",
        "run_key": run_key,
        "preset_key": request.preset_key,
        "run_role": request.run_role,
        "status": "queued",
        "input_root": input_root,
        "output_dir": output_dir,
        "command": command,
        "embedding_provider": embedding_provider,
        "enable_llm_tags": enable_llm_tags,
        "llm_tag_provider": llm_tag_provider,
        "ocr_fallback_provider": ocr_fallback_provider,
        "semantic_index_path": request.semantic_index_path,
        "run_metadata": {
            "execution_backend": execution_backend,
            "run_role": request.run_role,
            "source": "postgres",
            "embedding_provider": embedding_provider,
            "llm_tag_provider": llm_tag_provider,
            "ocr_fallback_provider": ocr_fallback_provider,
            "enable_llm_tags": enable_llm_tags,
            "taxonomy_path": str(DEFAULT_TAXONOMY_PATH),
            "taxonomy_version": Path(DEFAULT_TAXONOMY_PATH).name,
        },
        "summary": {"execution_backend": execution_backend, **({"run_role": request.run_role} if request.run_role else {})},
        "error": None,
    }
    postgres_record = record_postgres_pipeline_run_state_if_configured(
        run=run,
        status="queued",
        summary={**(run.get("summary") or {}), "execution_backend": execution_backend},
    )
    if not _postgres_runtime_configured():
        store = review_store()
        legacy_run = store.create_pipeline_run(
            preset_key=request.preset_key,
            run_role=request.run_role or "test",
            input_root=input_root,
            output_dir=output_dir,
            command=command,
            embedding_provider=embedding_provider,
            enable_llm_tags=enable_llm_tags,
            llm_tag_provider=llm_tag_provider,
            ocr_fallback_provider=ocr_fallback_provider,
            semantic_index_path=request.semantic_index_path,
        )
        legacy_summary = {**(legacy_run.get("summary") or {}), "execution_backend": execution_backend}
        store.update_pipeline_run_progress(int(legacy_run["id"]), legacy_summary)
        legacy_run = {
            **store.get_pipeline_run(int(legacy_run["id"])),
            "source": "sqlite",
            "execution_backend": execution_backend,
            "run_metadata": {
                "execution_backend": execution_backend,
                "run_role": request.run_role or "test",
                "source": "sqlite",
                "embedding_provider": embedding_provider,
                "llm_tag_provider": llm_tag_provider,
                "ocr_fallback_provider": ocr_fallback_provider,
                "enable_llm_tags": enable_llm_tags,
                "taxonomy_path": str(DEFAULT_TAXONOMY_PATH),
                "taxonomy_version": Path(DEFAULT_TAXONOMY_PATH).name,
            },
            "postgres_record": postgres_record,
        }
        if request.start:
            sample_count = _batch_input_sample_count(input_root)
            if sample_count == 0:
                error = "No runnable QA sample indexes found in input_root. Batch runs require grouped index.jsonl files; use the file browser for single-file runs."
                failed_summary = {"selected_sample_count": 0, "processed_count": 0, "error_count": 1, "execution_backend": execution_backend}
                store.mark_pipeline_run_finished(int(legacy_run["id"]), status="failed", summary=failed_summary, error=error)
                failed_run = store.get_pipeline_run(int(legacy_run["id"]))
                return {
                    **failed_run,
                    "source": "sqlite",
                    "execution_backend": execution_backend,
                    "run_metadata": legacy_run["run_metadata"],
                    "postgres_record": postgres_record,
                }
            store.update_pipeline_run_progress(
                int(legacy_run["id"]),
                {**legacy_summary, "selected_sample_count": sample_count, "processed_count": 0},
            )
            if execution_backend == "temporal":
                payload = _temporal_batch_payload(
                    input_root=input_root,
                    output_dir=output_dir,
                    semantic_index_path=request.semantic_index_path,
                )
                thread = threading.Thread(target=_execute_temporal_batch_run, args=(int(legacy_run["id"]), payload, request.import_on_success), daemon=True)
            else:
                thread = threading.Thread(target=_execute_run, args=(int(legacy_run["id"]), command, output_dir, request.import_on_success), daemon=True)
            thread.start()
            legacy_run = {
                **store.get_pipeline_run(int(legacy_run["id"])),
                "source": "sqlite",
                "execution_backend": execution_backend,
                "run_metadata": legacy_run["run_metadata"],
                "postgres_record": postgres_record,
            }
        return legacy_run
    if request.start:
        sample_count = _batch_input_sample_count(input_root)
        if sample_count == 0:
            error = "No runnable QA sample indexes found in input_root. Batch runs require grouped index.jsonl files; use the file browser for single-file runs."
            failed_run = {
                **run,
                "status": "failed",
                "summary": {"selected_sample_count": 0, "processed_count": 0, "error_count": 1, "execution_backend": execution_backend},
                "error": error,
            }
            record_postgres_pipeline_run_state_if_configured(
                run=failed_run,
                status="failed",
                summary={**(failed_run.get("summary") or {}), "execution_backend": execution_backend},
                error=failed_run.get("error"),
            )
            return {**failed_run, "postgres_record": postgres_record}
        run["summary"] = {**(run.get("summary") or {}), "selected_sample_count": sample_count, "processed_count": 0}
        record_postgres_pipeline_run_state_if_configured(run=run, status="queued", summary=run["summary"])
        if execution_backend == "temporal":
            payload = _temporal_batch_payload(
                input_root=input_root,
                output_dir=output_dir,
                semantic_index_path=request.semantic_index_path,
            )
            thread = threading.Thread(target=_execute_postgres_run, args=(run, command, output_dir, request.import_on_success), daemon=True)
        else:
            thread = threading.Thread(target=_execute_postgres_run, args=(run, command, output_dir, request.import_on_success), daemon=True)
        thread.start()
    return {**run, "postgres_record": postgres_record}


def _postgres_runtime_configured() -> bool:
    return bool(os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL"))


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
def runs(limit: int = 100, source: str | None = None) -> list[dict[str, Any]]:
    if source is None and not _postgres_runtime_configured():
        return review_store().list_pipeline_runs(limit=limit)
    if source not in (None, "postgres"):
        raise HTTPException(status_code=410, detail="SQLite dashboard run storage has been retired; use source=postgres")
    try:
        return [_postgres_run_for_dashboard(row) for row in list_postgres_pipeline_runs(limit=limit)]
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _legacy_runs_by_key_with_reconciliation() -> dict[str, dict[str, Any]]:
    store = review_store()
    reconciled: dict[str, dict[str, Any]] = {}
    for run in store.list_pipeline_runs(limit=1000):
        summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        if run.get("status") == "running":
            output_dir = str(run.get("output_dir") or "")
            summary = _read_live_run_summary(output_dir, summary)
            run, summary = _reconcile_completed_filesystem_run(store, run, summary)
        run_key = str(run.get("run_key") or "")
        if run_key:
            reconciled[run_key] = run
    return reconciled


def _postgres_run_for_dashboard(row: dict[str, Any], legacy_run: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    legacy_summary = legacy_run.get("summary") if isinstance(legacy_run, dict) and isinstance(legacy_run.get("summary"), dict) else {}
    effective_summary = {**summary, **legacy_summary}
    execution_backend = summary.get("execution_backend") or summary.get("graph_runtime", {}).get("execution_backend")
    run_metadata = {
        "source": "postgres",
        "legacy_run_id": legacy_run.get("id") if legacy_run else None,
        "result_count": row.get("result_count"),
        "review_required_count": row.get("review_required_count"),
        "model_usage_count": row.get("model_usage_count"),
        "provider_attempt_count": row.get("provider_attempt_count"),
        "document_segment_count": row.get("document_segment_count"),
        "execution_backend": execution_backend,
    }
    return {
        "id": legacy_run.get("id") if legacy_run else row.get("run_key") or row.get("id"),
        "legacy_run_id": legacy_run.get("id") if legacy_run else None,
        "postgres_id": row.get("id"),
        "source": "postgres",
        "run_key": row.get("run_key"),
        "preset_key": legacy_run.get("preset_key") if legacy_run else row.get("preset_key"),
        "run_role": effective_summary.get("run_role") or effective_summary.get("graph_runtime", {}).get("run_role") or "v2",
        "status": legacy_run.get("status") if legacy_run else row.get("status"),
        "input_root": legacy_run.get("input_root") if legacy_run else row.get("input_root"),
        "output_dir": legacy_run.get("output_dir") if legacy_run else row.get("output_dir"),
        "command": [],
        "embedding_provider": legacy_run.get("embedding_provider") if legacy_run else row.get("embedding_provider"),
        "enable_llm_tags": bool((legacy_run or {}).get("enable_llm_tags") if legacy_run else row.get("llm_provider")),
        "llm_tag_provider": legacy_run.get("llm_tag_provider") if legacy_run else row.get("llm_provider"),
        "ocr_fallback_provider": legacy_run.get("ocr_fallback_provider") if legacy_run else row.get("extraction_provider"),
        "semantic_index_path": legacy_run.get("semantic_index_path") if legacy_run else None,
        "run_metadata": run_metadata,
        "execution_backend": execution_backend,
        "started_at": legacy_run.get("started_at") if legacy_run else row.get("started_at"),
        "completed_at": legacy_run.get("completed_at") if legacy_run else row.get("finished_at"),
        "processed_count": effective_summary.get("processed_count") or effective_summary.get("total_results") or (legacy_run or {}).get("processed_count") or row.get("result_count"),
        "route_candidate_count": effective_summary.get("route_candidate_count") or (legacy_run or {}).get("route_candidate_count"),
        "review_required_count": (legacy_run or {}).get("review_required_count") or row.get("review_required_count"),
        "failed_count": effective_summary.get("failed_count") or effective_summary.get("error_count") or (legacy_run or {}).get("failed_count"),
        "summary": effective_summary,
        "error": (legacy_run or {}).get("error") or effective_summary.get("error"),
        "created_at": (legacy_run or {}).get("created_at") or row.get("created_at"),
        "updated_at": (legacy_run or {}).get("updated_at") or row.get("updated_at"),
    }


def _get_pipeline_run_by_key(store: Any, run_key: str) -> dict[str, Any]:
    for run in store.list_pipeline_runs(limit=5000):
        if str(run.get("run_key") or "") == run_key:
            return run
    raise HTTPException(status_code=404, detail=f"Pipeline run {run_key!r} not found in dashboard run store")


def _cancel_pipeline_run(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    run_id = int(run["id"])
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
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    store.mark_pipeline_run_finished(run_id, status="cancelled", summary=summary, error="Cancelled from dashboard.")
    cancelled = store.get_pipeline_run(run_id)
    try:
        record_postgres_pipeline_run_state_if_configured(
            run=cancelled,
            status="cancelled",
            summary={
                **(cancelled.get("summary") or {}),
                "execution_backend": cancelled.get("execution_backend") or (cancelled.get("run_metadata") or {}).get("execution_backend") or "subprocess",
            },
            error=cancelled.get("error"),
        )
    except Exception:  # noqa: BLE001 - legacy dashboard state remains authoritative.
        pass
    return cancelled


def _delete_pipeline_run(store: Any, run: dict[str, Any], *, delete_artifacts: bool = True, force: bool = False) -> dict[str, Any]:
    run_id = int(run["id"])
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


@router.post("/admin/runs/by-key/{run_key}/cancel")
def cancel_run_by_key(run_key: str) -> dict[str, Any]:
    try:
        postgres_run = _postgres_run_for_dashboard(next(row for row in list_postgres_pipeline_runs(limit=500) if row.get("run_key") == run_key))
    except StopIteration as error:
        raise HTTPException(status_code=404, detail=f"Postgres pipeline run {run_key!r} not found") from error
    if postgres_run["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=400, detail=f"Run is {postgres_run['status']}; only queued/running runs can be cancelled")
    cancel_postgres_run_process(run_key)
    cancelled = {**postgres_run, "status": "cancelled", "error": "Cancelled from dashboard."}
    record_postgres_pipeline_run_state_if_configured(
        run=cancelled,
        status="cancelled",
        summary={**(postgres_run.get("summary") or {}), "cancelled_from_dashboard": True},
        error=cancelled["error"],
    )
    return cancelled


@router.delete("/admin/runs/by-key/{run_key}")
def delete_run_by_key(run_key: str, delete_artifacts: bool = True, force: bool = False) -> dict[str, Any]:
    run = None
    for row in list_postgres_pipeline_runs(limit=500):
        if row.get("run_key") == run_key:
            run = _postgres_run_for_dashboard(row)
            break
    if run is None:
        raise HTTPException(status_code=404, detail=f"Postgres pipeline run {run_key!r} not found")
    if run["status"] == "running" and not force:
        raise HTTPException(status_code=400, detail=f"Run is {run['status']}; cancel it first or pass force=true")
    if force:
        cancel_postgres_run_process(run_key)
    postgres_delete = delete_postgres_pipeline_run_if_configured(run_key=run_key)
    artifact_result = {"deleted": False, "path": run.get("output_dir"), "skipped_reason": "delete_artifacts_false"}
    if delete_artifacts and run.get("output_dir"):
        artifact_result = _delete_run_output_dir(Path(str(run["output_dir"])))
    return {"deleted": True, "run": run, "postgres_delete": postgres_delete, "artifacts": artifact_result}


@router.post("/admin/runs/by-key/{run_key}/import-results")
def import_run_results_by_key(run_key: str) -> dict[str, Any]:
    run = None
    for row in list_postgres_pipeline_runs(limit=500):
        if row.get("run_key") == run_key:
            run = _postgres_run_for_dashboard(row)
            break
    if run is None:
        raise HTTPException(status_code=404, detail=f"Postgres pipeline run {run_key!r} not found")
    output_dir = run.get("output_dir")
    if not output_dir:
        raise HTTPException(status_code=400, detail="Run has no output_dir")
    return import_langgraph_output_to_postgres_if_configured(
        output_dir,
        run_key=run_key,
        preset_key=run.get("preset_key"),
    )


@router.get("/admin/runs/by-key/{run_key}/results")
def run_results_by_key(run_key: str, limit: int = 200) -> dict[str, Any]:
    for row in list_postgres_pipeline_runs(limit=500):
        if row.get("run_key") == run_key:
            run = _postgres_run_for_dashboard(row)
            output_dir = Path(str(run.get("output_dir") or ""))
            sample_results_path = output_dir / "sample-pipeline-results.jsonl"
            if sample_results_path.exists():
                rows = []
                with sample_results_path.open("r", encoding="utf-8") as input_file:
                    for line in input_file:
                        if len(rows) >= limit:
                            break
                        if line.strip():
                            rows.append(json.loads(line))
                return {"run_key": run_key, "output_dir": str(output_dir), "result_type": "batch", "results": rows}
            return {"run_key": run_key, "output_dir": str(output_dir), "result_type": "none", "results": []}
    raise HTTPException(status_code=404, detail=f"Postgres pipeline run {run_key!r} not found")


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
    run, summary = _reconcile_completed_filesystem_run(store, run, summary)
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


def _reconcile_completed_filesystem_run(
    store: Any,
    run: dict[str, Any],
    summary: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Repair stale running rows when final filesystem artifacts exist.

    Subprocess runs are owned by an API background thread. If the API restarts,
    the child process can finish and write complete JSONL artifacts while the
    SQLite run row remains stuck in ``running``. The final artifacts are the
    source of truth for dev subprocess runs, so progress/report reads reconcile
    that stale state.
    """

    active_summary = summary or run.get("summary") or {}
    if run.get("status") != "running":
        return run, active_summary
    run_id = int(run["id"])
    if _registered_process_is_active(run_id):
        return run, active_summary
    output_dir = Path(str(run.get("output_dir") or ""))
    artifact_summary = {**active_summary, **_read_live_run_summary(str(output_dir), run.get("summary") or {})}
    if output_dir.exists() and _run_artifacts_indicate_completion(output_dir, artifact_summary):
        reconciled_summary = {**artifact_summary, "progress_ratio": 1.0}
        error_count = _int_value(reconciled_summary.get("error_count"))
        status = "failed" if error_count > 0 else "succeeded"
        error = f"Run completed with {error_count} errors after API restart." if error_count > 0 else None
        if status == "succeeded" and (output_dir / "sample-pipeline-results.jsonl").exists():
            _import_reconciled_run_outputs(store, run_id, str(output_dir))
        store.mark_pipeline_run_finished(run_id, status=status, summary=reconciled_summary, error=error)
        repaired_run = store.get_pipeline_run(run_id)
        try:
            record_postgres_pipeline_run_state_if_configured(
                run=repaired_run,
                status=status,
                summary={
                    **(repaired_run.get("summary") or {}),
                    "execution_backend": repaired_run.get("execution_backend") or "subprocess",
                },
                error=repaired_run.get("error"),
            )
        except Exception:  # noqa: BLE001 - SQLite state and artifacts remain authoritative.
            pass
        return repaired_run, reconciled_summary
    if _run_is_inside_startup_grace_period(run):
        return run, active_summary

    if not output_dir.exists():
        return _mark_lost_process_run_failed(store, run, active_summary, "Run process is not active and output directory does not exist.")

    active_summary = {**active_summary, **_read_live_run_summary(str(output_dir), run.get("summary") or {})}
    if not _run_artifacts_indicate_completion(output_dir, active_summary):
        return _mark_lost_process_run_failed(store, run, active_summary, "Run process is not active and final artifacts are incomplete.")

    reconciled_summary = {**active_summary, "progress_ratio": 1.0}
    error_count = _int_value(reconciled_summary.get("error_count"))
    status = "failed" if error_count > 0 else "succeeded"
    error = f"Run completed with {error_count} errors after API restart." if error_count > 0 else None
    if status == "succeeded" and (output_dir / "sample-pipeline-results.jsonl").exists():
        _import_reconciled_run_outputs(store, run_id, str(output_dir))
    store.mark_pipeline_run_finished(run_id, status=status, summary=reconciled_summary, error=error)
    repaired_run = store.get_pipeline_run(run_id)
    try:
        record_postgres_pipeline_run_state_if_configured(
            run=repaired_run,
            status=status,
            summary={
                **(repaired_run.get("summary") or {}),
                "execution_backend": repaired_run.get("execution_backend") or "subprocess",
            },
            error=repaired_run.get("error"),
        )
    except Exception:  # noqa: BLE001 - SQLite state and artifacts remain authoritative.
        pass
    return repaired_run, reconciled_summary


def _mark_lost_process_run_failed(
    store: Any,
    run: dict[str, Any],
    summary: dict[str, Any],
    error: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mark stale dev subprocess runs failed when no live owner remains."""

    run_id = int(run["id"])
    failed_summary = {
        **(summary or run.get("summary") or {}),
        "stale_run_reconciled": True,
        "stale_run_reason": error,
    }
    store.mark_pipeline_run_finished(run_id, status="failed", summary=failed_summary, error=error)
    failed_run = store.get_pipeline_run(run_id)
    try:
        record_postgres_pipeline_run_state_if_configured(
            run=failed_run,
            status="failed",
            summary={
                **(failed_run.get("summary") or {}),
                "execution_backend": failed_run.get("execution_backend") or (failed_run.get("run_metadata") or {}).get("execution_backend") or "subprocess",
            },
            error=failed_run.get("error"),
        )
    except Exception:  # noqa: BLE001 - SQLite state remains authoritative.
        pass
    return failed_run, failed_summary


def _registered_process_is_active(run_id: int) -> bool:
    with _RUN_PROCESS_LOCK:
        process = _RUN_PROCESSES.get(run_id)
    return process is not None and process.poll() is None


def _run_is_inside_startup_grace_period(run: dict[str, Any], *, grace_seconds: int = 180) -> bool:
    """Avoid failing fresh runs before their subprocess has registered artifacts."""

    started_at = _parse_sqlite_timestamp(run.get("started_at") or run.get("updated_at") or run.get("created_at"))
    if started_at is None:
        return False
    return (datetime.now(UTC) - started_at).total_seconds() < grace_seconds


def _parse_sqlite_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _run_artifacts_indicate_completion(output_dir: Path, summary: dict[str, Any]) -> bool:
    if (output_dir / "graph-result.json").exists():
        return True
    if not (output_dir / "sample-pipeline-summary.json").exists():
        return False
    if not (output_dir / "sample-pipeline-results.jsonl").exists():
        return False
    processed = _int_value(summary.get("processed_count") or summary.get("total_results") or summary.get("graph_run_count"))
    total = _int_value(summary.get("selected_sample_count") or summary.get("total_count") or summary.get("graph_run_count"))
    return processed > 0 and total > 0 and processed >= total


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _import_reconciled_run_outputs(store: Any, run_id: int, output_dir: str) -> None:
    run = store.get_pipeline_run(run_id)
    sqlite_result = store.import_langgraph_output(output_dir, sample_routed_per_bucket=0, run_id=run_id)
    try:
        postgres_result = import_langgraph_output_to_postgres_if_configured(
            output_dir,
            run_key=str(run["run_key"]),
            preset_key=run.get("preset_key"),
        )
        postgres_level = "info" if postgres_result.get("import_status") != "skipped" else "warning"
    except Exception as error:  # noqa: BLE001 - import failures should be visible without hiding SQLite import.
        postgres_result = {
            "import_status": "failed",
            "importer": "postgres_runtime",
            "error": f"{type(error).__name__}: {error}",
        }
        postgres_level = "error"
    with store._connect() as connection:
        store.add_pipeline_run_event(
            connection,
            run_id,
            level="info",
            message="Auto-imported completed run artifacts into legacy dashboard store after stale-run reconciliation.",
            payload=sqlite_result,
        )
        store.add_pipeline_run_event(
            connection,
            run_id,
            level=postgres_level,
            message="Auto-imported completed run artifacts into Postgres V2 runtime after stale-run reconciliation." if postgres_result.get("import_status") == "imported" else "Postgres V2 runtime auto-import skipped or failed after stale-run reconciliation.",
            payload=postgres_result,
        )


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
    run = store.get_pipeline_run(run_id)
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
    chunks = store.list_run_chunks(run_id) or _read_run_jsonl_with_live_fallback(output_dir, "sample-chunks.jsonl", limit=500)
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
            "processed_count": _first_not_none(progress.get("processed_count"), run.get("processed_count"), summary.get("processed_count")),
            "total_count": progress.get("total_count"),
            "route_candidate_count": _first_not_none(run.get("route_candidate_count"), summary.get("route_candidate_count")),
            "review_required_count": _first_not_none(run.get("review_required_count"), summary.get("review_required_count")),
            "failed_count": _first_not_none(run.get("failed_count"), summary.get("failed_count")),
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
        "chunks": {
            "count": len(chunks),
            "by_kind": _count_values(chunks, "chunk_kind"),
            "by_segment_type": _count_values(chunks, "segment_type"),
            "segment_chunk_count": sum(1 for row in chunks if row.get("segment_id")),
            "items": chunks[:100],
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
    return _cancel_pipeline_run(store, run)


@router.delete("/admin/runs/{run_id}")
def delete_run(run_id: int, delete_artifacts: bool = True, force: bool = False) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _delete_pipeline_run(store, run, delete_artifacts=delete_artifacts, force=force)


@router.post("/admin/runs/{run_id}/import-results")
def import_run_results(run_id: str) -> dict[str, Any]:
    try:
        numeric_run_id = int(run_id)
    except ValueError:
        return import_run_results_by_key(run_id)
    store = review_store()
    try:
        run = store.get_pipeline_run(numeric_run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = run.get("output_dir")
    if not output_dir:
        raise HTTPException(status_code=400, detail="Run has no output_dir")
    legacy_result = store.import_langgraph_output(output_dir, sample_routed_per_bucket=0, run_id=numeric_run_id)
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
