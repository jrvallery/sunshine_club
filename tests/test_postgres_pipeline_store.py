from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sunshine_api.postgres_pipeline_store import PostgresPipelineStore
from sunshine_api.services.imports import import_langgraph_output_to_postgres
from sunshine_api.services.vector_index import rebuild_qdrant_from_postgres
from sunshine_extraction.providers.vectorstores.base import VectorStoreUpsertResult


class _Cursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.committed = False
        self.closed = False

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
        self.executed.append((query, params))
        if "returning id" in query.lower():
            return _Cursor(("00000000-0000-0000-0000-000000000123",))
        return _Cursor()

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_postgres_pipeline_store_imports_v2_artifacts(tmp_path: Path) -> None:
    output_dir = _postgres_import_artifacts(tmp_path)
    connection = _FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    result = store.import_langgraph_output(output_dir, run_key="run-1", preset_key="qa")

    assert result["run_id"] == "00000000-0000-0000-0000-000000000123"
    assert result["imported"] == {
        "pipeline_results": 1,
        "pipeline_chunks": 1,
        "pipeline_chunk_embeddings": 1,
        "model_usage": 1,
        "provider_attempts": 1,
        "document_segments": 1,
        "review_items": 1,
    }
    assert connection.committed is True
    assert connection.closed is True
    executed_sql = "\n".join(query for query, _params in connection.executed)
    assert "insert into pipeline_runs" in executed_sql
    assert "insert into pipeline_results" in executed_sql
    assert "insert into pipeline_chunks" in executed_sql
    assert "insert into pipeline_chunk_embeddings" in executed_sql
    assert "insert into model_usage" in executed_sql
    assert "insert into provider_attempts" in executed_sql
    assert "insert into document_segments" in executed_sql
    assert "insert into review_items_v2" in executed_sql
    run_params = next(params for query, params in connection.executed if "insert into pipeline_runs" in query)
    run_summary = json.loads(run_params[3])
    assert run_summary["artifact_manifest"]["artifacts"][0]["name"] == "sample-pipeline-results.jsonl"
    assert run_summary["graph_runtime"]["latency_status"] == "ok"
    assert run_summary["providers"]["embedding_provider"] == "cortex"
    assert run_params[4:11] == ("cortex", "local-embedding", None, None, "current", "qdrant", "sunshine-test")
    assert any("[0.1,0.2,0.3]" in str(params) for _query, params in connection.executed)
    provider_attempt_params = next(params for query, params in connection.executed if "insert into provider_attempts" in query)
    assert provider_attempt_params[1:4] == ("/source/a.pdf", "Sunshine/a.pdf", "current")
    review_item_params = next(params for query, params in connection.executed if "insert into review_items_v2" in query)
    assert review_item_params[1:8] == (
        "/source/a.pdf",
        "Sunshine/a.pdf",
        None,
        "tag_confidence_below_threshold",
        "document",
        "meeting_records",
        '["meeting_minutes"]',
    )


def test_postgres_import_service_wraps_store(tmp_path: Path) -> None:
    output_dir = _postgres_import_artifacts(tmp_path)
    connection = _FakeConnection()

    result = import_langgraph_output_to_postgres(
        output_dir,
        run_key="service-run",
        preset_key="qa",
        database_url="postgresql://local/test",
        connect_factory=lambda _url: connection,
    )

    assert result["run_key"] == "service-run"
    assert result["imported"]["pipeline_chunk_embeddings"] == 1
    assert connection.committed is True


def test_postgres_pipeline_store_reports_runtime_summary() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if normalized.startswith("select count(*)"):
                table_counts = {
                    "pipeline_runs": 2,
                    "pipeline_results": 7,
                    "review_items_v2": 1,
                    "model_usage": 3,
                    "provider_attempts": 4,
                    "document_segments": 5,
                    "pipeline_chunks": 6,
                    "pipeline_chunk_embeddings": 6,
                }
                for table, count in table_counts.items():
                    if f"from {table}" in normalized:
                        return _Cursor((count,))
            if "from pipeline_runs r" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "run-id",
                            "run_key": "run-1",
                            "preset_key": "qa",
                            "output_dir": "/tmp/run",
                            "status": "succeeded",
                            "local_only": True,
                            "embedding_provider": "cortex",
                            "llm_provider": "cortex",
                            "extraction_provider": "docling",
                            "vector_store_provider": "qdrant",
                            "vector_store_collection": "sunshine_chunks",
                            "started_at": None,
                            "finished_at": None,
                            "created_at": None,
                            "updated_at": None,
                            "summary": {"ok": True},
                            "result_count": 7,
                            "review_required_count": 1,
                            "model_usage_count": 3,
                            "provider_attempt_count": 4,
                            "document_segment_count": 5,
                        }
                    ]
                )
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    summary = store.runtime_summary()

    assert summary["pipeline_runs"] == 2
    assert summary["pipeline_results"] == 7
    assert summary["pipeline_chunk_embeddings"] == 6
    assert summary["recent_runs"][0]["run_key"] == "run-1"
    assert summary["recent_runs"][0]["result_count"] == 7
    assert connection.closed is True


