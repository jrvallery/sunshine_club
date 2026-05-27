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
    PipelineEvalRequest,
    SemanticEvalRequest,
    SemanticIndexBuildRequest,
)

router = APIRouter()


from sunshine_api.services.semantic import _semantic_index_status
from sunshine_extraction.evaluate_pipeline import DEFAULT_EVAL_OUTPUT_DIR, run_golden_pipeline_evaluation
from sunshine_extraction.sample_pipeline import load_pipeline_env
from sunshine_extraction.sample_pipeline import LLMTagInspector, llm_tag_inspector_from_env, ocr_executor_from_env
from sunshine_extraction.semantic_eval import evaluate_review_db
from sunshine_extraction.semantic_index import DEFAULT_INDEX_DB, build_semantic_index


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


@router.post("/admin/pipeline-eval/run")
def pipeline_eval_run(request: PipelineEvalRequest) -> dict[str, Any]:
    load_pipeline_env()
    labels_db = request.labels_db or str(review_store().db_path)
    output_dir = request.output_dir or DEFAULT_EVAL_OUTPUT_DIR
    report = run_golden_pipeline_evaluation(
        labels_db,
        output_dir=output_dir,
        limit=request.limit,
        llm_tag_inspector=llm_tag_inspector_from_env() if request.enable_llm_tags else LLMTagInspector(),
        ocr_executor=ocr_executor_from_env() if request.enable_ocr else None,
        semantic_index_path=None if request.disable_semantic_index else (request.semantic_index_path or DEFAULT_INDEX_DB),
    )
    return {"ok": True, "output_dir": output_dir, "report": report}
