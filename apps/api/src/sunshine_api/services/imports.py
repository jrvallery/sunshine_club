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


def postgres_runtime_summary(
    *,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> dict[str, Any]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.runtime_summary()


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


def list_postgres_review_items(
    *,
    run_key: str | None = None,
    limit: int = 100,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_review_items(run_key=run_key, limit=limit)


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
    notes: str | None = None,
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
        notes=notes,
    )


__all__ = [
    "import_langgraph_output_to_postgres",
    "import_langgraph_output_to_postgres_if_configured",
    "delete_postgres_pipeline_run_if_configured",
    "get_postgres_pipeline_run",
    "get_postgres_review_item",
    "get_postgres_run_report",
    "list_postgres_pipeline_runs",
    "list_postgres_review_items",
    "postgres_runtime_summary",
    "record_postgres_review_decision",
]