def test_postgres_pipeline_store_lists_review_items() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            return _Cursor(
                rows=[
                    {
                        "id": "review-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "preset_key": "qa",
                        "source_path": "/source/a.pdf",
                        "relative_path": "Sunshine/a.pdf",
                        "segment_id": None,
                        "status": "open",
                        "review_reason": "tag_confidence_below_threshold",
                        "proposed_class": "document",
                        "proposed_tag": "meeting_records",
                        "proposed_secondary_tags": ["meeting_minutes"],
                        "corrected_class": None,
                        "corrected_tag": None,
                        "corrected_secondary_tags": [],
                        "notes": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            )

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    rows = store.list_review_items(run_key="run-1", limit=10)

    assert rows[0]["run_key"] == "run-1"
    assert rows[0]["proposed_tag"] == "meeting_records"
    assert connection.executed[0][1] == ("run-1", 10)
    assert connection.closed is True


def test_postgres_pipeline_store_gets_run_detail_by_key() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            normalized = " ".join(query.lower().split())
            if "from pipeline_runs r" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "run-id",
                            "run_key": "run-detail",
                            "preset_key": "qa",
                            "output_dir": "/tmp/run",
                            "status": "succeeded",
                            "local_only": True,
                            "embedding_provider": "cortex",
                            "llm_provider": None,
                            "extraction_provider": "current",
                            "vector_store_provider": "qdrant",
                            "vector_store_collection": "sunshine-test",
                            "started_at": None,
                            "finished_at": None,
                            "created_at": None,
                            "updated_at": None,
                            "summary": {"graph_runtime": {"latency_status": "ok"}},
                            "result_count": 1,
                            "review_required_count": 0,
                            "model_usage_count": 1,
                            "provider_attempt_count": 1,
                            "document_segment_count": 1,
                        }
                    ]
                )
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    run = store.get_pipeline_run(run_key="run-detail")

    assert run["run_key"] == "run-detail"
    assert run["summary"]["graph_runtime"]["latency_status"] == "ok"
    assert connection.closed is True


def test_postgres_pipeline_store_deletes_run_with_cascade_counts() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from pipeline_runs r where r.run_key" in normalized:
                return _Cursor(
                    {
                        "id": "run-id",
                        "run_key": "run-delete",
                        "preset_key": "qa",
                        "output_dir": "/tmp/run",
                        "status": "succeeded",
                        "created_at": None,
                        "updated_at": None,
                        "pipeline_results": 2,
                        "pipeline_chunks": 3,
                        "pipeline_chunk_embeddings": 3,
                        "model_usage": 4,
                        "provider_attempts": 5,
                        "document_segments": 6,
                        "review_items": 7,
                    }
                )
            return _Cursor()

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    result = store.delete_pipeline_run(run_key="run-delete")

    assert result["deleted"] is True
    assert result["deleted_counts"] == {
        "pipeline_runs": 1,
        "pipeline_results": 2,
        "pipeline_chunks": 3,
        "pipeline_chunk_embeddings": 3,
        "model_usage": 4,
        "provider_attempts": 5,
        "document_segments": 6,
        "review_items": 7,
    }
    assert any(query.strip().lower().startswith("delete from pipeline_runs") for query, _params in connection.executed)
    assert connection.executed[-1][1] == ("run-id",)
    assert connection.committed is True
    assert connection.closed is True


