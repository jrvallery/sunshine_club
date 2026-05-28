"""Health and foundation-slice administration routes."""

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


from sunshine_core.models import FoundationRunRequest, ThinSliceOutcome
from sunshine_core.repository import InMemoryFoundationRepository
from sunshine_core.thin_slice import run_foundation_slice
from sunshine_api.services.imports import get_postgres_pipeline_run, list_postgres_pipeline_runs, list_postgres_review_items, postgres_runtime_summary
from sunshine_api.services.local_infrastructure import local_infrastructure_status

repository = InMemoryFoundationRepository()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/admin/system/local-infrastructure")
def local_infrastructure() -> dict[str, Any]:
    return local_infrastructure_status()


@router.get("/admin/system/postgres-runtime")
def postgres_runtime(limit: int = 25) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "summary": postgres_runtime_summary(),
            "runs": list_postgres_pipeline_runs(limit=limit),
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/admin/system/postgres-runtime/review-items")
def postgres_runtime_review_items(limit: int = 100, run_key: str | None = None) -> dict[str, Any]:
    try:
        items = list_postgres_review_items(limit=limit, run_key=run_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "run_key": run_key, "count": len(items), "items": items}


@router.get("/admin/system/postgres-runtime/runs/{run_key}")
def postgres_runtime_run_detail(run_key: str) -> dict[str, Any]:
    try:
        return {"ok": True, "run": get_postgres_pipeline_run(run_key=run_key)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/admin/foundation/run-staged-file", response_model=ThinSliceOutcome)
def run_staged_file(request: FoundationRunRequest) -> ThinSliceOutcome:
    return run_foundation_slice(request, repository)
