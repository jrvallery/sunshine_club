"""Import service boundaries for V2 pipeline artifacts."""

from __future__ import annotations

from pathlib import Path
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


def list_postgres_review_items(
    *,
    run_key: str | None = None,
    limit: int = 100,
    database_url: str | None = None,
    connect_factory: ConnectFactory | None = None,
) -> list[dict[str, Any]]:
    store = PostgresPipelineStore(database_url, connect_factory=connect_factory)
    return store.list_review_items(run_key=run_key, limit=limit)


__all__ = [
    "import_langgraph_output_to_postgres",
    "list_postgres_pipeline_runs",
    "list_postgres_review_items",
    "postgres_runtime_summary",
]