def test_postgres_pipeline_store_builds_run_report_from_normalized_tables() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from pipeline_runs r" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "run-id",
                            "run_key": "run-report",
                            "preset_key": "qa",
                            "output_dir": "/tmp/run",
                            "status": "succeeded",
                            "local_only": True,
                            "embedding_provider": "cortex",
                            "llm_provider": "cortex",
                            "extraction_provider": "docling",
                            "vector_store_provider": "qdrant",
                            "vector_store_collection": "sunshine-test",
                            "started_at": None,
                            "finished_at": None,
                            "created_at": None,
                            "updated_at": None,
                            "summary": {"counts": {"pipeline_results": 1}},
                            "result_count": 1,
                            "review_required_count": 1,
                            "model_usage_count": 1,
                            "provider_attempt_count": 1,
                            "document_segment_count": 1,
                        }
                    ]
                )
            if "from pipeline_results pr" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "result-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "route_status": "review_segment_boundary",
                            "review_reason": "segment_requires_review",
                            "final_class": "scanned_document",
                            "extraction_strategy": "ocr_page_level",
                            "extraction_status": "extracted",
                            "quality": "ok",
                            "top_tag_candidate": "scrapbooks",
                            "secondary_tags": ["scrapbook_page"],
                            "tag_confidence": 0.82,
                            "result": {"text_snippet": "Scrapbook page text"},
                            "created_at": None,
                            "updated_at": None,
                        }
                    ]
                )
            if "from review_items_v2 ri" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "review-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "preset_key": "qa",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "segment_id": "scrapbook:segment-001",
                            "status": "open",
                            "review_reason": "segment_requires_review",
                            "proposed_class": "scanned_document",
                            "proposed_tag": "scrapbooks",
                            "proposed_secondary_tags": ["scrapbook_page"],
                            "corrected_class": None,
                            "corrected_tag": None,
                            "corrected_secondary_tags": [],
                            "notes": None,
                            "created_at": None,
                            "updated_at": None,
                        }
                    ]
                )
            if "from model_usage mu" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "usage-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "node": "embed_chunks",
                            "purpose": "chunk_embedding",
                            "provider": "cortex",
                            "model": "local-embedding",
                            "status": "ok",
                            "call_count": 1,
                            "input_tokens": None,
                            "output_tokens": None,
                            "total_tokens": None,
                            "runtime_ms": 12,
                            "local_only": True,
                            "metadata": {},
                            "created_at": None,
                        }
                    ]
                )
            if "from provider_attempts pa" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "attempt-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "provider": "docling",
                            "capability": "extraction",
                            "status": "extracted",
                            "strategy": "ocr_page_level",
                            "runtime_ms": 420,
                            "warnings": [],
                            "metadata": {"local_only": True},
                            "created_at": None,
                        }
                    ]
                )
            if "from document_segments ds" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "segment-row-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "segment_id": "scrapbook:segment-001",
                            "parent_file_id": "file-id",
                            "page_start": 1,
                            "page_end": 4,
                            "segment_index": 1,
                            "segment_type": "scrapbook_page_group",
                            "segment_title": "Scrapbook pages 1-4",
                            "segment_confidence": 0.62,
                            "requires_segment_review": True,
                            "boundary_evidence": ["matched:scrapbook", "fixed_window:4_pages"],
                            "metadata": {"policy": "review_only"},
                            "created_at": None,
                        }
                    ]
                )
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    report = store.get_run_report(run_key="run-report", limit=10)

    assert report["run"]["run_key"] == "run-report"
    assert report["summary"]["result_count"] == 1
    assert report["summary"]["open_review_item_count"] == 1
    assert report["summary"]["model_call_count"] == 1
    assert report["summary"]["local_model_call_count"] == 1
    assert report["summary"]["segment_review_count"] == 1
    assert report["summary"]["segment_type"] == {"scrapbook_page_group": 1}
    assert report["results"][0]["top_tag_candidate"] == "scrapbooks"
    assert report["review_items"][0]["segment_id"] == "scrapbook:segment-001"
    assert report["model_usage"][0]["provider"] == "cortex"
    assert report["provider_attempts"][0]["provider"] == "docling"
    assert report["document_segments"][0]["segment_type"] == "scrapbook_page_group"
    assert report["document_segments"][0]["requires_segment_review"] is True
    assert any(params == ("run-report", 10) for _query, params in connection.executed)
    assert connection.closed is True


