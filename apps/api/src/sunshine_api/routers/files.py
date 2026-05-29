"""File browser, file detail, and single-file run routes."""

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
from sunshine_api.services.imports import (
    add_postgres_file_result_to_review,
    file_path_for_postgres_file_result,
    get_postgres_file_result,
    postgres_file_facets,
    postgres_file_result_inspection,
    postgres_file_result_text,
    search_postgres_files,
)
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


from sunshine_api.services.run_commands import _single_file_command
from sunshine_api.services.run_execution import _execute_run


@router.get("/admin/files")
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
    source: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if source is None and not _postgres_runtime_configured():
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
    if source in (None, "postgres"):
        return search_postgres_files(
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
        )["items"]
    raise HTTPException(status_code=410, detail="SQLite file browsing has been retired; use source=postgres")


@router.get("/admin/files/search")
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
    run_id: str | None = None,
    sort: str = "updated_desc",
    cursor: int | None = None,
    limit: int = 100,
    source: str | None = None,
) -> dict[str, Any]:
    if source is None and not _postgres_runtime_configured():
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
                run_id=_sqlite_file_id(run_id) if run_id else None,
                sort=sort,
                cursor=cursor,
                limit=limit,
            )
    if source in (None, "postgres"):
        try:
            return search_postgres_files(
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
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=410, detail="SQLite file browsing has been retired; use source=postgres")


@router.get("/admin/files/facets")
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
    run_id: str | None = None,
    source: str | None = None,
) -> dict[str, dict[str, int]]:
    if source is None and not _postgres_runtime_configured():
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
                run_id=_sqlite_file_id(run_id) if run_id else None,
            )
    if source in (None, "postgres"):
        try:
            return postgres_file_facets(
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
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=410, detail="SQLite file facets have been retired; use source=postgres")


@router.get("/admin/files/{file_id}")
def file_detail(file_id: str, source: str | None = None) -> dict[str, Any]:
    if source is None and not _postgres_runtime_configured():
            try:
                return review_store().get_file(_sqlite_file_id(file_id))
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
    if source in (None, "postgres"):
        try:
            return get_postgres_file_result(file_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        return review_store().get_file(_sqlite_file_id(file_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/admin/files/{file_id}/inspection")
def file_inspection(file_id: str, source: str | None = None) -> dict[str, Any]:
    if source is None and not _postgres_runtime_configured():
            try:
                return review_store().file_inspection(_sqlite_file_id(file_id))
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
    if source in (None, "postgres"):
        try:
            return postgres_file_result_inspection(file_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        return review_store().file_inspection(_sqlite_file_id(file_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/admin/files/{file_id}/preview")
def file_preview(file_id: str, source: str | None = None) -> FileResponse:
    if source is None and not _postgres_runtime_configured():
            try:
                path = review_store().file_path_for_file(_sqlite_file_id(file_id))
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            except FileNotFoundError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            return FileResponse(path, filename=path.name, content_disposition_type="inline")
    if source in (None, "postgres"):
        return _postgres_file_response(file_id, content_disposition_type="inline")
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        path = review_store().file_path_for_file(_sqlite_file_id(file_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.get("/admin/files/{file_id}/download")
def file_download(file_id: str, source: str | None = None) -> FileResponse:
    if source is None and not _postgres_runtime_configured():
            try:
                path = review_store().file_path_for_file(_sqlite_file_id(file_id))
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            except FileNotFoundError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            return FileResponse(path, filename=path.name, content_disposition_type="attachment")
    if source in (None, "postgres"):
        return _postgres_file_response(file_id, content_disposition_type="attachment")
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        path = review_store().file_path_for_file(_sqlite_file_id(file_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name, content_disposition_type="attachment")


@router.get("/admin/files/{file_id}/text")
def file_text(file_id: str, source: str | None = None) -> dict[str, Any]:
    if source is None and not _postgres_runtime_configured():
            try:
                return review_store().file_text(_sqlite_file_id(file_id))
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
    if source in (None, "postgres"):
        try:
            return postgres_file_result_text(file_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        return review_store().file_text(_sqlite_file_id(file_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/admin/files/{file_id}/review")
def add_file_to_review(file_id: str, request: FileReviewRequest, source: str | None = None) -> dict[str, Any]:
    if source is None and not _postgres_runtime_configured():
            try:
                return review_store().add_file_to_review(_sqlite_file_id(file_id), review_reason=request.review_reason)
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
    if source in (None, "postgres"):
        try:
            return add_postgres_file_result_to_review(file_id, review_reason=request.review_reason)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if source != "sqlite":
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    try:
        return review_store().add_file_to_review(_sqlite_file_id(file_id), review_reason=request.review_reason)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/admin/files/{file_id}/run")
def run_file_from_browser(file_id: str, request: FileRunRequest, source: str | None = None) -> dict[str, Any]:
    store = review_store()
    if source in (None, "postgres"):
        if source is None and not _postgres_runtime_configured():
            try:
                sqlite_file_id = _sqlite_file_id(file_id)
                file_record = store.get_file(sqlite_file_id)
                input_file = store.file_path_for_file(sqlite_file_id)
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            except FileNotFoundError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            default_output_name = f"single_file_{file_id}"
        else:
            try:
                file_record = get_postgres_file_result(file_id)
                input_file = file_path_for_postgres_file_result(file_id)
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            except FileNotFoundError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            default_output_name = f"single_file_postgres_{_safe_path_slug(file_id)}"
    elif source == "sqlite":
        try:
            sqlite_file_id = _sqlite_file_id(file_id)
            file_record = store.get_file(sqlite_file_id)
            input_file = store.file_path_for_file(sqlite_file_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        default_output_name = f"single_file_{file_id}"
    else:
        raise HTTPException(status_code=400, detail="source must be sqlite or postgres")
    output_dir = request.output_dir or str(Path(".local/dashboard-runs") / default_output_name)
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
        run_role="test",
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


def _sqlite_file_id(value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="file id must be an integer for sqlite source") from error


def _postgres_file_response(result_id: str, *, content_disposition_type: str) -> FileResponse:
    try:
        path = file_path_for_postgres_file_result(result_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name, content_disposition_type=content_disposition_type)


def _safe_path_slug(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")[:80] or "file"


def _postgres_runtime_configured() -> bool:
    return bool(os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL"))
