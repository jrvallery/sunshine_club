"""Import service boundaries for V2 pipeline artifacts."""

from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from sunshine_api.postgres_pipeline_store import ConnectFactory, PostgresPipelineStore


def import_langgraph_output_to_postgres(
    output_dir: str | Path,
    *,
    run_key: str,
    preset_key: str | None = None,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.import_langgraph_output(output_dir, run_key=run_key, preset_key=preset_key)


def import_langgraph_output_to_postgres_if_configured(
    output_dir: str | Path,
    *,
    run_key: str,
    preset_key: str | None = None,
) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    if not database_url:
        return {
            "import_status": "skipped",
            "importer": "postgres_runtime",
            "output_dir": str(output_dir),
            "run_key": run_key,
            "preset_key": preset_key,
            "reason": "postgres_database_url_not_configured",
        }
    return {
        "import_status": "imported",
        "importer": "postgres_runtime",
        "result": import_langgraph_output_to_postgres(output_dir, run_key=run_key, preset_key=preset_key, database_url=database_url),
    }


def delete_postgres_pipeline_run_if_configured(*, run_key: str) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    if not database_url:
        return {
            "delete_status": "skipped",
            "store": "postgres_runtime",
            "run_key": run_key,
            "reason": "postgres_database_url_not_configured",
        }
    store = PostgresPipelineStore(database_url)
    try:
        return {"delete_status": "deleted", "store": "postgres_runtime", "result": store.delete_pipeline_run(run_key=run_key)}
    except KeyError as error:
        return {
            "delete_status": "not_found",
            "store": "postgres_runtime",
            "run_key": run_key,
            "reason": str(error),
        }


def record_postgres_pipeline_run_state_if_configured(
    *,
    run: dict[str, Any],
    status: str | None = None,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    run_key = str(run.get("run_key") or "")
    if not database_url:
        return {
            "record_status": "skipped",
            "store": "postgres_runtime",
            "run_key": run_key,
            "reason": "postgres_database_url_not_configured",
        }
    store = PostgresPipelineStore(database_url)
    return {
        "record_status": "recorded",
        "store": "postgres_runtime",
        "result": store.record_pipeline_run_state(
            run_key=run_key,
            status=status or str(run.get("status") or "queued"),
            preset_key=run.get("preset_key"),
            input_root=run.get("input_root"),
            output_dir=run.get("output_dir"),
            summary=summary or run.get("summary") or {},
            error=error or run.get("error"),
            embedding_provider=run.get("embedding_provider"),
            llm_provider=run.get("llm_tag_provider") if run.get("llm_tag_provider") != "disabled" else None,
            vector_store_provider="qdrant",
        ),
    }


def import_provider_benchmark_output_to_postgres(
    output_dir: str | Path,
    *,
    benchmark_key: str | None = None,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.import_provider_benchmark_output(output_dir, benchmark_key=benchmark_key)


def import_provider_benchmark_output_to_postgres_if_configured(
    output_dir: str | Path,
    *,
    benchmark_key: str | None = None,
) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    if not database_url:
        return {
            "import_status": "skipped",
            "importer": "postgres_provider_benchmarks",
            "output_dir": str(output_dir),
            "benchmark_key": benchmark_key,
            "reason": "postgres_database_url_not_configured",
        }
    return {
        "import_status": "imported",
        "importer": "postgres_provider_benchmarks",
        "result": import_provider_benchmark_output_to_postgres(
            output_dir,
            benchmark_key=benchmark_key,
            database_url=database_url,
        ),
    }


def list_postgres_provider_benchmark_runs(
    *,
    limit: int = 50,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_provider_benchmark_runs(limit=limit)


def get_postgres_provider_benchmark_run(
    *,
    benchmark_key: str,
    result_limit: int = 500,
    parser_result_limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.get_provider_benchmark_run(
        benchmark_key=benchmark_key,
        result_limit=result_limit,
        parser_result_limit=parser_result_limit,
    )


def get_postgres_provider_benchmark_promotion_plan(
    *,
    benchmark_key: str,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.provider_benchmark_promotion_plan(benchmark_key=benchmark_key)


def postgres_runtime_summary(
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.runtime_summary()


def postgres_review_summary(
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.review_summary()


def list_postgres_pipeline_runs(
    *,
    limit: int = 100,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_pipeline_runs(limit=limit)


def get_postgres_pipeline_run(
    *,
    run_key: str,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.get_pipeline_run(run_key=run_key)


def get_postgres_run_report(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.get_run_report(run_key=run_key, limit=limit)


def list_postgres_run_artifacts(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_artifacts(run_key=run_key, limit=limit)


def list_postgres_run_results(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_results(run_key=run_key, limit=limit)


def list_postgres_run_model_usage(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_model_usage(run_key=run_key, limit=limit)


def list_postgres_run_provider_attempts(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_provider_attempts(run_key=run_key, limit=limit)


def list_postgres_run_provider_selections(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_provider_selections(run_key=run_key, limit=limit)


def list_postgres_run_quality_checks(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_quality_checks(run_key=run_key, limit=limit)


def list_postgres_run_tagging_evidence(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_tagging_evidence(run_key=run_key, limit=limit)


def list_postgres_run_file_metadata(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_file_metadata(run_key=run_key, limit=limit)


def list_postgres_run_processing_artifacts(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_processing_artifacts(run_key=run_key, limit=limit)


def list_postgres_run_parser_results(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_parser_results(run_key=run_key, limit=limit)


def list_postgres_run_document_segments(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_document_segments(run_key=run_key, limit=limit)


def list_postgres_run_chunks(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_chunks(run_key=run_key, limit=limit)


def list_postgres_run_chunk_embeddings(
    *,
    run_key: str,
    limit: int = 500,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_chunk_embeddings(run_key=run_key, limit=limit)


def list_postgres_run_events(
    *,
    run_key: str,
    limit: int = 200,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_run_events(run_key=run_key, limit=limit)


def list_postgres_review_items(
    *,
    run_key: str | None = None,
    limit: int = 100,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_review_items(run_key=run_key, limit=limit)


def search_postgres_files(
    *,
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
    run_id: str | int | None = None,
    sort: str = "updated_desc",
    cursor: int | None = None,
    limit: int = 100,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.search_files(
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


def postgres_file_facets(
    *,
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
    run_id: str | int | None = None,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, dict[str, int]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.file_facets(
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


def get_postgres_file_result(
    result_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.get_file_result(result_id)


def postgres_file_result_text(
    result_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.file_text_for_file_result(result_id)


def postgres_file_result_inspection(
    result_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.file_inspection_for_file_result(result_id)


def file_path_for_postgres_file_result(
    result_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> Path:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.file_path_for_file_result(result_id)


def add_postgres_file_result_to_review(
    result_id: str,
    *,
    review_reason: str = "manual_file_review",
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.add_file_result_to_review(result_id, review_reason=review_reason)


def list_postgres_golden_labels(
    *,
    limit: int = 100,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_golden_labels(limit=limit)


def postgres_golden_label_summary(
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.golden_label_summary()


def export_postgres_golden_labels_sqlite(
    output_db: str | Path,
    *,
    limit: int | None = None,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.export_golden_labels_sqlite(output_db, limit=limit)


def get_postgres_golden_label(
    label_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.get_golden_label(label_id)


def update_postgres_golden_label(
    label_id: str,
    *,
    content_class: str | None = None,
    correct_primary_tag: str | None = None,
    correct_secondary_tags: list[str] | None = None,
    ocr_quality_label: str | None = None,
    expected_review_required: bool | None = None,
    sensitive_record: bool | None = None,
    correct_destination_path: str | None = None,
    correct_placement_year: str | None = None,
    correct_privacy: str | None = None,
    reviewer: str | None = None,
    notes: str | None = None,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.update_golden_label(
        label_id,
        content_class=content_class,
        correct_primary_tag=correct_primary_tag,
        correct_secondary_tags=correct_secondary_tags,
        ocr_quality_label=ocr_quality_label,
        expected_review_required=expected_review_required,
        sensitive_record=sensitive_record,
        correct_destination_path=correct_destination_path,
        correct_placement_year=correct_placement_year,
        correct_privacy=correct_privacy,
        reviewer=reviewer,
        notes=notes,
    )


def delete_postgres_golden_label(
    label_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.delete_golden_label(label_id)


def file_path_for_postgres_golden_label(
    label_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> Path:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.file_path_for_golden_label(label_id)


def get_postgres_review_item(
    item_id: str,
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.get_review_item(item_id)


def record_postgres_review_decision(
    item_id: str,
    *,
    decision: str,
    correct_class: str | None = None,
    correct_tag: str | None = None,
    correct_secondary_tags: list[str] | None = None,
    ocr_quality_label: str | None = None,
    expected_review_required: bool | None = None,
    sensitive_record: bool | None = None,
    correct_destination_path: str | None = None,
    correct_placement_year: str | None = None,
    correct_privacy: str | None = None,
    reviewer: str | None = None,
    notes: str | None = None,
    save_as_golden: bool = True,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.record_review_decision(
        item_id,
        decision=decision,
        correct_class=correct_class,
        correct_tag=correct_tag,
        correct_secondary_tags=correct_secondary_tags,
        ocr_quality_label=ocr_quality_label,
        expected_review_required=expected_review_required,
        sensitive_record=sensitive_record,
        correct_destination_path=correct_destination_path,
        correct_placement_year=correct_placement_year,
        correct_privacy=correct_privacy,
        reviewer=reviewer,
        notes=notes,
        save_as_golden=save_as_golden,
    )


def record_postgres_segment_review_decision(
    *,
    run_key: str,
    segment_id: str,
    decision: str,
    notes: str | None = None,
    reviewer: str | None = None,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.record_segment_review_decision(
        run_key=run_key,
        segment_id=segment_id,
        decision=decision,
        notes=notes,
        reviewer=reviewer,
    )


__all__ = [
    "add_postgres_file_result_to_review",
    "import_langgraph_output_to_postgres",
    "import_langgraph_output_to_postgres_if_configured",
    "import_provider_benchmark_output_to_postgres",
    "import_provider_benchmark_output_to_postgres_if_configured",
    "delete_postgres_pipeline_run_if_configured",
    "delete_postgres_golden_label",
    "export_postgres_golden_labels_sqlite",
    "file_path_for_postgres_file_result",
    "file_path_for_postgres_golden_label",
    "get_postgres_file_result",
    "get_postgres_golden_label",
    "get_postgres_pipeline_run",
    "get_postgres_provider_benchmark_run",
    "get_postgres_provider_benchmark_promotion_plan",
    "get_postgres_review_item",
    "get_postgres_run_report",
    "list_postgres_golden_labels",
    "list_postgres_pipeline_runs",
    "list_postgres_provider_benchmark_runs",
    "list_postgres_review_items",
    "list_postgres_run_chunk_embeddings",
    "list_postgres_run_chunks",
    "list_postgres_run_document_segments",
    "list_postgres_run_events",
    "list_postgres_run_file_metadata",
    "list_postgres_run_parser_results",
    "list_postgres_run_processing_artifacts",
    "list_postgres_run_provider_attempts",
    "list_postgres_run_provider_selections",
    "list_postgres_run_quality_checks",
    "list_postgres_run_results",
    "list_postgres_run_tagging_evidence",
    "postgres_golden_label_summary",
    "postgres_file_facets",
    "postgres_file_result_inspection",
    "postgres_file_result_text",
    "postgres_runtime_summary",
    "postgres_review_summary",
    "record_postgres_pipeline_run_state_if_configured",
    "record_postgres_review_decision",
    "record_postgres_segment_review_decision",
    "search_postgres_files",
    "update_postgres_golden_label",
]