def test_postgres_pipeline_store_records_review_decision() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "select id, proposed_class" in normalized:
                return _Cursor(
                    {
                        "id": "review-id",
                        "proposed_class": "document",
                        "proposed_tag": "meeting_records",
                        "proposed_secondary_tags": ["meeting_minutes"],
                        "notes": "existing",
                    }
                )
            if "from review_items_v2 ri" in normalized:
                return _Cursor(
                    {
                        "id": "review-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "preset_key": "qa",
                        "source_path": "/source/a.pdf",
                        "relative_path": "Sunshine/a.pdf",
                        "segment_id": None,
                        "status": "changed",
                        "review_reason": "tag_confidence_below_threshold",
                        "proposed_class": "document",
                        "proposed_tag": "meeting_records",
                        "proposed_secondary_tags": ["meeting_minutes"],
                        "corrected_class": "document",
                        "corrected_tag": "history_archive_general",
                        "corrected_secondary_tags": ["history_archive"],
                        "notes": "existing\ncorrected after review",
                        "created_at": None,
                        "updated_at": None,
                    }
                )
            return _Cursor()

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    item = store.record_review_decision(
        "review-id",
        decision="change",
        correct_class="document",
        correct_tag="history_archive_general",
        correct_secondary_tags=["history_archive"],
        notes="corrected after review",
    )

    assert item["status"] == "changed"
    assert item["corrected_tag"] == "history_archive_general"
    assert connection.committed is True
    update_params = next(params for query, params in connection.executed if "update review_items_v2" in query)
    assert update_params[:5] == ("changed", "document", "history_archive_general", '["history_archive"]', "existing\ncorrected after review")
    assert connection.closed is True


def test_postgres_pipeline_store_gets_review_item() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            return _Cursor(
                {
                    "id": "review-id",
                    "run_id": "run-id",
                    "run_key": "run-1",
                    "preset_key": "qa",
                    "source_path": "/source/a.pdf",
                    "relative_path": "Sunshine/a.pdf",
                    "segment_id": "segment-1",
                    "status": "open",
                    "review_reason": "needs_segment_review",
                    "proposed_class": "scanned_document",
                    "proposed_tag": "scrapbooks",
                    "proposed_secondary_tags": ["history_archive"],
                    "corrected_class": None,
                    "corrected_tag": None,
                    "corrected_secondary_tags": [],
                    "notes": None,
                    "created_at": None,
                    "updated_at": None,
                }
            )

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    item = store.get_review_item("review-id")

    assert item["id"] == "review-id"
    assert item["run_key"] == "run-1"
    assert item["segment_id"] == "segment-1"
    assert item["proposed_tag"] == "scrapbooks"
    assert connection.executed[0][1] == ("review-id",)
    assert connection.closed is True


def test_postgres_pipeline_store_reports_review_summary() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "count(*)" in normalized and "group by" not in normalized:
                if "from pipeline_results" in normalized:
                    return _Cursor({"count": 4})
                if "from review_items_v2" in normalized:
                    return _Cursor({"count": 3})
            if "from review_items_v2" in normalized and "group by" in normalized:
                return _Cursor(rows=[{"key": "open", "count": 1}, {"key": "accepted", "count": 1}, {"key": "changed", "count": 1}])
            if "route_status" in normalized:
                return _Cursor(rows=[{"key": "route_candidate", "count": 2}, {"key": "review_required", "count": 2}])
            if "quality" in normalized:
                return _Cursor(rows=[{"key": "ok", "count": 3}, {"key": "poor", "count": 1}])
            if "top_tag_candidate" in normalized:
                return _Cursor(rows=[{"key": "scrapbooks", "count": 2}, {"key": "meeting_records", "count": 2}])
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    summary = store.review_summary()

    assert summary["source"] == "postgres"
    assert summary["total_results"] == 4
    assert summary["total_review_items"] == 3
    assert summary["total_golden_labels"] == 0
    assert summary["review_by_status"]["open"] == 1
    assert summary["review_by_status"]["resolved"] == 2
    assert summary["results_by_primary_tag"]["scrapbooks"] == 2
    assert connection.closed is True


