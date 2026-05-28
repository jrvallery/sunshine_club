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
from sunshine_api.services.imports import get_postgres_review_item, list_postgres_review_items, record_postgres_review_decision
from sunshine_api.schemas import (
    DocumentPipelineRunRequest,
    DocumentPipelineRunResponse,
    FileReviewRequest,
    FileRunRequest,
    GoldenLabelUpdateRequest,
    ReviewAssignRequest,
    ReviewDecisionRequest,
    ReviewImportRequest,
    ReviewOcrQualityRequest,
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
        "reviewed_at",
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
                "reviewed_at": row.get("reviewed_at"),
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
    source: str = "sqlite",
    run_key: str | None = None,
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
    ocr_fallback_used: str | None = None,
    enable_llm_tags: bool | None = None,
) -> list[dict[str, Any]]:
    if source == "postgres":
        try:
            rows = list_postgres_review_items(run_key=run_key, limit=limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _postgres_review_rows(
            rows,
            status=status,
            q=q,
            route_status=route_status,
            review_reason=review_reason,
            primary_tag=primary_tag,
            secondary_tag=secondary_tag,
            content_class=content_class,
            run_preset_key=run_preset_key,
        )[: max(1, min(limit, 500))]
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
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
        ocr_fallback_used=ocr_fallback_used,
        enable_llm_tags=enable_llm_tags,
    )


@router.get("/admin/review/facets")
def review_facets(
    status: str = "open",
    source: str = "sqlite",
    run_key: str | None = None,
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
    ocr_fallback_used: str | None = None,
    enable_llm_tags: bool | None = None,
) -> dict[str, dict[str, int]]:
    if source == "postgres":
        try:
            rows = list_postgres_review_items(run_key=run_key, limit=500)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        filtered = _postgres_review_rows(
            rows,
            status=status,
            q=q,
            route_status=route_status,
            review_reason=review_reason,
            primary_tag=primary_tag,
            secondary_tag=secondary_tag,
            content_class=content_class,
            run_preset_key=run_preset_key,
        )
        return _postgres_review_facets(filtered)
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
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
        ocr_fallback_used=ocr_fallback_used,
        enable_llm_tags=enable_llm_tags,
    )


@router.get("/admin/review/items/{item_id}")
def review_item_detail(item_id: str, source: str = "sqlite") -> dict[str, Any]:
    if source == "postgres":
        try:
            return _postgres_review_row(get_postgres_review_item(item_id))
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        sqlite_item_id = int(item_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="sqlite review item id must be an integer") from error
    try:
        return review_store().get_review_item(sqlite_item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/admin/review/items/{item_id}/decision")
def record_review_decision(item_id: str, request: ReviewDecisionRequest, source: str = "sqlite") -> dict[str, Any]:
    if source == "postgres":
        try:
            row = record_postgres_review_decision(
                item_id,
                decision=request.decision,
                correct_class=request.correct_class,
                correct_tag=request.correct_tag,
                correct_secondary_tags=request.correct_secondary_tags,
                notes=request.notes,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _postgres_review_row(row)
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        sqlite_item_id = int(item_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="sqlite review item id must be an integer") from error
    return review_store().record_decision(
        sqlite_item_id,
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


@router.post("/admin/review/items/{item_id}/ocr-quality")
def mark_review_ocr_quality(item_id: int, request: ReviewOcrQualityRequest) -> dict[str, Any]:
    try:
        return review_store().mark_ocr_quality(
            item_id,
            ocr_quality_label=request.ocr_quality_label,
            review_stage=request.review_stage,
            notes=request.notes,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


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
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.get("/admin/review/items/{item_id}/download")
def review_item_download(item_id: int) -> FileResponse:
    try:
        path = review_store().file_path_for_review_item(item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name, content_disposition_type="attachment")


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


def _postgres_review_rows(
    rows: list[dict[str, Any]],
    *,
    status: str,
    q: str | None,
    route_status: str | None,
    review_reason: str | None,
    primary_tag: str | None,
    secondary_tag: str | None,
    content_class: str | None,
    run_preset_key: str | None,
) -> list[dict[str, Any]]:
    mapped = [_postgres_review_row(row) for row in rows]
    return [
        row
        for row in mapped
        if _matches_status(row, status)
        and _matches_text(row, q)
        and _matches_equal(row.get("route_status"), route_status)
        and _matches_equal(row.get("review_reason"), review_reason)
        and _matches_equal(row.get("proposed_tag"), primary_tag)
        and _matches_equal(row.get("proposed_class"), content_class)
        and _matches_equal(row.get("run_preset_key"), run_preset_key)
        and (not secondary_tag or secondary_tag in (row.get("secondary_tags") or []))
    ]


def _postgres_review_row(row: dict[str, Any]) -> dict[str, Any]:
    secondary_tags = row.get("proposed_secondary_tags") if isinstance(row.get("proposed_secondary_tags"), list) else []
    corrected_secondary = row.get("corrected_secondary_tags") if isinstance(row.get("corrected_secondary_tags"), list) else []
    return {
        "id": row.get("id"),
        "source": "postgres",
        "source_path": row.get("source_path"),
        "relative_path": row.get("relative_path"),
        "route_status": "review_required",
        "review_reason": row.get("review_reason"),
        "status": row.get("status") or "open",
        "proposed_class": row.get("proposed_class"),
        "proposed_tag": row.get("proposed_tag"),
        "secondary_tags": secondary_tags,
        "extraction_text_snippet": None,
        "confidence": None,
        "warnings": [],
        "display_warnings": [],
        "run_id": row.get("run_id"),
        "run_key": row.get("run_key"),
        "run_preset_key": row.get("preset_key"),
        "decision": row.get("status"),
        "correct_class": row.get("corrected_class"),
        "correct_tag": row.get("corrected_tag"),
        "correct_secondary_tags": corrected_secondary,
        "notes": row.get("notes"),
        "segment_id": row.get("segment_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "result": {
            "source_path": row.get("source_path"),
            "relative_path": row.get("relative_path"),
            "final_class": row.get("proposed_class"),
            "top_tag_candidate": row.get("proposed_tag"),
            "secondary_tags": secondary_tags,
            "route_status": "review_required",
            "review_reason": row.get("review_reason"),
            "placement_status": "needs_review",
            "quality": None,
            "warnings": [],
        },
    }


def _postgres_review_facets(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    return {
        "review_status": _facet_count(rows, "status"),
        "run": _facet_count(rows, "run_key"),
        "preset": _facet_count(rows, "run_preset_key"),
        "review_reason": _facet_count(rows, "review_reason"),
        "primary_tag": _facet_count(rows, "proposed_tag"),
        "content_class": _facet_count(rows, "proposed_class"),
    }


def _facet_count(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _matches_status(row: dict[str, Any], status: str) -> bool:
    return status == "all" or row.get("status") == status


def _matches_text(row: dict[str, Any], q: str | None) -> bool:
    if not q:
        return True
    needle = q.lower()
    values = [row.get("relative_path"), row.get("source_path"), row.get("review_reason"), row.get("notes")]
    return any(needle in str(value or "").lower() for value in values)


def _matches_equal(actual: Any, expected: str | None) -> bool:
    return not expected or str(actual or "") == expected
