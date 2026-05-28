"""Optional import hooks for persisted graph artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol


class RunResultsImporter(Protocol):
    def import_output(self, output_dir: str | Path, *, run_id: int | None = None) -> dict[str, Any]:
        """Import persisted graph artifacts into an operational store."""


class NoopRunResultsImporter:
    def import_output(self, output_dir: str | Path, *, run_id: int | None = None) -> dict[str, Any]:
        return {
            "import_status": "skipped",
            "importer": "noop",
            "output_dir": str(output_dir),
            "run_id": run_id,
            "reason": "run_results_importer_not_configured",
        }


class SQLiteReviewStoreRunResultsImporter:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path) if db_path is not None else None

    def import_output(self, output_dir: str | Path, *, run_id: int | None = None) -> dict[str, Any]:
        from sunshine_api.review_store import ReviewStore

        store = ReviewStore(self.db_path)
        result = store.import_langgraph_output(output_dir, sample_routed_per_bucket=0, run_id=run_id)
        return {
            "import_status": "imported",
            "importer": "sqlite_review_store",
            "output_dir": str(output_dir),
            "run_id": run_id,
            "result": result,
        }


def run_results_importer_from_env() -> RunResultsImporter:
    mode = os.environ.get("SUNSHINE_GRAPH_IMPORT_RESULTS", "disabled").strip().lower()
    if mode in {"sqlite", "review_store", "review-store"}:
        return SQLiteReviewStoreRunResultsImporter(os.environ.get("SUNSHINE_REVIEW_DB_PATH"))
    return NoopRunResultsImporter()
