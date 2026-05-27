from pathlib import Path
import csv
import io
import json
import os
import re
import selectors
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from sunshine_core.models import FoundationRunRequest, ThinSliceOutcome
from sunshine_core.repository import InMemoryFoundationRepository
from sunshine_core.thin_slice import run_foundation_slice
from sunshine_extraction.langgraph_pipeline import run_document_graph
from sunshine_extraction.sample_pipeline import llm_tag_inspector_from_env, load_pipeline_env
from sunshine_extraction.semantic_eval import evaluate_review_db
from sunshine_extraction.semantic_index import DEFAULT_INDEX_DB, build_semantic_index
from sunshine_api.review_store import ReviewStore

app = FastAPI(title="Sunshine Club API")
repository = InMemoryFoundationRepository()
_RUN_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_RUN_PROCESS_LOCK = threading.Lock()
_RUN_PROGRESS_PATTERN = re.compile(r"\[(?P<current>\d+)/(?P<total>\d+)\]")


class DocumentPipelineRunRequest(BaseModel):
    input_file: str
    output_dir: str
    source_path: str | None = None
    relative_path: str | None = None
    checkpoint_path: str | None = None
    thread_id: str | None = None
    retry_attempts: int = Field(default=1, ge=1)
    retry_delay_seconds: float = Field(default=0, ge=0)
    enable_llm_tags: bool = False
    llm_tag_provider: str | None = None


class DocumentPipelineRunResponse(BaseModel):
    final_result: dict[str, Any]
    graph_result_path: str
    graph_audit_events_path: str
    checkpoint_path: str | None = None


class ReviewImportRequest(BaseModel):
    output_dir: str
    sample_routed_per_bucket: int = Field(default=0, ge=0)
    sample_seed: int = 20260526


class ReviewDecisionRequest(BaseModel):
    decision: str
    correct_class: str | None = None
    correct_tag: str | None = None
    correct_secondary_tags: list[str] | None = None
    correct_destination_path: str | None = None
    correct_placement_year: str | None = None
    correct_privacy: str | None = None
    review_stage: str | None = None
    notes: str | None = None
    reviewer: str | None = None
    save_as_golden: bool = True


class FileReviewRequest(BaseModel):
    review_reason: str = "manual_file_review"


class FileRunRequest(BaseModel):
    output_dir: str | None = None
    embedding_provider: Literal["cortex", "openai"] | None = None
    enable_llm_tags: bool = False
    llm_tag_provider: Literal["cortex", "openai"] | None = None
    ocr_fallback_provider: Literal["cortex", "openai"] | None = None
    semantic_index_path: str | None = None
    import_on_success: bool = False
    start: bool = True


class GoldenLabelUpdateRequest(BaseModel):
    correct_primary_tag: str | None = None
    correct_secondary_tags: list[str] | None = None
    reviewer: str | None = None
    notes: str | None = None


class ReviewAssignRequest(BaseModel):
    assigned_reviewer: str | None = None
    review_stage: str | None = None
    priority: str | None = None


class RunStartRequest(BaseModel):
    preset_key: str
    input_root: str | None = None
    output_dir: str | None = None
    embedding_provider: Literal["cortex", "openai"] | None = None
    enable_llm_tags: bool | None = None
    llm_tag_provider: Literal["cortex", "openai"] | None = None
    ocr_fallback_provider: Literal["cortex", "openai"] | None = None
    semantic_index_path: str | None = None
    import_on_success: bool = False
    start: bool = True


class SemanticIndexBuildRequest(BaseModel):
    labels_db: str | None = None
    output_db: str | None = None
    limit: int | None = Field(default=None, ge=1)


class SemanticEvalRequest(BaseModel):
    labels_db: str | None = None
    output_dir: str | None = None


def review_store() -> ReviewStore:
    return ReviewStore()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/foundation/run-staged-file", response_model=ThinSliceOutcome)
def run_staged_file(request: FoundationRunRequest) -> ThinSliceOutcome:
    return run_foundation_slice(request, repository)


@app.post("/admin/pipeline/run-file", response_model=DocumentPipelineRunResponse)
def run_pipeline_file(request: DocumentPipelineRunRequest) -> DocumentPipelineRunResponse:
    load_pipeline_env()
    inspector = llm_tag_inspector_from_env(
        enabled=request.enable_llm_tags,
        provider_override=request.llm_tag_provider or "auto",
    )
    result = run_document_graph(
        request.input_file,
        output_dir=request.output_dir,
        source_path=request.source_path,
        relative_path=request.relative_path,
        checkpoint_path=request.checkpoint_path,
        thread_id=request.thread_id,
        retry_attempts=request.retry_attempts,
        retry_delay_seconds=request.retry_delay_seconds,
        llm_tag_inspector=inspector,
    )
    output_dir = Path(request.output_dir)
    return DocumentPipelineRunResponse(
        final_result=result["final_result"],
        graph_result_path=str(output_dir / "graph-result.json"),
        graph_audit_events_path=str(output_dir / "graph-audit-events.jsonl"),
        checkpoint_path=request.checkpoint_path,
    )


@app.post("/admin/review/import-langgraph-output")
def import_langgraph_output(request: ReviewImportRequest) -> dict[str, Any]:
    return review_store().import_langgraph_output(
        request.output_dir,
        sample_routed_per_bucket=request.sample_routed_per_bucket,
        sample_seed=request.sample_seed,
    )


