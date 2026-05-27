"""Single-file document pipeline routes."""

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


from sunshine_extraction.langgraph_pipeline import run_document_graph
from sunshine_extraction.sample_pipeline import llm_tag_inspector_from_env, load_pipeline_env


@router.post("/admin/pipeline/run-file", response_model=DocumentPipelineRunResponse)
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


@router.post("/admin/review/import-langgraph-output")
def import_langgraph_output(request: ReviewImportRequest) -> dict[str, Any]:
    return review_store().import_langgraph_output(
        request.output_dir,
        sample_routed_per_bucket=request.sample_routed_per_bucket,
        sample_seed=request.sample_seed,
    )

