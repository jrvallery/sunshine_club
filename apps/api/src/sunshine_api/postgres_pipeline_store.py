"""Postgres persistence path for V2 pipeline runtime artifacts.

The current dashboard store remains SQLite-backed while the V2 runtime schema is
introduced. This module imports normalized LangGraph artifacts into the
Postgres tables defined under ``infra/db/migrations`` so the production store
can be built without coupling it to the legacy SQLite review methods.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Protocol


class PostgresConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        ...

    def commit(self) -> None:
        ...

    def close(self) -> None:
        ...


ConnectFactory = Callable[[str], PostgresConnection]


class PostgresPipelineStore:
    def __init__(self, database_url: str | None = None, *, connect_factory: ConnectFactory | None = None) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL or SUNSHINE_DATABASE_URL is required for PostgresPipelineStore")
        self._connect_factory = connect_factory or _connect_with_psycopg

    def import_langgraph_output(self, output_dir: str | Path, *, run_key: str, preset_key: str | None = None) -> dict[str, Any]:
        output_path = Path(output_dir)
        if not (output_path / "sample-pipeline-results.jsonl").exists():
            raise FileNotFoundError(f"Missing {output_path / 'sample-pipeline-results.jsonl'}")

        connection = self._connect_factory(self.database_url)
        try:
            run_id = self._upsert_run(connection, run_key=run_key, preset_key=preset_key, output_dir=output_path)
            counts = {
                "pipeline_results": self._import_results(connection, run_id, output_path),
                "model_usage": self._import_model_usage(connection, run_id, output_path),
                "provider_attempts": self._import_provider_attempts(connection, run_id, output_path),
                "document_segments": self._import_document_segments(connection, run_id, output_path),
            }
            connection.commit()
        finally:
            connection.close()
        return {"run_id": run_id, "run_key": run_key, "output_dir": str(output_path), "imported": counts}

    def _upsert_run(self, connection: PostgresConnection, *, run_key: str, preset_key: str | None, output_dir: Path) -> str:
        row = connection.execute(
            """
            insert into pipeline_runs (run_key, preset_key, output_dir, status, local_only, summary)
            values (%s, %s, %s, 'succeeded', true, '{}'::jsonb)
            on conflict (run_key) do update set
                preset_key = excluded.preset_key,
                output_dir = excluded.output_dir,
                status = excluded.status,
                updated_at = now()
            returning id
            """,
            (run_key, preset_key, str(output_dir)),
        ).fetchone()
        return str(row[0] if isinstance(row, tuple) else row["id"])

    def _import_results(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-pipeline-results.jsonl")
        connection.execute("delete from pipeline_results where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into pipeline_results (
                    run_id, source_path, relative_path, sample_path, route_status, review_reason,
                    final_class, extraction_strategy, extraction_status, quality, top_tag_candidate,
                    secondary_tags, tag_confidence, result
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path") or row.get("sample_path"),
                    row.get("relative_path"),
                    row.get("sample_path"),
                    row.get("route_status") or "unknown",
                    row.get("review_reason"),
                    row.get("final_class"),
                    row.get("extraction_strategy"),
                    row.get("extraction_status"),
                    row.get("quality"),
                    row.get("top_tag_candidate"),
                    json.dumps(row.get("secondary_tags") or []),
                    row.get("tag_confidence"),
                    json.dumps(row, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_model_usage(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-model-usage.jsonl")
        connection.execute("delete from model_usage where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into model_usage (
                    run_id, source_path, relative_path, node, purpose, provider, model, status,
                    call_count, input_tokens, output_tokens, total_tokens, runtime_ms, local_only, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("node") or "unknown",
                    row.get("purpose") or "unknown",
                    row.get("provider") or "unknown",
                    row.get("model") or "unknown",
                    row.get("status") or "unknown",
                    _call_count(row),
                    row.get("input_tokens"),
                    row.get("output_tokens"),
                    row.get("total_tokens"),
                    row.get("runtime_ms"),
                    json.dumps(row.get("metadata") or {}, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_provider_attempts(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-provider-attempts.jsonl")
        connection.execute("delete from provider_attempts where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into provider_attempts (
                    run_id, source_path, relative_path, provider, capability, status, strategy,
                    runtime_ms, warnings, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("provider") or "unknown",
                    row.get("capability") or "extraction",
                    row.get("status") or "unknown",
                    row.get("strategy"),
                    _seconds_to_runtime_ms(row.get("seconds")),
                    json.dumps(row.get("warnings") or []),
                    json.dumps(row.get("metadata") or {}, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_document_segments(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-document-segments.jsonl")
        connection.execute("delete from document_segments where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into document_segments (
                    run_id, source_path, relative_path, segment_id, parent_file_id, page_start, page_end,
                    segment_index, segment_type, segment_title, segment_confidence, requires_segment_review,
                    boundary_evidence, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("segment_id") or "",
                    row.get("parent_file_id"),
                    row.get("page_start"),
                    row.get("page_end"),
                    row.get("segment_index") or 0,
                    row.get("segment_type") or "unknown",
                    row.get("segment_title"),
                    row.get("segment_confidence") or 0,
                    bool(row.get("requires_segment_review")),
                    json.dumps(row.get("segment_boundary_evidence") or row.get("boundary_evidence") or []),
                    json.dumps(row.get("metadata") or {}, sort_keys=True),
                ),
            )
        return len(rows)


def _connect_with_psycopg(database_url: str) -> PostgresConnection:
    import psycopg

    return psycopg.connect(database_url)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _call_count(row: dict[str, Any]) -> int:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    try:
        return max(0, int(metadata.get("call_count", 1)))
    except (TypeError, ValueError):
        return 1


def _seconds_to_runtime_ms(value: Any) -> int | None:
    if not isinstance(value, int | float):
        return None
    return int(round(float(value) * 1000))
