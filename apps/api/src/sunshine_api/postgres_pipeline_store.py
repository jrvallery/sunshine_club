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
            run_summary = _run_summary_from_artifacts(output_path)
            run_id = self._upsert_run(connection, run_key=run_key, preset_key=preset_key, output_dir=output_path, summary=run_summary)
            counts = {
                "pipeline_results": self._import_results(connection, run_id, output_path),
                "pipeline_chunks": self._import_chunks(connection, run_id, output_path),
                "pipeline_chunk_embeddings": self._import_chunk_embeddings(connection, run_id, output_path),
                "model_usage": self._import_model_usage(connection, run_id, output_path),
                "provider_attempts": self._import_provider_attempts(connection, run_id, output_path),
                "document_segments": self._import_document_segments(connection, run_id, output_path),
                "review_items": self._import_review_items(connection, run_id, output_path),
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

    def get_pipeline_run(self, *, run_key: str) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            rows = self._list_pipeline_runs(connection, limit=500)
            for row in rows:
                if row.get("run_key") == run_key:
                    return row
        finally:
            connection.close()
        raise KeyError(f"Postgres pipeline run not found: {run_key}")

    def get_run_report(self, *, run_key: str, limit: int = 500) -> dict[str, Any]:
        """Return normalized run-report rows from Postgres.

        This is the V2 read model the dashboard can use instead of stitching
        together JSONL artifacts or legacy SQLite rows. It intentionally
        includes document segments so scrapbook/newspaper packet page ranges can
        be reviewed without mutating the source PDF.
        """

        connection = self._connect_factory(self.database_url)
        try:
            rows = self._list_pipeline_runs(connection, limit=500)
            run = next((row for row in rows if row.get("run_key") == run_key), None)
            if run is None:
                raise KeyError(f"Postgres pipeline run not found: {run_key}")
            capped_limit = max(1, min(int(limit), 1000))
            return {
                "run": run,
                "results": self._list_pipeline_results(connection, run_key=run_key, limit=capped_limit),
                "review_items": self._list_review_items(connection, run_key=run_key, limit=capped_limit),
                "model_usage": self._list_model_usage(connection, run_key=run_key, limit=capped_limit),
                "provider_attempts": self._list_provider_attempts(connection, run_key=run_key, limit=capped_limit),
                "document_segments": self._list_document_segments(connection, run_key=run_key, limit=capped_limit),
            }
        finally:
            connection.close()

    def list_review_items(self, *, run_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            return self._list_review_items(connection, run_key=run_key, limit=limit)
        finally:
            connection.close()

    def record_review_decision(
        self,
        item_id: str,
        *,
        decision: str,
        correct_class: str | None = None,
        correct_tag: str | None = None,
        correct_secondary_tags: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        status = _review_status_from_decision(decision)
        connection = self._connect_factory(self.database_url)
        try:
            existing = connection.execute(
                """
                select id, proposed_class, proposed_tag, proposed_secondary_tags, notes
                from review_items_v2
                where id = %s
                """,
                (item_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Postgres review item not found: {item_id}")
            existing_row = _row_to_dict(existing)
            resolved_class = correct_class if correct_class is not None else (existing_row.get("proposed_class") if decision == "accept" else None)
            resolved_tag = correct_tag if correct_tag is not None else (existing_row.get("proposed_tag") if decision == "accept" else None)
            resolved_secondary = (
                correct_secondary_tags
                if correct_secondary_tags is not None
                else (existing_row.get("proposed_secondary_tags") if decision == "accept" else [])
            )
            connection.execute(
                """
                update review_items_v2
                set status = %s,
                    corrected_class = %s,
                    corrected_tag = %s,
                    corrected_secondary_tags = %s::jsonb,
                    notes = %s,
                    updated_at = now()
                where id = %s
                """,
                (
                    status,
                    resolved_class,
                    resolved_tag,
                    json.dumps(resolved_secondary or []),
                    _append_note(existing_row.get("notes"), notes),
                    item_id,
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                select
                    ri.id,
                    ri.run_id,
                    r.run_key,
                    r.preset_key,
                    ri.source_path,
                    ri.relative_path,
                    ri.segment_id,
                    ri.status,
                    ri.review_reason,
                    ri.proposed_class,
                    ri.proposed_tag,
                    ri.proposed_secondary_tags,
                    ri.corrected_class,
                    ri.corrected_tag,
                    ri.corrected_secondary_tags,
                    ri.notes,
                    ri.created_at,
                    ri.updated_at
                from review_items_v2 ri
                left join pipeline_runs r on r.id = ri.run_id
                where ri.id = %s
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Postgres review item not found after update: {item_id}")
            return _json_safe_row(_row_to_dict(row))
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

    def _list_pipeline_results(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pr.id,
                pr.run_id,
                r.run_key,
                pr.source_path,
                pr.relative_path,
                pr.sample_path,
                pr.route_status,
                pr.review_reason,
                pr.final_class,
                pr.extraction_strategy,
                pr.extraction_status,
                pr.quality,
                pr.top_tag_candidate,
                pr.secondary_tags,
                pr.tag_confidence,
                pr.result,
                pr.created_at,
                pr.updated_at
            from pipeline_results pr
            join pipeline_runs r on r.id = pr.run_id
            where r.run_key = %s
            order by pr.created_at asc, pr.relative_path asc nulls last, pr.source_path asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_review_items(self, connection: PostgresConnection, *, run_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: tuple[Any, ...]
        where_sql = ""
        if run_key:
            where_sql = "where r.run_key = %s"
            params = (run_key, max(1, min(int(limit), 1000)))
        else:
            params = (max(1, min(int(limit), 500)),)
        rows = connection.execute(
            f"""
            select
                ri.id,
                ri.run_id,
                r.run_key,
                r.preset_key,
                ri.source_path,
                ri.relative_path,
                ri.segment_id,
                ri.status,
                ri.review_reason,
                ri.proposed_class,
                ri.proposed_tag,
                ri.proposed_secondary_tags,
                ri.corrected_class,
                ri.corrected_tag,
                ri.corrected_secondary_tags,
                ri.notes,
                ri.created_at,
                ri.updated_at
            from review_items_v2 ri
            left join pipeline_runs r on r.id = ri.run_id
            {where_sql}
            order by ri.created_at desc
            limit %s
            """,
            params,
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_model_usage(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                mu.id,
                mu.run_id,
                r.run_key,
                mu.source_path,
                mu.relative_path,
                mu.node,
                mu.purpose,
                mu.provider,
                mu.model,
                mu.status,
                mu.call_count,
                mu.input_tokens,
                mu.output_tokens,
                mu.total_tokens,
                mu.runtime_ms,
                mu.local_only,
                mu.metadata,
                mu.created_at
            from model_usage mu
            join pipeline_runs r on r.id = mu.run_id
            where r.run_key = %s
            order by mu.created_at asc, mu.purpose asc, mu.provider asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_provider_attempts(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pa.id,
                pa.run_id,
                r.run_key,
                pa.source_path,
                pa.relative_path,
                pa.provider,
                pa.capability,
                pa.status,
                pa.strategy,
                pa.runtime_ms,
                pa.warnings,
                pa.metadata,
                pa.created_at
            from provider_attempts pa
            join pipeline_runs r on r.id = pa.run_id
            where r.run_key = %s
            order by pa.created_at asc, pa.source_path asc nulls last, pa.provider asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_document_segments(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                ds.id,
                ds.run_id,
                r.run_key,
                ds.source_path,
                ds.relative_path,
                ds.segment_id,
                ds.parent_file_id,
                ds.page_start,
                ds.page_end,
                ds.segment_index,
                ds.segment_type,
                ds.segment_title,
                ds.segment_confidence,
                ds.requires_segment_review,
                ds.boundary_evidence,
                ds.metadata,
                ds.created_at
            from document_segments ds
            join pipeline_runs r on r.id = ds.run_id
            where r.run_key = %s
            order by ds.source_path asc, ds.segment_index asc, ds.page_start asc nulls last
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _upsert_run(self, connection: PostgresConnection, *, run_key: str, preset_key: str | None, output_dir: Path, summary: dict[str, Any]) -> str:
        graph_runtime = summary.get("graph_runtime") if isinstance(summary.get("graph_runtime"), dict) else {}
        providers = summary.get("providers") if isinstance(summary.get("providers"), dict) else {}
        row = connection.execute(
            """
            insert into pipeline_runs (
                run_key, preset_key, output_dir, status, local_only, summary,
                embedding_provider, embedding_model, llm_provider, llm_model,
                extraction_provider, vector_store_provider, vector_store_collection
            )
            values (%s, %s, %s, 'succeeded', true, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_key) do update set
                preset_key = excluded.preset_key,
                output_dir = excluded.output_dir,
                status = excluded.status,
                summary = excluded.summary,
                embedding_provider = excluded.embedding_provider,
                embedding_model = excluded.embedding_model,
                llm_provider = excluded.llm_provider,
                llm_model = excluded.llm_model,
                extraction_provider = excluded.extraction_provider,
                vector_store_provider = excluded.vector_store_provider,
                vector_store_collection = excluded.vector_store_collection,
                updated_at = now()
            returning id
            """,
            (
                run_key,
                preset_key,
                str(output_dir),
                json.dumps(summary, sort_keys=True),
                providers.get("embedding_provider"),
                providers.get("embedding_model"),
                providers.get("llm_provider"),
                providers.get("llm_model"),
                providers.get("extraction_provider"),
                providers.get("vector_store_provider"),
                providers.get("vector_store_collection") or graph_runtime.get("policy", {}).get("qdrant_collection"),
            ),
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

    def _import_review_items(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-review-queue.jsonl")
        connection.execute("delete from review_items_v2 where run_id = %s", (run_id,))
        imported = 0
        for row in rows:
            source_path = row.get("source_path") or row.get("sample_path")
            if not source_path:
                continue
            connection.execute(
                """
                insert into review_items_v2 (
                    run_id, source_path, relative_path, segment_id, status, review_reason,
                    proposed_class, proposed_tag, proposed_secondary_tags, notes
                ) values (%s, %s, %s, %s, 'open', %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    run_id,
                    source_path,
                    row.get("relative_path"),
                    row.get("segment_id"),
                    row.get("review_reason") or row.get("route_status") or "review_required",
                    row.get("final_class"),
                    row.get("top_tag_candidate"),
                    json.dumps(row.get("secondary_tags") or []),
                    _review_notes(row),
                ),
            )
            imported += 1
        return imported


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


def _run_summary_from_artifacts(output_path: Path) -> dict[str, Any]:
    result_rows = _read_jsonl(output_path / "sample-pipeline-results.jsonl")
    model_usage_rows = _read_jsonl(output_path / "sample-model-usage.jsonl")
    provider_attempt_rows = _read_jsonl(output_path / "sample-provider-attempts.jsonl")
    indexing_rows = _read_jsonl(output_path / "sample-indexing.jsonl")
    manifest = _read_json(output_path / "artifact-manifest.json")
    run_metadata = _read_json(output_path / "graph-run-metadata.json")
    graph_runtime = run_metadata.get("graph_runtime") if isinstance(run_metadata.get("graph_runtime"), dict) else {}
    providers = _provider_summary(model_usage_rows, provider_attempt_rows, indexing_rows)
    return {
        "artifact_manifest": manifest,
        "graph_run_metadata": run_metadata,
        "graph_runtime": graph_runtime,
        "providers": providers,
        "counts": {
            "pipeline_results": len(result_rows),
            "review_required": sum(1 for row in result_rows if row.get("route_status") != "route_candidate"),
            "model_usage": len(model_usage_rows),
            "provider_attempts": len(provider_attempt_rows),
            "indexing": len(indexing_rows),
        },
        "distributions": {
            "route_status": _count_values(result_rows, "route_status"),
            "quality": _count_values(result_rows, "quality"),
            "final_class": _count_values(result_rows, "final_class"),
        },
        "local_only": True,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "invalid_json", "path": str(path)}
    return value if isinstance(value, dict) else {"value": value}


def _provider_summary(model_usage_rows: list[dict[str, Any]], provider_attempt_rows: list[dict[str, Any]], indexing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    embedding = next((row for row in model_usage_rows if row.get("purpose") == "chunk_embedding"), {})
    llm = next((row for row in model_usage_rows if row.get("purpose") == "tag_inspection"), {})
    extraction = next((row for row in provider_attempt_rows if row.get("capability", "extraction") == "extraction"), {})
    indexing = next((row for row in indexing_rows if row.get("provider")), {})
    return {
        "embedding_provider": embedding.get("provider"),
        "embedding_model": embedding.get("model"),
        "llm_provider": llm.get("provider"),
        "llm_model": llm.get("model"),
        "extraction_provider": extraction.get("provider"),
        "vector_store_provider": indexing.get("provider"),
        "vector_store_collection": indexing.get("collection"),
    }


def _count_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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


def _review_notes(row: dict[str, Any]) -> str | None:
    warnings = row.get("warnings")
    parts = [
        f"route_status={row.get('route_status')}" if row.get("route_status") else None,
        f"quality={row.get('quality')}" if row.get("quality") else None,
        f"tag_confidence={row.get('tag_confidence')}" if row.get("tag_confidence") is not None else None,
        "warnings=" + ";".join(map(str, warnings)) if isinstance(warnings, list) and warnings else None,
    ]
    note = " | ".join(part for part in parts if part)
    return note or None


def _review_status_from_decision(decision: str) -> str:
    normalized = (decision or "").strip().lower()
    return {
        "accept": "accepted",
        "accepted": "accepted",
        "change": "changed",
        "changed": "changed",
        "defer": "deferred",
        "deferred": "deferred",
        "reject": "rejected",
        "rejected": "rejected",
    }.get(normalized, "open")


def _append_note(existing: Any, note: str | None) -> str | None:
    existing_text = str(existing).strip() if existing else ""
    note_text = str(note).strip() if note else ""
    if existing_text and note_text:
        return f"{existing_text}\n{note_text}"
    return existing_text or note_text or None