@app.get("/admin/review/summary")
def review_summary() -> dict[str, Any]:
    return review_store().summary()


@app.get("/admin/review/placement-report")
def review_placement_report(limit: int = 100) -> dict[str, Any]:
    return review_store().placement_report(limit=limit)


@app.get("/admin/review/export")
def review_export(status: str = "all", limit: int = 1000) -> StreamingResponse:
    rows = review_store().review_export_rows(status=status, limit=limit)
    output = io.StringIO()
    fieldnames = [
        "id",
        "status",
        "review_reason",
        "relative_path",
        "source_path",
        "proposed_class",
        "proposed_tag",
        "secondary_tags",
        "confidence",
        "quality",
        "placement_status",
        "destination_path",
        "run_id",
        "run_key",
        "run_preset_key",
        "embedding_provider",
        "llm_tag_provider",
        "ocr_fallback_provider",
        "enable_llm_tags",
        "correct_class",
        "correct_tag",
        "correct_secondary_tags",
        "correct_destination_path",
        "correct_placement_year",
        "correct_privacy",
        "review_stage",
        "priority",
        "assigned_reviewer",
        "decision",
        "notes",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        result = row.get("result") or {}
        writer.writerow(
            {
                "id": row.get("id"),
                "status": row.get("status"),
                "review_reason": row.get("review_reason"),
                "relative_path": row.get("relative_path"),
                "source_path": row.get("source_path"),
                "proposed_class": row.get("proposed_class"),
                "proposed_tag": row.get("proposed_tag"),
                "secondary_tags": ";".join(row.get("secondary_tags") or []),
                "confidence": row.get("confidence"),
                "quality": result.get("quality"),
                "placement_status": result.get("placement_status"),
                "destination_path": result.get("destination_path"),
                "run_id": row.get("run_id"),
                "run_key": row.get("run_key"),
                "run_preset_key": row.get("run_preset_key"),
                "embedding_provider": row.get("embedding_provider"),
                "llm_tag_provider": row.get("llm_tag_provider"),
                "ocr_fallback_provider": row.get("ocr_fallback_provider"),
                "enable_llm_tags": row.get("enable_llm_tags"),
                "correct_class": row.get("correct_class"),
                "correct_tag": row.get("correct_tag"),
                "correct_secondary_tags": ";".join(row.get("correct_secondary_tags") or []),
                "correct_destination_path": row.get("correct_destination_path"),
                "correct_placement_year": row.get("correct_placement_year"),
                "correct_privacy": row.get("correct_privacy"),
                "review_stage": row.get("review_stage"),
                "priority": row.get("priority"),
                "assigned_reviewer": row.get("assigned_reviewer"),
                "decision": row.get("decision"),
                "notes": row.get("notes"),
            }
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sunshine-review-export.csv"'},
    )


@app.get("/admin/review/golden-labels")
def golden_labels(limit: int = 100) -> list[dict[str, Any]]:
    return review_store().list_golden_labels(limit=limit)


@app.get("/admin/review/golden-labels/summary")
def golden_label_summary() -> dict[str, Any]:
    return review_store().golden_label_summary()


@app.patch("/admin/review/golden-labels/{label_id}")
def update_golden_label(label_id: int, request: GoldenLabelUpdateRequest) -> dict[str, Any]:
    try:
        return review_store().update_golden_label(
            label_id,
            correct_primary_tag=request.correct_primary_tag,
            correct_secondary_tags=request.correct_secondary_tags,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/admin/review/golden-labels/{label_id}")
def delete_golden_label(label_id: int) -> dict[str, Any]:
    try:
        return review_store().delete_golden_label(label_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/admin/review/golden-labels/{label_id}/file")
def golden_label_file(label_id: int) -> FileResponse:
    try:
        path = review_store().file_path_for_golden_label(label_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name)


@app.get("/admin/review/items")
def review_items(
    status: str = "open",
    limit: int = 100,
    q: str | None = None,
    route_status: str | None = None,
    review_reason: str | None = None,
    primary_tag: str | None = None,
    secondary_tag: str | None = None,
    content_class: str | None = None,
    quality: str | None = None,
    placement_status: str | None = None,
    warning_type: str | None = None,
    source_collection: str | None = None,
    run_id: int | None = None,
    run_preset_key: str | None = None,
    embedding_provider: str | None = None,
    llm_tag_provider: str | None = None,
    ocr_fallback_provider: str | None = None,
    enable_llm_tags: bool | None = None,
) -> list[dict[str, Any]]:
    return review_store().list_review_items(
        status=status,
        limit=limit,
        q=q,
        route_status=route_status,
        review_reason=review_reason,
        primary_tag=primary_tag,
        secondary_tag=secondary_tag,
        content_class=content_class,
        quality=quality,
        placement_status=placement_status,
        warning_type=warning_type,
        source_collection=source_collection,
        run_id=run_id,
        run_preset_key=run_preset_key,
        embedding_provider=embedding_provider,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        enable_llm_tags=enable_llm_tags,
    )


@app.get("/admin/review/facets")
def review_facets(
    status: str = "open",
    q: str | None = None,
    route_status: str | None = None,
    review_reason: str | None = None,
    primary_tag: str | None = None,
    secondary_tag: str | None = None,
    content_class: str | None = None,
    quality: str | None = None,
    placement_status: str | None = None,
    warning_type: str | None = None,
    source_collection: str | None = None,
    run_id: int | None = None,
    run_preset_key: str | None = None,
    embedding_provider: str | None = None,
    llm_tag_provider: str | None = None,
    ocr_fallback_provider: str | None = None,
    enable_llm_tags: bool | None = None,
) -> dict[str, dict[str, int]]:
    return review_store().review_facets(
        status=status,
        q=q,
        route_status=route_status,
        review_reason=review_reason,
        primary_tag=primary_tag,
        secondary_tag=secondary_tag,
        content_class=content_class,
        quality=quality,
        placement_status=placement_status,
        warning_type=warning_type,
        source_collection=source_collection,
        run_id=run_id,
        run_preset_key=run_preset_key,
        embedding_provider=embedding_provider,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        enable_llm_tags=enable_llm_tags,
    )


@app.get("/admin/review/items/{item_id}")
def review_item_detail(item_id: int) -> dict[str, Any]:
    try:
        return review_store().get_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/admin/review/items/{item_id}/decision")
def record_review_decision(item_id: int, request: ReviewDecisionRequest) -> dict[str, Any]:
    return review_store().record_decision(
        item_id,
        decision=request.decision,
        correct_class=request.correct_class,
        correct_tag=request.correct_tag,
        correct_secondary_tags=request.correct_secondary_tags,
        correct_destination_path=request.correct_destination_path,
        correct_placement_year=request.correct_placement_year,
        correct_privacy=request.correct_privacy,
        review_stage=request.review_stage,
        notes=request.notes,
        reviewer=request.reviewer,
        save_as_golden=request.save_as_golden,
    )


@app.post("/admin/review/items/{item_id}/assign")
def assign_review_item(item_id: int, request: ReviewAssignRequest) -> dict[str, Any]:
    try:
        return review_store().assign_review_item(
            item_id,
            assigned_reviewer=request.assigned_reviewer,
            review_stage=request.review_stage,
            priority=request.priority,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/admin/review/items/{item_id}/file")
def review_item_file(item_id: int) -> FileResponse:
    try:
        path = review_store().file_path_for_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name)


@app.get("/admin/review/items/{item_id}/text")
def review_item_text(item_id: int) -> PlainTextResponse:
    try:
        item = review_store().get_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return PlainTextResponse(str(item.get("extraction_text_snippet") or ""))


@app.get("/admin/review/items/{item_id}/neighbors")
def review_item_neighbors(item_id: int) -> list[dict[str, Any]]:
    try:
        item = review_store().get_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return list(item.get("result", {}).get("semantic_examples") or [])


@app.get("/admin/files")
def files(
    q: str | None = None,
    source_collection: str | None = None,
    extension: str | None = None,
    content_class: str | None = None,
    primary_tag: str | None = None,
    secondary_tag: str | None = None,
    route_status: str | None = None,
    review_status: str | None = None,
    placement_status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return review_store().list_files(
        q=q,
        source_collection=source_collection,
        extension=extension,
        content_class=content_class,
        primary_tag=primary_tag,
        secondary_tag=secondary_tag,
        route_status=route_status,
        review_status=review_status,
        placement_status=placement_status,
        limit=limit,
    )


@app.get("/admin/files/search")
def file_search(
    q: str | None = None,
    source_collection: str | None = None,
    extension: str | None = None,
    content_class: str | None = None,
    primary_tag: str | None = None,
    secondary_tag: str | None = None,
    route_status: str | None = None,
    review_status: str | None = None,
    ocr_quality: str | None = None,
    warning_type: str | None = None,
    placement_status: str | None = None,
    run_id: int | None = None,
    sort: str = "updated_desc",
    cursor: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return review_store().search_files(
        q=q,
        source_collection=source_collection,
        extension=extension,
        content_class=content_class,
        primary_tag=primary_tag,
        secondary_tag=secondary_tag,
        route_status=route_status,
        review_status=review_status,
        ocr_quality=ocr_quality,
        warning_type=warning_type,
        placement_status=placement_status,
        run_id=run_id,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@app.get("/admin/files/facets")
def file_facets(
    q: str | None = None,
    source_collection: str | None = None,
    extension: str | None = None,
    content_class: str | None = None,
    primary_tag: str | None = None,
    secondary_tag: str | None = None,
    route_status: str | None = None,
    review_status: str | None = None,
    ocr_quality: str | None = None,
    warning_type: str | None = None,
    placement_status: str | None = None,
    run_id: int | None = None,
) -> dict[str, dict[str, int]]:
    return review_store().file_facets(
        q=q,
        source_collection=source_collection,
        extension=extension,
        content_class=content_class,
        primary_tag=primary_tag,
        secondary_tag=secondary_tag,
        route_status=route_status,
        review_status=review_status,
        ocr_quality=ocr_quality,
        warning_type=warning_type,
        placement_status=placement_status,
        run_id=run_id,
    )


@app.get("/admin/files/{file_id}")
def file_detail(file_id: int) -> dict[str, Any]:
    try:
        return review_store().get_file(file_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/admin/files/{file_id}/inspection")
def file_inspection(file_id: int) -> dict[str, Any]:
    try:
        return review_store().file_inspection(file_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/admin/files/{file_id}/preview")
def file_preview(file_id: int) -> FileResponse:
    try:
        path = review_store().file_path_for_file(file_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name)


@app.get("/admin/files/{file_id}/text")
def file_text(file_id: int) -> dict[str, Any]:
    try:
        return review_store().file_text(file_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/admin/files/{file_id}/review")
def add_file_to_review(file_id: int, request: FileReviewRequest) -> dict[str, Any]:
    try:
        return review_store().add_file_to_review(file_id, review_reason=request.review_reason)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/admin/files/{file_id}/run")
def run_file_from_browser(file_id: int, request: FileRunRequest) -> dict[str, Any]:
    store = review_store()
    try:
        file_record = store.get_file(file_id)
        input_file = store.file_path_for_file(file_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = request.output_dir or str(Path(".local/dashboard-runs") / f"single_file_{file_id}")
    command = _single_file_command(
        input_file=str(input_file),
        source_path=str(file_record["source_path"]),
        relative_path=str(file_record["relative_path"]),
        output_dir=output_dir,
        embedding_provider=request.embedding_provider,
        enable_llm_tags=request.enable_llm_tags,
        llm_tag_provider=request.llm_tag_provider,
        ocr_fallback_provider=request.ocr_fallback_provider,
        semantic_index_path=request.semantic_index_path,
    )
    run = store.create_pipeline_run(
        preset_key="single_file_debug",
        input_root=str(input_file),
        output_dir=output_dir,
        command=command,
        embedding_provider=request.embedding_provider,
        enable_llm_tags=request.enable_llm_tags,
        llm_tag_provider=request.llm_tag_provider,
        ocr_fallback_provider=request.ocr_fallback_provider,
        semantic_index_path=request.semantic_index_path,
    )
    if request.start:
        thread = threading.Thread(target=_execute_run, args=(run["id"], command, output_dir, request.import_on_success), daemon=True)
        thread.start()
    return run


@app.get("/admin/runs/presets")
def run_presets() -> list[dict[str, Any]]:
    return review_store().run_presets()


@app.post("/admin/runs")
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
    run = store.create_pipeline_run(
        preset_key=request.preset_key,
        input_root=input_root,
        output_dir=output_dir,
        command=command,
        embedding_provider=embedding_provider,
        enable_llm_tags=enable_llm_tags,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        semantic_index_path=request.semantic_index_path,
    )
    if request.start:
        sample_count = _batch_input_sample_count(input_root)
        if sample_count == 0:
            store.mark_pipeline_run_finished(
                run["id"],
                status="failed",
                summary={"selected_sample_count": 0, "processed_count": 0, "error_count": 1},
                error="No runnable QA sample indexes found in input_root. Batch runs require grouped index.jsonl files; use the file browser for single-file runs.",
            )
            return store.get_pipeline_run(run["id"])
        store.update_pipeline_run_progress(run["id"], {"selected_sample_count": sample_count, "processed_count": 0})
        thread = threading.Thread(target=_execute_run, args=(run["id"], command, output_dir, request.import_on_success), daemon=True)
        thread.start()
    return run


@app.get("/admin/runs")
def runs(limit: int = 100) -> list[dict[str, Any]]:
    return review_store().list_pipeline_runs(limit=limit)


@app.get("/admin/runs/{run_id}")
def run_detail(run_id: int) -> dict[str, Any]:
    try:
        return review_store().get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/admin/runs/{run_id}/events")
def run_events(run_id: int, limit: int = 200) -> list[dict[str, Any]]:
    return review_store().list_pipeline_run_events(run_id, limit=limit)


@app.get("/admin/runs/{run_id}/progress")
def run_progress(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = str(run.get("output_dir") or "")
    summary = _read_run_summary(output_dir)
    if run["status"] == "running":
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


@app.get("/admin/runs/{run_id}/results")
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


@app.get("/admin/runs/{run_id}/artifacts")
def run_artifacts(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = Path(str(run.get("output_dir") or ""))
    return {"run_id": run_id, "output_dir": str(output_dir), "artifacts": _run_artifacts(output_dir)}


@app.get("/admin/runs/{run_id}/model-usage")
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


@app.get("/admin/runs/{run_id}/report")
def run_report(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = Path(str(run.get("output_dir") or ""))
    progress = run_progress(run_id)
    results = list(_load_run_results_by_source(str(output_dir)).values())
    review_queue = _read_jsonl_file(output_dir / "sample-review-queue.jsonl", limit=200)
    ocr_documents = _read_jsonl_file(output_dir / "sample-ocr-documents.jsonl", limit=200)
    ocr_pages = _read_jsonl_file(output_dir / "sample-ocr-pages.jsonl", limit=200)
    extraction_results = _read_jsonl_file(output_dir / "sample-extraction-results.jsonl", limit=200)
    model_usage_rows = store.list_model_usage(run_id) or _read_model_usage_artifact(output_dir, run_id=run_id)
    comparison = run_compare_previous(run_id)
    artifacts = _run_artifacts(output_dir)
    summary = _read_run_summary(str(output_dir)) or run.get("summary") or {}
    review_items = store.list_review_items(status="all", run_id=run_id, limit=200)
    training_cycle = _training_cycle_metrics(run, review_items, store.list_golden_labels(limit=10000), comparison)
    return {
        "run": run,
        "progress": progress,
        "overview": {
            "processed_count": progress.get("processed_count") or run.get("processed_count") or summary.get("processed_count"),
            "total_count": progress.get("total_count"),
            "route_candidate_count": run.get("route_candidate_count") or summary.get("route_candidate_count"),
            "review_required_count": run.get("review_required_count") or summary.get("review_required_count"),
            "failed_count": run.get("failed_count") or summary.get("failed_count"),
            "summary": summary,
        },
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
        "extraction": {"count": len(extraction_results), "items": extraction_results[:100]},
        "tags": {
            "primary": _count_values(results, "top_tag_candidate"),
            "secondary": _count_list_values(results, "secondary_tags"),
            "llm_status": _count_values(results, "llm_status"),
        },
        "placement": {
            "status": _count_values(results, "placement_status"),
            "privacy": _count_values(results, "default_privacy"),
            "rule": _count_values(results, "placement_rule"),
        },
        "model_usage": _model_usage_report(model_usage_rows),
        "artifacts": artifacts,
        "diff": comparison,
        "training_cycle": training_cycle,
    }


@app.get("/admin/runs/{run_id}/compare-previous")
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


@app.post("/admin/runs/{run_id}/cancel")
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


@app.post("/admin/runs/{run_id}/import-results")
def import_run_results(run_id: int) -> dict[str, Any]:
    store = review_store()
    try:
        run = store.get_pipeline_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    output_dir = run.get("output_dir")
    if not output_dir:
        raise HTTPException(status_code=400, detail="Run has no output_dir")
    return store.import_langgraph_output(output_dir, sample_routed_per_bucket=0, run_id=run_id)


@app.post("/admin/runs/{run_id}/rerun-failed")
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


@app.get("/admin/semantic-index/status")
def semantic_index_status(index_db: str | None = None) -> dict[str, Any]:
    return _semantic_index_status(index_db or DEFAULT_INDEX_DB)


@app.post("/admin/semantic-index/build")
def semantic_index_build(request: SemanticIndexBuildRequest) -> dict[str, Any]:
    load_pipeline_env()
    labels_db = request.labels_db or str(review_store().db_path)
    output_db = request.output_db or DEFAULT_INDEX_DB
    summary = build_semantic_index(labels_db, output_db, limit=request.limit)
    return {"ok": True, "status": _semantic_index_status(output_db), **summary}


@app.get("/admin/semantic-eval/latest")
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


@app.post("/admin/semantic-eval/run")
def semantic_eval_run(request: SemanticEvalRequest) -> dict[str, Any]:
    labels_db = request.labels_db or str(review_store().db_path)
    output_dir = request.output_dir or ".local/semantic-eval"
    report = evaluate_review_db(labels_db, output_dir=output_dir)
    return {"ok": True, "output_dir": output_dir, "report": report}


def _batch_command(
    *,
    input_root: str,
    output_dir: str,
    embedding_provider: str | None,
    enable_llm_tags: bool,
    llm_tag_provider: str | None,
    ocr_fallback_provider: str | None,
    semantic_index_path: str | None,
) -> list[str]:
    command = [
        ".venv/bin/python",
        "-m",
        "sunshine_extraction.langgraph_pipeline",
        "--input-root",
        input_root,
        "--output-dir",
        output_dir,
        "--retry-attempts",
        "1",
    ]
    if embedding_provider:
        command.extend(["--embedding-provider", embedding_provider])
    if enable_llm_tags:
        command.append("--enable-llm-tags")
    if llm_tag_provider:
        command.extend(["--llm-tag-provider", llm_tag_provider])
    if ocr_fallback_provider:
        command.extend(["--ocr-fallback-provider", ocr_fallback_provider])
    if semantic_index_path:
        command.extend(["--semantic-index-path", semantic_index_path])
    return command


def _single_file_command(
    *,
    input_file: str,
    source_path: str,
    relative_path: str,
    output_dir: str,
    embedding_provider: str | None,
    enable_llm_tags: bool,
    llm_tag_provider: str | None,
    ocr_fallback_provider: str | None,
    semantic_index_path: str | None,
) -> list[str]:
    command = [
        ".venv/bin/python",
        "-m",
        "sunshine_extraction.langgraph_pipeline",
        "--input-file",
        input_file,
        "--source-path",
        source_path,
        "--relative-path",
        relative_path,
        "--output-dir",
        output_dir,
        "--retry-attempts",
        "1",
    ]
    if embedding_provider:
        command.extend(["--embedding-provider", embedding_provider])
    if enable_llm_tags:
        command.append("--enable-llm-tags")
    if llm_tag_provider:
        command.extend(["--llm-tag-provider", llm_tag_provider])
    if ocr_fallback_provider:
        command.extend(["--ocr-fallback-provider", ocr_fallback_provider])
    if semantic_index_path:
        command.extend(["--semantic-index-path", semantic_index_path])
    return command


def _batch_input_sample_count(input_root: str) -> int:
    input_path = Path(input_root)
    if not input_path.exists() or not input_path.is_dir():
        return 0
    count = 0
    for index_path in input_path.glob("*/index.jsonl"):
        try:
            with index_path.open("r", encoding="utf-8") as input_file:
                count += sum(1 for line in input_file if line.strip())
        except OSError:
            continue
    return count


def _execute_run(run_id: int, command: list[str], output_dir: str, import_on_success: bool) -> None:
    store = review_store()
    store.mark_pipeline_run_started(run_id)
    try:
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES[run_id] = process
        _stream_run_output(store, run_id, process, output_dir)
        summary = _read_run_summary(output_dir)
        if store.get_pipeline_run(run_id)["status"] == "cancelled":
            return
        if process.returncode == 0:
            if import_on_success and (Path(output_dir) / "sample-pipeline-results.jsonl").exists():
                store.import_langgraph_output(output_dir, sample_routed_per_bucket=0)
            store.mark_pipeline_run_finished(run_id, status="succeeded", summary=summary)
        else:
            store.mark_pipeline_run_finished(run_id, status="failed", summary=summary, error=f"Command exited {process.returncode}")
    except Exception as error:  # noqa: BLE001 - background run errors must be captured for the UI.
        store.mark_pipeline_run_finished(run_id, status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES.pop(run_id, None)


def _stream_run_output(store: ReviewStore, run_id: int, process: subprocess.Popen[str], output_dir: str) -> None:
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    last_heartbeat = time.monotonic()
    try:
        while selector.get_map():
            for key, _mask in selector.select(timeout=1.0):
                stream = key.fileobj
                line = stream.readline()
                if line == "":
                    selector.unregister(stream)
                    continue
                message = line.rstrip()
                if not message:
                    continue
                level = "error" if key.data == "stderr" and _is_error_log(message) else "info"
                payload = _progress_payload_from_message(message)
                with store._connect() as connection:
                    store.add_pipeline_run_event(connection, run_id, level=level, message=message[-4000:], payload=payload)
                if payload:
                    summary = {
                        "processed_count": payload["current"],
                        "selected_sample_count": payload["total"],
                        "progress_ratio": payload["current"] / payload["total"] if payload["total"] else None,
                    }
                    store.update_pipeline_run_progress(run_id, summary)
            if process.poll() is not None:
                for key in list(selector.get_map().values()):
                    line = key.fileobj.readline()
                    while line:
                        message = line.rstrip()
                        if message:
                            level = "error" if key.data == "stderr" and _is_error_log(message) else "info"
                            payload = _progress_payload_from_message(message)
                            with store._connect() as connection:
                                store.add_pipeline_run_event(connection, run_id, level=level, message=message[-4000:], payload=payload)
                        line = key.fileobj.readline()
                    selector.unregister(key.fileobj)
                break
            if time.monotonic() - last_heartbeat >= 15:
                summary = _read_live_run_summary(output_dir, store.get_pipeline_run(run_id).get("summary") or {})
                if summary:
                    store.update_pipeline_run_progress(run_id, summary)
                with store._connect() as connection:
                    store.add_pipeline_run_event(connection, run_id, level="info", message="Run still active.", payload=summary)
                last_heartbeat = time.monotonic()
    finally:
        selector.close()


def _is_error_log(message: str) -> bool:
    lowered = message.lower()
    return "error" in lowered or "traceback" in lowered or "exception" in lowered or "failed" in lowered


def _progress_payload_from_message(message: str) -> dict[str, Any]:
    match = _RUN_PROGRESS_PATTERN.search(message)
    if not match:
        return {}
    current = int(match.group("current"))
    total = int(match.group("total"))
    return {"current": current, "total": total, "progress_ratio": current / total if total else None}


def _read_live_run_summary(output_dir: str, current_summary: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(output_dir)
    summary = dict(current_summary)
    results_path = output_path / "sample-pipeline-results.jsonl"
    if results_path.exists():
        processed = _count_jsonl_rows(results_path)
        summary["processed_count"] = processed
        summary.setdefault("graph_run_count", processed)
    review_path = output_path / "sample-review-queue.jsonl"
    if review_path.exists():
        summary["review_required_count"] = _count_jsonl_rows(review_path)
    audit_path = output_path / "graph-audit-events.jsonl"
    if audit_path.exists():
        summary["audit_event_count"] = _count_jsonl_rows(audit_path)
    return summary


def _count_jsonl_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as input_file:
            return sum(1 for line in input_file if line.strip())
    except OSError:
        return 0


def _progress_total(run: dict[str, Any], summary: dict[str, Any]) -> int | None:
    value = summary.get("selected_sample_count") or summary.get("total_count") or summary.get("graph_run_count")
    if isinstance(value, int | float) and value > 0:
        return int(value)
    return None


def _progress_ratio(run: dict[str, Any], summary: dict[str, Any]) -> float | None:
    value = summary.get("progress_ratio")
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    total = _progress_total(run, summary)
    processed = run.get("processed_count") or summary.get("processed_count") or summary.get("graph_run_count")
    if total and isinstance(processed, int | float):
        return max(0.0, min(float(processed) / total, 1.0))
    if run.get("status") == "succeeded":
        return 1.0
    return None


def _read_run_summary(output_dir: str) -> dict[str, Any]:
    path = Path(output_dir) / "sample-pipeline-summary.json"
    if not path.exists():
        graph_result_path = Path(output_dir) / "graph-result.json"
        if not graph_result_path.exists():
            return {}
        try:
            graph_result = json.loads(graph_result_path.read_text(encoding="utf-8"))
            final_result = graph_result.get("final_result", graph_result)
            return {
                "processed_count": 1,
                "route_candidate_count": 1 if final_result.get("route_status") == "route_candidate" else 0,
                "review_required_count": 0 if final_result.get("route_status") == "route_candidate" else 1,
                "failed_count": 1 if str(final_result.get("route_status", "")).startswith("review_failed") else 0,
                "final_result": final_result,
            }
        except Exception:
            return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _load_run_results_by_source(output_dir: str) -> dict[str, dict[str, Any]]:
    output_path = Path(output_dir)
    sample_results_path = output_path / "sample-pipeline-results.jsonl"
    if sample_results_path.exists():
        rows: dict[str, dict[str, Any]] = {}
        with sample_results_path.open("r", encoding="utf-8") as input_file:
            for line in input_file:
                if not line.strip():
                    continue
                row = json.loads(line)
                source_path = str(row.get("source_path") or row.get("sample_path") or "")
                if source_path:
                    rows[source_path] = row
        return rows
    graph_result_path = output_path / "graph-result.json"
    if graph_result_path.exists():
        row = json.loads(graph_result_path.read_text(encoding="utf-8"))
        final_result = row.get("final_result", row)
        source_path = str(final_result.get("source_path") or final_result.get("sample_path") or "")
        return {source_path: final_result} if source_path else {}
    return {}


def _read_jsonl_file(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as input_file:
            for line in input_file:
                if limit is not None and len(rows) >= limit:
                    break
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def _run_artifacts(output_dir: Path) -> list[dict[str, Any]]:
    names = [
        "sample-pipeline-summary.json",
        "sample-pipeline-results.jsonl",
        "sample-review-queue.jsonl",
        "sample-extraction-results.jsonl",
        "sample-ocr-documents.jsonl",
        "sample-ocr-pages.jsonl",
        "sample-model-usage.jsonl",
        "graph-result.json",
        "graph-audit-events.jsonl",
    ]
    artifacts: list[dict[str, Any]] = []
    for name in names:
        path = output_dir / name
        exists = path.exists()
        stat = path.stat() if exists else None
        row_count = _count_jsonl_rows(path) if exists and path.suffix == ".jsonl" else None
        artifacts.append(
            {
                "name": name,
                "path": str(path),
                "exists": exists,
                "size_bytes": stat.st_size if stat else None,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat() if stat else None,
                "row_count": row_count,
            }
        )
    return artifacts


def _training_cycle_metrics(
    run: dict[str, Any],
    review_items: list[dict[str, Any]],
    golden_labels: list[dict[str, Any]],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    review_item_ids = {item.get("id") for item in review_items}
    linked_golden = [label for label in golden_labels if label.get("review_item_id") in review_item_ids]
    resolved = [item for item in review_items if item.get("status") == "resolved"]
    accepted = [item for item in resolved if item.get("decision") == "accept"]
    corrected = [item for item in resolved if item.get("decision") == "change"]
    processed = int(run.get("processed_count") or 0)
    review_required = int(run.get("review_required_count") or len(review_items))
    reviewed_with_decision = len(accepted) + len(corrected)
    primary_evaluated = [label for label in linked_golden if label.get("proposed_tag")]
    primary_correct = sum(1 for label in primary_evaluated if label.get("proposed_tag") == label.get("correct_primary_tag"))
    secondary_true_positive = 0
    secondary_false_positive = 0
    secondary_false_negative = 0
    for label in linked_golden:
        proposed = set(label.get("proposed_secondary_tags") or [])
        correct = set(label.get("correct_secondary_tags") or [])
        secondary_true_positive += len(proposed & correct)
        secondary_false_positive += len(proposed - correct)
        secondary_false_negative += len(correct - proposed)
    ocr_failure_count = sum(1 for item in review_items if _review_item_mentions(item, "ocr"))
    tag_disagreement_count = sum(1 for item in review_items if item.get("review_reason") == "llm_tag_disagreement")
    return {
        "files_processed": processed,
        "review_required_count": review_required,
        "review_item_count": len(review_items),
        "ocr_failure_count": ocr_failure_count,
        "tag_disagreement_count": tag_disagreement_count,
        "open_review_count": sum(1 for item in review_items if item.get("status") == "open"),
        "resolved_review_count": len(resolved),
        "accepted_count": len(accepted),
        "corrected_count": len(corrected),
        "golden_labels_created": len(linked_golden),
        "review_rate": _ratio(review_required, processed),
        "ocr_failure_rate": _ratio(ocr_failure_count, processed),
        "resolution_rate": _ratio(len(resolved), len(review_items)),
        "correction_rate": _ratio(len(corrected), reviewed_with_decision),
        "reviewed_primary_accuracy": _ratio(len(accepted), reviewed_with_decision),
        "golden_primary_accuracy": _ratio(primary_correct, len(primary_evaluated)),
        "golden_primary_correct": primary_correct,
        "golden_primary_evaluated": len(primary_evaluated),
        "secondary_precision": _ratio(secondary_true_positive, secondary_true_positive + secondary_false_positive),
        "secondary_recall": _ratio(secondary_true_positive, secondary_true_positive + secondary_false_negative),
        "run_to_run_changed_count": (comparison.get("summary") or {}).get("changed", 0),
        "run_to_run_added_count": (comparison.get("summary") or {}).get("added", 0),
        "run_to_run_removed_count": (comparison.get("summary") or {}).get("removed", 0),
        "previous_run_id": comparison.get("previous_run_id"),
    }


def _review_item_mentions(item: dict[str, Any], needle: str) -> bool:
    text_parts = [item.get("review_reason"), item.get("route_status")]
    text_parts.extend(item.get("warnings") or [])
    text = " ".join(str(part).lower() for part in text_parts if part)
    return needle.lower() in text


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _read_model_usage_artifact(output_dir: Path, *, run_id: int) -> list[dict[str, Any]]:
    rows = _read_jsonl_file(output_dir / "sample-model-usage.jsonl")
    for index, row in enumerate(rows, start=1):
        row.setdefault("id", index)
        row.setdefault("run_id", run_id)
        row.setdefault("purpose", "unknown")
        row.setdefault("provider", "unknown")
        row.setdefault("model", "unknown")
        row.setdefault("status", "unknown")
    return rows


def _model_usage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_calls": len(rows),
        "failed_calls": sum(1 for row in rows if str(row.get("status") or "").lower() not in {"ok", "success", "succeeded", "completed"}),
        "external_calls": sum(1 for row in rows if _is_external_model_call(row)),
        "local_calls": sum(1 for row in rows if not _is_external_model_call(row)),
        "runtime_ms": _sum_numeric(rows, "runtime_ms"),
        "input_tokens": _sum_numeric(rows, "input_tokens"),
        "output_tokens": _sum_numeric(rows, "output_tokens"),
        "total_tokens": _sum_numeric(rows, "total_tokens"),
        "estimated_external_cost_usd": round(
            sum(float(row.get("estimated_cost_usd") or 0) for row in rows if _is_external_model_call(row)),
            6,
        ),
    }
    return {
        "summary": summary,
        "by_provider_model": _model_usage_breakdowns(rows, ["provider", "model"]),
        "by_purpose": _model_usage_breakdowns(rows, ["purpose"]),
        "by_status": _count_values(rows, "status"),
        "calls": rows[:500],
    }


def _is_external_model_call(row: dict[str, Any]) -> bool:
    cost_basis = str(row.get("cost_basis") or "").lower()
    provider = str(row.get("provider") or "").lower()
    if cost_basis == "external":
        return True
    if cost_basis == "local":
        return False
    return provider in {"openai", "gemini", "google", "anthropic"}


def _model_usage_breakdowns(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, Any]]:
    breakdown: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = " / ".join(str(row.get(field) or "unknown") for field in fields)
        bucket = breakdown.setdefault(
            key,
            {
                "calls": 0,
                "failed_calls": 0,
                "runtime_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_external_cost_usd": 0.0,
            },
        )
        bucket["calls"] += 1
        if str(row.get("status") or "").lower() not in {"ok", "success", "succeeded", "completed"}:
            bucket["failed_calls"] += 1
        bucket["runtime_ms"] += int(row.get("runtime_ms") or 0)
        bucket["input_tokens"] += int(row.get("input_tokens") or 0)
        bucket["output_tokens"] += int(row.get("output_tokens") or 0)
        bucket["total_tokens"] += int(row.get("total_tokens") or 0)
        if _is_external_model_call(row):
            bucket["estimated_external_cost_usd"] = round(
                float(bucket["estimated_external_cost_usd"]) + float(row.get("estimated_cost_usd") or 0),
                6,
            )
    return breakdown


def _sum_numeric(rows: list[dict[str, Any]], field: str) -> int:
    return sum(int(row.get(field) or 0) for row in rows)


def _count_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _count_list_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        values = row.get(field) or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            key = str(value or "unknown")
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _result_file_rows(results: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = []
    for result in results[:limit]:
        rows.append(
            {
                "source_path": result.get("source_path"),
                "relative_path": result.get("relative_path"),
                "final_class": result.get("final_class"),
                "quality": result.get("quality"),
                "route_status": result.get("route_status"),
                "top_tag_candidate": result.get("top_tag_candidate"),
                "secondary_tags": result.get("secondary_tags") or [],
                "tag_confidence": result.get("tag_confidence"),
                "placement_status": result.get("placement_status"),
                "warnings": result.get("warnings") or [],
                "extraction_text_snippet": result.get("extraction_text_snippet") or result.get("text_snippet") or result.get("extracted_text_snippet"),
            }
        )
    return rows


def _semantic_index_status(index_db: str | Path) -> dict[str, Any]:
    path = Path(index_db)
    status: dict[str, Any] = {
        "index_db": str(path),
        "exists": path.exists(),
        "indexed": 0,
        "updated_at": None,
        "embedding_provider": None,
        "embedding_model": None,
        "embedding_dimensions": None,
        "semantic_quality": None,
    }
    if not path.exists():
        return status
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                select count(*) as indexed,
                       max(updated_at) as updated_at,
                       max(embedding_provider) as embedding_provider,
                       max(embedding_model) as embedding_model,
                       max(embedding_dimensions) as embedding_dimensions,
                       min(semantic_quality) as semantic_quality
                from semantic_index
                """
            ).fetchone()
    except sqlite3.Error as error:
        status["error"] = str(error)
        return status
    if row:
        status.update(
            {
                "indexed": int(row["indexed"] or 0),
                "updated_at": row["updated_at"],
                "embedding_provider": row["embedding_provider"],
                "embedding_model": row["embedding_model"],
                "embedding_dimensions": row["embedding_dimensions"],
                "semantic_quality": bool(row["semantic_quality"]) if row["semantic_quality"] is not None else None,
            }
        )
    return status
