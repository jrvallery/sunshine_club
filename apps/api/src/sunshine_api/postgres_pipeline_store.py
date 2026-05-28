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
                "pipeline_chunks": self._import_chunks(connection, run_id, output_path),
                "pipeline_chunk_embeddings": self._import_chunk_embeddings(connection, run_id, output_path),
                "model_usage": self._import_model_usage(connection, run_id, output_path),
                "provider_attempts": self._import_provider_attempts(connection, run_id, output_path),
                "document_segments": self._import_document_segments(connection, run_id, output_path),
            }
            connection.commit()
        finally:
            connection.close()
        return {"run_id": run_id, "run_key": run_key, "output_dir": str(output_path), "imported": counts}

    def runtime_summary(self) -> dict[str, Any]:
        """Return V2 runtime counts from Postgres for dashboard readiness checks."""

        connection = self._connect_factory(self.database_url)
        try:
            return {
                "pipeline_runs": _scalar_count(connection, "select count(*) from pipeline_runs"),
                "pipeline_results": _scalar_count(connection, "select count(*) from pipeline_results"),
                "review_items": _scalar_count(connection, "select count(*) from review_items_v2"),
                "model_usage": _scalar_count(connection, "select count(*) from model_usage"),
                "provider_attempts": _scalar_count(connection, "select count(*) from provider_attempts"),
                "document_segments": _scalar_count(connection, "select count(*) from document_segments"),
                "pipeline_chunks": _scalar_count(connection, "select count(*) from pipeline_chunks"),
                "pipeline_chunk_embeddings": _scalar_count(connection, "select count(*) from pipeline_chunk_embeddings"),
                "recent_runs": self._list_pipeline_runs(connection, limit=5),
            }
        finally:
            connection.close()

    def list_pipeline_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            return self._list_pipeline_runs(connection, limit=limit)
        finally:
            connection.close()

    def _list_pipeline_runs(self, connection: PostgresConnection, *, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                r.id,
                r.run_key,
                r.preset_key,
                r.output_dir,
                r.status,
                r.local_only,
                r.embedding_provider,
                r.llm_provider,
                r.extraction_provider,
                r.vector_store_provider,
                r.vector_store_collection,
                r.started_at,
                r.finished_at,
                r.created_at,
                r.updated_at,
                r.summary,
                (select count(*) from pipeline_results pr where pr.run_id = r.id) as result_count,
                (select count(*) from pipeline_results pr where pr.run_id = r.id and pr.route_status <> 'route_candidate') as review_required_count,
                (select count(*) from model_usage mu where mu.run_id = r.id) as model_usage_count,
                (select count(*) from provider_attempts pa where pa.run_id = r.id) as provider_attempt_count,
                (select count(*) from document_segments ds where ds.run_id = r.id) as document_segment_count
            from pipeline_runs r
            order by r.created_at desc
            limit %s
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

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

    def _import_chunks(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-chunks.jsonl")
        connection.execute("delete from pipeline_chunks where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into pipeline_chunks (
                    run_id, source_path, relative_path, sample_path, chunk_id, chunk_index,
                    chunk_kind, content, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("sample_path"),
                    row.get("chunk_id") or "",
                    row.get("chunk_index") or 0,
                    row.get("chunk_kind") or "text",
                    row.get("text") or "",
                    json.dumps(row.get("metadata") or {}, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_chunk_embeddings(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-embeddings.jsonl")
        connection.execute("delete from pipeline_chunk_embeddings where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into pipeline_chunk_embeddings (
                    run_id, chunk_id, source_path, relative_path, embedding_provider, embedding_model,
                    embedding_dimensions, embedding_status, semantic_quality, embedding, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("chunk_id") or "",
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("embedding_provider") or "unknown",
                    row.get("embedding_model") or "unknown",
                    row.get("embedding_dimensions"),
                    row.get("embedding_status") or "unknown",
                    bool(row.get("semantic_quality")),
                    _vector_literal(row.get("embedding")),
                    json.dumps(row.get("metadata") or {}, sort_keys=True),
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
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _scalar_count(connection: PostgresConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(next(iter(row.values())) or 0)
    if isinstance(row, tuple):
        return int(row[0] or 0)
    if hasattr(row, "keys"):
        values = [row[key] for key in row.keys()]
        return int(values[0] or 0) if values else 0
    return int(row or 0)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"Unsupported Postgres row type: {type(row).__name__}")


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            safe[key] = value.isoformat()
        else:
            safe[key] = value
    return safe


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


def _vector_literal(value: Any) -> str | None:
    if not isinstance(value, list) or not all(isinstance(item, int | float) for item in value):
        return None
    return "[" + ",".join(str(float(item)) for item in value) + "]"
