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

repository = InMemoryFoundationRepository()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/admin/foundation/run-staged-file", response_model=ThinSliceOutcome)
def run_staged_file(request: FoundationRunRequest) -> ThinSliceOutcome:
    return run_foundation_slice(request, repository)

