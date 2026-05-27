"""Review queue and golden-label routes."""

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


@router.get("/admin/review/summary")
def review_summary() -> dict[str, Any]:
    return review_store().summary()


@router.get("/admin/review/placement-report")
def review_placement_report(limit: int = 100) -> dict[str, Any]:
    return review_store().placement_report(limit=limit)


@router.get("/admin/review/export")
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


@router.get("/admin/review/golden-labels")
def golden_labels(limit: int = 100) -> list[dict[str, Any]]:
    return review_store().list_golden_labels(limit=limit)


@router.get("/admin/review/golden-labels/export")
def golden_labels_export(format: str = "csv", limit: int = 10000) -> StreamingResponse:
    rows = review_store().golden_label_export_rows(limit=limit)
    normalized_format = format.strip().lower()
    if normalized_format == "jsonl":
        payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        return StreamingResponse(
            iter([payload]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="sunshine-golden-labels.jsonl"'},
        )
    if normalized_format != "csv":
        raise HTTPException(status_code=400, detail="format must be csv or jsonl")

    output = io.StringIO()
    fieldnames = [
        "id",
        "review_item_id",
        "relative_path",
        "source_path",
        "sample_path",
        "content_class",
        "correct_primary_tag",
        "correct_secondary_tags",
        "ocr_quality_label",
        "expected_review_required",
        "sensitive_record",
        "correct_destination_path",
        "correct_placement_year",
        "correct_privacy",
        "proposed_tag",
        "proposed_secondary_tags",
        "proposed_confidence",
        "reviewer",
        "notes",
        "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "id": row.get("id"),
                "review_item_id": row.get("review_item_id"),
                "relative_path": row.get("relative_path"),
                "source_path": row.get("source_path"),
                "sample_path": row.get("sample_path"),
                "content_class": row.get("content_class"),
                "correct_primary_tag": row.get("correct_primary_tag"),
                "correct_secondary_tags": ";".join(row.get("correct_secondary_tags") or []),
                "ocr_quality_label": row.get("ocr_quality_label"),
                "expected_review_required": row.get("expected_review_required"),
                "sensitive_record": row.get("sensitive_record"),
                "correct_destination_path": row.get("correct_destination_path"),
                "correct_placement_year": row.get("correct_placement_year"),
                "correct_privacy": row.get("correct_privacy"),
                "proposed_tag": row.get("proposed_tag"),
                "proposed_secondary_tags": ";".join(row.get("proposed_secondary_tags") or []),
                "proposed_confidence": row.get("proposed_confidence"),
                "reviewer": row.get("reviewer"),
                "notes": row.get("notes"),
                "updated_at": row.get("updated_at"),
            }
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sunshine-golden-labels.csv"'},
    )


@router.get("/admin/review/golden-labels/summary")
def golden_label_summary() -> dict[str, Any]:
    return review_store().golden_label_summary()


@router.patch("/admin/review/golden-labels/{label_id}")
def update_golden_label(label_id: int, request: GoldenLabelUpdateRequest) -> dict[str, Any]:
    try:
        return review_store().update_golden_label(
            label_id,
            content_class=request.content_class,
            correct_primary_tag=request.correct_primary_tag,
            correct_secondary_tags=request.correct_secondary_tags,
            ocr_quality_label=request.ocr_quality_label,
            expected_review_required=request.expected_review_required,
            sensitive_record=request.sensitive_record,
            correct_destination_path=request.correct_destination_path,
            correct_placement_year=request.correct_placement_year,
            correct_privacy=request.correct_privacy,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/admin/review/golden-labels/{label_id}")
def delete_golden_label(label_id: int) -> dict[str, Any]:
    try:
        return review_store().delete_golden_label(label_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/admin/review/golden-labels/{label_id}/file")
def golden_label_file(label_id: int) -> FileResponse:
    try:
        path = review_store().file_path_for_golden_label(label_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name)


@router.get("/admin/review/items")
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
    confidence_bucket: str | None = None,
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
        confidence_bucket=confidence_bucket,
        warning_type=warning_type,
        source_collection=source_collection,
        run_id=run_id,
        run_preset_key=run_preset_key,
        embedding_provider=embedding_provider,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        enable_llm_tags=enable_llm_tags,
    )


@router.get("/admin/review/facets")
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
    confidence_bucket: str | None = None,
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
        confidence_bucket=confidence_bucket,
        warning_type=warning_type,
        source_collection=source_collection,
        run_id=run_id,
        run_preset_key=run_preset_key,
        embedding_provider=embedding_provider,
        llm_tag_provider=llm_tag_provider,
        ocr_fallback_provider=ocr_fallback_provider,
        enable_llm_tags=enable_llm_tags,
    )


@router.get("/admin/review/items/{item_id}")
def review_item_detail(item_id: int) -> dict[str, Any]:
    try:
        return review_store().get_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/admin/review/items/{item_id}/decision")
def record_review_decision(item_id: int, request: ReviewDecisionRequest) -> dict[str, Any]:
    return review_store().record_decision(
        item_id,
        decision=request.decision,
        correct_class=request.correct_class,
        correct_tag=request.correct_tag,
        correct_secondary_tags=request.correct_secondary_tags,
        ocr_quality_label=request.ocr_quality_label,
        expected_review_required=request.expected_review_required,
        sensitive_record=request.sensitive_record,
        correct_destination_path=request.correct_destination_path,
        correct_placement_year=request.correct_placement_year,
        correct_privacy=request.correct_privacy,
        review_stage=request.review_stage,
        notes=request.notes,
        reviewer=request.reviewer,
        save_as_golden=request.save_as_golden,
    )


@router.post("/admin/review/items/{item_id}/assign")
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


@router.get("/admin/review/items/{item_id}/file")
def review_item_file(item_id: int) -> FileResponse:
    try:
        path = review_store().file_path_for_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name)


@router.get("/admin/review/items/{item_id}/text")
def review_item_text(item_id: int) -> PlainTextResponse:
    try:
        item = review_store().get_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return PlainTextResponse(str(item.get("extraction_text_snippet") or ""))


@router.get("/admin/review/items/{item_id}/neighbors")
def review_item_neighbors(item_id: int) -> list[dict[str, Any]]:
    try:
        item = review_store().get_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return list(item.get("result", {}).get("semantic_examples") or [])