def test_rebuild_qdrant_from_postgres_replays_semantic_embeddings() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            return _Cursor(
                rows=[
                    {
                        "run_key": "run-1",
                        "source_path": "/source/a.pdf",
                        "relative_path": "Sunshine/a.pdf",
                        "sample_path": "/sample/a.pdf",
                        "chunk_id": "chunk-1",
                        "chunk_index": 1,
                        "chunk_kind": "text",
                        "content": "Meeting minutes",
                        "chunk_metadata": {"segment_id": "segment-1"},
                        "embedding_provider": "cortex",
                        "embedding_model": "local-embed",
                        "embedding_dimensions": 3,
                        "embedding_status": "embedded",
                        "semantic_quality": True,
                        "embedding": "[0.1,0.2,0.3]",
                    }
                ]
            )

        def close(self) -> None:
            self.closed = True

    class FakeVectorStore:
        provider_name = "qdrant"

        def __init__(self) -> None:
            self.chunks: list[dict[str, Any]] = []
            self.embeddings: list[dict[str, Any]] = []

        def dependency_status(self) -> dict[str, Any]:
            return {"provider": "qdrant", "local_only": True}

        def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
            self.chunks = chunks
            self.embeddings = embeddings
            return VectorStoreUpsertResult(
                provider="qdrant",
                collection="sunshine-test",
                status="indexed",
                indexed_count=len(embeddings),
                skipped_count=0,
                indexed_chunk_ids=[str(row["chunk_id"]) for row in embeddings],
                skipped_chunk_ids=[],
                warnings=[],
                metadata={"local_only": True},
            )

    connection = FakeConnection()
    vector_store = FakeVectorStore()

    result = rebuild_qdrant_from_postgres(
        database_url="postgresql://local/test",
        run_key="run-1",
        limit=10,
        connect_factory=lambda _url: connection,
        vector_store=vector_store,
    )

    assert result["ok"] is True
    assert result["source_row_count"] == 1
    assert result["vector_store"]["indexed_count"] == 1
    assert vector_store.chunks[0]["text"] == "Meeting minutes"
    assert vector_store.chunks[0]["metadata"]["segment_id"] == "segment-1"
    assert vector_store.embeddings[0]["embedding"] == [0.1, 0.2, 0.3]
    assert connection.executed[0][1] == ("run-1", 10)
    assert connection.closed is True


def _postgres_import_artifacts(tmp_path: Path) -> Path:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    _write_jsonl(
        output_dir / "sample-pipeline-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "route_status": "route_candidate",
                "final_class": "document",
                "extraction_strategy": "text_extraction",
                "extraction_status": "extracted",
                "quality": "ok",
                "top_tag_candidate": "meeting_records",
                "secondary_tags": ["meeting_minutes"],
                "tag_confidence": 0.95,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-model-usage.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "node": "embed_chunks",
                "purpose": "chunk_embedding",
                "provider": "cortex",
                "model": "local-embedding",
                "status": "ok",
                "runtime_ms": 12,
                "metadata": {"call_count": 1},
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-chunks.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "chunk_id": "golden-eval:1:1",
                "chunk_index": 1,
                "chunk_kind": "text",
                "text": "Meeting minutes and Sunshine Club notes.",
                "metadata": {"page_start": 1},
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-embeddings.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "chunk_id": "golden-eval:1:1",
                "embedding_status": "embedded",
                "embedding_provider": "cortex",
                "embedding_model": "local-embedding",
                "embedding_dimensions": 3,
                "semantic_quality": True,
                "embedding": [0.1, 0.2, 0.3],
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-provider-attempts.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "provider": "current",
                "status": "extracted",
                "strategy": "text_extraction",
                "seconds": 0.25,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-document-segments.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "segment_id": "test:1:segment-001",
                "page_start": 1,
                "page_end": 1,
                "segment_index": 1,
                "segment_type": "single_document",
                "segment_confidence": 0.8,
                "requires_segment_review": False,
                "segment_boundary_evidence": ["default:single_document"],
                "metadata": {},
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-review-queue.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "route_status": "review_tag_confidence_calibration",
                "review_reason": "tag_confidence_below_threshold",
                "final_class": "document",
                "top_tag_candidate": "meeting_records",
                "secondary_tags": ["meeting_minutes"],
                "tag_confidence": 0.62,
                "quality": "ok",
                "warnings": [],
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-indexing.jsonl",
        [
            {
                "provider": "qdrant",
                "collection": "sunshine-test",
                "status": "indexed",
            }
        ],
    )
    (output_dir / "artifact-manifest.json").write_text(
        json.dumps({"artifacts": [{"name": "sample-pipeline-results.jsonl", "row_count": 1}]}),
        encoding="utf-8",
    )
    (output_dir / "graph-run-metadata.json").write_text(
        json.dumps({"graph_runtime": {"latency_status": "ok", "runtime_ms": 42}}),
        encoding="utf-8",
    )
    return output_dir
