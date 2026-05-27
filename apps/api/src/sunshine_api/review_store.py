"""SQLite-backed persistence for dashboard review, file, and run state.

``ReviewStore`` owns the local review database schema and the query/update
methods used by API routers. It currently includes review queue operations,
golden labels, file browser indexes, pipeline run metadata, run events, and
model usage records.
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import shutil
import sqlite3
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sunshine_extraction.sample_pipeline import DEFAULT_TAXONOMY_PATH, load_taxonomy_options


DEFAULT_REVIEW_DB_PATH = ".local/sunshine-review.sqlite"


class ReviewStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("SUNSHINE_REVIEW_DB_PATH", DEFAULT_REVIEW_DB_PATH))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def import_langgraph_output(
        self,
        output_dir: str | Path,
        *,
        sample_routed_per_bucket: int = 0,
        sample_seed: int = 20260526,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        output_path = Path(output_dir)
        results_path = output_path / "sample-pipeline-results.jsonl"
        if not results_path.exists():
            raise FileNotFoundError(f"Missing {results_path}")

        results = _read_jsonl(results_path)
        extraction_by_source = {
            row.get("source_path"): row
            for row in _read_jsonl(output_path / "sample-extraction-results.jsonl")
            if row.get("source_path")
        }
        review_by_source = {
            row.get("source_path"): row
            for row in _read_jsonl(output_path / "sample-review-queue.jsonl")
            if row.get("source_path")
        }
        imported_results = 0
        imported_review_items = 0
        imported_sample_items = 0
        sampled_sources = _sample_routed_sources(results, per_bucket=sample_routed_per_bucket, seed=sample_seed)
        with self._connect() as connection:
            run_snapshot = _run_snapshot(connection, run_id)
            for result in results:
                source_path = str(result.get("source_path") or result.get("sample_path") or "")
                if not source_path:
                    continue
                relative_path = str(result.get("relative_path") or "")
                route_status = str(result.get("route_status") or "unknown")
                secondary_tags_json = json.dumps(result.get("secondary_tags", []), sort_keys=True)
                extraction_text_snippet = _extraction_text_snippet(extraction_by_source.get(source_path))
                if "ocr_evidence" not in result:
                    result = {**result, "ocr_evidence": _ocr_evidence_from_result(result, extraction_text_snippet)}
                review_row = review_by_source.get(source_path)
                review_reason = str(
                    (review_row or {}).get("review_reason")
                    or result.get("review_reason")
                    or ("route_candidate" if route_status == "route_candidate" else "review_required")
                )
                connection.execute(
                    """
                    insert into pipeline_results (
                        source_path, relative_path, sample_path, output_dir, route_status, review_reason,
                        final_class, extraction_strategy, extraction_status, quality, top_tag_candidate,
                        secondary_tags_json, extraction_text_snippet, tag_confidence, llm_status, warnings_json, result_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(source_path) do update set
                        relative_path=excluded.relative_path,
                        sample_path=excluded.sample_path,
                        output_dir=excluded.output_dir,
                        route_status=excluded.route_status,
                        review_reason=excluded.review_reason,
                        final_class=excluded.final_class,
                        extraction_strategy=excluded.extraction_strategy,
                        extraction_status=excluded.extraction_status,
                        quality=excluded.quality,
                        top_tag_candidate=excluded.top_tag_candidate,
                        secondary_tags_json=excluded.secondary_tags_json,
                        extraction_text_snippet=excluded.extraction_text_snippet,
                        tag_confidence=excluded.tag_confidence,
                        llm_status=excluded.llm_status,
                        warnings_json=excluded.warnings_json,
                        result_json=excluded.result_json,
                        imported_at=datetime('now')
                    """,
                    (
                        source_path,
                        relative_path,
                        result.get("sample_path"),
                        str(output_path),
                        route_status,
                        review_reason,
                        result.get("final_class"),
                        result.get("extraction_strategy"),
                        result.get("extraction_status"),
                        result.get("quality"),
                        result.get("top_tag_candidate"),
                        secondary_tags_json,
                        extraction_text_snippet,
                        result.get("tag_confidence"),
                        result.get("llm_status"),
                        json.dumps(result.get("warnings", []), sort_keys=True),
                        json.dumps(result, sort_keys=True),
                    ),
                )
                imported_results += 1
                self._upsert_file_index_from_result(connection, result, output_path, extraction_text_snippet, run_id=run_id)
                is_routed_sample = source_path in sampled_sources
                if route_status != "route_candidate" or is_routed_sample:
                    item_review_reason = review_reason
                    item_route_status = route_status
                    if is_routed_sample and route_status == "route_candidate":
                        item_review_reason = "qa_random_route_candidate_sample"
                    connection.execute(
                        """
                        insert into review_items (
                            source_path, relative_path, route_status, review_reason, status,
                            proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json, ocr_quality_label
                            , run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags
                        ) values (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        on conflict(source_path) do update set
                            relative_path=excluded.relative_path,
                            route_status=excluded.route_status,
                            review_reason=excluded.review_reason,
                            proposed_class=excluded.proposed_class,
                            proposed_tag=excluded.proposed_tag,
                            secondary_tags_json=excluded.secondary_tags_json,
                            extraction_text_snippet=excluded.extraction_text_snippet,
                            confidence=excluded.confidence,
                            warnings_json=excluded.warnings_json,
                            result_json=excluded.result_json,
                            ocr_quality_label=coalesce(review_items.ocr_quality_label, excluded.ocr_quality_label),
                            run_id=excluded.run_id,
                            run_key=excluded.run_key,
                            run_preset_key=excluded.run_preset_key,
                            embedding_provider=excluded.embedding_provider,
                            llm_tag_provider=excluded.llm_tag_provider,
                            ocr_fallback_provider=excluded.ocr_fallback_provider,
                            enable_llm_tags=excluded.enable_llm_tags,
                            updated_at=datetime('now')
                        """,
                        (
                            source_path,
                            relative_path,
                            item_route_status,
                            item_review_reason,
                            result.get("final_class"),
                            result.get("top_tag_candidate"),
                            secondary_tags_json,
                            extraction_text_snippet,
                            result.get("tag_confidence"),
                            json.dumps(result.get("warnings", []), sort_keys=True),
                            json.dumps(result, sort_keys=True),
                            result.get("quality"),
                            run_snapshot.get("run_id"),
                            run_snapshot.get("run_key"),
                            run_snapshot.get("run_preset_key"),
                            run_snapshot.get("embedding_provider"),
                            run_snapshot.get("llm_tag_provider"),
                            run_snapshot.get("ocr_fallback_provider"),
                            run_snapshot.get("enable_llm_tags"),
                        ),
                    )
                    imported_review_items += 1
                    if is_routed_sample and route_status == "route_candidate":
                        imported_sample_items += 1
            imported_model_usage = self.import_model_usage_artifact(connection, run_id, output_path)
        return {
            "output_dir": str(output_path),
            "imported_results": imported_results,
            "imported_review_items": imported_review_items,
            "imported_sample_items": imported_sample_items,
            "imported_model_usage": imported_model_usage,
            "db_path": str(self.db_path),
        }

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            total_results = connection.execute("select count(*) from pipeline_results").fetchone()[0]
            total_review = connection.execute("select count(*) from review_items").fetchone()[0]
            total_golden_labels = connection.execute("select count(*) from golden_labels").fetchone()[0]
            by_status = _count_rows(connection, "select status, count(*) from review_items group by status")
            by_route = _count_rows(connection, "select route_status, count(*) from pipeline_results group by route_status")
            by_quality = _count_rows(connection, "select quality, count(*) from pipeline_results group by quality")
            by_primary_tag = _count_rows(
                connection,
                "select coalesce(top_tag_candidate, 'none'), count(*) from pipeline_results group by coalesce(top_tag_candidate, 'none')",
            )
            by_secondary_tag = _secondary_tag_counts(connection)
        return {
            "db_path": str(self.db_path),
            "total_results": total_results,
            "total_review_items": total_review,
            "total_golden_labels": total_golden_labels,
            "review_by_status": by_status,
            "results_by_route_status": by_route,
            "results_by_quality": by_quality,
            "results_by_primary_tag": by_primary_tag,
            "results_by_secondary_tag": by_secondary_tag,
        }

    def placement_report(self, *, limit: int = 100) -> dict[str, Any]:
        with self._connect() as connection:
            by_placement_status = _count_rows(
                connection,
                """
                select coalesce(json_extract(result_json, '$.placement_status'), 'unknown'), count(*)
                from pipeline_results
                group by coalesce(json_extract(result_json, '$.placement_status'), 'unknown')
                """,
            )
            by_privacy = _count_rows(
                connection,
                """
                select coalesce(json_extract(result_json, '$.default_privacy'), 'unknown'), count(*)
                from pipeline_results
                group by coalesce(json_extract(result_json, '$.default_privacy'), 'unknown')
                """,
            )
            corrected_placement = connection.execute(
                """
                select count(*) from review_items
                where correct_destination_path is not null
                   or correct_placement_year is not null
                   or correct_privacy is not null
                """
            ).fetchone()[0]
            missing_date_rows = connection.execute(
                """
                select id, source_path, relative_path, route_status, review_reason, status,
                       proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json,
                       run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                       ocr_quality_label, decision, correct_class, correct_tag, correct_secondary_tags_json, correct_destination_path,
                       correct_placement_year, correct_privacy, review_stage, priority, assigned_reviewer, notes, created_at, updated_at
                from review_items
                where coalesce(json_extract(result_json, '$.placement_status'), '') in ('missing_date', 'needs_review', 'unresolved')
                   or coalesce(json_extract(result_json, '$.placement_date_confidence'), '') in ('low', 'missing', '0')
                   or correct_placement_year is null
                order by updated_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
            missing_date_queue = [
                _review_item_from_row(row, model_usage_summary=_review_item_model_usage_summary(connection, row))
                for row in missing_date_rows
            ]
        total = sum(by_placement_status.values())
        resolved = sum(count for status, count in by_placement_status.items() if status in {"resolved", "proposed", "ok"})
        return {
            "db_path": str(self.db_path),
            "total_results": total,
            "placement_resolution_rate": (resolved / total) if total else None,
            "corrected_placement_decisions": int(corrected_placement),
            "by_placement_status": by_placement_status,
            "by_privacy": by_privacy,
            "missing_date_queue": missing_date_queue,
        }

    def review_export_rows(self, *, status: str = "all", limit: int = 1000) -> list[dict[str, Any]]:
        return self.list_review_items(status=status, limit=limit)

    def list_review_items(
        self,
        *,
        status: str = "open",
        limit: int = 100,
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
        query = """
            select id, source_path, relative_path, route_status, review_reason, status,
                   proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json,
                   run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                   ocr_quality_label, decision, correct_class, correct_tag, correct_secondary_tags_json, correct_destination_path,
                   correct_placement_year, correct_privacy, review_stage, priority, assigned_reviewer, notes, created_at, updated_at
            from review_items
        """
        params: list[Any] = []
        predicates: list[str] = []
        if status != "all":
            predicates.append("status = ?")
            params.append(status)
        if q:
            predicates.append("(relative_path like ? or source_path like ? or extraction_text_snippet like ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        if route_status:
            predicates.append("route_status = ?")
            params.append(route_status)
        if review_reason:
            predicates.append("review_reason = ?")
            params.append(review_reason)
        if primary_tag:
            predicates.append("proposed_tag = ?")
            params.append(primary_tag)
        if secondary_tag:
            predicates.append("secondary_tags_json like ?")
            params.append(f"%{secondary_tag}%")
        if content_class:
            predicates.append("proposed_class = ?")
            params.append(content_class)
        if quality:
            predicates.append("json_extract(result_json, '$.quality') = ?")
            params.append(quality)
        if placement_status:
            predicates.append("json_extract(result_json, '$.placement_status') = ?")
            params.append(placement_status)
        confidence_predicate = _confidence_bucket_predicate(confidence_bucket)
        if confidence_predicate:
            predicates.append(confidence_predicate)
        if warning_type:
            predicates.append("warnings_json like ?")
            params.append(f"%{warning_type}%")
        if source_collection:
            collection_predicate = _source_collection_sql_predicate(source_collection)
            if collection_predicate:
                predicates.append(collection_predicate)
        if run_id is not None:
            predicates.append("run_id = ?")
            params.append(run_id)
        if run_preset_key:
            predicates.append("run_preset_key = ?")
            params.append(run_preset_key)
        if embedding_provider:
            predicates.append("embedding_provider = ?")
            params.append(embedding_provider)
        if llm_tag_provider:
            predicates.append("llm_tag_provider = ?")
            params.append(llm_tag_provider)
        if ocr_fallback_provider:
            predicates.append("ocr_fallback_provider = ?")
            params.append(ocr_fallback_provider)
        fallback_used_predicate = _ocr_fallback_used_predicate(ocr_fallback_used, warnings_column="warnings_json")
        if fallback_used_predicate:
            predicates.append(fallback_used_predicate)
        if enable_llm_tags is not None:
            predicates.append("enable_llm_tags = ?")
            params.append(1 if enable_llm_tags else 0)
        if predicates:
            query += " where " + " and ".join(predicates)
        query += " order by updated_at desc, id desc limit ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
            return [
                _review_item_from_row(row, model_usage_summary=_review_item_model_usage_summary(connection, row))
                for row in rows
            ]

    def review_facets(
        self,
        *,
        status: str = "open",
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
        where_sql, params = _review_items_where(
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
        source_collection_expression = """
            case
                when relative_path like '_manifest/%' or relative_path like '%/_manifest/%' or source_path like '%/_manifest/%' then 'manifest'
                when relative_path like 'Sunshine shared folders/%' or source_path like '%/Sunshine shared folders/%' then 'sunshine_shared_folders'
                when relative_path like 'archive-2026-05-25/%' or source_path like '%/archive-2026-05-25/%' then 'archive'
                when relative_path like 'google-drive-delta-2026-05-25/%' or source_path like '%/google-drive-delta-2026-05-25/%' then 'google_drive_delta'
                when relative_path like 'Paige Agent Sunshine Files/%' or source_path like '%/Paige Agent Sunshine Files/%' then 'paige_agent_files'
                when relative_path like 'From Mac Sunshine Pass 2026-05-25/%' or source_path like '%/From Mac Sunshine Pass 2026-05-25/%' then 'from_mac_pass'
                else 'other'
            end
        """
        facets: dict[str, dict[str, int]] = {}
        with self._connect() as connection:
            for name, expression in {
                "run": "coalesce(cast(run_id as text), 'none')",
                "preset": "coalesce(run_preset_key, 'unknown')",
                "embedding_provider": "coalesce(embedding_provider, 'unknown')",
                "llm_tag_provider": "coalesce(llm_tag_provider, 'unknown')",
                "ocr_fallback_provider": "coalesce(ocr_fallback_provider, 'unknown')",
                "ocr_fallback_used": _ocr_fallback_used_expression("warnings_json"),
                "llm_tags": "case when enable_llm_tags = 1 then 'enabled' when enable_llm_tags = 0 then 'disabled' else 'unknown' end",
                "review_reason": "coalesce(review_reason, 'unknown')",
                "route_status": "coalesce(route_status, 'unknown')",
                "primary_tag": "coalesce(proposed_tag, 'unknown')",
                "content_class": "coalesce(proposed_class, 'unknown')",
                "quality": "coalesce(json_extract(result_json, '$.quality'), 'unknown')",
                "placement_status": "coalesce(json_extract(result_json, '$.placement_status'), 'unknown')",
                "confidence_bucket": _confidence_bucket_expression(),
                "review_status": "coalesce(status, 'unknown')",
                "source_collection": source_collection_expression,
            }.items():
                facets[name] = _table_facet_counts(connection, "review_items", expression, where_sql, params)
            facets["secondary_tag"] = _review_json_array_facet_counts(connection, "secondary_tags_json", where_sql, params)
            facets["warning_type"] = _review_json_array_facet_counts(connection, "warnings_json", where_sql, params, split_prefix=True)
        return facets

    def list_files(
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
        placement_status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = """
            select id, source_path, relative_path, sample_path, filename, extension, mime_type,
                   size_bytes, source_collection, source_mtime, content_class, latest_run_id,
                   latest_result_json, extraction_text_snippet, created_at, updated_at,
                   (select run_key from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_run_key,
                   (select preset_key from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_run_preset_key,
                   (select embedding_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_embedding_provider,
                   (select enable_llm_tags from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_enable_llm_tags,
                   (select llm_tag_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_llm_tag_provider,
                   (select ocr_fallback_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_ocr_fallback_provider,
                   (
                       select status from review_items
                       where review_items.source_path = file_index.source_path
                       order by updated_at desc, id desc
                       limit 1
                   ) as review_status
            from file_index
        """
        params: list[Any] = []
        predicates: list[str] = []
        if q:
            predicates.append("(filename like ? or relative_path like ? or source_path like ? or extraction_text_snippet like ?)")
            like = f"%{q}%"
            params.extend([like, like, like, like])
        if source_collection:
            predicates.append("source_collection = ?")
            params.append(source_collection)
        if extension:
            normalized = extension if extension.startswith(".") else f".{extension}"
            predicates.append("extension = ?")
            params.append(normalized.lower())
        if content_class:
            predicates.append("content_class = ?")
            params.append(content_class)
        if primary_tag:
            predicates.append("json_extract(latest_result_json, '$.top_tag_candidate') = ?")
            params.append(primary_tag)
        if secondary_tag:
            predicates.append("json_extract(latest_result_json, '$.secondary_tags') like ?")
            params.append(f"%{secondary_tag}%")
        if route_status:
            predicates.append("json_extract(latest_result_json, '$.route_status') = ?")
            params.append(route_status)
        if placement_status:
            predicates.append("json_extract(latest_result_json, '$.placement_status') = ?")
            params.append(placement_status)
        if review_status:
            predicates.append(
                """
                exists (
                    select 1 from review_items
                    where review_items.source_path = file_index.source_path
                    and review_items.status = ?
                )
                """
            )
            params.append(review_status)
        if predicates:
            query += " where " + " and ".join(predicates)
        query += " order by updated_at desc, id desc limit ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_file_index_from_row(row) for row in rows]

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
        run_id: int | None = None,
        sort: str = "updated_desc",
        cursor: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        where_sql, params = _file_search_where(
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
        offset = max(int(cursor or 0), 0)
        order_sql = _file_search_order(sort)
        query = f"""
            select id, source_path, relative_path, sample_path, filename, extension, mime_type,
                   size_bytes, source_collection, source_mtime, content_class, latest_run_id,
                   latest_result_json, extraction_text_snippet, created_at, updated_at,
                   (select run_key from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_run_key,
                   (select preset_key from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_run_preset_key,
                   (select embedding_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_embedding_provider,
                   (select enable_llm_tags from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_enable_llm_tags,
                   (select llm_tag_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_llm_tag_provider,
                   (select ocr_fallback_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_ocr_fallback_provider
            from file_index
            {where_sql}
            {order_sql}
            limit ? offset ?
        """
        with self._connect() as connection:
            rows = connection.execute(query, [*params, limit, offset]).fetchall()
            total = connection.execute(f"select count(*) from file_index {where_sql}", params).fetchone()[0]
            review_status_by_source = _review_status_by_source(connection, [str(row["source_path"]) for row in rows])
        next_cursor = offset + len(rows) if offset + len(rows) < int(total) else None
        query_params = {
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
            "limit": limit,
        }
        return {
            "items": [_file_search_item_from_row(row, review_status=review_status_by_source.get(str(row["source_path"]))) for row in rows],
            "next_cursor": next_cursor,
            "total_estimate": int(total),
            "query": {key: value for key, value in query_params.items() if value not in (None, "")},
        }

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
        run_id: int | None = None,
    ) -> dict[str, dict[str, int]]:
        where_sql, params = _file_search_where(
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
        facets: dict[str, dict[str, int]] = {}
        with self._connect() as connection:
            for name, expression in {
                "extension": "coalesce(extension, 'unknown')",
                "source_collection": "coalesce(source_collection, 'unknown')",
                "content_class": "coalesce(content_class, 'unknown')",
                "primary_tag": "coalesce(json_extract(latest_result_json, '$.top_tag_candidate'), 'unknown')",
                "route_status": "coalesce(json_extract(latest_result_json, '$.route_status'), 'unknown')",
                "ocr_quality": "coalesce(json_extract(latest_result_json, '$.quality'), 'unknown')",
                "placement_status": "coalesce(json_extract(latest_result_json, '$.placement_status'), 'unknown')",
                "latest_run": "coalesce(cast(latest_run_id as text), 'none')",
            }.items():
                facets[name] = _facet_counts(connection, expression, where_sql, params)
            facets["review_status"] = _review_status_facet_counts(connection, where_sql, params)
            facets["secondary_tag"] = _json_array_facet_counts(connection, "latest_result_json", "$.secondary_tags", where_sql, params)
            facets["warning_type"] = _json_array_facet_counts(connection, "latest_result_json", "$.warnings", where_sql, params)
        return facets

    def file_inspection(self, file_id: int) -> dict[str, Any]:
        file_record = self.get_file(file_id)
        latest_result = file_record.get("latest_result") or {}
        with self._connect() as connection:
            review_row = connection.execute(
                """
                select id, source_path, relative_path, route_status, review_reason, status,
                       proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json,
                       run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                       ocr_quality_label, decision, correct_class, correct_tag, correct_secondary_tags_json, correct_destination_path,
                       correct_placement_year, correct_privacy, review_stage, priority, assigned_reviewer, notes, created_at, updated_at
                from review_items
                where source_path = ?
                order by updated_at desc, id desc
                limit 1
                """,
                (file_record["source_path"],),
            ).fetchone()
            golden_row = connection.execute(
                """
                select id, review_item_id, source_path, relative_path, sample_path, extracted_text_snippet,
                       content_class, correct_primary_tag, correct_secondary_tags_json, ocr_quality_label,
                       expected_review_required, sensitive_record, correct_destination_path, correct_placement_year,
                       correct_privacy, reviewer, notes, proposed_tag,
                       proposed_secondary_tags_json, proposed_confidence, reviewed_at, created_at, updated_at
                from golden_labels
                where source_path = ?
                """,
                (file_record["source_path"],),
            ).fetchone()
            run_rows = []
            if file_record.get("latest_run_id"):
                run_rows = connection.execute(
                    """
                    select id, run_key, preset_key, status, input_root, output_dir, command_json,
                           embedding_provider, enable_llm_tags, llm_tag_provider, ocr_fallback_provider, semantic_index_path,
                           run_metadata_json, started_at, completed_at, processed_count, route_candidate_count,
                           review_required_count, failed_count, summary_json, error, created_at, updated_at
                    from pipeline_runs
                    where id = ?
                    """,
                    (file_record["latest_run_id"],),
                ).fetchall()
        text = self.file_text(file_id)
        review_item = _review_item_from_row(review_row) if review_row else None
        golden_label = _golden_label_from_row(golden_row) if golden_row else None
        return {
            "file": _file_identity(file_record),
            "latest_result": latest_result,
            "review_item": review_item,
            "golden_label": golden_label,
            "ocr": {
                "quality": latest_result.get("quality"),
                "ocr_status": latest_result.get("ocr_status"),
                "mean_confidence": latest_result.get("mean_confidence"),
                "fallback_provider": _ocr_fallback_provider(latest_result.get("warnings") or []),
                "evidence": _ocr_evidence_from_result(latest_result, file_record.get("extraction_text_snippet")),
                "warnings": latest_result.get("warnings") or [],
            },
            "text": {
                "snippet": file_record.get("extraction_text_snippet"),
                "text": text.get("text"),
                "length": len(str(text.get("text") or "")),
            },
            "runs": [_pipeline_run_from_row(row) for row in run_rows],
            "actions": {
                "preview_url": f"/api/admin/files/{file_id}/preview",
                "text_url": f"/api/admin/files/{file_id}/text",
                "run_url": f"/api/admin/files/{file_id}/run",
                "review_url": f"/api/admin/files/{file_id}/review",
                "latest_run_report_url": f"/runs/{file_record['latest_run_id']}/report" if file_record.get("latest_run_id") else None,
            },
            "raw": {"file": file_record, "latest_result": latest_result},
        }

    def get_file(self, file_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                select id, source_path, relative_path, sample_path, filename, extension, mime_type,
                       size_bytes, source_collection, source_mtime, content_class, latest_run_id,
                       latest_result_json, extraction_text_snippet, created_at, updated_at,
                       (select run_key from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_run_key,
                       (select preset_key from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_run_preset_key,
                       (select embedding_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_embedding_provider,
                       (select enable_llm_tags from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_enable_llm_tags,
                       (select llm_tag_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_llm_tag_provider,
                       (select ocr_fallback_provider from pipeline_runs where pipeline_runs.id = file_index.latest_run_id) as latest_ocr_fallback_provider
                from file_index where id = ?
                """,
                (file_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"file {file_id} not found")
        return _file_index_from_row(row)

    def file_path_for_file(self, file_id: int) -> Path:
        item = self.get_file(file_id)
        result = item.get("latest_result") or {}
        candidates = [item.get("sample_path"), result.get("sample_path"), item.get("source_path")]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(str(candidate))
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError(f"No readable file found for file {file_id}")

    def file_text(self, file_id: int) -> dict[str, Any]:
        item = self.get_file(file_id)
        result = item.get("latest_result") or {}
        output_dir = result.get("output_dir")
        text = item.get("extraction_text_snippet") or ""
        if output_dir:
            extraction_path = Path(str(output_dir)) / "sample-extraction-results.jsonl"
            rows = _read_jsonl(extraction_path)
            for row in rows:
                if row.get("source_path") == item["source_path"] or row.get("sample_path") == item.get("sample_path"):
                    text = str(row.get("text") or text)
                    break
        return {"file_id": file_id, "source_path": item["source_path"], "relative_path": item["relative_path"], "text": text}

    def add_file_to_review(self, file_id: int, *, review_reason: str = "manual_file_review") -> dict[str, Any]:
        file_record = self.get_file(file_id)
        result = file_record.get("latest_result") or {}
        secondary_tags_json = json.dumps(result.get("secondary_tags", []), sort_keys=True)
        warnings_json = json.dumps(result.get("warnings", []), sort_keys=True)
        with self._connect() as connection:
            run_snapshot = _run_snapshot(connection, file_record.get("latest_run_id"))
            cursor = connection.execute(
                """
                insert into review_items (
                    source_path, relative_path, route_status, review_reason, status,
                    proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet,
                    confidence, warnings_json, result_json, review_stage,
                    run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                    updated_at
                ) values (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, 'needs_tag_review', ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                on conflict(source_path) do update set
                    review_reason=excluded.review_reason,
                    status='open',
                    proposed_class=excluded.proposed_class,
                    proposed_tag=excluded.proposed_tag,
                    secondary_tags_json=excluded.secondary_tags_json,
                    extraction_text_snippet=excluded.extraction_text_snippet,
                    confidence=excluded.confidence,
                    warnings_json=excluded.warnings_json,
                    result_json=excluded.result_json,
                    review_stage=excluded.review_stage,
                    run_id=excluded.run_id,
                    run_key=excluded.run_key,
                    run_preset_key=excluded.run_preset_key,
                    embedding_provider=excluded.embedding_provider,
                    llm_tag_provider=excluded.llm_tag_provider,
                    ocr_fallback_provider=excluded.ocr_fallback_provider,
                    enable_llm_tags=excluded.enable_llm_tags,
                    updated_at=datetime('now')
                returning id
                """,
                (
                    file_record["source_path"],
                    file_record["relative_path"],
                    result.get("route_status") or "manual_review",
                    review_reason,
                    file_record.get("content_class") or result.get("final_class"),
                    result.get("top_tag_candidate"),
                    secondary_tags_json,
                    file_record.get("extraction_text_snippet"),
                    result.get("tag_confidence"),
                    warnings_json,
                    json.dumps(result, sort_keys=True),
                    run_snapshot.get("run_id"),
                    run_snapshot.get("run_key"),
                    run_snapshot.get("run_preset_key"),
                    run_snapshot.get("embedding_provider"),
                    run_snapshot.get("llm_tag_provider"),
                    run_snapshot.get("ocr_fallback_provider"),
                    run_snapshot.get("enable_llm_tags"),
                ),
            )
            item_id = int(cursor.fetchone()[0])
        return self.get_review_item(item_id)

    def record_decision(
        self,
        item_id: int,
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
        review_stage: str | None = None,
        notes: str | None = None,
        reviewer: str | None = None,
        save_as_golden: bool = True,
    ) -> dict[str, Any]:
        status = "resolved" if decision in {"accept", "change", "defer", "reject", "ignore", "duplicate"} else "open"
        with self._connect() as connection:
            existing = connection.execute(
                """
                select id, source_path, relative_path, route_status, proposed_class, proposed_tag,
                       secondary_tags_json, extraction_text_snippet, confidence, ocr_quality_label, result_json
                from review_items where id = ?
                """,
                (item_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"review item {item_id} not found")

            resolved_tag = correct_tag
            if decision == "accept" and not resolved_tag:
                resolved_tag = existing["proposed_tag"]
            resolved_secondary_tags = (
                _clean_tags(correct_secondary_tags)
                if correct_secondary_tags is not None
                else (_json_list(existing["secondary_tags_json"]) if decision == "accept" else [])
            )
            connection.execute(
                """
                update review_items
                set decision = ?, correct_class = ?, correct_tag = ?, correct_secondary_tags_json = ?,
                    ocr_quality_label = coalesce(?, ocr_quality_label),
                    correct_destination_path = ?, correct_placement_year = ?, correct_privacy = ?,
                    review_stage = ?, notes = ?, status = ?, updated_at = datetime('now')
                where id = ?
                """,
                (
                    decision,
                    correct_class,
                    resolved_tag,
                    json.dumps(resolved_secondary_tags, sort_keys=True),
                    ocr_quality_label,
                    correct_destination_path,
                    correct_placement_year,
                    correct_privacy,
                    review_stage or ("resolved" if status == "resolved" else None),
                    notes,
                    status,
                    item_id,
                ),
            )
            if save_as_golden and decision in {"accept", "change"} and resolved_tag:
                result = _json_object(existing["result_json"])
                resolved_content_class = correct_class or existing["proposed_class"]
                resolved_ocr_quality = ocr_quality_label or existing["ocr_quality_label"] or result.get("quality")
                resolved_expected_review_required = (
                    expected_review_required
                    if expected_review_required is not None
                    else existing["route_status"] != "route_candidate"
                )
                connection.execute(
                    """
                    insert into golden_labels (
                        review_item_id, source_path, relative_path, sample_path, extracted_text_snippet,
                        content_class, correct_primary_tag, correct_secondary_tags_json, ocr_quality_label,
                        expected_review_required, sensitive_record, correct_destination_path, correct_placement_year,
                        correct_privacy, reviewer, notes, proposed_tag,
                        proposed_secondary_tags_json, proposed_confidence, reviewed_at, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                    on conflict(source_path) do update set
                        review_item_id=excluded.review_item_id,
                        relative_path=excluded.relative_path,
                        sample_path=excluded.sample_path,
                        extracted_text_snippet=excluded.extracted_text_snippet,
                        content_class=excluded.content_class,
                        correct_primary_tag=excluded.correct_primary_tag,
                        correct_secondary_tags_json=excluded.correct_secondary_tags_json,
                        ocr_quality_label=excluded.ocr_quality_label,
                        expected_review_required=excluded.expected_review_required,
                        sensitive_record=excluded.sensitive_record,
                        correct_destination_path=excluded.correct_destination_path,
                        correct_placement_year=excluded.correct_placement_year,
                        correct_privacy=excluded.correct_privacy,
                        reviewer=excluded.reviewer,
                        notes=excluded.notes,
                        proposed_tag=excluded.proposed_tag,
                        proposed_secondary_tags_json=excluded.proposed_secondary_tags_json,
                        proposed_confidence=excluded.proposed_confidence,
                        reviewed_at=datetime('now'),
                        updated_at=datetime('now')
                    """,
                    (
                        item_id,
                        existing["source_path"],
                        existing["relative_path"],
                        _sample_path_from_result(connection, existing["source_path"]),
                        existing["extraction_text_snippet"],
                        resolved_content_class,
                        resolved_tag,
                        json.dumps(resolved_secondary_tags, sort_keys=True),
                        resolved_ocr_quality,
                        1 if resolved_expected_review_required else 0,
                        1 if sensitive_record else 0,
                        correct_destination_path,
                        correct_placement_year,
                        correct_privacy,
                        reviewer,
                        notes,
                        existing["proposed_tag"],
                        existing["secondary_tags_json"],
                        existing["confidence"],
                    ),
                )
            row = connection.execute(
                """
                select id, source_path, relative_path, route_status, review_reason, status,
                       proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json,
                       run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                       ocr_quality_label, decision, correct_class, correct_tag, correct_secondary_tags_json, correct_destination_path,
                       correct_placement_year, correct_privacy, review_stage, priority, assigned_reviewer, notes, created_at, updated_at
                from review_items where id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"review item {item_id} not found")
            return _review_item_from_row(row, model_usage_summary=_review_item_model_usage_summary(connection, row))

    def mark_ocr_quality(
        self,
        item_id: int,
        *,
        ocr_quality_label: str,
        review_stage: str | None = "needs_ocr_review",
        notes: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            existing = connection.execute("select id, notes from review_items where id = ?", (item_id,)).fetchone()
            if existing is None:
                raise KeyError(f"review item {item_id} not found")
            merged_notes = _append_review_note(existing["notes"], notes)
            connection.execute(
                """
                update review_items
                set ocr_quality_label = ?,
                    review_stage = coalesce(?, review_stage),
                    notes = ?,
                    status = 'open',
                    updated_at = datetime('now')
                where id = ?
                """,
                (ocr_quality_label, review_stage, merged_notes, item_id),
            )
            row = connection.execute(
                """
                select id, source_path, relative_path, route_status, review_reason, status,
                       proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json,
                       run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                       ocr_quality_label, decision, correct_class, correct_tag, correct_secondary_tags_json, correct_destination_path,
                       correct_placement_year, correct_privacy, review_stage, priority, assigned_reviewer, notes, created_at, updated_at
                from review_items where id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"review item {item_id} not found")
            return _review_item_from_row(row, model_usage_summary=_review_item_model_usage_summary(connection, row))

    def get_review_item(self, item_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                select id, source_path, relative_path, route_status, review_reason, status,
                       proposed_class, proposed_tag, secondary_tags_json, extraction_text_snippet, confidence, warnings_json, result_json,
                       run_id, run_key, run_preset_key, embedding_provider, llm_tag_provider, ocr_fallback_provider, enable_llm_tags,
                       ocr_quality_label, decision, correct_class, correct_tag, correct_secondary_tags_json, correct_destination_path,
                       correct_placement_year, correct_privacy, review_stage, priority, assigned_reviewer, notes, created_at, updated_at
                from review_items where id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"review item {item_id} not found")
            return _review_item_from_row(row, model_usage_summary=_review_item_model_usage_summary(connection, row))

    def assign_review_item(
        self,
        item_id: int,
        *,
        assigned_reviewer: str | None = None,
        review_stage: str | None = None,
        priority: str | None = None,
    ) -> dict[str, Any]:
        self.get_review_item(item_id)
        with self._connect() as connection:
            connection.execute(
                """
                update review_items
                set assigned_reviewer = coalesce(?, assigned_reviewer),
                    review_stage = coalesce(?, review_stage),
                    priority = coalesce(?, priority),
                    updated_at = datetime('now')
                where id = ?
                """,
                (assigned_reviewer, review_stage, priority, item_id),
            )
        return self.get_review_item(item_id)

    def file_path_for_review_item(self, item_id: int) -> Path:
        item = self.get_review_item(item_id)
        result = item["result"]
        candidates = [result.get("sample_path"), item.get("source_path")]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(str(candidate))
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError(f"No readable file found for review item {item_id}")

    def list_golden_labels(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, review_item_id, source_path, relative_path, sample_path, extracted_text_snippet,
                       content_class, correct_primary_tag, correct_secondary_tags_json, ocr_quality_label,
                       expected_review_required, sensitive_record, correct_destination_path, correct_placement_year,
                       correct_privacy, reviewer, notes, proposed_tag,
                       proposed_secondary_tags_json, proposed_confidence, reviewed_at, created_at, updated_at
                from golden_labels
                order by updated_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [_golden_label_from_row(row) for row in rows]

    def golden_label_export_rows(self, *, limit: int = 10000) -> list[dict[str, Any]]:
        return self.list_golden_labels(limit=limit)

    def get_golden_label(self, label_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                select id, review_item_id, source_path, relative_path, sample_path, extracted_text_snippet,
                       content_class, correct_primary_tag, correct_secondary_tags_json, ocr_quality_label,
                       expected_review_required, sensitive_record, correct_destination_path, correct_placement_year,
                       correct_privacy, reviewer, notes, proposed_tag,
                       proposed_secondary_tags_json, proposed_confidence, reviewed_at, created_at, updated_at
                from golden_labels
                where id = ?
                """,
                (label_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"golden label {label_id} not found")
        return _golden_label_from_row(row)

    def file_path_for_golden_label(self, label_id: int) -> Path:
        label = self.get_golden_label(label_id)
        candidates = [label.get("sample_path"), label.get("source_path")]
        with self._connect() as connection:
            result_sample_path = _sample_path_from_result(connection, str(label.get("source_path") or ""))
            if result_sample_path:
                candidates.insert(0, result_sample_path)
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(str(candidate))
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError(f"No readable file found for golden label {label_id}")

    def update_golden_label(
        self,
        label_id: int,
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
        resolved_primary = (correct_primary_tag or existing["correct_primary_tag"]).strip()
        if not resolved_primary:
            raise ValueError("correct_primary_tag is required")
        resolved_secondary = _clean_tags(correct_secondary_tags) if correct_secondary_tags is not None else existing["correct_secondary_tags"]
        with self._connect() as connection:
            connection.execute(
                """
                update golden_labels
                set content_class = ?,
                    correct_primary_tag = ?,
                    correct_secondary_tags_json = ?,
                    ocr_quality_label = ?,
                    expected_review_required = ?,
                    sensitive_record = ?,
                    correct_destination_path = ?,
                    correct_placement_year = ?,
                    correct_privacy = ?,
                    reviewer = ?,
                    notes = ?,
                    reviewed_at = coalesce(reviewed_at, datetime('now')),
                    updated_at = datetime('now')
                where id = ?
                """,
                (
                    content_class if content_class is not None else existing["content_class"],
                    resolved_primary,
                    json.dumps(resolved_secondary, sort_keys=True),
                    ocr_quality_label if ocr_quality_label is not None else existing["ocr_quality_label"],
                    (
                        1
                        if (expected_review_required if expected_review_required is not None else existing["expected_review_required"])
                        else 0
                    ),
                    1 if (sensitive_record if sensitive_record is not None else existing["sensitive_record"]) else 0,
                    correct_destination_path if correct_destination_path is not None else existing["correct_destination_path"],
                    correct_placement_year if correct_placement_year is not None else existing["correct_placement_year"],
                    correct_privacy if correct_privacy is not None else existing["correct_privacy"],
                    reviewer if reviewer is not None else existing["reviewer"],
                    notes if notes is not None else existing["notes"],
                    label_id,
                ),
            )
        return self.get_golden_label(label_id)

    def delete_golden_label(self, label_id: int) -> dict[str, Any]:
        existing = self.get_golden_label(label_id)
        with self._connect() as connection:
            connection.execute("delete from golden_labels where id = ?", (label_id,))
        return {"deleted": True, "id": label_id, "source_path": existing["source_path"]}

    def golden_label_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute("select count(*) from golden_labels").fetchone()[0]
            by_primary_tag = _count_rows(
                connection,
                "select correct_primary_tag, count(*) from golden_labels group by correct_primary_tag",
            )
            by_secondary_tag = _golden_secondary_tag_counts(connection)
        taxonomy_primary_tags = _taxonomy_primary_tags()
        missing_primary_tags = [tag for tag in taxonomy_primary_tags if tag not in by_primary_tag]
        return {
            "db_path": str(self.db_path),
            "total_golden_labels": total,
            "golden_by_primary_tag": by_primary_tag,
            "golden_by_secondary_tag": by_secondary_tag,
            "taxonomy_primary_tags": taxonomy_primary_tags,
            "missing_primary_tags": missing_primary_tags,
            "primary_coverage_rate": _safe_divide(len(taxonomy_primary_tags) - len(missing_primary_tags), len(taxonomy_primary_tags)),
        }

    def record_pipeline_eval(self, summary: dict[str, Any]) -> dict[str, Any]:
        output_dir = str(summary.get("output_dir") or "")
        if not output_dir:
            raise ValueError("pipeline eval summary requires output_dir")
        run_metadata = summary.get("run_metadata") if isinstance(summary.get("run_metadata"), dict) else {}
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into pipeline_eval_runs (
                    eval_key, labels_db, output_dir, status, total_golden_labels, evaluated_predictions,
                    primary_accuracy, content_class_accuracy, secondary_precision, secondary_recall,
                    ocr_quality_accuracy, ocr_acceptable_rate, review_routing_accuracy, review_false_accepts,
                    embedding_success_rate, semantic_same_family_top5_rate, placement_destination_accuracy,
                    source_file_mutations, acceptance_gate_status, production_readiness_status, failure_count,
                    model_usage_json, summary_json, run_metadata_json, created_at, updated_at
                ) values (?, ?, ?, 'succeeded', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                on conflict(output_dir) do update set
                    labels_db=excluded.labels_db,
                    status=excluded.status,
                    total_golden_labels=excluded.total_golden_labels,
                    evaluated_predictions=excluded.evaluated_predictions,
                    primary_accuracy=excluded.primary_accuracy,
                    content_class_accuracy=excluded.content_class_accuracy,
                    secondary_precision=excluded.secondary_precision,
                    secondary_recall=excluded.secondary_recall,
                    ocr_quality_accuracy=excluded.ocr_quality_accuracy,
                    ocr_acceptable_rate=excluded.ocr_acceptable_rate,
                    review_routing_accuracy=excluded.review_routing_accuracy,
                    review_false_accepts=excluded.review_false_accepts,
                    embedding_success_rate=excluded.embedding_success_rate,
                    semantic_same_family_top5_rate=excluded.semantic_same_family_top5_rate,
                    placement_destination_accuracy=excluded.placement_destination_accuracy,
                    source_file_mutations=excluded.source_file_mutations,
                    acceptance_gate_status=excluded.acceptance_gate_status,
                    production_readiness_status=excluded.production_readiness_status,
                    failure_count=excluded.failure_count,
                    model_usage_json=excluded.model_usage_json,
                    summary_json=excluded.summary_json,
                    run_metadata_json=excluded.run_metadata_json,
                    updated_at=datetime('now')
                returning id
                """,
                (
                    f"pipeline-eval-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
                    summary.get("labels_db"),
                    output_dir,
                    summary.get("total_golden_labels"),
                    summary.get("evaluated_predictions"),
                    summary.get("primary_accuracy"),
                    summary.get("content_class_accuracy"),
                    summary.get("secondary_precision"),
                    summary.get("secondary_recall"),
                    summary.get("ocr_quality_accuracy"),
                    summary.get("ocr_acceptable_rate"),
                    summary.get("review_routing_accuracy"),
                    summary.get("review_false_accepts"),
                    summary.get("embedding_success_rate"),
                    summary.get("semantic_same_family_top5_rate"),
                    summary.get("placement_destination_accuracy"),
                    summary.get("source_file_mutations"),
                    (summary.get("acceptance_gate") or {}).get("status") if isinstance(summary.get("acceptance_gate"), dict) else None,
                    (summary.get("production_readiness") or {}).get("status") if isinstance(summary.get("production_readiness"), dict) else None,
                    summary.get("failure_count"),
                    json.dumps(summary.get("model_usage") or {}, sort_keys=True),
                    json.dumps(summary, sort_keys=True),
                    json.dumps(run_metadata, sort_keys=True),
                ),
            )
            row_id = int(cursor.fetchone()[0])
        return self.get_pipeline_eval_run(row_id)

    def list_pipeline_eval_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, eval_key, labels_db, output_dir, status, total_golden_labels, evaluated_predictions,
                       primary_accuracy, content_class_accuracy, secondary_precision, secondary_recall,
                       ocr_quality_accuracy, ocr_acceptable_rate, review_routing_accuracy, review_false_accepts,
                       embedding_success_rate, semantic_same_family_top5_rate, placement_destination_accuracy,
                       source_file_mutations, acceptance_gate_status, production_readiness_status, failure_count, model_usage_json,
                       summary_json, run_metadata_json, created_at, updated_at
                from pipeline_eval_runs
                order by updated_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [_pipeline_eval_run_from_row(row) for row in rows]

    def get_pipeline_eval_run(self, eval_run_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                select id, eval_key, labels_db, output_dir, status, total_golden_labels, evaluated_predictions,
                       primary_accuracy, content_class_accuracy, secondary_precision, secondary_recall,
                       ocr_quality_accuracy, ocr_acceptable_rate, review_routing_accuracy, review_false_accepts,
                       embedding_success_rate, semantic_same_family_top5_rate, placement_destination_accuracy,
                       source_file_mutations, acceptance_gate_status, production_readiness_status, failure_count, model_usage_json,
                       summary_json, run_metadata_json, created_at, updated_at
                from pipeline_eval_runs
                where id = ?
                """,
                (eval_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"pipeline eval run {eval_run_id} not found")
        return _pipeline_eval_run_from_row(row)

    def run_presets(self) -> list[dict[str, Any]]:
        base_manifest = "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25"
        return [
            {
                "preset_key": "qa_samples_full",
                "label": "QA samples full",
                "description": "Full QA sample with LLM tags, OCR fallback, and semantic examples.",
                "input_root": f"{base_manifest}/qa samples",
                "output_dir": f"{base_manifest}/dashboard-runs/qa_samples_full",
                "enable_llm_tags": True,
                "embedding_provider": "cortex",
                "llm_tag_provider": "auto",
                "ocr_fallback_provider": "openai",
            },
            {
                "preset_key": "qa_samples_fast",
                "label": "QA samples fast",
                "description": "Fast QA regression pass without LLM tag inspection.",
                "input_root": f"{base_manifest}/qa samples",
                "output_dir": f"{base_manifest}/dashboard-runs/qa_samples_fast",
                "enable_llm_tags": False,
                "embedding_provider": "cortex",
                "llm_tag_provider": "disabled",
                "ocr_fallback_provider": "disabled",
            },
            {
                "preset_key": "ocr_fallback_focus",
                "label": "OCR fallback focus",
                "description": "OCR-heavy QA sample with OpenAI fallback enabled.",
                "input_root": f"{base_manifest}/qa samples",
                "output_dir": f"{base_manifest}/dashboard-runs/ocr_fallback_focus",
                "enable_llm_tags": False,
                "embedding_provider": "cortex",
                "llm_tag_provider": "disabled",
                "ocr_fallback_provider": "openai",
            },
            {
                "preset_key": "review_required_rerun",
                "label": "Review required rerun",
                "description": "Rerun currently open review files after pipeline changes.",
                "input_root": f"{base_manifest}/review required files",
                "output_dir": f"{base_manifest}/dashboard-runs/review_required_rerun",
                "enable_llm_tags": True,
                "embedding_provider": "cortex",
                "llm_tag_provider": "auto",
                "ocr_fallback_provider": "openai",
            },
            {
                "preset_key": "random_route_candidate_audit",
                "label": "Route candidate audit",
                "description": "Audit a random sample of auto-routed files after a run import.",
                "input_root": f"{base_manifest}/qa samples",
                "output_dir": f"{base_manifest}/dashboard-runs/random_route_candidate_audit",
                "enable_llm_tags": True,
                "embedding_provider": "cortex",
                "llm_tag_provider": "auto",
                "ocr_fallback_provider": "openai",
            },
            {
                "preset_key": "single_file_debug",
                "label": "Single file debug",
                "description": "Debug one file by overriding input root/output parameters or using the file browser Run File action.",
                "input_root": f"{base_manifest}/qa samples",
                "output_dir": f"{base_manifest}/dashboard-runs/single_file_debug",
                "enable_llm_tags": False,
                "embedding_provider": "cortex",
                "llm_tag_provider": "disabled",
                "ocr_fallback_provider": "disabled",
            },
        ]

    def create_pipeline_run(
        self,
        *,
        preset_key: str,
        run_role: str | None = None,
        input_root: str,
        output_dir: str,
        command: list[str],
        embedding_provider: str | None,
        enable_llm_tags: bool,
        llm_tag_provider: str | None,
        ocr_fallback_provider: str | None,
        semantic_index_path: str | None = None,
    ) -> dict[str, Any]:
        run_key = f"{preset_key}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        run_metadata = _run_metadata(
            input_root=input_root,
            output_dir=output_dir,
            run_role=run_role,
            embedding_provider=embedding_provider,
            enable_llm_tags=enable_llm_tags,
            llm_tag_provider=llm_tag_provider,
            ocr_fallback_provider=ocr_fallback_provider,
            semantic_index_path=semantic_index_path,
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert into pipeline_runs (
                    run_key, preset_key, status, input_root, output_dir, command_json,
                    embedding_provider, enable_llm_tags, llm_tag_provider, ocr_fallback_provider, semantic_index_path,
                    run_metadata_json, created_at, updated_at
                ) values (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    run_key,
                    preset_key,
                    input_root,
                    output_dir,
                    json.dumps(command),
                    embedding_provider,
                    1 if enable_llm_tags else 0,
                    llm_tag_provider,
                    ocr_fallback_provider,
                    semantic_index_path,
                    json.dumps(run_metadata, sort_keys=True),
                ),
            )
            run_id = int(cursor.lastrowid)
            self.add_pipeline_run_event(connection, run_id, level="info", message="Run queued.", payload={"command": command, "run_metadata": run_metadata})
        return self.get_pipeline_run(run_id)

    def mark_pipeline_run_started(self, run_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "update pipeline_runs set status = 'running', started_at = datetime('now'), updated_at = datetime('now') where id = ?",
                (run_id,),
            )
            self.add_pipeline_run_event(connection, run_id, level="info", message="Run started.")

    def update_pipeline_run_progress(self, run_id: int, summary: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update pipeline_runs
                set updated_at = datetime('now'),
                    processed_count = ?,
                    route_candidate_count = ?,
                    review_required_count = ?,
                    failed_count = ?,
                    summary_json = ?
                where id = ? and status = 'running'
                """,
                (
                    summary.get("processed_count") or summary.get("total_results") or summary.get("graph_run_count"),
                    summary.get("route_candidate_count") or summary.get("by_route_status", {}).get("route_candidate"),
                    summary.get("review_required_count"),
                    summary.get("failed_count") or summary.get("error_count"),
                    json.dumps(summary, sort_keys=True),
                    run_id,
                ),
            )

    def mark_pipeline_run_finished(self, run_id: int, *, status: str, summary: dict[str, Any] | None = None, error: str | None = None) -> None:
        summary = summary or {}
        with self._connect() as connection:
            connection.execute(
                """
                update pipeline_runs
                set status = ?, completed_at = datetime('now'), updated_at = datetime('now'),
                    processed_count = ?, route_candidate_count = ?, review_required_count = ?,
                    failed_count = ?, summary_json = ?, error = ?
                where id = ?
                """,
                (
                    status,
                    summary.get("processed_count") or summary.get("total_results") or summary.get("graph_run_count"),
                    summary.get("route_candidate_count") or summary.get("by_route_status", {}).get("route_candidate"),
                    summary.get("review_required_count"),
                    summary.get("failed_count") or summary.get("error_count"),
                    json.dumps(summary, sort_keys=True),
                    error,
                    run_id,
                ),
            )
            self.add_pipeline_run_event(connection, run_id, level="error" if error else "info", message=error or f"Run {status}.")

    def add_pipeline_run_event(
        self,
        connection: sqlite3.Connection,
        run_id: int,
        *,
        level: str,
        message: str,
        node: str | None = None,
        source_path: str | None = None,
        relative_path: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            insert into pipeline_run_events (
                run_id, timestamp, level, node, source_path, relative_path, message, payload_json
            ) values (?, datetime('now'), ?, ?, ?, ?, ?, ?)
            """,
            (run_id, level, node, source_path, relative_path, message, json.dumps(payload or {}, sort_keys=True)),
        )

    def list_pipeline_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, run_key, preset_key, status, input_root, output_dir, command_json,
                       embedding_provider, enable_llm_tags, llm_tag_provider, ocr_fallback_provider, semantic_index_path,
                       run_metadata_json, started_at, completed_at, processed_count, route_candidate_count,
                       review_required_count, failed_count, summary_json, error, created_at, updated_at
                from pipeline_runs
                order by created_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [_pipeline_run_from_row(row) for row in rows]

    def get_pipeline_run(self, run_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                select id, run_key, preset_key, status, input_root, output_dir, command_json,
                       embedding_provider, enable_llm_tags, llm_tag_provider, ocr_fallback_provider, semantic_index_path,
                       run_metadata_json, started_at, completed_at, processed_count, route_candidate_count,
                       review_required_count, failed_count, summary_json, error, created_at, updated_at
                from pipeline_runs where id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"pipeline run {run_id} not found")
        return _pipeline_run_from_row(row)

    def delete_pipeline_run(self, run_id: int, *, delete_artifacts: bool = True) -> dict[str, Any]:
        """Delete a pipeline run and all dashboard-owned rows tied to it.

        Source corpus files are never deleted. Artifact deletion is limited to
        the run output directory, and shared output directories are preserved
        until no remaining run points at the same path.
        """

        with self._connect() as connection:
            run_row = connection.execute(
                """
                select id, run_key, preset_key, status, input_root, output_dir, command_json,
                       embedding_provider, enable_llm_tags, llm_tag_provider, ocr_fallback_provider, semantic_index_path,
                       run_metadata_json, started_at, completed_at, processed_count, route_candidate_count,
                       review_required_count, failed_count, summary_json, error, created_at, updated_at
                from pipeline_runs where id = ?
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                raise KeyError(f"pipeline run {run_id} not found")
            run = _pipeline_run_from_row(run_row)
            output_dir = str(run.get("output_dir") or "")
            source_paths = [
                str(row["source_path"])
                for row in connection.execute("select source_path from review_items where run_id = ?", (run_id,)).fetchall()
                if row["source_path"]
            ]
            counts: dict[str, int] = {}
            counts["review_items"] = _delete_count(connection, "delete from review_items where run_id = ?", (run_id,))
            counts["golden_labels"] = 0
            if source_paths:
                placeholders = ",".join("?" for _ in source_paths)
                counts["golden_labels"] = _delete_count(connection, f"delete from golden_labels where source_path in ({placeholders})", tuple(source_paths))
            counts["file_index"] = _delete_count(connection, "delete from file_index where latest_run_id = ?", (run_id,))
            counts["model_usage"] = _delete_count(connection, "delete from pipeline_run_model_usage where run_id = ?", (run_id,))
            counts["events"] = _delete_count(connection, "delete from pipeline_run_events where run_id = ?", (run_id,))

            sibling_count = 0
            if output_dir:
                sibling_count = int(
                    connection.execute(
                        "select count(*) from pipeline_runs where id != ? and output_dir = ?",
                        (run_id, output_dir),
                    ).fetchone()[0]
                    or 0
                )
            if output_dir and sibling_count == 0:
                counts["pipeline_results"] = _delete_count(connection, "delete from pipeline_results where output_dir = ?", (output_dir,))
            else:
                counts["pipeline_results"] = 0

            counts["pipeline_runs"] = _delete_count(connection, "delete from pipeline_runs where id = ?", (run_id,))

        artifact_result = {
            "deleted": False,
            "path": output_dir or None,
            "skipped_reason": None,
        }
        if delete_artifacts:
            if not output_dir:
                artifact_result["skipped_reason"] = "run_has_no_output_dir"
            elif sibling_count > 0:
                artifact_result["skipped_reason"] = "output_dir_shared_by_other_runs"
                artifact_result["shared_run_count"] = sibling_count
            else:
                artifact_result = _delete_run_output_dir(Path(output_dir))

        return {
            "deleted": True,
            "run": run,
            "deleted_counts": counts,
            "artifacts": artifact_result,
        }

    def list_pipeline_run_events(self, run_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, run_id, timestamp, level, node, source_path, relative_path, message, payload_json
                from pipeline_run_events
                where run_id = ?
                order by id desc
                limit ?
                """,
                (run_id, limit),
            ).fetchall()
        return [_pipeline_run_event_from_row(row) for row in rows]

    def import_model_usage_artifact(self, connection: sqlite3.Connection, run_id: int | None, output_path: Path) -> int:
        rows = _read_jsonl(output_path / "sample-model-usage.jsonl")
        if run_id is not None:
            connection.execute("delete from pipeline_run_model_usage where run_id = ?", (run_id,))
        imported = 0
        for row in rows:
            self.record_model_usage(connection, run_id=run_id, row=row)
            imported += 1
        return imported

    def record_model_usage(self, connection: sqlite3.Connection, *, run_id: int | None, row: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into pipeline_run_model_usage (
                run_id, source_path, relative_path, node, purpose, provider, model, status,
                started_at, completed_at, runtime_ms, input_tokens, output_tokens, total_tokens,
                estimated_cost_usd, cost_basis, request_id, trace_id, error, metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row.get("source_path"),
                row.get("relative_path"),
                row.get("node"),
                str(row.get("purpose") or "unknown"),
                str(row.get("provider") or "unknown"),
                str(row.get("model") or "unknown"),
                str(row.get("status") or "unknown"),
                row.get("started_at"),
                row.get("completed_at"),
                _optional_int(row.get("runtime_ms")),
                _optional_int(row.get("input_tokens")),
                _optional_int(row.get("output_tokens")),
                _optional_int(row.get("total_tokens")),
                _optional_float(row.get("estimated_cost_usd")),
                row.get("cost_basis"),
                row.get("request_id"),
                row.get("trace_id"),
                row.get("error"),
                json.dumps(row.get("metadata") or row.get("metadata_json") or {}, sort_keys=True),
            ),
        )

    def list_model_usage(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, run_id, source_path, relative_path, node, purpose, provider, model, status,
                       started_at, completed_at, runtime_ms, input_tokens, output_tokens, total_tokens,
                       estimated_cost_usd, cost_basis, request_id, trace_id, error, metadata_json, created_at
                from pipeline_run_model_usage
                where run_id = ?
                order by id asc
                """,
                (run_id,),
            ).fetchall()
        return [_model_usage_from_row(row) for row in rows]

    def _upsert_file_index_from_result(
        self,
        connection: sqlite3.Connection,
        result: dict[str, Any],
        output_path: Path,
        extraction_text_snippet: str | None,
        *,
        run_id: int | None = None,
    ) -> None:
        source_path = str(result.get("source_path") or result.get("sample_path") or "")
        if not source_path:
            return
        sample_path = result.get("sample_path")
        relative_path = str(result.get("relative_path") or Path(source_path).name)
        file_path = _first_existing_path([sample_path, source_path])
        filename = Path(str(sample_path or source_path)).name
        extension = Path(filename).suffix.lower()
        mime_type = mimetypes.guess_type(filename)[0]
        size_bytes = file_path.stat().st_size if file_path else None
        source_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, UTC).isoformat() if file_path else None
        result_with_output = {**result, "output_dir": str(output_path)}
        connection.execute(
            """
            insert into file_index (
                source_path, relative_path, sample_path, filename, extension, mime_type, size_bytes,
                source_collection, source_mtime, content_class, latest_run_id, latest_result_json, extraction_text_snippet,
                created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            on conflict(source_path) do update set
                relative_path=excluded.relative_path,
                sample_path=excluded.sample_path,
                filename=excluded.filename,
                extension=excluded.extension,
                mime_type=excluded.mime_type,
                size_bytes=excluded.size_bytes,
                source_collection=excluded.source_collection,
                source_mtime=excluded.source_mtime,
                content_class=excluded.content_class,
                latest_run_id=excluded.latest_run_id,
                latest_result_json=excluded.latest_result_json,
                extraction_text_snippet=coalesce(excluded.extraction_text_snippet, file_index.extraction_text_snippet),
                updated_at=datetime('now')
            """,
            (
                source_path,
                relative_path,
                sample_path,
                filename,
                extension,
                mime_type,
                size_bytes,
                _source_collection(relative_path or source_path),
                source_mtime,
                result.get("final_class"),
                run_id,
                json.dumps(result_with_output, sort_keys=True),
                extraction_text_snippet,
            ),
        )

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                create table if not exists pipeline_results (
                    source_path text primary key,
                    relative_path text not null,
                    sample_path text,
                    output_dir text not null,
                    route_status text not null,
                    review_reason text,
                    final_class text,
                    extraction_strategy text,
                    extraction_status text,
                    quality text,
                    top_tag_candidate text,
                    secondary_tags_json text not null default '[]',
                    extraction_text_snippet text,
                    tag_confidence real,
                    llm_status text,
                    warnings_json text not null,
                    result_json text not null,
                    imported_at text not null default (datetime('now'))
                );

                create table if not exists review_items (
                    id integer primary key autoincrement,
                    source_path text not null unique,
                    relative_path text not null,
                    route_status text not null,
                    review_reason text,
                    status text not null default 'open',
                    proposed_class text,
                    proposed_tag text,
                    secondary_tags_json text not null default '[]',
                    extraction_text_snippet text,
                    confidence real,
                    warnings_json text not null,
                    result_json text not null,
                    ocr_quality_label text,
                    decision text,
                    correct_class text,
                    correct_tag text,
                    correct_secondary_tags_json text not null default '[]',
                    correct_destination_path text,
                    correct_placement_year text,
                    correct_privacy text,
                    review_stage text,
                    priority text,
                    assigned_reviewer text,
                    run_id integer,
                    run_key text,
                    run_preset_key text,
                    embedding_provider text,
                    llm_tag_provider text,
                    ocr_fallback_provider text,
                    enable_llm_tags integer,
                    notes text,
                    created_at text not null default (datetime('now')),
                    updated_at text not null default (datetime('now'))
                );

                create table if not exists golden_labels (
                    id integer primary key autoincrement,
                    review_item_id integer,
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
                    created_at text not null default (datetime('now')),
                    updated_at text not null default (datetime('now'))
                );

                create table if not exists file_index (
                    id integer primary key autoincrement,
                    source_path text not null unique,
                    relative_path text not null,
                    sample_path text,
                    filename text not null,
                    extension text,
                    mime_type text,
                    size_bytes integer,
                    source_collection text,
                    source_mtime text,
                    content_class text,
                    latest_run_id integer,
                    latest_result_json text not null default '{}',
                    extraction_text_snippet text,
                    created_at text not null default (datetime('now')),
                    updated_at text not null default (datetime('now'))
                );

                create table if not exists pipeline_runs (
                    id integer primary key autoincrement,
                    run_key text not null unique,
                    preset_key text not null,
                    status text not null,
                    input_root text,
                    output_dir text,
                    command_json text not null default '[]',
                    embedding_provider text,
                    enable_llm_tags integer not null default 0,
                    llm_tag_provider text,
                    ocr_fallback_provider text,
                    semantic_index_path text,
                    run_metadata_json text not null default '{}',
                    started_at text,
                    completed_at text,
                    processed_count integer,
                    route_candidate_count integer,
                    review_required_count integer,
                    failed_count integer,
                    summary_json text not null default '{}',
                    error text,
                    created_at text not null default (datetime('now')),
                    updated_at text not null default (datetime('now'))
                );

                create table if not exists pipeline_run_events (
                    id integer primary key autoincrement,
                    run_id integer not null,
                    timestamp text not null default (datetime('now')),
                    level text not null,
                    node text,
                    source_path text,
                    relative_path text,
                    message text not null,
                    payload_json text not null default '{}'
                );

                create table if not exists pipeline_run_model_usage (
                    id integer primary key autoincrement,
                    run_id integer,
                    source_path text,
                    relative_path text,
                    node text,
                    purpose text not null,
                    provider text not null,
                    model text not null,
                    status text not null,
                    started_at text,
                    completed_at text,
                    runtime_ms integer,
                    input_tokens integer,
                    output_tokens integer,
                    total_tokens integer,
                    estimated_cost_usd real,
                    cost_basis text,
                    request_id text,
                    trace_id text,
                    error text,
                    metadata_json text not null default '{}',
                    created_at text not null default (datetime('now'))
                );

                create table if not exists pipeline_eval_runs (
                    id integer primary key autoincrement,
                    eval_key text not null unique,
                    labels_db text,
                    output_dir text not null unique,
                    status text not null,
                    total_golden_labels integer,
                    evaluated_predictions integer,
                    primary_accuracy real,
                    content_class_accuracy real,
                    secondary_precision real,
                    secondary_recall real,
                    ocr_quality_accuracy real,
                    ocr_acceptable_rate real,
                    review_routing_accuracy real,
                    review_false_accepts integer,
                    embedding_success_rate real,
                    semantic_same_family_top5_rate real,
                    placement_destination_accuracy real,
                    source_file_mutations integer,
                    acceptance_gate_status text,
                    production_readiness_status text,
                    failure_count integer,
                    model_usage_json text not null default '{}',
                    summary_json text not null default '{}',
                    run_metadata_json text not null default '{}',
                    created_at text not null default (datetime('now')),
                    updated_at text not null default (datetime('now'))
                );

                create index if not exists idx_model_usage_run_id
                    on pipeline_run_model_usage(run_id);
                create index if not exists idx_model_usage_provider_model
                    on pipeline_run_model_usage(provider, model);
                create index if not exists idx_model_usage_source_path
                    on pipeline_run_model_usage(source_path);
                create index if not exists idx_pipeline_eval_runs_updated_at
                    on pipeline_eval_runs(updated_at);
                """
            )
            _ensure_column(connection, "pipeline_results", "secondary_tags_json", "secondary_tags_json text not null default '[]'")
            _ensure_column(connection, "pipeline_results", "extraction_text_snippet", "extraction_text_snippet text")
            _ensure_column(connection, "review_items", "secondary_tags_json", "secondary_tags_json text not null default '[]'")
            _ensure_column(connection, "review_items", "extraction_text_snippet", "extraction_text_snippet text")
            _ensure_column(connection, "review_items", "ocr_quality_label", "ocr_quality_label text")
            _ensure_column(connection, "review_items", "correct_secondary_tags_json", "correct_secondary_tags_json text not null default '[]'")
            _ensure_column(connection, "review_items", "correct_destination_path", "correct_destination_path text")
            _ensure_column(connection, "review_items", "correct_placement_year", "correct_placement_year text")
            _ensure_column(connection, "review_items", "correct_privacy", "correct_privacy text")
            _ensure_column(connection, "review_items", "review_stage", "review_stage text")
            _ensure_column(connection, "review_items", "priority", "priority text")
            _ensure_column(connection, "review_items", "assigned_reviewer", "assigned_reviewer text")
            _ensure_column(connection, "review_items", "run_id", "run_id integer")
            _ensure_column(connection, "review_items", "run_key", "run_key text")
            _ensure_column(connection, "review_items", "run_preset_key", "run_preset_key text")
            _ensure_column(connection, "review_items", "embedding_provider", "embedding_provider text")
            _ensure_column(connection, "review_items", "llm_tag_provider", "llm_tag_provider text")
            _ensure_column(connection, "review_items", "ocr_fallback_provider", "ocr_fallback_provider text")
            _ensure_column(connection, "review_items", "enable_llm_tags", "enable_llm_tags integer")
            _ensure_column(connection, "pipeline_runs", "embedding_provider", "embedding_provider text")
            _ensure_column(connection, "pipeline_runs", "run_metadata_json", "run_metadata_json text not null default '{}'")
            _ensure_column(connection, "pipeline_eval_runs", "run_metadata_json", "run_metadata_json text not null default '{}'")
            _ensure_column(connection, "pipeline_eval_runs", "ocr_acceptable_rate", "ocr_acceptable_rate real")
            _ensure_column(connection, "pipeline_eval_runs", "review_false_accepts", "review_false_accepts integer")
            _ensure_column(connection, "pipeline_eval_runs", "embedding_success_rate", "embedding_success_rate real")
            _ensure_column(connection, "pipeline_eval_runs", "semantic_same_family_top5_rate", "semantic_same_family_top5_rate real")
            _ensure_column(connection, "pipeline_eval_runs", "placement_destination_accuracy", "placement_destination_accuracy real")
            _ensure_column(connection, "pipeline_eval_runs", "source_file_mutations", "source_file_mutations integer")
            _ensure_column(connection, "pipeline_eval_runs", "acceptance_gate_status", "acceptance_gate_status text")
            _ensure_column(connection, "pipeline_eval_runs", "production_readiness_status", "production_readiness_status text")
            _ensure_column(connection, "golden_labels", "content_class", "content_class text")
            _ensure_column(connection, "golden_labels", "ocr_quality_label", "ocr_quality_label text")
            _ensure_column(connection, "golden_labels", "expected_review_required", "expected_review_required integer")
            _ensure_column(connection, "golden_labels", "sensitive_record", "sensitive_record integer not null default 0")
            _ensure_column(connection, "golden_labels", "correct_destination_path", "correct_destination_path text")
            _ensure_column(connection, "golden_labels", "correct_placement_year", "correct_placement_year text")
            _ensure_column(connection, "golden_labels", "correct_privacy", "correct_privacy text")
            _ensure_column(connection, "golden_labels", "reviewed_at", "reviewed_at text")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as input_file:
        return [json.loads(line) for line in input_file if line.strip()]


def _count_rows(connection: sqlite3.Connection, query: str) -> dict[str, int]:
    return {str(key or "unknown"): int(count) for key, count in connection.execute(query).fetchall()}


def _delete_count(connection: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> int:
    cursor = connection.execute(query, params)
    return int(cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0)


def _delete_run_output_dir(output_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "deleted": False,
        "path": str(output_dir),
        "skipped_reason": None,
    }
    if not output_dir.exists():
        result["skipped_reason"] = "output_dir_missing"
        return result
    if not output_dir.is_dir():
        result["skipped_reason"] = "output_path_not_directory"
        return result
    if not _looks_like_dashboard_run_output(output_dir):
        result["skipped_reason"] = "output_dir_not_recognized_as_dashboard_run_artifacts"
        return result
    shutil.rmtree(output_dir)
    result["deleted"] = True
    return result


def _looks_like_dashboard_run_output(output_dir: Path) -> bool:
    if "dashboard-runs" in output_dir.parts:
        return True
    known_artifacts = {
        "sample-pipeline-summary.json",
        "sample-pipeline-results.jsonl",
        "graph-result.json",
        "graph-audit-events.jsonl",
    }
    return any((output_dir / artifact).exists() for artifact in known_artifacts)


def _secondary_tag_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = connection.execute("select secondary_tags_json from pipeline_results").fetchall()
    for row in rows:
        for tag in _json_list(row["secondary_tags_json"]):
            tag_name = str(tag)
            counts[tag_name] = counts.get(tag_name, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _golden_secondary_tag_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = connection.execute("select correct_secondary_tags_json from golden_labels").fetchall()
    for row in rows:
        for tag in _json_list(row["correct_secondary_tags_json"]):
            counts[str(tag)] = counts.get(str(tag), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _taxonomy_primary_tags() -> list[str]:
    try:
        return load_taxonomy_options(DEFAULT_TAXONOMY_PATH).primary_tags
    except Exception:  # noqa: BLE001 - coverage summary should not break review CRUD.
        return []


def _run_metadata(
    *,
    input_root: str,
    output_dir: str,
    run_role: str | None,
    embedding_provider: str | None,
    enable_llm_tags: bool,
    llm_tag_provider: str | None,
    ocr_fallback_provider: str | None,
    semantic_index_path: str | None,
) -> dict[str, Any]:
    resolved_run_role = run_role or _run_role_for_preset(Path(output_dir), input_root=input_root)
    return {
        "run_kind": "pipeline_batch",
        "run_role": resolved_run_role,
        "input_root": input_root,
        "output_dir": output_dir,
        "taxonomy_path": str(DEFAULT_TAXONOMY_PATH),
        "taxonomy_version": Path(DEFAULT_TAXONOMY_PATH).name,
        "embedding_provider": embedding_provider,
        "enable_llm_tags": enable_llm_tags,
        "llm_tag_provider": llm_tag_provider,
        "ocr_fallback_provider": ocr_fallback_provider,
        "semantic_index_path": semantic_index_path,
        "git_commit": _git_commit(),
    }


def _run_role_for_preset(output_dir: Path, *, input_root: str) -> str:
    output_text = str(output_dir).lower()
    input_text = str(input_root).lower()
    if "qa_samples_full" in output_text or "qa samples" in input_text and "full" in output_text:
        return "baseline"
    return "test"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path.cwd(), text=True).strip()
    except Exception:  # noqa: BLE001 - metadata should not block dashboard runs.
        return None


def _safe_divide(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _append_review_note(existing: str | None, note: str | None) -> str | None:
    clean_note = (note or "").strip()
    if not clean_note:
        return existing
    if not existing:
        return clean_note
    return f"{existing.rstrip()}\n{clean_note}"


def _extraction_text_snippet(extraction_row: dict[str, Any] | None, *, max_chars: int = 360) -> str | None:
    if not extraction_row:
        return None
    text = str(extraction_row.get("text") or "")
    compact = " ".join(text.split())
    if not compact:
        return None
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row["name"] for row in connection.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        try:
            connection.execute(f"alter table {table} add column {ddl}")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise


def _sample_path_from_result(connection: sqlite3.Connection, source_path: str) -> str | None:
    row = connection.execute("select sample_path from pipeline_results where source_path = ?", (source_path,)).fetchone()
    if row and row["sample_path"]:
        return str(row["sample_path"])
    return None


def _first_existing_path(candidates: list[Any]) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.exists() and path.is_file():
            return path
    return None


def _source_collection(path: str) -> str:
    if path.startswith("_manifest/") or "/_manifest/" in path:
        return "manifest"
    if path.startswith("Sunshine shared folders/"):
        return "sunshine_shared_folders"
    if path.startswith("archive-2026-05-25/"):
        return "archive"
    if path.startswith("google-drive-delta-2026-05-25/"):
        return "google_drive_delta"
    if path.startswith("Paige Agent Sunshine Files/"):
        return "paige_agent_files"
    if path.startswith("From Mac Sunshine Pass 2026-05-25/"):
        return "from_mac_pass"
    return "other"


def _source_collection_sql_predicate(source_collection: str) -> str | None:
    predicates = {
        "manifest": "(relative_path like '_manifest/%' or relative_path like '%/_manifest/%' or source_path like '%/_manifest/%')",
        "sunshine_shared_folders": "(relative_path like 'Sunshine shared folders/%' or source_path like '%/Sunshine shared folders/%')",
        "archive": "(relative_path like 'archive-2026-05-25/%' or source_path like '%/archive-2026-05-25/%')",
        "google_drive_delta": "(relative_path like 'google-drive-delta-2026-05-25/%' or source_path like '%/google-drive-delta-2026-05-25/%')",
        "paige_agent_files": "(relative_path like 'Paige Agent Sunshine Files/%' or source_path like '%/Paige Agent Sunshine Files/%')",
        "from_mac_pass": "(relative_path like 'From Mac Sunshine Pass 2026-05-25/%' or source_path like '%/From Mac Sunshine Pass 2026-05-25/%')",
    }
    return predicates.get(source_collection)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _clean_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags:
        normalized = str(tag).strip()
        if normalized and normalized not in seen:
            cleaned.append(normalized)
            seen.add(normalized)
    return cleaned


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _sample_routed_sources(results: list[dict[str, Any]], *, per_bucket: int, seed: int) -> set[str]:
    if per_bucket <= 0:
        return set()
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for result in results:
        if result.get("route_status") != "route_candidate":
            continue
        source_path = result.get("source_path") or result.get("sample_path")
        if not source_path:
            continue
        bucket = (
            str(result.get("final_class") or "unknown"),
            str(result.get("extraction_strategy") or "unknown"),
            str(result.get("quality") or "unknown"),
            str(result.get("top_tag_candidate") or "none"),
        )
        buckets.setdefault(bucket, []).append(result)

    rng = random.Random(seed)
    sampled: set[str] = set()
    for rows in buckets.values():
        selected = rng.sample(rows, min(per_bucket, len(rows)))
        for result in selected:
            sampled.add(str(result.get("source_path") or result.get("sample_path")))
    return sampled


def _review_item_from_row(row: sqlite3.Row, *, model_usage_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    result = json.loads(row["result_json"])
    return {
        "id": row["id"],
        "source_path": row["source_path"],
        "relative_path": row["relative_path"],
        "route_status": row["route_status"],
        "review_reason": row["review_reason"],
        "status": row["status"],
        "proposed_class": row["proposed_class"],
        "proposed_tag": row["proposed_tag"],
        "secondary_tags": _json_list(row["secondary_tags_json"]),
        "extraction_text_snippet": row["extraction_text_snippet"],
        "confidence": row["confidence"],
        "warnings": _json_list(row["warnings_json"]),
        "display_warnings": _display_warnings(_json_list(row["warnings_json"])),
        "ocr_evidence": _ocr_evidence_from_result(result, row["extraction_text_snippet"]),
        "ocr_quality_label": _row_value(row, "ocr_quality_label"),
        "run_id": _row_value(row, "run_id"),
        "run_key": _row_value(row, "run_key"),
        "run_preset_key": _row_value(row, "run_preset_key"),
        "embedding_provider": _row_value(row, "embedding_provider"),
        "llm_tag_provider": _row_value(row, "llm_tag_provider"),
        "ocr_fallback_provider": _row_value(row, "ocr_fallback_provider"),
        "enable_llm_tags": bool(_row_value(row, "enable_llm_tags")) if _row_value(row, "enable_llm_tags") is not None else None,
        "decision": row["decision"],
        "correct_class": row["correct_class"],
        "correct_tag": row["correct_tag"],
        "correct_secondary_tags": _json_list(row["correct_secondary_tags_json"]),
        "correct_destination_path": row["correct_destination_path"],
        "correct_placement_year": row["correct_placement_year"],
        "correct_privacy": row["correct_privacy"],
        "review_stage": row["review_stage"],
        "priority": row["priority"],
        "assigned_reviewer": row["assigned_reviewer"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "model_usage_summary": model_usage_summary or _empty_review_item_model_usage_summary(),
        "result": result,
    }


def _review_item_model_usage_summary(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    run_id = _row_value(row, "run_id")
    if run_id is None:
        return _empty_review_item_model_usage_summary()

    source_path = str(row["source_path"] or "")
    relative_path = str(row["relative_path"] or "")
    rows = connection.execute(
        """
        select purpose, provider, model, status, runtime_ms, total_tokens, estimated_cost_usd, cost_basis
        from pipeline_run_model_usage
        where run_id = ?
          and (
                source_path = ?
             or relative_path = ?
          )
        order by id asc
        """,
        (run_id, source_path, relative_path),
    ).fetchall()
    scope = "file"
    if not rows:
        rows = connection.execute(
            """
            select purpose, provider, model, status, runtime_ms, total_tokens, estimated_cost_usd, cost_basis
            from pipeline_run_model_usage
            where run_id = ?
            order by id asc
            """,
            (run_id,),
        ).fetchall()
        scope = "run" if rows else "none"

    total_calls = len(rows)
    failed_calls = sum(1 for usage in rows if str(usage["status"] or "").lower() in {"failed", "error"})
    external_calls = sum(1 for usage in rows if str(usage["cost_basis"] or "").lower() == "external")
    local_calls = sum(1 for usage in rows if str(usage["cost_basis"] or "").lower() == "local")
    unknown_external_cost_calls = sum(
        1
        for usage in rows
        if str(usage["cost_basis"] or "").lower() == "external" and usage["estimated_cost_usd"] is None
    )
    purposes = sorted({str(usage["purpose"] or "unknown") for usage in rows})
    providers = sorted({
        f"{str(usage['provider'] or 'unknown')}:{str(usage['model'] or 'unknown')}"
        for usage in rows
    })
    return {
        "scope": scope,
        "total_calls": total_calls,
        "failed_calls": failed_calls,
        "external_calls": external_calls,
        "local_calls": local_calls,
        "unknown_external_cost_calls": unknown_external_cost_calls,
        "total_runtime_ms": sum(int(usage["runtime_ms"] or 0) for usage in rows),
        "total_tokens": sum(int(usage["total_tokens"] or 0) for usage in rows),
        "estimated_external_cost_usd": round(sum(float(usage["estimated_cost_usd"] or 0) for usage in rows), 6),
        "purposes": purposes,
        "providers": providers,
    }


def _empty_review_item_model_usage_summary() -> dict[str, Any]:
    return {
        "scope": "none",
        "total_calls": 0,
        "failed_calls": 0,
        "external_calls": 0,
        "local_calls": 0,
        "unknown_external_cost_calls": 0,
        "total_runtime_ms": 0,
        "total_tokens": 0,
        "estimated_external_cost_usd": 0.0,
        "purposes": [],
        "providers": [],
    }


def _file_index_from_row(row: sqlite3.Row) -> dict[str, Any]:
    latest_result = _json_object(row["latest_result_json"])
    return {
        "id": row["id"],
        "source_path": row["source_path"],
        "relative_path": row["relative_path"],
        "sample_path": row["sample_path"],
        "filename": row["filename"],
        "extension": row["extension"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "source_collection": row["source_collection"],
        "source_mtime": row["source_mtime"],
        "content_class": row["content_class"],
        "latest_run_id": row["latest_run_id"],
        "latest_run_key": _row_value(row, "latest_run_key"),
        "latest_run_preset_key": _row_value(row, "latest_run_preset_key"),
        "latest_embedding_provider": _row_value(row, "latest_embedding_provider"),
        "latest_enable_llm_tags": bool(_row_value(row, "latest_enable_llm_tags")) if _row_value(row, "latest_enable_llm_tags") is not None else None,
        "latest_llm_tag_provider": _row_value(row, "latest_llm_tag_provider"),
        "latest_ocr_fallback_provider": _row_value(row, "latest_ocr_fallback_provider"),
        "latest_result": latest_result,
        "extraction_text_snippet": row["extraction_text_snippet"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_value(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _run_snapshot(connection: sqlite3.Connection, run_id: int | None) -> dict[str, Any]:
    if run_id is None:
        return {}
    row = connection.execute(
        """
        select id, run_key, preset_key, embedding_provider, llm_tag_provider,
               ocr_fallback_provider, enable_llm_tags
        from pipeline_runs
        where id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return {"run_id": run_id}
    return {
        "run_id": row["id"],
        "run_key": row["run_key"],
        "run_preset_key": row["preset_key"],
        "embedding_provider": row["embedding_provider"],
        "llm_tag_provider": row["llm_tag_provider"],
        "ocr_fallback_provider": row["ocr_fallback_provider"],
        "enable_llm_tags": row["enable_llm_tags"],
    }


def _file_identity(file_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": file_record["id"],
        "filename": file_record["filename"],
        "source_path": file_record["source_path"],
        "relative_path": file_record["relative_path"],
        "sample_path": file_record.get("sample_path"),
        "extension": file_record.get("extension"),
        "mime_type": file_record.get("mime_type"),
        "size_bytes": file_record.get("size_bytes"),
        "source_collection": file_record.get("source_collection"),
        "source_mtime": file_record.get("source_mtime"),
        "content_class": file_record.get("content_class"),
        "latest_run_id": file_record.get("latest_run_id"),
        "latest_run_key": file_record.get("latest_run_key"),
        "latest_run_preset_key": file_record.get("latest_run_preset_key"),
        "latest_embedding_provider": file_record.get("latest_embedding_provider"),
        "latest_enable_llm_tags": file_record.get("latest_enable_llm_tags"),
        "latest_llm_tag_provider": file_record.get("latest_llm_tag_provider"),
        "latest_ocr_fallback_provider": file_record.get("latest_ocr_fallback_provider"),
        "created_at": file_record.get("created_at"),
        "updated_at": file_record.get("updated_at"),
    }


def _file_search_item_from_row(row: sqlite3.Row, *, review_status: str | None = None) -> dict[str, Any]:
    file_record = _file_index_from_row(row)
    latest_result = file_record.get("latest_result") or {}
    return {
        "id": file_record["id"],
        "filename": file_record["filename"],
        "compact_path": _compact_path(file_record["relative_path"]),
        "source_path": file_record["source_path"],
        "relative_path": file_record["relative_path"],
        "extension": file_record.get("extension"),
        "source_collection": file_record.get("source_collection"),
        "content_class": file_record.get("content_class"),
        "primary_tag": latest_result.get("top_tag_candidate"),
        "secondary_tags": latest_result.get("secondary_tags") or [],
        "route_status": latest_result.get("route_status"),
        "quality": latest_result.get("quality"),
        "review_status": review_status,
        "placement_status": latest_result.get("placement_status"),
        "text_snippet": _short_text(file_record.get("extraction_text_snippet"), 240),
        "latest_run_id": file_record.get("latest_run_id"),
        "latest_run_key": file_record.get("latest_run_key"),
        "latest_run_preset_key": file_record.get("latest_run_preset_key"),
        "latest_embedding_provider": file_record.get("latest_embedding_provider"),
        "latest_enable_llm_tags": file_record.get("latest_enable_llm_tags"),
        "latest_llm_tag_provider": file_record.get("latest_llm_tag_provider"),
        "latest_ocr_fallback_provider": file_record.get("latest_ocr_fallback_provider"),
        "updated_at": file_record.get("updated_at"),
    }


def _review_status_by_source(connection: sqlite3.Connection, source_paths: list[str]) -> dict[str, str]:
    if not source_paths:
        return {}
    placeholders = ", ".join("?" for _ in source_paths)
    rows = connection.execute(
        f"""
        select source_path, status
        from review_items
        where source_path in ({placeholders})
        order by updated_at desc, id desc
        """,
        source_paths,
    ).fetchall()
    statuses: dict[str, str] = {}
    for row in rows:
        statuses.setdefault(str(row["source_path"]), str(row["status"]))
    return statuses


def _file_search_where(
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
    run_id: int | None = None,
) -> tuple[str, list[Any]]:
    predicates: list[str] = []
    params: list[Any] = []
    if q:
        like = f"%{q}%"
        text_predicate = "(filename like ? or relative_path like ? or source_path like ?"
        params.extend([like, like, like])
        if len(q.strip()) >= 2:
            text_predicate += " or extraction_text_snippet like ?"
            params.append(like)
        text_predicate += ")"
        predicates.append(text_predicate)
    if source_collection:
        predicates.append("source_collection = ?")
        params.append(source_collection)
    if extension:
        normalized = extension if extension.startswith(".") else f".{extension}"
        predicates.append("extension = ?")
        params.append(normalized.lower())
    if content_class:
        predicates.append("content_class = ?")
        params.append(content_class)
    if primary_tag:
        predicates.append("json_extract(latest_result_json, '$.top_tag_candidate') = ?")
        params.append(primary_tag)
    if secondary_tag:
        predicates.append("json_extract(latest_result_json, '$.secondary_tags') like ?")
        params.append(f"%{secondary_tag}%")
    if route_status:
        predicates.append("json_extract(latest_result_json, '$.route_status') = ?")
        params.append(route_status)
    if ocr_quality:
        predicates.append("json_extract(latest_result_json, '$.quality') = ?")
        params.append(ocr_quality)
    if warning_type:
        predicates.append("json_extract(latest_result_json, '$.warnings') like ?")
        params.append(f"%{warning_type}%")
    if placement_status:
        predicates.append("json_extract(latest_result_json, '$.placement_status') = ?")
        params.append(placement_status)
    if run_id is not None:
        predicates.append("latest_run_id = ?")
        params.append(run_id)
    if review_status:
        if review_status == "none":
            predicates.append("not exists (select 1 from review_items where review_items.source_path = file_index.source_path)")
        else:
            predicates.append(
                """
                exists (
                    select 1 from review_items
                    where review_items.source_path = file_index.source_path
                    and review_items.status = ?
                )
                """
            )
            params.append(review_status)
    if not predicates:
        return "", params
    return "where " + " and ".join(predicates), params


def _review_items_where(
    *,
    status: str = "open",
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
) -> tuple[str, list[Any]]:
    predicates: list[str] = []
    params: list[Any] = []
    if status != "all":
        predicates.append("status = ?")
        params.append(status)
    if q:
        like = f"%{q}%"
        predicates.append("(relative_path like ? or source_path like ? or extraction_text_snippet like ?)")
        params.extend([like, like, like])
    if route_status:
        predicates.append("route_status = ?")
        params.append(route_status)
    if review_reason:
        predicates.append("review_reason = ?")
        params.append(review_reason)
    if primary_tag:
        predicates.append("proposed_tag = ?")
        params.append(primary_tag)
    if secondary_tag:
        predicates.append("secondary_tags_json like ?")
        params.append(f"%{secondary_tag}%")
    if content_class:
        predicates.append("proposed_class = ?")
        params.append(content_class)
    if quality:
        predicates.append("json_extract(result_json, '$.quality') = ?")
        params.append(quality)
    if placement_status:
        predicates.append("json_extract(result_json, '$.placement_status') = ?")
        params.append(placement_status)
    confidence_predicate = _confidence_bucket_predicate(confidence_bucket)
    if confidence_predicate:
        predicates.append(confidence_predicate)
    if warning_type:
        predicates.append("warnings_json like ?")
        params.append(f"%{warning_type}%")
    if source_collection:
        collection_predicate = _source_collection_sql_predicate(source_collection)
        if collection_predicate:
            predicates.append(collection_predicate)
    if run_id is not None:
        predicates.append("run_id = ?")
        params.append(run_id)
    if run_preset_key:
        predicates.append("run_preset_key = ?")
        params.append(run_preset_key)
    if embedding_provider:
        predicates.append("embedding_provider = ?")
        params.append(embedding_provider)
    if llm_tag_provider:
        predicates.append("llm_tag_provider = ?")
        params.append(llm_tag_provider)
    if ocr_fallback_provider:
        predicates.append("ocr_fallback_provider = ?")
        params.append(ocr_fallback_provider)
    fallback_used_predicate = _ocr_fallback_used_predicate(ocr_fallback_used, warnings_column="warnings_json")
    if fallback_used_predicate:
        predicates.append(fallback_used_predicate)
    if enable_llm_tags is not None:
        predicates.append("enable_llm_tags = ?")
        params.append(1 if enable_llm_tags else 0)
    if not predicates:
        return "", params
    return "where " + " and ".join(predicates), params


def _confidence_bucket_expression() -> str:
    return """
        case
            when confidence is null then 'missing'
            when confidence >= 0.85 then 'high'
            when confidence >= 0.70 then 'medium'
            else 'low'
        end
    """


def _confidence_bucket_predicate(bucket: str | None) -> str | None:
    if not bucket:
        return None
    normalized = bucket.strip().lower()
    if normalized == "high":
        return "confidence >= 0.85"
    if normalized == "medium":
        return "confidence >= 0.70 and confidence < 0.85"
    if normalized == "low":
        return "confidence < 0.70"
    if normalized == "missing":
        return "confidence is null"
    return None


def _ocr_fallback_used_expression(warnings_column: str) -> str:
    return f"""
        case
            when {warnings_column} like '%ocr_fallback_used:%' then 'used'
            else 'not_used'
        end
    """


def _ocr_fallback_used_predicate(value: str | None, *, warnings_column: str) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"used", "true", "yes", "1"}:
        return f"{warnings_column} like '%ocr_fallback_used:%'"
    if normalized in {"not_used", "false", "no", "0"}:
        return f"({warnings_column} is null or {warnings_column} not like '%ocr_fallback_used:%')"
    return None


def _file_search_order(sort: str) -> str:
    orders = {
        "updated_desc": "order by updated_at desc, id desc",
        "updated_asc": "order by updated_at asc, id asc",
        "filename": "order by filename collate nocase asc, id asc",
        "primary_tag": "order by json_extract(latest_result_json, '$.top_tag_candidate') collate nocase asc, filename asc",
        "quality": "order by json_extract(latest_result_json, '$.quality') collate nocase asc, filename asc",
    }
    return orders.get(sort, orders["updated_desc"])


def _facet_counts(connection: sqlite3.Connection, expression: str, where_sql: str, params: list[Any]) -> dict[str, int]:
    rows = connection.execute(
        f"""
        select {expression} as value, count(*) as count
        from file_index
        {where_sql}
        group by {expression}
        order by count desc, value asc
        limit 50
        """,
        params,
    ).fetchall()
    return {str(row["value"] or "unknown"): int(row["count"]) for row in rows}


def _table_facet_counts(connection: sqlite3.Connection, table: str, expression: str, where_sql: str, params: list[Any]) -> dict[str, int]:
    rows = connection.execute(
        f"""
        select {expression} as value, count(*) as count
        from {table}
        {where_sql}
        group by {expression}
        order by count desc, value asc
        limit 50
        """,
        params,
    ).fetchall()
    return {str(row["value"] or "unknown"): int(row["count"]) for row in rows}


def _review_json_array_facet_counts(
    connection: sqlite3.Connection,
    column: str,
    where_sql: str,
    params: list[Any],
    *,
    split_prefix: bool = False,
) -> dict[str, int]:
    rows = connection.execute(
        f"""
        select {column} from review_items
        {where_sql}
        limit 5000
        """,
        params,
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        values = _json_list(row[column])
        for value in values:
            key = value.split(":", 1)[0] if split_prefix else value
            if key:
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:50])


def _review_status_facet_counts(connection: sqlite3.Connection, where_sql: str, params: list[Any]) -> dict[str, int]:
    rows = connection.execute(
        f"""
        select coalesce(
            (select status from review_items where review_items.source_path = file_index.source_path order by updated_at desc, id desc limit 1),
            'none'
        ) as value, count(*) as count
        from file_index
        {where_sql}
        group by value
        order by count desc, value asc
        """,
        params,
    ).fetchall()
    return {str(row["value"] or "none"): int(row["count"]) for row in rows}


def _json_array_facet_counts(
    connection: sqlite3.Connection,
    column: str,
    path: str,
    where_sql: str,
    params: list[Any],
) -> dict[str, int]:
    rows = connection.execute(
        f"""
        select {column} from file_index
        {where_sql}
        limit 5000
        """,
        params,
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        payload = _json_object(row[column])
        values = payload
        for part in path.strip("$.").split("."):
            if isinstance(values, dict):
                values = values.get(part)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            key = str(value).split(":", 1)[0] if path.endswith("warnings") else str(value)
            if key:
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:50])


def _compact_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) <= 4:
        return path
    return f"{'/'.join(parts[:2])}/.../{'/'.join(parts[-2:])}"


def _short_text(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _ocr_fallback_provider(warnings: list[Any]) -> str | None:
    for warning in warnings:
        text = str(warning)
        if text.startswith("ocr_fallback_used:"):
            return text.split(":", 1)[1]
    return None


def _golden_label_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "review_item_id": row["review_item_id"],
        "source_path": row["source_path"],
        "relative_path": row["relative_path"],
        "sample_path": row["sample_path"],
        "extracted_text_snippet": row["extracted_text_snippet"],
        "content_class": row["content_class"],
        "correct_primary_tag": row["correct_primary_tag"],
        "correct_secondary_tags": _json_list(row["correct_secondary_tags_json"]),
        "ocr_quality_label": row["ocr_quality_label"],
        "expected_review_required": bool(row["expected_review_required"]) if row["expected_review_required"] is not None else None,
        "sensitive_record": bool(row["sensitive_record"]),
        "correct_destination_path": row["correct_destination_path"],
        "correct_placement_year": row["correct_placement_year"],
        "correct_privacy": row["correct_privacy"],
        "reviewer": row["reviewer"],
        "notes": row["notes"],
        "proposed_tag": row["proposed_tag"],
        "proposed_secondary_tags": _json_list(row["proposed_secondary_tags_json"]),
        "proposed_confidence": row["proposed_confidence"],
        "reviewed_at": row["reviewed_at"] or row["updated_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _pipeline_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    run_metadata = _json_object(row["run_metadata_json"])
    return {
        "id": row["id"],
        "run_key": row["run_key"],
        "preset_key": row["preset_key"],
        "status": row["status"],
        "input_root": row["input_root"],
        "output_dir": row["output_dir"],
        "command": _json_list(row["command_json"]),
        "embedding_provider": row["embedding_provider"],
        "enable_llm_tags": bool(row["enable_llm_tags"]),
        "llm_tag_provider": row["llm_tag_provider"],
        "ocr_fallback_provider": row["ocr_fallback_provider"],
        "semantic_index_path": row["semantic_index_path"],
        "run_metadata": run_metadata,
        "run_role": run_metadata.get("run_role") or "test",
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "processed_count": row["processed_count"],
        "route_candidate_count": row["route_candidate_count"],
        "review_required_count": row["review_required_count"],
        "failed_count": row["failed_count"],
        "summary": _json_object(row["summary_json"]),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _pipeline_eval_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "eval_key": row["eval_key"],
        "labels_db": row["labels_db"],
        "output_dir": row["output_dir"],
        "status": row["status"],
        "total_golden_labels": row["total_golden_labels"],
        "evaluated_predictions": row["evaluated_predictions"],
        "primary_accuracy": row["primary_accuracy"],
        "content_class_accuracy": row["content_class_accuracy"],
        "secondary_precision": row["secondary_precision"],
        "secondary_recall": row["secondary_recall"],
        "ocr_quality_accuracy": row["ocr_quality_accuracy"],
        "ocr_acceptable_rate": row["ocr_acceptable_rate"],
        "review_routing_accuracy": row["review_routing_accuracy"],
        "review_false_accepts": row["review_false_accepts"],
        "embedding_success_rate": row["embedding_success_rate"],
        "semantic_same_family_top5_rate": row["semantic_same_family_top5_rate"],
        "placement_destination_accuracy": row["placement_destination_accuracy"],
        "source_file_mutations": row["source_file_mutations"],
        "acceptance_gate_status": row["acceptance_gate_status"],
        "production_readiness_status": row["production_readiness_status"],
        "failure_count": row["failure_count"],
        "model_usage": _json_object(row["model_usage_json"]),
        "summary": _json_object(row["summary_json"]),
        "run_metadata": _json_object(row["run_metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _pipeline_run_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "timestamp": row["timestamp"],
        "level": row["level"],
        "node": row["node"],
        "source_path": row["source_path"],
        "relative_path": row["relative_path"],
        "message": row["message"],
        "payload": _json_object(row["payload_json"]),
    }


def _model_usage_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "source_path": row["source_path"],
        "relative_path": row["relative_path"],
        "node": row["node"],
        "purpose": row["purpose"],
        "provider": row["provider"],
        "model": row["model"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "runtime_ms": row["runtime_ms"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "total_tokens": row["total_tokens"],
        "estimated_cost_usd": row["estimated_cost_usd"],
        "cost_basis": row["cost_basis"],
        "request_id": row["request_id"],
        "trace_id": row["trace_id"],
        "error": row["error"],
        "metadata": _json_object(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _display_warnings(warnings: list[str]) -> list[str]:
    hidden_prefixes = ("ocr_fallback_note:", "ocr_original_snippet:", "ocr_fallback_snippet:")
    return [warning for warning in warnings if not str(warning).startswith(hidden_prefixes)]


def _ocr_evidence_from_result(result: dict[str, Any], fallback_final_snippet: str | None = None) -> dict[str, Any]:
    evidence = result.get("ocr_evidence")
    if isinstance(evidence, dict):
        return evidence
    warnings = result.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = []
    fallback_provider = _warning_value(warnings, "ocr_fallback_used:")
    fallback_reason = _warning_value(warnings, "ocr_fallback_reason:")
    fallback_snippet = _warning_value(warnings, "ocr_fallback_snippet:")
    if fallback_provider and not fallback_snippet:
        fallback_snippet = fallback_final_snippet
    return {
        "fallback_used": bool(fallback_provider),
        "fallback_provider": fallback_provider,
        "fallback_reason": fallback_reason,
        "fallback_notes": _warning_values(warnings, "ocr_fallback_note:"),
        "original_text_snippet": _warning_value(warnings, "ocr_original_snippet:"),
        "fallback_text_snippet": fallback_snippet,
        "final_text_snippet": result.get("extraction_text_snippet") or fallback_final_snippet,
    }


def _warning_value(warnings: list[Any], prefix: str) -> str | None:
    values = _warning_values(warnings, prefix)
    return values[0] if values else None


def _warning_values(warnings: list[Any], prefix: str) -> list[str]:
    return [str(warning)[len(prefix) :] for warning in warnings if str(warning).startswith(prefix)]
