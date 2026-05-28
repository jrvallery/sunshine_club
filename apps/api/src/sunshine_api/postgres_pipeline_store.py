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
import sqlite3
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
                "pipeline_run_events": self._import_run_events(connection, run_id, output_path),
                "model_usage": self._import_model_usage(connection, run_id, output_path),
                "provider_attempts": self._import_provider_attempts(connection, run_id, output_path),
                "pipeline_provider_selections": self._import_provider_selections(connection, run_id, output_path),
                "pipeline_quality_checks": self._import_quality_checks(connection, run_id, output_path),
                "pipeline_tagging_evidence": self._import_tagging_evidence(connection, run_id, output_path),
                "pipeline_file_metadata": self._import_file_metadata(connection, run_id, output_path),
                "pipeline_artifacts": self._import_pipeline_artifacts(connection, run_id, output_path),
                "pipeline_parser_results": self._import_parser_results(connection, run_id, output_path),
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
                "pipeline_provider_selections": _scalar_count(connection, "select count(*) from pipeline_provider_selections"),
                "pipeline_quality_checks": _scalar_count(connection, "select count(*) from pipeline_quality_checks"),
                "pipeline_tagging_evidence": _scalar_count(connection, "select count(*) from pipeline_tagging_evidence"),
                "pipeline_file_metadata": _scalar_count(connection, "select count(*) from pipeline_file_metadata"),
                "pipeline_artifacts": _scalar_count(connection, "select count(*) from pipeline_artifacts"),
                "pipeline_parser_results": _scalar_count(connection, "select count(*) from pipeline_parser_results"),
                "pipeline_run_events": _scalar_count(connection, "select count(*) from pipeline_run_events"),
                "document_segments": _scalar_count(connection, "select count(*) from document_segments"),
                "pipeline_chunks": _scalar_count(connection, "select count(*) from pipeline_chunks"),
                "pipeline_chunk_embeddings": _scalar_count(connection, "select count(*) from pipeline_chunk_embeddings"),
                "provider_benchmark_runs": _scalar_count(connection, "select count(*) from provider_benchmark_runs"),
                "provider_benchmark_results": _scalar_count(connection, "select count(*) from provider_benchmark_results"),
                "provider_benchmark_parser_results": _scalar_count(connection, "select count(*) from provider_benchmark_parser_results"),
                "provider_benchmark_recommendations": _scalar_count(connection, "select count(*) from provider_benchmark_recommendations"),
                "recent_runs": self._list_pipeline_runs(connection, limit=5),
                "recent_provider_benchmarks": self.list_provider_benchmark_runs(limit=5),
            }
        finally:
            connection.close()

    def review_summary(self) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            by_status = _postgres_count_rows(
                connection,
                "select coalesce(status, 'open') as key, count(*) as count from review_items_v2 group by coalesce(status, 'open')",
            )
            return {
                "db_path": str(self.database_url),
                "source": "postgres",
                "total_results": _scalar_count(connection, "select count(*) from pipeline_results"),
                "total_review_items": _scalar_count(connection, "select count(*) from review_items_v2"),
                "total_golden_labels": _scalar_count(connection, "select count(*) from golden_labels_v2"),
                "review_by_status": {**by_status, "resolved": sum(count for status, count in by_status.items() if status != "open")},
                "results_by_route_status": _postgres_count_rows(
                    connection,
                    "select coalesce(route_status, 'unknown') as key, count(*) as count from pipeline_results group by coalesce(route_status, 'unknown')",
                ),
                "results_by_quality": _postgres_count_rows(
                    connection,
                    "select coalesce(quality, 'unknown') as key, count(*) as count from pipeline_results group by coalesce(quality, 'unknown')",
                ),
                "results_by_primary_tag": _postgres_count_rows(
                    connection,
                    "select coalesce(top_tag_candidate, 'none') as key, count(*) as count from pipeline_results group by coalesce(top_tag_candidate, 'none')",
                ),
                "results_by_secondary_tag": {},
            }
        finally:
            connection.close()

    def list_pipeline_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            return self._list_pipeline_runs(connection, limit=limit)
        finally:
            connection.close()

    def record_pipeline_run_state(
        self,
        *,
        run_key: str,
        status: str,
        preset_key: str | None = None,
        input_root: str | None = None,
        output_dir: str | Path | None = None,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        extraction_provider: str | None = None,
        vector_store_provider: str | None = None,
        vector_store_collection: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"queued", "running", "succeeded", "failed", "cancelled"}:
            raise ValueError(f"Unsupported pipeline run status: {status}")
        resolved_output_dir = str(output_dir or "")
        if not resolved_output_dir:
            raise ValueError("output_dir is required to record a Postgres pipeline run")
        run_summary = dict(summary or {})
        if error:
            run_summary["error"] = error
        connection = self._connect_factory(self.database_url)
        try:
            run_id = self._upsert_run_state(
                connection,
                run_key=run_key,
                preset_key=preset_key,
                input_root=input_root,
                output_dir=Path(resolved_output_dir),
                status=status,
                summary=run_summary,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                llm_provider=llm_provider,
                llm_model=llm_model,
                extraction_provider=extraction_provider,
                vector_store_provider=vector_store_provider,
                vector_store_collection=vector_store_collection,
            )
            connection.execute(
                """
                insert into pipeline_run_events (
                    run_id, node, status, message, payload
                ) values (%s, 'dashboard_run_lifecycle', %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    status,
                    error or f"Dashboard run state recorded as {status}.",
                    json.dumps({"run_key": run_key, "status": status, "summary": run_summary}, sort_keys=True),
                ),
            )
            connection.commit()
            return {
                "run_id": run_id,
                "run_key": run_key,
                "status": status,
                "output_dir": resolved_output_dir,
            }
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

    def delete_pipeline_run(self, *, run_key: str) -> dict[str, Any]:
        """Delete one imported V2 run and all cascade-owned Postgres rows."""

        connection = self._connect_factory(self.database_url)
        try:
            run = connection.execute(
                """
                select
                    r.id,
                    r.run_key,
                    r.preset_key,
                    r.output_dir,
                    r.status,
                    r.created_at,
                    r.updated_at,
                    (select count(*) from pipeline_results pr where pr.run_id = r.id) as pipeline_results,
                    (select count(*) from pipeline_chunks pc where pc.run_id = r.id) as pipeline_chunks,
                    (select count(*) from pipeline_chunk_embeddings pce where pce.run_id = r.id) as pipeline_chunk_embeddings,
                    (select count(*) from pipeline_run_events pre where pre.run_id = r.id) as pipeline_run_events,
                    (select count(*) from model_usage mu where mu.run_id = r.id) as model_usage,
                    (select count(*) from provider_attempts pa where pa.run_id = r.id) as provider_attempts,
                    (select count(*) from pipeline_provider_selections pps where pps.run_id = r.id) as pipeline_provider_selections,
                    (select count(*) from pipeline_quality_checks pqc where pqc.run_id = r.id) as pipeline_quality_checks,
                    (select count(*) from pipeline_tagging_evidence pte where pte.run_id = r.id) as pipeline_tagging_evidence,
                    (select count(*) from pipeline_file_metadata pfm where pfm.run_id = r.id) as pipeline_file_metadata,
                    (select count(*) from pipeline_artifacts pa where pa.run_id = r.id) as pipeline_artifacts,
                    (select count(*) from pipeline_parser_results ppr where ppr.run_id = r.id) as pipeline_parser_results,
                    (select count(*) from document_segments ds where ds.run_id = r.id) as document_segments,
                    (select count(*) from review_items_v2 ri where ri.run_id = r.id) as review_items
                from pipeline_runs r
                where r.run_key = %s
                """,
                (run_key,),
            ).fetchone()
            if run is None:
                raise KeyError(f"Postgres pipeline run not found: {run_key}")
            run_row = _json_safe_row(_row_to_dict(run))
            connection.execute("delete from pipeline_runs where id = %s", (run_row["id"],))
            connection.commit()
            return {
                "deleted": True,
                "run_key": run_key,
                "run": run_row,
                "deleted_counts": {
                    "pipeline_runs": 1,
                    "pipeline_results": _int_value(run_row.get("pipeline_results")),
                    "pipeline_chunks": _int_value(run_row.get("pipeline_chunks")),
                    "pipeline_chunk_embeddings": _int_value(run_row.get("pipeline_chunk_embeddings")),
                    "pipeline_run_events": _int_value(run_row.get("pipeline_run_events")),
                    "model_usage": _int_value(run_row.get("model_usage")),
                    "provider_attempts": _int_value(run_row.get("provider_attempts")),
                    "pipeline_provider_selections": _int_value(run_row.get("pipeline_provider_selections")),
                    "pipeline_quality_checks": _int_value(run_row.get("pipeline_quality_checks")),
                    "pipeline_tagging_evidence": _int_value(run_row.get("pipeline_tagging_evidence")),
                    "pipeline_file_metadata": _int_value(run_row.get("pipeline_file_metadata")),
                    "pipeline_artifacts": _int_value(run_row.get("pipeline_artifacts")),
                    "pipeline_parser_results": _int_value(run_row.get("pipeline_parser_results")),
                    "document_segments": _int_value(run_row.get("document_segments")),
                    "review_items": _int_value(run_row.get("review_items")),
                },
            }
        finally:
            connection.close()

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
            results = self._list_pipeline_results(connection, run_key=run_key, limit=capped_limit)
            review_items = self._list_review_items(connection, run_key=run_key, limit=capped_limit)
            model_usage = self._list_model_usage(connection, run_key=run_key, limit=capped_limit)
            provider_attempts = self._list_provider_attempts(connection, run_key=run_key, limit=capped_limit)
            provider_selections = self._list_provider_selections(connection, run_key=run_key, limit=capped_limit)
            quality_checks = self._list_quality_checks(connection, run_key=run_key, limit=capped_limit)
            tagging_evidence = self._list_tagging_evidence(connection, run_key=run_key, limit=capped_limit)
            file_metadata = self._list_file_metadata(connection, run_key=run_key, limit=capped_limit)
            artifacts = self._list_pipeline_artifacts(connection, run_key=run_key, limit=capped_limit)
            parser_results = self._list_parser_results(connection, run_key=run_key, limit=capped_limit)
            document_segments = self._list_document_segments(connection, run_key=run_key, limit=capped_limit)
            chunks = self._list_chunks(connection, run_key=run_key, limit=capped_limit)
            chunk_embeddings = self._list_chunk_embeddings(connection, run_key=run_key, limit=capped_limit)
            run_events = self._list_run_events(connection, run_key=run_key, limit=capped_limit)
            return {
                "run": run,
                "summary": _run_report_summary(
                    results=results,
                    review_items=review_items,
                    model_usage=model_usage,
                    provider_attempts=provider_attempts,
                    provider_selections=provider_selections,
                    quality_checks=quality_checks,
                    tagging_evidence=tagging_evidence,
                    file_metadata=file_metadata,
                    artifacts=artifacts,
                    parser_results=parser_results,
                    document_segments=document_segments,
                    chunks=chunks,
                    chunk_embeddings=chunk_embeddings,
                    run_events=run_events,
                ),
                "results": results,
                "review_items": review_items,
                "model_usage": model_usage,
                "provider_attempts": provider_attempts,
                "provider_selections": provider_selections,
                "quality_checks": quality_checks,
                "tagging_evidence": tagging_evidence,
                "file_metadata": file_metadata,
                "artifacts": artifacts,
                "parser_results": parser_results,
                "document_segments": document_segments,
                "chunks": chunks,
                "chunk_embeddings": chunk_embeddings,
                "run_events": run_events,
            }
        finally:
            connection.close()

    def list_run_events(self, *, run_key: str, limit: int = 200) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            return self._list_run_events(connection, run_key=run_key, limit=limit)
        finally:
            connection.close()

    def import_provider_benchmark_output(
        self,
        output_dir: str | Path,
        *,
        benchmark_key: str | None = None,
    ) -> dict[str, Any]:
        output_path = Path(output_dir)
        if not output_path.exists():
            raise FileNotFoundError(f"Provider benchmark output directory not found: {output_path}")
        results = _read_jsonl(output_path / "provider-benchmark-results.jsonl")
        parser_results = _read_jsonl(output_path / "sample-parser-results.jsonl")
        recommendations = _read_jsonl(output_path / "provider-benchmark-recommendations.jsonl")
        summary = _read_json(output_path / "provider-benchmark-summary.json")
        artifact_manifest = _read_json(output_path / "artifact-manifest.json")
        background_error = _read_json(output_path / "provider-benchmark-background-error.json")
        if not any((results, parser_results, recommendations, summary, background_error)):
            raise FileNotFoundError(f"No provider benchmark artifacts found in {output_path}")
        resolved_key = benchmark_key or output_path.name
        partial = not bool(summary)
        status = "failed" if background_error else ("partial" if partial else "completed")
        connection = self._connect_factory(self.database_url)
        try:
            run_id = self._upsert_provider_benchmark_run(
                connection,
                benchmark_key=resolved_key,
                output_dir=output_path,
                status=status,
                partial=partial,
                summary=summary or _provider_benchmark_partial_summary(results, parser_results, recommendations),
                artifact_manifest=artifact_manifest,
                background_error=background_error,
            )
            counts = {
                "provider_benchmark_results": self._import_provider_benchmark_results(connection, run_id, results),
                "provider_benchmark_parser_results": self._import_provider_benchmark_parser_results(connection, run_id, parser_results),
                "provider_benchmark_recommendations": self._import_provider_benchmark_recommendations(connection, run_id, recommendations),
            }
            connection.commit()
        finally:
            connection.close()
        return {
            "benchmark_run_id": run_id,
            "benchmark_key": resolved_key,
            "output_dir": str(output_path),
            "status": status,
            "partial": partial,
            "imported": counts,
        }

    def list_provider_benchmark_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            rows = connection.execute(
                """
                select
                    pbr.id,
                    pbr.benchmark_key,
                    pbr.output_dir,
                    pbr.status,
                    pbr.partial,
                    pbr.summary,
                    pbr.artifact_manifest,
                    pbr.background_error,
                    pbr.created_at,
                    pbr.updated_at,
                    (select count(*) from provider_benchmark_results r where r.benchmark_run_id = pbr.id) as result_count,
                    (select count(*) from provider_benchmark_parser_results r where r.benchmark_run_id = pbr.id) as parser_result_count,
                    (select count(*) from provider_benchmark_recommendations r where r.benchmark_run_id = pbr.id) as recommendation_count
                from provider_benchmark_runs pbr
                order by pbr.updated_at desc, pbr.created_at desc
                limit %s
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [_json_safe_row(_row_to_dict(row)) for row in rows]
        finally:
            connection.close()

    def get_provider_benchmark_run(
        self,
        *,
        benchmark_key: str,
        result_limit: int = 500,
        parser_result_limit: int = 500,
    ) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            run_row = connection.execute(
                """
                select
                    pbr.id,
                    pbr.benchmark_key,
                    pbr.output_dir,
                    pbr.status,
                    pbr.partial,
                    pbr.summary,
                    pbr.artifact_manifest,
                    pbr.background_error,
                    pbr.created_at,
                    pbr.updated_at,
                    (select count(*) from provider_benchmark_results r where r.benchmark_run_id = pbr.id) as result_count,
                    (select count(*) from provider_benchmark_parser_results r where r.benchmark_run_id = pbr.id) as parser_result_count,
                    (select count(*) from provider_benchmark_recommendations r where r.benchmark_run_id = pbr.id) as recommendation_count
                from provider_benchmark_runs pbr
                where pbr.benchmark_key = %s
                limit 1
                """,
                (benchmark_key,),
            ).fetchone()
            if run_row is None:
                raise KeyError(f"Provider benchmark run not found: {benchmark_key}")
            run = _json_safe_row(_row_to_dict(run_row))
            benchmark_run_id = str(run["id"])
            results = connection.execute(
                """
                select
                    id,
                    benchmark_run_id,
                    source_path,
                    relative_path,
                    sample_category,
                    sample_label,
                    provider,
                    status,
                    quality,
                    requires_review,
                    seconds,
                    result,
                    created_at
                from provider_benchmark_results
                where benchmark_run_id = %s
                order by sample_category nulls last, relative_path nulls last, source_path nulls last, provider
                limit %s
                """,
                (benchmark_run_id, max(1, min(int(result_limit), 2000))),
            ).fetchall()
            parser_results = connection.execute(
                """
                select
                    id,
                    benchmark_run_id,
                    source_path,
                    relative_path,
                    sample_category,
                    sample_label,
                    provider,
                    status,
                    quality,
                    requires_review,
                    seconds,
                    text_length,
                    page_count,
                    result,
                    created_at
                from provider_benchmark_parser_results
                where benchmark_run_id = %s
                order by sample_category nulls last, relative_path nulls last, source_path nulls last, provider
                limit %s
                """,
                (benchmark_run_id, max(1, min(int(parser_result_limit), 2000))),
            ).fetchall()
            recommendations = connection.execute(
                """
                select
                    id,
                    benchmark_run_id,
                    provider,
                    recommendation,
                    status,
                    average_seconds,
                    result,
                    created_at
                from provider_benchmark_recommendations
                where benchmark_run_id = %s
                order by provider
                """,
                (benchmark_run_id,),
            ).fetchall()
            result_rows = [_json_safe_row(_row_to_dict(row)) for row in results]
            parser_result_rows = [_json_safe_row(_row_to_dict(row)) for row in parser_results]
            recommendation_rows = [_json_safe_row(_row_to_dict(row)) for row in recommendations]
            return {
                "run": run,
                "summary": _provider_benchmark_detail_summary(
                    result_rows=result_rows,
                    parser_result_rows=parser_result_rows,
                    recommendation_rows=recommendation_rows,
                ),
                "results": result_rows,
                "parser_results": parser_result_rows,
                "recommendations": recommendation_rows,
            }
        finally:
            connection.close()

    def provider_benchmark_promotion_plan(self, *, benchmark_key: str) -> dict[str, Any]:
        detail = self.get_provider_benchmark_run(benchmark_key=benchmark_key, result_limit=1, parser_result_limit=1)
        run = detail["run"]
        recommendations = detail["recommendations"]
        candidates = [
            row
            for row in recommendations
            if _provider_benchmark_recommendation_status(row) == "candidate" and str(row.get("provider") or "") not in {"", "current", "unknown"}
        ]
        selected = candidates[0] if candidates else None
        blockers = [
            {
                "provider": row.get("provider"),
                "status": _provider_benchmark_recommendation_status(row),
                "reason": _provider_benchmark_recommendation_reason(row),
            }
            for row in recommendations
            if _provider_benchmark_recommendation_status(row) != "candidate"
        ]
        if run.get("partial") or run.get("status") != "completed":
            blockers.insert(
                0,
                {
                    "provider": None,
                    "status": "blocked_incomplete_benchmark",
                    "reason": "benchmark run must be completed before provider promotion",
                },
            )
            selected = None
        provider = str(selected.get("provider")) if selected else None
        env = {
            "SUNSHINE_OCR_PARSER_PROVIDER": provider,
            "SUNSHINE_TEXT_PARSER_PROVIDER": provider,
            "SUNSHINE_DEFAULT_PARSER_PROVIDER": provider,
        } if provider else {}
        return {
            "benchmark_key": benchmark_key,
            "benchmark_run": run,
            "status": "candidate" if provider else "blocked_or_review_required",
            "selected_provider": provider,
            "local_only": bool(_provider_benchmark_recommendation_result(selected).get("local_only")) if selected else False,
            "recommended_env": env,
            "shell_exports": [f"export {key}={value}" for key, value in env.items() if value],
            "recommended_next_steps": _provider_benchmark_next_steps(provider=provider, blockers=blockers),
            "blockers": blockers,
            "recommendations": recommendations,
        }

    def list_review_items(self, *, run_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            return self._list_review_items(connection, run_key=run_key, limit=limit)
        finally:
            connection.close()

    def search_files(
        self,
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
    ) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            rows = connection.execute(
                """
                select
                    pr.id,
                    pr.run_id,
                    r.run_key,
                    r.preset_key,
                    r.embedding_provider,
                    r.llm_provider,
                    r.extraction_provider,
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
                    pr.updated_at,
                    (
                        select ri.status
                        from review_items_v2 ri
                        where ri.source_path = pr.source_path
                          and (ri.segment_id is null or ri.segment_id = '')
                        order by ri.updated_at desc, ri.created_at desc
                        limit 1
                    ) as review_status
                from pipeline_results pr
                left join pipeline_runs r on r.id = pr.run_id
                order by pr.updated_at desc, pr.created_at desc
                limit %s
                """,
                (5000,),
            ).fetchall()
            mapped = _dedupe_postgres_file_rows(
                [_postgres_file_search_item(_json_safe_row(_row_to_dict(row))) for row in rows]
            )
            filtered = _filter_postgres_files(
                mapped,
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
            ordered = _sort_postgres_files(filtered, sort)
            offset = max(int(cursor or 0), 0)
            capped_limit = max(1, min(int(limit), 500))
            items = ordered[offset : offset + capped_limit]
            next_cursor = offset + len(items) if offset + len(items) < len(ordered) else None
            return {
                "items": items,
                "next_cursor": next_cursor,
                "total_estimate": len(ordered),
                "query": {
                    key: value
                    for key, value in {
                        "q": q,
                        "source_collection": source_collection,
                        "extension": extension,
                        "content_class": content_class,
                        "primary_tag": primary_tag,
                        "secondary_tag": secondary_tag,
                        "route_status": route_status,
                        "review_status": review_status,
                        "ocr_quality": ocr_quality,
                        "warning_type": warning_type,
                        "placement_status": placement_status,
                        "run_id": run_id,
                        "sort": sort,
                        "cursor": offset,
                        "limit": capped_limit,
                        "source": "postgres",
                    }.items()
                    if value not in (None, "")
                },
            }
        finally:
            connection.close()

    def file_facets(
        self,
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
    ) -> dict[str, dict[str, int]]:
        search = self.search_files(
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
            limit=5000,
        )
        rows = search["items"]
        return {
            "extension": _facet_count_postgres(rows, "extension"),
            "source_collection": _facet_count_postgres(rows, "source_collection"),
            "content_class": _facet_count_postgres(rows, "content_class"),
            "primary_tag": _facet_count_postgres(rows, "primary_tag"),
            "secondary_tag": _facet_array_count_postgres(rows, "secondary_tags"),
            "route_status": _facet_count_postgres(rows, "route_status"),
            "review_status": _facet_count_postgres(rows, "review_status"),
            "ocr_quality": _facet_count_postgres(rows, "quality"),
            "warning_type": _facet_array_count_postgres(rows, "warnings"),
            "placement_status": _facet_count_postgres(rows, "placement_status"),
            "latest_run": _facet_count_postgres(rows, "latest_run_id"),
        }

    def get_file_result(self, result_id: str) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            row = connection.execute(
                """
                select
                    pr.id,
                    pr.run_id,
                    r.run_key,
                    r.preset_key,
                    r.embedding_provider,
                    r.llm_provider,
                    r.extraction_provider,
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
                    pr.updated_at,
                    (
                        select ri.status
                        from review_items_v2 ri
                        where ri.source_path = pr.source_path
                          and (ri.segment_id is null or ri.segment_id = '')
                        order by ri.updated_at desc, ri.created_at desc
                        limit 1
                    ) as review_status
                from pipeline_results pr
                left join pipeline_runs r on r.id = pr.run_id
                where pr.id = %s
                """,
                (result_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Postgres file result not found: {result_id}")
            raw = _json_safe_row(_row_to_dict(row))
            item = _postgres_file_search_item(raw)
            item["latest_result"] = raw.get("result") if isinstance(raw.get("result"), dict) else {}
            item["tag_confidence"] = raw.get("tag_confidence")
            item["extraction_strategy"] = raw.get("extraction_strategy")
            item["extraction_status"] = raw.get("extraction_status")
            item["review_reason"] = raw.get("review_reason")
            return item
        finally:
            connection.close()

    def file_path_for_file_result(self, result_id: str) -> Path:
        item = self.get_file_result(result_id)
        result = item.get("latest_result") if isinstance(item.get("latest_result"), dict) else {}
        for candidate in (item.get("sample_path"), result.get("sample_path"), item.get("source_path")):
            if not candidate:
                continue
            path = Path(str(candidate))
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError(f"No readable file found for Postgres file result {result_id}")

    def file_text_for_file_result(self, result_id: str) -> dict[str, Any]:
        item = self.get_file_result(result_id)
        connection = self._connect_factory(self.database_url)
        try:
            rows = connection.execute(
                """
                select content
                from pipeline_chunks
                where run_id = %s
                  and source_path = %s
                order by chunk_index asc, id asc
                limit %s
                """,
                (item.get("latest_run_id"), item.get("source_path"), 1000),
            ).fetchall()
        finally:
            connection.close()
        chunk_text = "\n\n".join(str(_row_to_dict(row).get("content") or "") for row in rows).strip()
        result = item.get("latest_result") if isinstance(item.get("latest_result"), dict) else {}
        fallback = item.get("text_snippet") or result.get("extraction_text_snippet") or result.get("text") or ""
        return {
            "file_id": result_id,
            "source": "postgres",
            "source_path": item.get("source_path"),
            "relative_path": item.get("relative_path"),
            "text": chunk_text or str(fallback or ""),
        }

    def file_inspection_for_file_result(self, result_id: str) -> dict[str, Any]:
        item = self.get_file_result(result_id)
        text = self.file_text_for_file_result(result_id)
        result = item.get("latest_result") if isinstance(item.get("latest_result"), dict) else {}
        return {
            "file": {key: value for key, value in item.items() if key != "latest_result"},
            "latest_result": result,
            "review_item": None,
            "golden_label": None,
            "ocr": {
                "quality": item.get("quality") or result.get("quality"),
                "ocr_status": result.get("ocr_status"),
                "mean_confidence": result.get("mean_confidence"),
                "fallback_provider": item.get("latest_ocr_fallback_provider"),
                "evidence": result.get("ocr_evidence") or result.get("warnings") or [],
                "warnings": result.get("warnings") or [],
            },
            "text": {
                "snippet": item.get("text_snippet"),
                "text": text.get("text"),
                "length": len(str(text.get("text") or "")),
            },
            "runs": [
                {
                    "id": item.get("latest_run_id"),
                    "run_key": item.get("latest_run_key"),
                    "preset_key": item.get("latest_run_preset_key"),
                    "embedding_provider": item.get("latest_embedding_provider"),
                    "llm_tag_provider": item.get("latest_llm_tag_provider"),
                    "ocr_fallback_provider": item.get("latest_ocr_fallback_provider"),
                }
            ]
            if item.get("latest_run_id")
            else [],
            "actions": {
                "preview_url": f"/api/admin/files/{result_id}/preview?source=postgres",
                "text_url": f"/api/admin/files/{result_id}/text?source=postgres",
                "run_url": None,
                "review_url": None,
                "latest_run_report_url": f"/runs/{item['latest_run_key']}/report" if item.get("latest_run_key") else None,
            },
            "raw": {"file": item, "latest_result": result},
        }

    def add_file_result_to_review(self, result_id: str, *, review_reason: str = "manual_file_review") -> dict[str, Any]:
        item = self.get_file_result(result_id)
        connection = self._connect_factory(self.database_url)
        try:
            existing = connection.execute(
                """
                select id
                from review_items_v2
                where run_id = %s
                  and source_path = %s
                  and (segment_id is null or segment_id = '')
                order by updated_at desc, created_at desc
                limit 1
                """,
                (item.get("latest_run_id"), item.get("source_path")),
            ).fetchone()
            if existing is not None:
                review_id = _row_to_dict(existing).get("id")
                connection.execute(
                    """
                    update review_items_v2
                    set status = 'open',
                        review_reason = %s,
                        proposed_class = %s,
                        proposed_tag = %s,
                        proposed_secondary_tags = %s::jsonb,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        review_reason,
                        item.get("content_class"),
                        item.get("primary_tag"),
                        json.dumps(item.get("secondary_tags") or [], sort_keys=True),
                        review_id,
                    ),
                )
            else:
                inserted = connection.execute(
                    """
                    insert into review_items_v2 (
                        run_id, source_path, relative_path, segment_id, status, review_reason,
                        proposed_class, proposed_tag, proposed_secondary_tags
                    ) values (%s, %s, %s, null, 'open', %s, %s, %s, %s::jsonb)
                    returning id
                    """,
                    (
                        item.get("latest_run_id"),
                        item.get("source_path"),
                        item.get("relative_path"),
                        review_reason,
                        item.get("content_class"),
                        item.get("primary_tag"),
                        json.dumps(item.get("secondary_tags") or [], sort_keys=True),
                    ),
                ).fetchone()
                review_id = _row_to_dict(inserted).get("id")
            connection.commit()
        finally:
            connection.close()
        return {
            "id": review_id,
            "source": "postgres",
            "file_result_id": result_id,
            "source_path": item.get("source_path"),
            "relative_path": item.get("relative_path"),
            "status": "open",
            "review_reason": review_reason,
            "proposed_class": item.get("content_class"),
            "proposed_tag": item.get("primary_tag"),
            "proposed_secondary_tags": item.get("secondary_tags") or [],
        }

    def list_golden_labels(self, *, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect_factory(self.database_url)
        try:
            rows = connection.execute(
                _golden_label_select_sql("order by gl.updated_at desc limit %s"),
                (max(1, min(int(limit), 10000)),),
            ).fetchall()
            return [_json_safe_row(_row_to_dict(row)) for row in rows]
        finally:
            connection.close()

    def get_golden_label(self, label_id: str) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            row = connection.execute(_golden_label_select_sql("where gl.id = %s"), (label_id,)).fetchone()
            if row is None:
                raise KeyError(f"Postgres golden label not found: {label_id}")
            return _json_safe_row(_row_to_dict(row))
        finally:
            connection.close()

    def update_golden_label(
        self,
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
    ) -> dict[str, Any]:
        existing = self.get_golden_label(label_id)
        resolved_primary = (correct_primary_tag or existing.get("correct_primary_tag") or "").strip()
        if not resolved_primary:
            raise ValueError("correct_primary_tag is required")
        resolved_secondary = _clean_json_tags(correct_secondary_tags) if correct_secondary_tags is not None else _clean_json_tags(existing.get("correct_secondary_tags"))
        connection = self._connect_factory(self.database_url)
        try:
            connection.execute(
                """
                update golden_labels_v2
                set content_class = %s,
                    correct_primary_tag = %s,
                    correct_secondary_tags = %s::jsonb,
                    ocr_quality_label = %s,
                    expected_review_required = %s,
                    sensitive_record = %s,
                    correct_destination_path = %s,
                    correct_placement_year = %s,
                    correct_privacy = %s,
                    reviewer = %s,
                    notes = %s,
                    reviewed_at = coalesce(reviewed_at, now()),
                    updated_at = now()
                where id = %s
                """,
                (
                    content_class if content_class is not None else existing.get("content_class"),
                    resolved_primary,
                    json.dumps(resolved_secondary, sort_keys=True),
                    ocr_quality_label if ocr_quality_label is not None else existing.get("ocr_quality_label"),
                    expected_review_required if expected_review_required is not None else existing.get("expected_review_required"),
                    sensitive_record if sensitive_record is not None else existing.get("sensitive_record"),
                    correct_destination_path if correct_destination_path is not None else existing.get("correct_destination_path"),
                    correct_placement_year if correct_placement_year is not None else existing.get("correct_placement_year"),
                    correct_privacy if correct_privacy is not None else existing.get("correct_privacy"),
                    reviewer if reviewer is not None else existing.get("reviewer"),
                    notes if notes is not None else existing.get("notes"),
                    label_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_golden_label(label_id)

    def delete_golden_label(self, label_id: str) -> dict[str, Any]:
        existing = self.get_golden_label(label_id)
        connection = self._connect_factory(self.database_url)
        try:
            connection.execute("delete from golden_labels_v2 where id = %s", (label_id,))
            connection.commit()
        finally:
            connection.close()
        return {"deleted": True, "id": label_id, "source_path": existing.get("source_path")}

    def file_path_for_golden_label(self, label_id: str) -> Path:
        label = self.get_golden_label(label_id)
        for candidate in (label.get("sample_path"), label.get("source_path")):
            if not candidate:
                continue
            path = Path(str(candidate))
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError(f"No readable file found for Postgres golden label {label_id}")

    def golden_label_summary(self) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
            return {
                "db_path": str(self.database_url),
                "source": "postgres",
                "total_golden_labels": _scalar_count(connection, "select count(*) from golden_labels_v2"),
                "golden_by_primary_tag": _postgres_count_rows(
                    connection,
                    "select correct_primary_tag as key, count(*) as count from golden_labels_v2 group by correct_primary_tag",
                ),
                "golden_by_secondary_tag": _postgres_jsonb_array_count_rows(connection, "golden_labels_v2", "correct_secondary_tags"),
            }
        finally:
            connection.close()

    def export_golden_labels_sqlite(self, output_db: str | Path, *, limit: int | None = None) -> dict[str, Any]:
        labels = self.list_golden_labels(limit=limit or 10000)
        output_path = Path(output_db)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(output_path) as connection:
            connection.execute(
                """
                create table if not exists golden_labels (
                    id text primary key,
                    review_item_id text,
                    source_path text not null unique,
                    relative_path text not null,
                    sample_path text,
                    extracted_text_snippet text,
                    content_class text,
                    correct_primary_tag text not null,
                    correct_secondary_tags_json text not null default '[]',
                    ocr_quality_label text,
                    expected_review_required integer,
                    sensitive_record integer not null default 0,
                    correct_destination_path text,
                    correct_placement_year text,
                    correct_privacy text,
                    reviewer text,
                    reviewed_at text,
                    notes text,
                    proposed_tag text,
                    proposed_secondary_tags_json text not null default '[]',
                    proposed_confidence real,
                    created_at text,
                    updated_at text
                )
                """
            )
            connection.execute("delete from golden_labels")
            for row in labels:
                connection.execute(
                    """
                    insert into golden_labels (
                        id, review_item_id, source_path, relative_path, sample_path, extracted_text_snippet,
                        content_class, correct_primary_tag, correct_secondary_tags_json, ocr_quality_label,
                        expected_review_required, sensitive_record, correct_destination_path, correct_placement_year,
                        correct_privacy, reviewer, reviewed_at, notes, proposed_tag, proposed_secondary_tags_json,
                        proposed_confidence, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(row.get("id")),
                        str(row.get("review_item_id")) if row.get("review_item_id") else None,
                        row.get("source_path"),
                        row.get("relative_path") or row.get("source_path"),
                        row.get("sample_path"),
                        row.get("extracted_text_snippet"),
                        row.get("content_class"),
                        row.get("correct_primary_tag"),
                        json.dumps(row.get("correct_secondary_tags") or []),
                        row.get("ocr_quality_label"),
                        _optional_bool_int(row.get("expected_review_required")),
                        1 if row.get("sensitive_record") else 0,
                        row.get("correct_destination_path"),
                        row.get("correct_placement_year"),
                        row.get("correct_privacy"),
                        row.get("reviewer"),
                        row.get("reviewed_at"),
                        row.get("notes"),
                        row.get("proposed_tag"),
                        json.dumps(row.get("proposed_secondary_tags") or []),
                        row.get("proposed_confidence"),
                        row.get("created_at"),
                        row.get("updated_at"),
                    ),
                )
            connection.commit()
        return {"status": "exported", "source": "postgres", "output_db": str(output_path), "label_count": len(labels)}

    def get_review_item(self, item_id: str) -> dict[str, Any]:
        connection = self._connect_factory(self.database_url)
        try:
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
                    pr.sample_path,
                    pr.result,
                    pr.tag_confidence,
                    pr.quality,
                    ri.created_at,
                    ri.updated_at
                from review_items_v2 ri
                left join pipeline_runs r on r.id = ri.run_id
                left join lateral (
                    select pr.sample_path, pr.result, pr.tag_confidence, pr.quality
                    from pipeline_results pr
                    where pr.run_id = ri.run_id
                      and (pr.source_path = ri.source_path or pr.relative_path = ri.relative_path)
                    order by pr.created_at asc
                    limit 1
                ) pr on true
                where ri.id = %s
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Postgres review item not found: {item_id}")
            return _json_safe_row(_row_to_dict(row))
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
        ocr_quality_label: str | None = None,
        expected_review_required: bool | None = None,
        sensitive_record: bool | None = None,
        correct_destination_path: str | None = None,
        correct_placement_year: str | None = None,
        correct_privacy: str | None = None,
        reviewer: str | None = None,
        notes: str | None = None,
        save_as_golden: bool = True,
    ) -> dict[str, Any]:
        status = _review_status_from_decision(decision)
        connection = self._connect_factory(self.database_url)
        try:
            existing = connection.execute(
                """
                select
                    ri.id,
                    ri.run_id,
                    ri.source_path,
                    ri.relative_path,
                    ri.segment_id,
                    ri.proposed_class,
                    ri.proposed_tag,
                    ri.proposed_secondary_tags,
                    ri.notes,
                    pr.sample_path,
                    pr.result,
                    pr.tag_confidence,
                    pr.quality
                from review_items_v2 ri
                left join lateral (
                    select pr.sample_path, pr.result, pr.tag_confidence, pr.quality
                    from pipeline_results pr
                    where pr.run_id = ri.run_id
                      and (pr.source_path = ri.source_path or pr.relative_path = ri.relative_path)
                    order by pr.created_at asc
                    limit 1
                ) pr on true
                where ri.id = %s
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
            if save_as_golden and decision in {"accept", "change", "accepted", "changed"} and resolved_tag:
                self._upsert_golden_label(
                    connection,
                    review_item=existing_row,
                    decision=decision,
                    correct_class=resolved_class,
                    correct_tag=resolved_tag,
                    correct_secondary_tags=resolved_secondary or [],
                    ocr_quality_label=ocr_quality_label,
                    expected_review_required=expected_review_required,
                    sensitive_record=sensitive_record,
                    correct_destination_path=correct_destination_path,
                    correct_placement_year=correct_placement_year,
                    correct_privacy=correct_privacy,
                    reviewer=reviewer,
                    notes=notes,
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

    def record_segment_review_decision(
        self,
        *,
        run_key: str,
        segment_id: str,
        decision: str,
        notes: str | None = None,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"accept", "reject", "split", "merge", "defer", "change"}:
            raise ValueError("segment decision must be accept, reject, split, merge, defer, or change")
        review_status = _segment_review_status(normalized_decision)
        connection = self._connect_factory(self.database_url)
        try:
            row = connection.execute(
                """
                select
                    ds.id,
                    ds.run_id,
                    r.run_key,
                    ds.source_path,
                    ds.relative_path,
                    ds.segment_id,
                    ds.segment_type,
                    ds.segment_title,
                    ds.page_start,
                    ds.page_end,
                    ds.metadata
                from document_segments ds
                join pipeline_runs r on r.id = ds.run_id
                where r.run_key = %s
                  and ds.segment_id = %s
                """,
                (run_key, segment_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Postgres document segment not found: {run_key}/{segment_id}")
            segment = _json_safe_row(_row_to_dict(row))
            metadata = segment.get("metadata") if isinstance(segment.get("metadata"), dict) else {}
            metadata = {
                **metadata,
                "segment_review": {
                    "decision": normalized_decision,
                    "status": review_status,
                    "reviewer": reviewer,
                    "notes": notes,
                },
            }
            connection.execute(
                """
                update document_segments
                set metadata = %s::jsonb,
                    requires_segment_review = case when %s in ('accepted', 'rejected') then false else requires_segment_review end
                where id = %s
                """,
                (json.dumps(metadata, sort_keys=True), review_status, segment["id"]),
            )
            review_item_id = self._upsert_segment_review_item(
                connection,
                segment=segment,
                status=review_status,
                review_reason=f"segment_boundary_{normalized_decision}",
                notes=notes,
            )
            connection.commit()
            updated = connection.execute(
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
                where ds.id = %s
                """,
                (segment["id"],),
            ).fetchone()
            return {
                "run_key": run_key,
                "segment_id": segment_id,
                "decision": normalized_decision,
                "review_status": review_status,
                "review_item_id": review_item_id,
                "segment": _json_safe_row(_row_to_dict(updated)) if updated is not None else {**segment, "metadata": metadata},
            }
        finally:
            connection.close()

    def _upsert_segment_review_item(
        self,
        connection: PostgresConnection,
        *,
        segment: dict[str, Any],
        status: str,
        review_reason: str,
        notes: str | None,
    ) -> str | None:
        existing = connection.execute(
            """
            select id, notes
            from review_items_v2
            where run_id = %s
              and source_path = %s
              and segment_id = %s
            order by updated_at desc, created_at desc
            limit 1
            """,
            (segment.get("run_id"), segment.get("source_path"), segment.get("segment_id")),
        ).fetchone()
        if existing is not None:
            existing_row = _row_to_dict(existing)
            connection.execute(
                """
                update review_items_v2
                set status = %s,
                    review_reason = %s,
                    notes = %s,
                    updated_at = now()
                where id = %s
                """,
                (
                    status,
                    review_reason,
                    _append_note(existing_row.get("notes"), notes),
                    existing_row.get("id"),
                ),
            )
            return str(existing_row.get("id"))
        inserted = connection.execute(
            """
            insert into review_items_v2 (
                run_id, source_path, relative_path, segment_id, status, review_reason,
                proposed_class, proposed_tag, proposed_secondary_tags, notes
            ) values (%s, %s, %s, %s, %s, %s, null, null, '[]'::jsonb, %s)
            returning id
            """,
            (
                segment.get("run_id"),
                segment.get("source_path"),
                segment.get("relative_path"),
                segment.get("segment_id"),
                status,
                review_reason,
                notes,
            ),
        ).fetchone()
        return str(_row_to_dict(inserted).get("id")) if inserted is not None else None

    def _upsert_golden_label(
        self,
        connection: PostgresConnection,
        *,
        review_item: dict[str, Any],
        decision: str,
        correct_class: str | None,
        correct_tag: str,
        correct_secondary_tags: list[str],
        ocr_quality_label: str | None,
        expected_review_required: bool | None,
        sensitive_record: bool | None,
        correct_destination_path: str | None,
        correct_placement_year: str | None,
        correct_privacy: str | None,
        reviewer: str | None,
        notes: str | None,
    ) -> None:
        result = review_item.get("result") if isinstance(review_item.get("result"), dict) else {}
        resolved_quality = ocr_quality_label if ocr_quality_label is not None else (result.get("quality") or review_item.get("quality"))
        resolved_expected = expected_review_required if expected_review_required is not None else True
        text_snippet = result.get("extraction_text_snippet") or result.get("text_snippet") or result.get("text")
        connection.execute(
            """
            insert into golden_labels_v2 (
                review_item_id, run_id, source_path, relative_path, sample_path, segment_id,
                extracted_text_snippet, content_class, correct_primary_tag, correct_secondary_tags,
                ocr_quality_label, expected_review_required, sensitive_record, correct_destination_path,
                correct_placement_year, correct_privacy, reviewer, notes, proposed_tag,
                proposed_secondary_tags, proposed_confidence, reviewed_at, updated_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now(), now())
            on conflict (source_path, segment_id) do update set
                review_item_id = excluded.review_item_id,
                run_id = excluded.run_id,
                relative_path = excluded.relative_path,
                sample_path = excluded.sample_path,
                extracted_text_snippet = excluded.extracted_text_snippet,
                content_class = excluded.content_class,
                correct_primary_tag = excluded.correct_primary_tag,
                correct_secondary_tags = excluded.correct_secondary_tags,
                ocr_quality_label = excluded.ocr_quality_label,
                expected_review_required = excluded.expected_review_required,
                sensitive_record = excluded.sensitive_record,
                correct_destination_path = excluded.correct_destination_path,
                correct_placement_year = excluded.correct_placement_year,
                correct_privacy = excluded.correct_privacy,
                reviewer = excluded.reviewer,
                notes = excluded.notes,
                proposed_tag = excluded.proposed_tag,
                proposed_secondary_tags = excluded.proposed_secondary_tags,
                proposed_confidence = excluded.proposed_confidence,
                reviewed_at = now(),
                updated_at = now()
            """,
            (
                review_item.get("id"),
                review_item.get("run_id"),
                review_item.get("source_path"),
                review_item.get("relative_path"),
                review_item.get("sample_path"),
                review_item.get("segment_id") or "",
                str(text_snippet)[:4000] if text_snippet else None,
                correct_class or review_item.get("proposed_class"),
                correct_tag,
                json.dumps(correct_secondary_tags or []),
                resolved_quality,
                bool(resolved_expected),
                bool(sensitive_record),
                correct_destination_path,
                correct_placement_year,
                correct_privacy,
                reviewer,
                notes,
                review_item.get("proposed_tag"),
                json.dumps(review_item.get("proposed_secondary_tags") or []),
                review_item.get("tag_confidence"),
            ),
        )

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
                (select count(*) from pipeline_provider_selections pps where pps.run_id = r.id) as provider_selection_count,
                (select count(*) from pipeline_quality_checks pqc where pqc.run_id = r.id) as quality_check_count,
                (select count(*) from pipeline_tagging_evidence pte where pte.run_id = r.id) as tagging_evidence_count,
                (select count(*) from pipeline_file_metadata pfm where pfm.run_id = r.id) as file_metadata_count,
                (select count(*) from pipeline_artifacts pa where pa.run_id = r.id) as artifact_count,
                (select count(*) from pipeline_parser_results ppr where ppr.run_id = r.id) as parser_result_count,
                (select count(*) from document_segments ds where ds.run_id = r.id) as document_segment_count
            from pipeline_runs r
            order by r.created_at desc
            limit %s
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [_model_usage_report_row(_json_safe_row(_row_to_dict(row))) for row in rows]

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
                mu.host,
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

    def _list_run_events(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pre.id,
                pre.run_id,
                r.run_key,
                pre.source_path,
                pre.relative_path,
                pre.node,
                pre.status,
                pre.message,
                pre.payload,
                pre.created_at
            from pipeline_run_events pre
            join pipeline_runs r on r.id = pre.run_id
            where r.run_key = %s
            order by pre.created_at asc, pre.id asc
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

    def _list_provider_selections(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pps.id,
                pps.run_id,
                r.run_key,
                pps.source_path,
                pps.relative_path,
                pps.selected_provider,
                pps.preferred_provider,
                pps.configured_provider,
                pps.provider_chain,
                pps.skipped_providers,
                pps.provider_selection_reason,
                pps.metadata,
                pps.created_at
            from pipeline_provider_selections pps
            join pipeline_runs r on r.id = pps.run_id
            where r.run_key = %s
            order by pps.created_at asc, pps.source_path asc nulls last, pps.selected_provider asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_quality_checks(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pqc.id,
                pqc.run_id,
                r.run_key,
                pqc.source_path,
                pqc.relative_path,
                pqc.check_type,
                pqc.status,
                pqc.quality,
                pqc.requires_review,
                pqc.can_chunk,
                pqc.can_embed,
                pqc.provider,
                pqc.strategy,
                pqc.reason,
                pqc.warnings,
                pqc.result,
                pqc.created_at
            from pipeline_quality_checks pqc
            join pipeline_runs r on r.id = pqc.run_id
            where r.run_key = %s
            order by pqc.created_at asc, pqc.source_path asc nulls last, pqc.check_type asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_tagging_evidence(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pte.id,
                pte.run_id,
                r.run_key,
                pte.source_path,
                pte.relative_path,
                pte.evidence_type,
                pte.status,
                pte.provider,
                pte.model,
                pte.primary_tag,
                pte.confidence,
                pte.assignment_source,
                pte.route_status,
                pte.review_reason,
                pte.placement_status,
                pte.destination_path,
                pte.warnings,
                pte.evidence,
                pte.result,
                pte.created_at
            from pipeline_tagging_evidence pte
            join pipeline_runs r on r.id = pte.run_id
            where r.run_key = %s
            order by pte.created_at asc, pte.source_path asc nulls last, pte.evidence_type asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_file_metadata(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pfm.id,
                pfm.run_id,
                r.run_key,
                pfm.source_path,
                pfm.relative_path,
                pfm.sample_path,
                pfm.metadata_type,
                pfm.file_id,
                pfm.content_sha256,
                pfm.size_bytes,
                pfm.extension,
                pfm.mime_type,
                pfm.media_type,
                pfm.status,
                pfm.provider,
                pfm.page_count,
                pfm.text_length,
                pfm.sample_group,
                pfm.sample_number,
                pfm.final_class,
                pfm.extraction_strategy,
                pfm.import_status,
                pfm.warnings,
                pfm.result,
                pfm.created_at
            from pipeline_file_metadata pfm
            join pipeline_runs r on r.id = pfm.run_id
            where r.run_key = %s
            order by pfm.created_at asc, pfm.source_path asc nulls last, pfm.metadata_type asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_pipeline_artifacts(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pa.id,
                pa.run_id,
                r.run_key,
                pa.name,
                pa.path,
                pa.kind,
                pa.exists,
                pa.size_bytes,
                pa.row_count,
                pa.sha256,
                pa.note,
                pa.result,
                pa.created_at
            from pipeline_artifacts pa
            join pipeline_runs r on r.id = pa.run_id
            where r.run_key = %s
            order by pa.name asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_parser_results(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                ppr.id,
                ppr.run_id,
                r.run_key,
                ppr.source_path,
                ppr.relative_path,
                ppr.sample_path,
                ppr.sample_group,
                ppr.sample_number,
                ppr.provider,
                ppr.status,
                ppr.quality,
                ppr.requires_review,
                ppr.strategy,
                ppr.document_subtype,
                ppr.review_reason,
                ppr.text_length,
                ppr.page_count,
                ppr.page_structure_available,
                ppr.page_text_coverage_rate,
                ppr.layout_signal_count,
                ppr.result,
                ppr.created_at
            from pipeline_parser_results ppr
            join pipeline_runs r on r.id = ppr.run_id
            where r.run_key = %s
            order by ppr.created_at asc, ppr.source_path asc nulls last, ppr.provider asc
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

    def _list_chunks(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pc.id,
                pc.run_id,
                r.run_key,
                pc.source_path,
                pc.relative_path,
                pc.sample_path,
                pc.chunk_id,
                pc.chunk_index,
                pc.chunk_kind,
                left(pc.content, 500) as content_snippet,
                length(pc.content) as content_length,
                pc.metadata,
                pc.created_at
            from pipeline_chunks pc
            join pipeline_runs r on r.id = pc.run_id
            where r.run_key = %s
            order by pc.source_path asc nulls last, pc.chunk_index asc, pc.id asc
            limit %s
            """,
            (run_key, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [_json_safe_row(_row_to_dict(row)) for row in rows]

    def _list_chunk_embeddings(self, connection: PostgresConnection, *, run_key: str, limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            select
                pce.id,
                pce.run_id,
                r.run_key,
                pce.chunk_id,
                pce.source_path,
                pce.relative_path,
                pce.embedding_provider,
                pce.embedding_model,
                pce.embedding_dimensions,
                pce.embedding_status,
                pce.semantic_quality,
                pce.metadata,
                pce.created_at
            from pipeline_chunk_embeddings pce
            join pipeline_runs r on r.id = pce.run_id
            where r.run_key = %s
            order by pce.source_path asc nulls last, pce.chunk_id asc, pce.embedding_provider asc
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

    def _upsert_run_state(
        self,
        connection: PostgresConnection,
        *,
        run_key: str,
        preset_key: str | None,
        input_root: str | None,
        output_dir: Path,
        status: str,
        summary: dict[str, Any],
        embedding_provider: str | None,
        embedding_model: str | None,
        llm_provider: str | None,
        llm_model: str | None,
        extraction_provider: str | None,
        vector_store_provider: str | None,
        vector_store_collection: str | None,
    ) -> str:
        row = connection.execute(
            """
            insert into pipeline_runs (
                run_key, preset_key, input_root, output_dir, status, local_only, summary,
                embedding_provider, embedding_model, llm_provider, llm_model,
                extraction_provider, vector_store_provider, vector_store_collection,
                started_at, finished_at
            )
            values (
                %s, %s, %s, %s, %s, true, %s::jsonb,
                %s, %s, %s, %s, %s, %s, %s,
                case when %s = 'running' then now() else null end,
                case when %s in ('succeeded', 'failed', 'cancelled') then now() else null end
            )
            on conflict (run_key) do update set
                preset_key = coalesce(excluded.preset_key, pipeline_runs.preset_key),
                input_root = coalesce(excluded.input_root, pipeline_runs.input_root),
                output_dir = excluded.output_dir,
                status = excluded.status,
                summary = excluded.summary,
                embedding_provider = coalesce(excluded.embedding_provider, pipeline_runs.embedding_provider),
                embedding_model = coalesce(excluded.embedding_model, pipeline_runs.embedding_model),
                llm_provider = coalesce(excluded.llm_provider, pipeline_runs.llm_provider),
                llm_model = coalesce(excluded.llm_model, pipeline_runs.llm_model),
                extraction_provider = coalesce(excluded.extraction_provider, pipeline_runs.extraction_provider),
                vector_store_provider = coalesce(excluded.vector_store_provider, pipeline_runs.vector_store_provider),
                vector_store_collection = coalesce(excluded.vector_store_collection, pipeline_runs.vector_store_collection),
                started_at = case
                    when excluded.status = 'running' then coalesce(pipeline_runs.started_at, now())
                    else pipeline_runs.started_at
                end,
                finished_at = case
                    when excluded.status in ('succeeded', 'failed', 'cancelled') then now()
                    else pipeline_runs.finished_at
                end,
                updated_at = now()
            returning id
            """,
            (
                run_key,
                preset_key,
                input_root,
                str(output_dir),
                status,
                json.dumps(summary, sort_keys=True),
                embedding_provider,
                embedding_model,
                llm_provider,
                llm_model,
                extraction_provider,
                vector_store_provider,
                vector_store_collection,
                status,
                status,
            ),
        ).fetchone()
        return str(row[0] if isinstance(row, tuple) else row["id"])

    def _upsert_provider_benchmark_run(
        self,
        connection: PostgresConnection,
        *,
        benchmark_key: str,
        output_dir: Path,
        status: str,
        partial: bool,
        summary: dict[str, Any],
        artifact_manifest: dict[str, Any],
        background_error: dict[str, Any],
    ) -> str:
        row = connection.execute(
            """
            insert into provider_benchmark_runs (
                benchmark_key, output_dir, status, partial, summary, artifact_manifest, background_error
            ) values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
            on conflict (benchmark_key) do update set
                output_dir = excluded.output_dir,
                status = excluded.status,
                partial = excluded.partial,
                summary = excluded.summary,
                artifact_manifest = excluded.artifact_manifest,
                background_error = excluded.background_error,
                updated_at = now()
            returning id
            """,
            (
                benchmark_key,
                str(output_dir),
                status,
                partial,
                json.dumps(summary, sort_keys=True),
                json.dumps(artifact_manifest or {}, sort_keys=True),
                json.dumps(background_error or {}, sort_keys=True),
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

    def _import_run_events(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "graph-audit-events.jsonl")
        connection.execute("delete from pipeline_run_events where run_id = %s", (run_id,))
        for row in rows:
            payload = {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "run_id",
                    "source_path",
                    "relative_path",
                    "node",
                    "status",
                    "summary",
                    "message",
                    "timestamp",
                }
            }
            connection.execute(
                """
                insert into pipeline_run_events (
                    run_id, source_path, relative_path, node, status, message, payload, created_at
                ) values (%s, %s, %s, %s, %s, %s, %s::jsonb, coalesce(%s::timestamptz, now()))
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("node"),
                    row.get("status") or "unknown",
                    row.get("message") or row.get("summary"),
                    json.dumps(payload, sort_keys=True),
                    row.get("timestamp"),
                ),
            )
        return len(rows)

    def _import_provider_benchmark_results(self, connection: PostgresConnection, benchmark_run_id: str, rows: list[dict[str, Any]]) -> int:
        connection.execute("delete from provider_benchmark_results where benchmark_run_id = %s", (benchmark_run_id,))
        for row in rows:
            connection.execute(
                """
                insert into provider_benchmark_results (
                    benchmark_run_id, source_path, relative_path, sample_category, sample_label,
                    provider, status, quality, requires_review, seconds, result
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    benchmark_run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("sample_category"),
                    row.get("sample_label"),
                    row.get("provider") or "unknown",
                    row.get("status") or "unknown",
                    row.get("quality"),
                    row.get("requires_review"),
                    row.get("seconds"),
                    json.dumps(row, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_provider_benchmark_parser_results(self, connection: PostgresConnection, benchmark_run_id: str, rows: list[dict[str, Any]]) -> int:
        connection.execute("delete from provider_benchmark_parser_results where benchmark_run_id = %s", (benchmark_run_id,))
        for row in rows:
            connection.execute(
                """
                insert into provider_benchmark_parser_results (
                    benchmark_run_id, source_path, relative_path, sample_category, sample_label,
                    provider, status, quality, requires_review, seconds, text_length, page_count, result
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    benchmark_run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("sample_category"),
                    row.get("sample_label"),
                    row.get("provider") or row.get("parser_provider") or "unknown",
                    row.get("status") or "unknown",
                    row.get("quality"),
                    row.get("requires_review"),
                    row.get("seconds"),
                    row.get("text_length"),
                    row.get("page_count"),
                    json.dumps(row, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_provider_benchmark_recommendations(self, connection: PostgresConnection, benchmark_run_id: str, rows: list[dict[str, Any]]) -> int:
        connection.execute("delete from provider_benchmark_recommendations where benchmark_run_id = %s", (benchmark_run_id,))
        for row in rows:
            connection.execute(
                """
                insert into provider_benchmark_recommendations (
                    benchmark_run_id, provider, recommendation, status, average_seconds, result
                ) values (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    benchmark_run_id,
                    row.get("provider") or "unknown",
                    row.get("recommendation"),
                    row.get("status"),
                    row.get("average_seconds") or row.get("avg_seconds"),
                    json.dumps(row, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_model_usage(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-model-usage.jsonl")
        connection.execute("delete from model_usage where run_id = %s", (run_id,))
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if row.get("host") and not metadata.get("host"):
                metadata = {**metadata, "host": row.get("host")}
            connection.execute(
                """
                insert into model_usage (
                    run_id, source_path, relative_path, node, purpose, provider, model, host, status,
                    call_count, input_tokens, output_tokens, total_tokens, runtime_ms, local_only, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("node") or "unknown",
                    row.get("purpose") or "unknown",
                    row.get("provider") or "unknown",
                    row.get("model") or "unknown",
                    row.get("host") or metadata.get("host"),
                    row.get("status") or "unknown",
                    _call_count(row),
                    row.get("input_tokens"),
                    row.get("output_tokens"),
                    row.get("total_tokens"),
                    row.get("runtime_ms"),
                    _model_usage_local_only(row),
                    json.dumps(metadata, sort_keys=True),
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

    def _import_provider_selections(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-provider-selections.jsonl")
        connection.execute("delete from pipeline_provider_selections where run_id = %s", (run_id,))
        for row in rows:
            metadata = {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "source_path",
                    "relative_path",
                    "selected_provider",
                    "preferred_provider",
                    "configured_provider",
                    "provider_chain",
                    "skipped_providers",
                    "provider_selection_reason",
                }
            }
            connection.execute(
                """
                insert into pipeline_provider_selections (
                    run_id, source_path, relative_path, selected_provider, preferred_provider,
                    configured_provider, provider_chain, skipped_providers, provider_selection_reason, metadata
                ) values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("selected_provider") or "unknown",
                    row.get("preferred_provider"),
                    row.get("configured_provider"),
                    json.dumps(row.get("provider_chain") or []),
                    json.dumps(row.get("skipped_providers") or []),
                    row.get("provider_selection_reason"),
                    json.dumps(metadata, sort_keys=True),
                ),
            )
        return len(rows)

    def _import_quality_checks(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        artifacts = [
            ("extraction_validation", output_path / "sample-extraction-validations.jsonl"),
            ("extraction_repair", output_path / "sample-extraction-repairs.jsonl"),
            ("quality_gate", output_path / "sample-quality-gates.jsonl"),
            ("chunking_result", output_path / "sample-chunking-results.jsonl"),
        ]
        connection.execute("delete from pipeline_quality_checks where run_id = %s", (run_id,))
        imported = 0
        for check_type, path in artifacts:
            for row in _read_jsonl(path):
                connection.execute(
                    """
                    insert into pipeline_quality_checks (
                        run_id, source_path, relative_path, check_type, status, quality,
                        requires_review, can_chunk, can_embed, provider, strategy, reason, warnings, result
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        run_id,
                        row.get("source_path"),
                        row.get("relative_path"),
                        check_type,
                        row.get("status") or row.get("repair_status") or row.get("chunking_status"),
                        row.get("quality"),
                        _optional_bool(row.get("requires_review")),
                        _optional_bool(row.get("can_chunk")),
                        _optional_bool(row.get("can_embed")),
                        row.get("provider"),
                        row.get("strategy"),
                        row.get("reason") or row.get("validation_reason") or row.get("review_reason"),
                        json.dumps(row.get("warnings") or []),
                        json.dumps(row, sort_keys=True),
                    ),
                )
                imported += 1
        return imported

    def _import_tagging_evidence(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        artifacts = [
            ("retrieval_result", output_path / "sample-retrieval-results.jsonl"),
            ("semantic_example", output_path / "sample-semantic-examples.jsonl"),
            ("llm_tag_inspection_result", output_path / "sample-llm-tag-inspection-results.jsonl"),
            ("llm_tag_inspection", output_path / "sample-llm-tag-inspections.jsonl"),
            ("tag_candidate", output_path / "sample-tag-candidates.jsonl"),
            ("confidence_calibration", output_path / "sample-confidence-calibrations.jsonl"),
            ("placement_proposal", output_path / "sample-placement-proposals.jsonl"),
            ("route_decision", output_path / "sample-route-decisions.jsonl"),
        ]
        connection.execute("delete from pipeline_tagging_evidence where run_id = %s", (run_id,))
        imported = 0
        for evidence_type, path in artifacts:
            for row in _read_jsonl(path):
                normalized = _tagging_evidence_row(evidence_type, row)
                connection.execute(
                    """
                    insert into pipeline_tagging_evidence (
                        run_id, source_path, relative_path, evidence_type, status, provider, model,
                        primary_tag, confidence, assignment_source, route_status, review_reason,
                        placement_status, destination_path, warnings, evidence, result
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    """,
                    (
                        run_id,
                        normalized["source_path"],
                        normalized["relative_path"],
                        evidence_type,
                        normalized["status"],
                        normalized["provider"],
                        normalized["model"],
                        normalized["primary_tag"],
                        normalized["confidence"],
                        normalized["assignment_source"],
                        normalized["route_status"],
                        normalized["review_reason"],
                        normalized["placement_status"],
                        normalized["destination_path"],
                        json.dumps(normalized["warnings"]),
                        json.dumps(normalized["evidence"]),
                        json.dumps(row, sort_keys=True),
                    ),
                )
                imported += 1
        return imported

    def _import_file_metadata(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        artifacts = [
            ("source_identity", output_path / "sample-source-identity.jsonl"),
            ("file_probe", output_path / "sample-file-probes.jsonl"),
            ("sample_input", output_path / "sample-inputs.jsonl"),
            ("document_structure", output_path / "sample-structure.jsonl"),
            ("import_result", output_path / "sample-import-results.jsonl"),
        ]
        connection.execute("delete from pipeline_file_metadata where run_id = %s", (run_id,))
        imported = 0
        for metadata_type, path in artifacts:
            for row in _read_jsonl(path):
                normalized = _file_metadata_row(metadata_type, row)
                connection.execute(
                    """
                    insert into pipeline_file_metadata (
                        run_id, source_path, relative_path, sample_path, metadata_type, file_id,
                        content_sha256, size_bytes, extension, mime_type, media_type, status,
                        provider, page_count, text_length, sample_group, sample_number, final_class,
                        extraction_strategy, import_status, warnings, result
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        run_id,
                        normalized["source_path"],
                        normalized["relative_path"],
                        normalized["sample_path"],
                        metadata_type,
                        normalized["file_id"],
                        normalized["content_sha256"],
                        normalized["size_bytes"],
                        normalized["extension"],
                        normalized["mime_type"],
                        normalized["media_type"],
                        normalized["status"],
                        normalized["provider"],
                        normalized["page_count"],
                        normalized["text_length"],
                        normalized["sample_group"],
                        normalized["sample_number"],
                        normalized["final_class"],
                        normalized["extraction_strategy"],
                        normalized["import_status"],
                        json.dumps(normalized["warnings"]),
                        json.dumps(row, sort_keys=True),
                    ),
                )
                imported += 1
        return imported

    def _import_pipeline_artifacts(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        manifest = _read_json(output_path / "artifact-manifest.json")
        rows = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []
        connection.execute("delete from pipeline_artifacts where run_id = %s", (run_id,))
        imported = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            connection.execute(
                """
                insert into pipeline_artifacts (
                    run_id, name, path, kind, exists, size_bytes, row_count, sha256, note, result
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                on conflict (run_id, name) do update set
                    path = excluded.path,
                    kind = excluded.kind,
                    exists = excluded.exists,
                    size_bytes = excluded.size_bytes,
                    row_count = excluded.row_count,
                    sha256 = excluded.sha256,
                    note = excluded.note,
                    result = excluded.result
                """,
                (
                    run_id,
                    row.get("name"),
                    row.get("path"),
                    row.get("kind"),
                    bool(row.get("exists")),
                    row.get("size_bytes"),
                    row.get("row_count"),
                    row.get("sha256"),
                    row.get("note"),
                    json.dumps(row, sort_keys=True),
                ),
            )
            imported += 1
        return imported

    def _import_parser_results(self, connection: PostgresConnection, run_id: str, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-parser-results.jsonl")
        connection.execute("delete from pipeline_parser_results where run_id = %s", (run_id,))
        for row in rows:
            connection.execute(
                """
                insert into pipeline_parser_results (
                    run_id, source_path, relative_path, sample_path, sample_group, sample_number,
                    provider, status, quality, requires_review, strategy, document_subtype,
                    review_reason, text_length, page_count, page_structure_available,
                    page_text_coverage_rate, layout_signal_count, result
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    row.get("source_path"),
                    row.get("relative_path"),
                    row.get("sample_path"),
                    row.get("sample_group") or row.get("sample_category"),
                    row.get("sample_number"),
                    row.get("provider") or row.get("parser_provider") or "unknown",
                    row.get("status") or "unknown",
                    row.get("quality"),
                    row.get("requires_review"),
                    row.get("strategy"),
                    row.get("document_subtype"),
                    row.get("review_reason"),
                    row.get("text_length"),
                    row.get("page_count"),
                    row.get("page_structure_available"),
                    row.get("page_text_coverage_rate"),
                    row.get("layout_signal_count"),
                    json.dumps(row, sort_keys=True),
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
    provider_selection_rows = _read_jsonl(output_path / "sample-provider-selections.jsonl")
    quality_check_rows = [
        *_read_jsonl(output_path / "sample-extraction-validations.jsonl"),
        *_read_jsonl(output_path / "sample-extraction-repairs.jsonl"),
        *_read_jsonl(output_path / "sample-quality-gates.jsonl"),
        *_read_jsonl(output_path / "sample-chunking-results.jsonl"),
    ]
    tagging_evidence_rows = [
        *_read_jsonl(output_path / "sample-retrieval-results.jsonl"),
        *_read_jsonl(output_path / "sample-semantic-examples.jsonl"),
        *_read_jsonl(output_path / "sample-llm-tag-inspection-results.jsonl"),
        *_read_jsonl(output_path / "sample-llm-tag-inspections.jsonl"),
        *_read_jsonl(output_path / "sample-tag-candidates.jsonl"),
        *_read_jsonl(output_path / "sample-confidence-calibrations.jsonl"),
        *_read_jsonl(output_path / "sample-placement-proposals.jsonl"),
        *_read_jsonl(output_path / "sample-route-decisions.jsonl"),
    ]
    file_metadata_rows = [
        *_read_jsonl(output_path / "sample-source-identity.jsonl"),
        *_read_jsonl(output_path / "sample-file-probes.jsonl"),
        *_read_jsonl(output_path / "sample-inputs.jsonl"),
        *_read_jsonl(output_path / "sample-structure.jsonl"),
        *_read_jsonl(output_path / "sample-import-results.jsonl"),
    ]
    parser_result_rows = _read_jsonl(output_path / "sample-parser-results.jsonl")
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
            "provider_selections": len(provider_selection_rows),
            "quality_checks": len(quality_check_rows),
            "tagging_evidence": len(tagging_evidence_rows),
            "file_metadata": len(file_metadata_rows),
            "artifacts": len(manifest.get("artifacts") or []) if isinstance(manifest.get("artifacts"), list) else 0,
            "parser_results": len(parser_result_rows),
            "indexing": len(indexing_rows),
        },
        "distributions": {
            "route_status": _count_values(result_rows, "route_status"),
            "quality": _count_values(result_rows, "quality"),
            "final_class": _count_values(result_rows, "final_class"),
            "parser_status": _count_values(parser_result_rows, "status"),
            "parser_quality": _count_values(parser_result_rows, "quality"),
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


def _provider_benchmark_partial_summary(
    results: list[dict[str, Any]],
    parser_results: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "partial": True,
        "result_count": len(results),
        "parser_result_count": len(parser_results),
        "recommendation_count": len(recommendations),
        "by_provider": _count_values(results, "provider"),
        "by_status": _count_values(results, "status"),
        "by_quality": _count_values(results, "quality"),
        "sample_category": _count_values(results, "sample_category"),
    }


def _provider_benchmark_detail_summary(
    *,
    result_rows: list[dict[str, Any]],
    parser_result_rows: list[dict[str, Any]],
    recommendation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "result_count": len(result_rows),
        "parser_result_count": len(parser_result_rows),
        "recommendation_count": len(recommendation_rows),
        "result_status": _count_values(result_rows, "status"),
        "result_quality": _count_values(result_rows, "quality"),
        "parser_status": _count_values(parser_result_rows, "status"),
        "parser_quality": _count_values(parser_result_rows, "quality"),
        "providers": _count_values(result_rows + parser_result_rows, "provider"),
        "sample_categories": _count_values(result_rows + parser_result_rows, "sample_category"),
        "recommendations": _count_values(recommendation_rows, "recommendation"),
        "review_required_count": sum(1 for row in result_rows + parser_result_rows if row.get("requires_review") is True),
        "segmentation": _provider_benchmark_segmentation_summary(result_rows + parser_result_rows),
    }


def _provider_benchmark_segmentation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_rows = [row for row in rows if _provider_benchmark_row_value(row, "segmentation_required") is True]
    ready_rows = [row for row in required_rows if _provider_benchmark_row_value(row, "segmentation_readiness") == "ready_for_review"]
    return {
        "required_count": len(required_rows),
        "ready_for_review_count": len(ready_rows),
        "ready_for_review_rate": round(len(ready_rows) / len(required_rows), 4) if required_rows else 0.0,
        "by_readiness": _count_provider_benchmark_values(rows, "segmentation_readiness"),
    }


def _count_provider_benchmark_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(_provider_benchmark_row_value(row, field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _provider_benchmark_row_value(row: dict[str, Any], field: str) -> Any:
    if field in row:
        return row.get(field)
    result = row.get("result")
    if isinstance(result, dict):
        return result.get(field)
    return None


def _provider_benchmark_recommendation_result(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result = row.get("result")
    return result if isinstance(result, dict) else {}


def _provider_benchmark_recommendation_status(row: dict[str, Any]) -> str:
    result = _provider_benchmark_recommendation_result(row)
    return str(row.get("promotion_status") or row.get("status") or row.get("recommendation") or result.get("promotion_status") or "needs_review")


def _provider_benchmark_recommendation_reason(row: dict[str, Any]) -> str:
    result = _provider_benchmark_recommendation_result(row)
    return str(row.get("promotion_reason") or row.get("reason") or result.get("promotion_reason") or result.get("reason") or "")


def _provider_benchmark_next_steps(*, provider: str | None, blockers: list[dict[str, Any]]) -> list[str]:
    if provider:
        return [
            f"Set SUNSHINE_OCR_PARSER_PROVIDER={provider} in the local runtime environment.",
            f"Set SUNSHINE_TEXT_PARSER_PROVIDER={provider} only after born-digital/text-heavy samples are benchmarked.",
            "Rerun golden-label evals and a sliced QA batch before promoting the provider for broad production runs.",
        ]
    if blockers:
        return [
            "Resolve blocker rows or review benchmark output before changing parser provider configuration.",
            "Rerun provider benchmarks with representative scrapbook, newspaper, financial, and normal document samples.",
        ]
    return ["Import provider benchmark recommendations before changing parser provider configuration."]


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


def _count_bool_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        key = "true" if value is True else ("false" if value is False else "unknown")
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


def _postgres_count_rows(connection: PostgresConnection, query: str) -> dict[str, int]:
    rows = connection.execute(query).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            key = row.get("key")
            count = row.get("count")
        elif isinstance(row, tuple):
            key, count = row
        else:
            row_dict = _row_to_dict(row)
            key = row_dict.get("key")
            count = row_dict.get("count")
        counts[str(key or "unknown")] = _int_value(count)
    return dict(sorted(counts.items()))


def _postgres_jsonb_array_count_rows(connection: PostgresConnection, table: str, column: str) -> dict[str, int]:
    rows = connection.execute(
        f"""
        select value as key, count(*) as count
        from {table}, jsonb_array_elements_text({column}) as value
        group by value
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, tuple):
            key, count = row
        else:
            row_dict = _row_to_dict(row)
            key = row_dict.get("key")
            count = row_dict.get("count")
        counts[str(key or "unknown")] = _int_value(count)
    return dict(sorted(counts.items()))


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


def _golden_label_select_sql(suffix: str) -> str:
    return f"""
        select
            gl.id,
            gl.review_item_id,
            gl.run_id,
            r.run_key,
            r.preset_key,
            gl.source_path,
            gl.relative_path,
            gl.sample_path,
            gl.segment_id,
            gl.extracted_text_snippet,
            gl.content_class,
            gl.correct_primary_tag,
            gl.correct_secondary_tags,
            gl.ocr_quality_label,
            gl.expected_review_required,
            gl.sensitive_record,
            gl.correct_destination_path,
            gl.correct_placement_year,
            gl.correct_privacy,
            gl.reviewer,
            gl.notes,
            gl.proposed_tag,
            gl.proposed_secondary_tags,
            gl.proposed_confidence,
            gl.reviewed_at,
            gl.created_at,
            gl.updated_at
        from golden_labels_v2 gl
        left join pipeline_runs r on r.id = gl.run_id
        {suffix}
        """


def _clean_json_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
        value = parsed
    if not isinstance(value, list):
        return []
    return sorted({str(tag).strip() for tag in value if str(tag).strip()})


def _postgres_file_search_item(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    source_path = str(row.get("source_path") or row.get("sample_path") or "")
    relative_path = str(row.get("relative_path") or source_path)
    filename = Path(relative_path or source_path).name
    extension = Path(filename).suffix.lower() or None
    secondary_tags = row.get("secondary_tags") if isinstance(row.get("secondary_tags"), list) else result.get("secondary_tags")
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    return {
        "id": row.get("id"),
        "source": "postgres",
        "filename": filename,
        "compact_path": _compact_postgres_path(relative_path),
        "source_path": source_path,
        "relative_path": relative_path,
        "sample_path": row.get("sample_path"),
        "extension": extension,
        "source_collection": _source_collection_postgres(relative_path, source_path),
        "content_class": row.get("final_class") or result.get("final_class"),
        "primary_tag": row.get("top_tag_candidate") or result.get("top_tag_candidate"),
        "secondary_tags": secondary_tags if isinstance(secondary_tags, list) else [],
        "route_status": row.get("route_status") or result.get("route_status"),
        "quality": row.get("quality") or result.get("quality"),
        "review_status": row.get("review_status"),
        "placement_status": result.get("placement_status"),
        "text_snippet": _short_postgres_text(result.get("extraction_text_snippet") or result.get("text") or ""),
        "warnings": warnings,
        "latest_run_id": row.get("run_id"),
        "latest_run_key": row.get("run_key"),
        "latest_run_preset_key": row.get("preset_key"),
        "latest_embedding_provider": row.get("embedding_provider"),
        "latest_enable_llm_tags": bool(row.get("llm_provider")) if row.get("llm_provider") is not None else None,
        "latest_llm_tag_provider": row.get("llm_provider"),
        "latest_ocr_fallback_provider": row.get("extraction_provider"),
        "updated_at": row.get("updated_at") or row.get("created_at"),
    }


def _filter_postgres_files(rows: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
    result = rows
    q = str(filters.get("q") or "").strip().lower()
    if q:
        result = [
            row
            for row in result
            if q in " ".join(str(row.get(key) or "") for key in ("filename", "relative_path", "source_path", "text_snippet")).lower()
        ]
    for filter_key, row_key in {
        "source_collection": "source_collection",
        "content_class": "content_class",
        "primary_tag": "primary_tag",
        "route_status": "route_status",
        "review_status": "review_status",
        "ocr_quality": "quality",
        "placement_status": "placement_status",
    }.items():
        value = filters.get(filter_key)
        if value:
            result = [row for row in result if str(row.get(row_key) or "") == str(value)]
    extension = filters.get("extension")
    if extension:
        normalized = str(extension).lower()
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        result = [row for row in result if row.get("extension") == normalized]
    secondary_tag = filters.get("secondary_tag")
    if secondary_tag:
        result = [row for row in result if str(secondary_tag) in set(map(str, row.get("secondary_tags") or []))]
    warning_type = filters.get("warning_type")
    if warning_type:
        result = [row for row in result if str(warning_type) in set(map(str, row.get("warnings") or []))]
    run_id = filters.get("run_id")
    if run_id:
        result = [row for row in result if str(row.get("latest_run_id") or "") == str(run_id)]
    return result


def _dedupe_postgres_file_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest row for each source file while preserving query order."""

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("source_path") or row.get("relative_path") or row.get("id") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _sort_postgres_files(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "updated_asc":
        return sorted(rows, key=lambda row: str(row.get("updated_at") or ""))
    if sort == "filename":
        return sorted(rows, key=lambda row: str(row.get("filename") or "").lower())
    if sort == "primary_tag":
        return sorted(rows, key=lambda row: (str(row.get("primary_tag") or ""), str(row.get("filename") or "")))
    if sort == "quality":
        return sorted(rows, key=lambda row: (str(row.get("quality") or ""), str(row.get("filename") or "")))
    return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)


def _facet_count_postgres(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _facet_array_count_postgres(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        values = row.get(key)
        if not isinstance(values, list) or not values:
            counts["none"] = counts.get("none", 0) + 1
            continue
        for value in values:
            text = str(value or "unknown")
            counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def _compact_postgres_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) <= 3:
        return path
    return "/".join([parts[0], "...", parts[-2], parts[-1]])


def _short_postgres_text(value: Any, limit: int = 240) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _source_collection_postgres(relative_path: str, source_path: str) -> str:
    text = f"{relative_path} {source_path}"
    if "_manifest/" in text or "/_manifest/" in text:
        return "manifest"
    if "Sunshine shared folders/" in text:
        return "sunshine_shared_folders"
    if "archive-2026-05-25/" in text:
        return "archive"
    if "google-drive-delta-2026-05-25/" in text:
        return "google_drive_delta"
    if "Paige Agent Sunshine Files/" in text:
        return "paige_agent_files"
    if "From Mac Sunshine Pass 2026-05-25/" in text:
        return "from_mac_pass"
    return "other"


def _run_report_summary(
    *,
    results: list[dict[str, Any]],
    review_items: list[dict[str, Any]],
    model_usage: list[dict[str, Any]],
    provider_attempts: list[dict[str, Any]],
    provider_selections: list[dict[str, Any]],
    quality_checks: list[dict[str, Any]],
    tagging_evidence: list[dict[str, Any]],
    file_metadata: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    parser_results: list[dict[str, Any]],
    document_segments: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    chunk_embeddings: list[dict[str, Any]],
    run_events: list[dict[str, Any]],
) -> dict[str, Any]:
    model_call_count = sum(_int_value(row.get("call_count"), default=1) for row in model_usage)
    semantic_embedding_count = sum(1 for row in chunk_embeddings if row.get("semantic_quality") is True)
    return {
        "result_count": len(results),
        "review_item_count": len(review_items),
        "open_review_item_count": sum(1 for row in review_items if row.get("status") == "open"),
        "model_usage_count": len(model_usage),
        "model_call_count": model_call_count,
        "local_model_call_count": sum(_int_value(row.get("call_count"), default=1) for row in model_usage if row.get("local_only") is True),
        "nonlocal_model_call_count": sum(_int_value(row.get("call_count"), default=1) for row in model_usage if row.get("local_only") is False),
        "provider_attempt_count": len(provider_attempts),
        "provider_selection_count": len(provider_selections),
        "quality_check_count": len(quality_checks),
        "quality_review_required_count": sum(1 for row in quality_checks if row.get("requires_review") is True),
        "tagging_evidence_count": len(tagging_evidence),
        "file_metadata_count": len(file_metadata),
        "artifact_count": len(artifacts),
        "existing_artifact_count": sum(1 for row in artifacts if row.get("exists") is True),
        "missing_artifact_count": sum(1 for row in artifacts if row.get("exists") is False),
        "artifact_total_size_bytes": sum(_int_value(row.get("size_bytes")) for row in artifacts),
        "parser_result_count": len(parser_results),
        "parser_review_required_count": sum(1 for row in parser_results if row.get("requires_review") is True),
        "run_event_count": len(run_events),
        "failed_run_event_count": sum(1 for row in run_events if row.get("status") == "failed"),
        "document_segment_count": len(document_segments),
        "segment_review_count": sum(1 for row in document_segments if row.get("requires_segment_review") is True),
        "chunk_count": len(chunks),
        "chunk_embedding_count": len(chunk_embeddings),
        "semantic_embedding_count": semantic_embedding_count,
        "placeholder_embedding_count": len(chunk_embeddings) - semantic_embedding_count,
        "route_status": _count_values(results, "route_status"),
        "quality": _count_values(results, "quality"),
        "primary_tag": _count_values(results, "top_tag_candidate"),
        "segment_type": _count_values(document_segments, "segment_type"),
        "chunk_kind": _count_values(chunks, "chunk_kind"),
        "embedding_provider": _count_values(chunk_embeddings, "embedding_provider"),
        "embedding_status": _count_values(chunk_embeddings, "embedding_status"),
        "embedding_model": _count_values(chunk_embeddings, "embedding_model"),
        "provider_attempt_status": _count_values(provider_attempts, "status"),
        "selected_provider": _count_values(provider_selections, "selected_provider"),
        "provider_selection_reason": _count_values(provider_selections, "provider_selection_reason"),
        "quality_check_type": _count_values(quality_checks, "check_type"),
        "quality_check_status": _count_values(quality_checks, "status"),
        "quality_check_quality": _count_values(quality_checks, "quality"),
        "tagging_evidence_type": _count_values(tagging_evidence, "evidence_type"),
        "tagging_primary_tag": _count_values(tagging_evidence, "primary_tag"),
        "tagging_assignment_source": _count_values(tagging_evidence, "assignment_source"),
        "tagging_route_status": _count_values(tagging_evidence, "route_status"),
        "tagging_placement_status": _count_values(tagging_evidence, "placement_status"),
        "file_metadata_type": _count_values(file_metadata, "metadata_type"),
        "file_media_type": _count_values(file_metadata, "media_type"),
        "file_probe_status": _count_values([row for row in file_metadata if row.get("metadata_type") == "file_probe"], "status"),
        "import_status": _count_values([row for row in file_metadata if row.get("metadata_type") == "import_result"], "import_status"),
        "artifact_kind": _count_values(artifacts, "kind"),
        "artifact_exists": _count_bool_values(artifacts, "exists"),
        "parser_status": _count_values(parser_results, "status"),
        "parser_quality": _count_values(parser_results, "quality"),
        "parser_provider": _count_values(parser_results, "provider"),
        "run_event_status": _count_values(run_events, "status"),
        "model_provider": _count_values(model_usage, "provider"),
    }


def _int_value(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _tagging_evidence_row(evidence_type: str, row: dict[str, Any]) -> dict[str, Any]:
    proposal = row.get("proposal") if isinstance(row.get("proposal"), dict) else {}
    return {
        "source_path": row.get("source_path") or row.get("sample_path"),
        "relative_path": row.get("relative_path"),
        "status": row.get("status") or row.get("llm_status") or row.get("route_status") or proposal.get("placement_status"),
        "provider": row.get("provider") or row.get("retrieval_provider") or row.get("llm_provider"),
        "model": row.get("model") or row.get("llm_model"),
        "primary_tag": _tagging_primary_tag(evidence_type, row, proposal),
        "confidence": _tagging_confidence(evidence_type, row),
        "assignment_source": row.get("assignment_source") or row.get("source") or row.get("tag_assignment_source"),
        "route_status": row.get("route_status"),
        "review_reason": row.get("review_reason") or row.get("llm_review_reason"),
        "placement_status": row.get("placement_status") or proposal.get("placement_status"),
        "destination_path": row.get("destination_path") or proposal.get("destination_path"),
        "warnings": row.get("warnings") if isinstance(row.get("warnings"), list) else [],
        "evidence": row.get("evidence") if isinstance(row.get("evidence"), list) else [],
    }


def _tagging_primary_tag(evidence_type: str, row: dict[str, Any], proposal: dict[str, Any]) -> str | None:
    if evidence_type == "semantic_example":
        return row.get("correct_primary_tag")
    return row.get("tag") or row.get("primary_tag") or row.get("top_tag") or row.get("llm_primary_tag") or proposal.get("primary_tag")


def _tagging_confidence(evidence_type: str, row: dict[str, Any]) -> Any:
    if evidence_type == "confidence_calibration":
        return row.get("calibrated_confidence")
    return row.get("confidence") or row.get("score") or row.get("tag_confidence") or row.get("llm_confidence")


def _file_metadata_row(metadata_type: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": row.get("source_path") or row.get("sample_path"),
        "relative_path": row.get("relative_path"),
        "sample_path": row.get("sample_path"),
        "file_id": row.get("file_id"),
        "content_sha256": row.get("content_sha256"),
        "size_bytes": row.get("size_bytes"),
        "extension": row.get("extension"),
        "mime_type": row.get("mime_type"),
        "media_type": row.get("media_type"),
        "status": row.get("status"),
        "provider": row.get("provider"),
        "page_count": row.get("page_count"),
        "text_length": row.get("text_length"),
        "sample_group": row.get("sample_group"),
        "sample_number": row.get("sample_number"),
        "final_class": row.get("final_class"),
        "extraction_strategy": row.get("extraction_strategy"),
        "import_status": (row.get("import_status") or row.get("status")) if metadata_type == "import_result" else None,
        "warnings": row.get("warnings") if isinstance(row.get("warnings"), list) else [],
    }


def _call_count(row: dict[str, Any]) -> int:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    try:
        return max(0, int(metadata.get("call_count", 1)))
    except (TypeError, ValueError):
        return 1


def _model_usage_report_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {**row, "host": row.get("host") or metadata.get("host")}


def _model_usage_local_only(row: dict[str, Any]) -> bool:
    if isinstance(row.get("local_only"), bool):
        return bool(row["local_only"])
    cost_basis = str(row.get("cost_basis") or "").strip().lower()
    if cost_basis == "external":
        return False
    provider = str(row.get("provider") or "").strip().lower()
    return provider not in {"openai", "gemini", "google", "anthropic"}


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
        f"segment={row.get('segment_id')}" if row.get("segment_id") else None,
        f"pages={row.get('page_start')}-{row.get('page_end')}" if row.get("page_start") or row.get("page_end") else None,
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


def _segment_review_status(decision: str) -> str:
    normalized = (decision or "").strip().lower()
    if normalized == "accept":
        return "accepted"
    if normalized == "reject":
        return "rejected"
    if normalized == "defer":
        return "deferred"
    if normalized in {"split", "merge", "change"}:
        return "changed"
    return "open"


def _append_note(existing: Any, note: str | None) -> str | None:
    existing_text = str(existing).strip() if existing else ""
    note_text = str(note).strip() if note else ""
    if existing_text and note_text:
        return f"{existing_text}\n{note_text}"
    return existing_text or note_text or None
