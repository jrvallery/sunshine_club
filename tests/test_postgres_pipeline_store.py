from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from sunshine_api.postgres_pipeline_store import PostgresPipelineStore, _model_usage_local_only
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


def test_model_usage_local_only_flag_preserves_external_legacy_rows() -> None:
    assert _model_usage_local_only({"provider": "cortex", "cost_basis": "local"}) is True
    assert _model_usage_local_only({"provider": "openai", "cost_basis": "external"}) is False
    assert _model_usage_local_only({"provider": "cortex", "local_only": False}) is False


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
        "pipeline_run_events": 1,
        "model_usage": 1,
        "provider_attempts": 1,
        "pipeline_provider_selections": 1,
        "pipeline_quality_checks": 4,
        "pipeline_tagging_evidence": 8,
        "pipeline_file_metadata": 5,
        "pipeline_artifacts": 2,
        "pipeline_processing_artifacts": 4,
        "pipeline_parser_results": 1,
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
    assert "insert into pipeline_run_events" in executed_sql
    assert "insert into model_usage" in executed_sql
    assert "insert into provider_attempts" in executed_sql
    assert "insert into pipeline_provider_selections" in executed_sql
    assert "insert into pipeline_quality_checks" in executed_sql
    assert "insert into pipeline_tagging_evidence" in executed_sql
    assert "insert into pipeline_file_metadata" in executed_sql
    assert "insert into pipeline_artifacts" in executed_sql
    assert "insert into pipeline_processing_artifacts" in executed_sql
    assert "insert into pipeline_parser_results" in executed_sql
    assert "insert into document_segments" in executed_sql
    assert "insert into review_items_v2" in executed_sql
    run_params = next(params for query, params in connection.executed if "insert into pipeline_runs" in query)
    run_summary = json.loads(run_params[3])
    assert run_summary["artifact_manifest"]["artifacts"][0]["name"] == "sample-pipeline-results.jsonl"
    assert run_summary["graph_runtime"]["latency_status"] == "ok"
    assert run_summary["providers"]["embedding_provider"] == "cortex"
    assert run_params[4:11] == ("cortex", "local-embedding", None, None, "current", "qdrant", "sunshine-test")
    assert any("[0.1,0.2,0.3]" in str(params) for _query, params in connection.executed)
    model_usage_params = next(params for query, params in connection.executed if "insert into model_usage" in query)
    assert model_usage_params[6:9] == ("local-embedding", "cortex.vallery.net", "ok")
    assert model_usage_params[-2] is True
    assert json.loads(model_usage_params[-1])["host"] == "cortex.vallery.net"
    provider_attempt_params = next(params for query, params in connection.executed if "insert into provider_attempts" in query)
    assert provider_attempt_params[1:4] == ("/source/a.pdf", "Sunshine/a.pdf", "current")
    provider_selection_params = next(params for query, params in connection.executed if "insert into pipeline_provider_selections" in query)
    assert provider_selection_params[1:6] == ("/source/a.pdf", "Sunshine/a.pdf", "current", "current", "current")
    assert json.loads(provider_selection_params[6]) == ["current", "cortex_ocr"]
    quality_check_params = next(params for query, params in connection.executed if "insert into pipeline_quality_checks" in query)
    assert quality_check_params[1:6] == ("/source/a.pdf", "Sunshine/a.pdf", "extraction_validation", "valid", None)
    tagging_evidence_params = next(params for query, params in connection.executed if "insert into pipeline_tagging_evidence" in query)
    assert tagging_evidence_params[1:6] == ("/source/a.pdf", "Sunshine/a.pdf", "retrieval_result", "ok", "qdrant")
    file_metadata_params = next(params for query, params in connection.executed if "insert into pipeline_file_metadata" in query)
    assert file_metadata_params[1:6] == ("/source/a.pdf", "Sunshine/a.pdf", "/sample/a.pdf", "source_identity", "file-a")
    artifact_params = next(params for query, params in connection.executed if "insert into pipeline_artifacts" in query)
    assert artifact_params[1:5] == ("sample-pipeline-results.jsonl", str(output_dir / "sample-pipeline-results.jsonl"), "jsonl", True)
    raw_artifact_params = next(params for query, params in connection.executed if "insert into pipeline_artifacts" in query and params[1] == "raw-provider:raw-providers/docling-test.json")
    assert raw_artifact_params[2:5] == (str(output_dir / "raw-providers/docling-test.json"), "raw_provider_snapshot", True)
    assert json.loads(raw_artifact_params[-1])["note"] == "raw_provider_artifact"
    processing_params = next(params for query, params in connection.executed if "insert into pipeline_processing_artifacts" in query)
    assert processing_params[1:8] == ("/source/a.pdf", "Sunshine/a.pdf", "/sample/a.pdf", "extraction_result", "current", None, "extracted")
    parser_params = next(params for query, params in connection.executed if "insert into pipeline_parser_results" in query)
    assert parser_params[1:9] == (
        "/source/a.pdf",
        "Sunshine/a.pdf",
        "/sample/a.pdf",
        "qa",
        1,
        "current",
        "extracted",
        "ok",
    )
    assert parser_params[13:18] == (37, 1, True, 1.0, 1)
    run_event_params = next(params for query, params in connection.executed if "insert into pipeline_run_events" in query)
    assert run_event_params[1:6] == ("/source/a.pdf", "Sunshine/a.pdf", "extract_content", "ok", "extracted text")
    assert json.loads(run_event_params[6])["duration_ms"] == 12.5
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


def test_postgres_pipeline_store_records_run_lifecycle_state() -> None:
    connection = _FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    result = store.record_pipeline_run_state(
        run_key="qa-run-1",
        preset_key="qa_samples_fast",
        input_root="/mnt/sunshine/qa samples",
        output_dir="/mnt/sunshine/dashboard-runs/qa-run-1",
        status="running",
        summary={"processed_count": 2, "selected_sample_count": 10},
        embedding_provider="cortex",
        llm_provider="cortex",
        vector_store_provider="qdrant",
    )

    assert result["run_id"] == "00000000-0000-0000-0000-000000000123"
    assert result["run_key"] == "qa-run-1"
    assert result["status"] == "running"
    executed_sql = "\n".join(query for query, _params in connection.executed)
    assert "insert into pipeline_runs" in executed_sql
    assert "dashboard_run_lifecycle" in executed_sql
    run_params = next(params for query, params in connection.executed if "insert into pipeline_runs" in query)
    assert run_params[0:6] == (
        "qa-run-1",
        "qa_samples_fast",
        "/mnt/sunshine/qa samples",
        "/mnt/sunshine/dashboard-runs/qa-run-1",
        "running",
        '{"processed_count": 2, "selected_sample_count": 10}',
    )
    event_params = next(params for query, params in connection.executed if "insert into pipeline_run_events" in query)
    assert event_params[0:3] == ("00000000-0000-0000-0000-000000000123", "running", "Dashboard run state recorded as running.")
    assert connection.committed is True
    assert connection.closed is True


def test_postgres_pipeline_store_imports_provider_benchmark_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "provider-benchmark"
    output_dir.mkdir()
    _write_jsonl(
        output_dir / "provider-benchmark-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_category": "scanned_pdf",
                "sample_label": "A",
                "provider": "docling",
                "status": "extracted",
                "quality": "ok",
                "requires_review": False,
                "seconds": 12.5,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-parser-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_category": "scanned_pdf",
                "sample_label": "A",
                "provider": "docling",
                "status": "extracted",
                "quality": "ok",
                "requires_review": False,
                "seconds": 12.5,
                "text_length": 1234,
                "page_count": 4,
            }
        ],
    )
    _write_jsonl(output_dir / "provider-benchmark-recommendations.jsonl", [{"provider": "docling", "recommendation": "candidate", "average_seconds": 12.5}])
    (output_dir / "provider-benchmark-summary.json").write_text(json.dumps({"result_count": 1, "partial": False}), encoding="utf-8")
    (output_dir / "artifact-manifest.json").write_text(json.dumps({"artifacts": [{"name": "provider-benchmark-results.jsonl"}]}), encoding="utf-8")
    connection = _FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    result = store.import_provider_benchmark_output(output_dir, benchmark_key="benchmark-1")

    assert result["benchmark_run_id"] == "00000000-0000-0000-0000-000000000123"
    assert result["benchmark_key"] == "benchmark-1"
    assert result["status"] == "completed"
    assert result["partial"] is False
    assert result["imported"] == {
        "provider_benchmark_results": 1,
        "provider_benchmark_parser_results": 1,
        "provider_benchmark_recommendations": 1,
    }
    executed_sql = "\n".join(query for query, _params in connection.executed)
    assert "insert into provider_benchmark_runs" in executed_sql
    assert "insert into provider_benchmark_results" in executed_sql
    assert "insert into provider_benchmark_parser_results" in executed_sql
    assert "insert into provider_benchmark_recommendations" in executed_sql
    assert connection.committed is True


def test_postgres_pipeline_store_gets_provider_benchmark_detail() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from provider_benchmark_runs pbr" in normalized:
                return _Cursor(
                    {
                        "id": "benchmark-id",
                        "benchmark_key": "benchmark-1",
                        "output_dir": "/tmp/provider-benchmark",
                        "status": "completed",
                        "partial": False,
                        "summary": {"result_count": 1},
                        "artifact_manifest": {"artifacts": []},
                        "background_error": {},
                        "created_at": None,
                        "updated_at": None,
                        "result_count": 1,
                        "parser_result_count": 1,
                        "recommendation_count": 1,
                    }
                )
            if "from provider_benchmark_results" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "result-id",
                            "benchmark_run_id": "benchmark-id",
                            "source_path": "/source/a.pdf",
                            "relative_path": "Sunshine/a.pdf",
                            "sample_category": "scanned_pdf",
                            "sample_label": "A",
                            "provider": "docling",
                            "status": "extracted",
                            "quality": "ok",
                            "requires_review": False,
                            "seconds": 12.5,
                            "result": {"text_length": 1234},
                            "created_at": None,
                        }
                    ]
                )
            if "from provider_benchmark_parser_results" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "parser-id",
                            "benchmark_run_id": "benchmark-id",
                            "source_path": "/source/a.pdf",
                            "relative_path": "Sunshine/a.pdf",
                            "sample_category": "scanned_pdf",
                            "sample_label": "A",
                            "provider": "docling",
                            "status": "extracted",
                            "quality": "ok",
                            "requires_review": False,
                            "seconds": 12.5,
                            "text_length": 1234,
                            "page_count": 4,
                            "result": {"text_snippet": "Sunshine"},
                            "created_at": None,
                        }
                    ]
                )
            if "from provider_benchmark_recommendations" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "recommendation-id",
                            "benchmark_run_id": "benchmark-id",
                            "provider": "docling",
                            "recommendation": "candidate",
                            "status": "candidate",
                            "average_seconds": 12.5,
                            "result": {"reason": "quality_ok"},
                            "created_at": None,
                        }
                    ]
                )
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    detail = store.get_provider_benchmark_run(benchmark_key="benchmark-1", result_limit=7, parser_result_limit=9)

    assert detail["run"]["benchmark_key"] == "benchmark-1"
    assert detail["summary"]["providers"] == {"docling": 2}
    assert detail["summary"]["recommendations"] == {"candidate": 1}
    assert detail["results"][0]["result"]["text_length"] == 1234
    assert detail["parser_results"][0]["page_count"] == 4
    assert detail["recommendations"][0]["recommendation"] == "candidate"
    assert connection.executed[0][1] == ("benchmark-1",)
    assert connection.executed[1][1] == ("benchmark-id", 7)
    assert connection.executed[2][1] == ("benchmark-id", 9)
    assert connection.closed is True


def test_postgres_pipeline_store_builds_provider_benchmark_promotion_plan() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            normalized = " ".join(query.lower().split())
            if "from provider_benchmark_runs pbr" in normalized:
                return _Cursor(
                    {
                        "id": "benchmark-id",
                        "benchmark_key": params[0],
                        "output_dir": "/tmp/provider-benchmark",
                        "status": "completed",
                        "partial": False,
                        "summary": {"result_count": 1},
                        "artifact_manifest": {"artifacts": []},
                        "background_error": {},
                        "created_at": None,
                        "updated_at": None,
                        "result_count": 1,
                        "parser_result_count": 1,
                        "recommendation_count": 1,
                    }
                )
            if "from provider_benchmark_results" in normalized:
                return _Cursor(rows=[])
            if "from provider_benchmark_parser_results" in normalized:
                return _Cursor(rows=[])
            if "from provider_benchmark_recommendations" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "recommendation-id",
                            "benchmark_run_id": "benchmark-id",
                            "provider": "docling",
                            "recommendation": "candidate",
                            "status": "candidate",
                            "average_seconds": 12.5,
                            "result": {
                                "promotion_status": "candidate",
                                "promotion_reason": "local quality gate passed",
                                "local_only": True,
                            },
                            "created_at": None,
                        }
                    ]
                )
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    plan = store.provider_benchmark_promotion_plan(benchmark_key="benchmark-1")

    assert plan["status"] == "candidate"
    assert plan["selected_provider"] == "docling"
    assert plan["local_only"] is True
    assert plan["recommended_env"]["SUNSHINE_OCR_PARSER_PROVIDER"] == "docling"
    assert plan["recommended_env"]["SUNSHINE_TEXT_PARSER_PROVIDER"] == "docling"
    assert "export SUNSHINE_OCR_PARSER_PROVIDER=docling" in plan["shell_exports"]
    assert connection.closed is True


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
                    "pipeline_provider_selections": 5,
                    "pipeline_quality_checks": 5,
                    "pipeline_tagging_evidence": 5,
                    "pipeline_file_metadata": 5,
                    "pipeline_artifacts": 5,
                    "pipeline_processing_artifacts": 5,
                    "pipeline_parser_results": 5,
                    "pipeline_run_events": 8,
                    "document_segments": 5,
                    "pipeline_chunks": 6,
                    "pipeline_chunk_embeddings": 6,
                    "provider_benchmark_runs": 2,
                    "provider_benchmark_results": 9,
                    "provider_benchmark_parser_results": 8,
                    "provider_benchmark_recommendations": 3,
                }
                for table, count in table_counts.items():
                    if f"from {table}" in normalized:
                        return _Cursor((count,))
            if "from provider_benchmark_runs pbr" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "benchmark-id",
                            "benchmark_key": "benchmark-1",
                            "output_dir": "/tmp/provider-benchmark",
                            "status": "completed",
                            "partial": False,
                            "summary": {"ok": True},
                            "artifact_manifest": {},
                            "background_error": {},
                            "created_at": None,
                            "updated_at": None,
                            "result_count": 9,
                            "parser_result_count": 8,
                            "recommendation_count": 3,
                        }
                    ]
                )
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
                            "parser_result_count": 5,
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
    assert summary["pipeline_run_events"] == 8
    assert summary["pipeline_artifacts"] == 5
    assert summary["pipeline_processing_artifacts"] == 5
    assert summary["pipeline_parser_results"] == 5
    assert summary["pipeline_chunk_embeddings"] == 6
    assert summary["provider_benchmark_runs"] == 2
    assert summary["provider_benchmark_parser_results"] == 8
    assert summary["recent_runs"][0]["run_key"] == "run-1"
    assert summary["recent_runs"][0]["result_count"] == 7
    assert summary["recent_provider_benchmarks"][0]["benchmark_key"] == "benchmark-1"
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


def test_postgres_pipeline_store_lists_run_events() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            return _Cursor(
                rows=[
                    {
                        "id": "event-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "source_path": "/source/a.pdf",
                        "relative_path": "Sunshine/a.pdf",
                        "node": "extract_content",
                        "status": "ok",
                        "message": "extracted text",
                        "payload": {"duration_ms": 12.5},
                        "created_at": "2026-05-28T00:00:00",
                    }
                ]
            )

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    rows = store.list_run_events(run_key="run-1", limit=10)

    assert rows[0]["run_key"] == "run-1"
    assert rows[0]["node"] == "extract_content"
    assert rows[0]["payload"]["duration_ms"] == 12.5
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
                        "pipeline_run_events": 8,
                        "model_usage": 4,
                        "provider_attempts": 5,
                        "pipeline_provider_selections": 6,
                        "pipeline_quality_checks": 10,
                        "pipeline_tagging_evidence": 11,
                        "pipeline_file_metadata": 12,
                        "pipeline_artifacts": 13,
                        "pipeline_processing_artifacts": 14,
                        "pipeline_parser_results": 9,
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
        "pipeline_run_events": 8,
        "model_usage": 4,
        "provider_attempts": 5,
        "pipeline_provider_selections": 6,
        "pipeline_quality_checks": 10,
        "pipeline_tagging_evidence": 11,
        "pipeline_file_metadata": 12,
        "pipeline_artifacts": 13,
        "pipeline_processing_artifacts": 14,
        "pipeline_parser_results": 9,
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
                            "provider_selection_count": 1,
                            "quality_check_count": 1,
                            "tagging_evidence_count": 1,
                            "file_metadata_count": 1,
                            "artifact_count": 1,
                            "processing_artifact_count": 4,
                            "parser_result_count": 1,
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
                            "host": "cortex.vallery.net",
                            "status": "ok",
                            "call_count": 1,
                            "input_tokens": None,
                            "output_tokens": None,
                            "total_tokens": None,
                            "runtime_ms": 12,
                            "local_only": True,
                            "metadata": {"host": "cortex.vallery.net"},
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
            if "from pipeline_provider_selections pps" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "selection-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "selected_provider": "docling",
                            "preferred_provider": "docling",
                            "configured_provider": "current",
                            "provider_chain": ["docling", "current", "cortex_ocr"],
                            "skipped_providers": [],
                            "provider_selection_reason": "preferred_docling_available",
                            "metadata": {"local_only": True},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_quality_checks pqc" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "quality-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "check_type": "quality_gate",
                            "status": "ok",
                            "quality": "ok",
                            "requires_review": False,
                            "can_chunk": True,
                            "can_embed": True,
                            "provider": "docling",
                            "strategy": "ocr_page_level",
                            "reason": None,
                            "warnings": [],
                            "result": {"quality": "ok"},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_tagging_evidence pte" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "tagging-evidence-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "evidence_type": "tag_candidate",
                            "status": None,
                            "provider": None,
                            "model": None,
                            "primary_tag": "scrapbooks",
                            "confidence": 0.92,
                            "assignment_source": "deterministic+semantic",
                            "route_status": None,
                            "review_reason": None,
                            "placement_status": None,
                            "destination_path": None,
                            "warnings": [],
                            "evidence": ["matched:scrapbook"],
                            "result": {"tag": "scrapbooks"},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_file_metadata pfm" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "file-metadata-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "metadata_type": "file_probe",
                            "file_id": "file-id",
                            "content_sha256": None,
                            "size_bytes": 1234,
                            "extension": ".pdf",
                            "mime_type": "application/pdf",
                            "media_type": "pdf",
                            "status": "probed",
                            "provider": "native",
                            "page_count": 4,
                            "text_length": None,
                            "sample_group": None,
                            "sample_number": None,
                            "final_class": None,
                            "extraction_strategy": None,
                            "import_status": None,
                            "warnings": [],
                            "result": {"media_type": "pdf"},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_artifacts pa" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "artifact-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "name": "sample-pipeline-results.jsonl",
                            "path": "/tmp/run/sample-pipeline-results.jsonl",
                            "kind": "jsonl",
                            "exists": True,
                            "size_bytes": 123,
                            "row_count": 1,
                            "sha256": "b" * 64,
                            "note": None,
                            "result": {"name": "sample-pipeline-results.jsonl"},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_processing_artifacts ppa" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "processing-extraction-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "artifact_type": "extraction_result",
                            "provider": "docling",
                            "model": None,
                            "status": "extracted",
                            "quality": "ok",
                            "strategy": "ocr_page_level",
                            "page_number": None,
                            "text_length": 2450,
                            "requested_count": None,
                            "embedded_count": None,
                            "dimensions": None,
                            "cache_hits": None,
                            "cache_misses": None,
                            "warnings": [],
                            "result": {"text_snippet": "Scrapbook page text"},
                            "created_at": None,
                        },
                        {
                            "id": "processing-ocr-doc-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "artifact_type": "ocr_document",
                            "provider": "docling",
                            "model": None,
                            "status": "ok",
                            "quality": "ok",
                            "strategy": "ocr_page_level",
                            "page_number": None,
                            "text_length": 2450,
                            "requested_count": None,
                            "embedded_count": None,
                            "dimensions": None,
                            "cache_hits": None,
                            "cache_misses": None,
                            "warnings": [],
                            "result": {"page_count": 1},
                            "created_at": None,
                        },
                        {
                            "id": "processing-ocr-page-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "artifact_type": "ocr_page",
                            "provider": "docling",
                            "model": None,
                            "status": "ok",
                            "quality": "ok",
                            "strategy": "ocr_page_level",
                            "page_number": 1,
                            "text_length": 1200,
                            "requested_count": None,
                            "embedded_count": None,
                            "dimensions": None,
                            "cache_hits": None,
                            "cache_misses": None,
                            "warnings": [],
                            "result": {"text": "Scrapbook page text"},
                            "created_at": None,
                        },
                        {
                            "id": "processing-embedding-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "artifact_type": "embedding_result",
                            "provider": "cortex",
                            "model": "local-embedding",
                            "status": "embedded",
                            "quality": None,
                            "strategy": None,
                            "page_number": None,
                            "text_length": None,
                            "requested_count": 1,
                            "embedded_count": 1,
                            "dimensions": 768,
                            "cache_hits": 0,
                            "cache_misses": 1,
                            "warnings": [],
                            "result": {"embedding_status": "embedded"},
                            "created_at": None,
                        },
                    ]
                )
            if "from pipeline_parser_results ppr" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "parser-result-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "sample_group": "qa",
                            "sample_number": 1,
                            "provider": "docling",
                            "status": "extracted",
                            "quality": "ok",
                            "requires_review": False,
                            "strategy": "ocr_page_level",
                            "document_subtype": "scrapbook",
                            "review_reason": None,
                            "text_length": 2450,
                            "page_count": 4,
                            "page_structure_available": True,
                            "page_text_coverage_rate": 0.92,
                            "layout_signal_count": 7,
                            "result": {"text_snippet": "Scrapbook page text"},
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
            if "from pipeline_chunks pc" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "chunk-row-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "sample_path": "/sample/scrapbook.pdf",
                            "chunk_id": "scrapbook:segment-001:chunk-001",
                            "chunk_index": 1,
                            "chunk_kind": "segment_text",
                            "content_snippet": "Scrapbook page text",
                            "content_length": 19,
                            "metadata": {"segment_id": "scrapbook:segment-001"},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_chunk_embeddings pce" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "embedding-row-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "chunk_id": "scrapbook:segment-001:chunk-001",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "embedding_provider": "cortex",
                            "embedding_model": "local-embedding",
                            "embedding_dimensions": 768,
                            "embedding_status": "embedded",
                            "semantic_quality": True,
                            "metadata": {"vector_store_provider": "qdrant"},
                            "created_at": None,
                        }
                    ]
                )
            if "from pipeline_run_events pre" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "event-id",
                            "run_id": "run-id",
                            "run_key": "run-report",
                            "source_path": "/source/scrapbook.pdf",
                            "relative_path": "History/scrapbook.pdf",
                            "node": "propose_document_segments",
                            "status": "ok",
                            "message": "proposed segments",
                            "payload": {"duration_ms": 31.5},
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
    assert report["summary"]["provider_selection_count"] == 1
    assert report["summary"]["quality_check_count"] == 1
    assert report["summary"]["quality_review_required_count"] == 0
    assert report["summary"]["tagging_evidence_count"] == 1
    assert report["summary"]["file_metadata_count"] == 1
    assert report["summary"]["artifact_count"] == 1
    assert report["summary"]["existing_artifact_count"] == 1
    assert report["summary"]["processing_artifact_count"] == 4
    assert report["summary"]["extraction_result_count"] == 1
    assert report["summary"]["ocr_document_count"] == 1
    assert report["summary"]["ocr_page_count"] == 1
    assert report["summary"]["embedding_result_count"] == 1
    assert report["summary"]["embedding_cache_misses"] == 1
    assert report["summary"]["parser_result_count"] == 1
    assert report["summary"]["parser_status"] == {"extracted": 1}
    assert report["summary"]["parser_quality"] == {"ok": 1}
    assert report["summary"]["run_event_count"] == 1
    assert report["summary"]["run_event_status"] == {"ok": 1}
    assert report["summary"]["segment_review_count"] == 1
    assert report["summary"]["segment_type"] == {"scrapbook_page_group": 1}
    assert report["summary"]["chunk_count"] == 1
    assert report["summary"]["chunk_embedding_count"] == 1
    assert report["summary"]["semantic_embedding_count"] == 1
    assert report["summary"]["placeholder_embedding_count"] == 0
    assert report["summary"]["chunk_kind"] == {"segment_text": 1}
    assert report["summary"]["embedding_provider"] == {"cortex": 1}
    assert report["summary"]["embedding_status"] == {"embedded": 1}
    assert report["summary"]["selected_provider"] == {"docling": 1}
    assert report["summary"]["provider_selection_reason"] == {"preferred_docling_available": 1}
    assert report["summary"]["quality_check_type"] == {"quality_gate": 1}
    assert report["summary"]["quality_check_status"] == {"ok": 1}
    assert report["summary"]["tagging_evidence_type"] == {"tag_candidate": 1}
    assert report["summary"]["tagging_primary_tag"] == {"scrapbooks": 1}
    assert report["summary"]["file_metadata_type"] == {"file_probe": 1}
    assert report["summary"]["file_media_type"] == {"pdf": 1}
    assert report["summary"]["artifact_kind"] == {"jsonl": 1}
    assert report["summary"]["artifact_exists"] == {"true": 1}
    assert report["summary"]["processing_artifact_type"] == {
        "embedding_result": 1,
        "extraction_result": 1,
        "ocr_document": 1,
        "ocr_page": 1,
    }
    assert report["results"][0]["top_tag_candidate"] == "scrapbooks"
    assert report["review_items"][0]["segment_id"] == "scrapbook:segment-001"
    assert report["model_usage"][0]["provider"] == "cortex"
    assert report["model_usage"][0]["host"] == "cortex.vallery.net"
    assert report["provider_attempts"][0]["provider"] == "docling"
    assert report["provider_selections"][0]["selected_provider"] == "docling"
    assert report["provider_selections"][0]["provider_chain"] == ["docling", "current", "cortex_ocr"]
    assert report["quality_checks"][0]["check_type"] == "quality_gate"
    assert report["tagging_evidence"][0]["primary_tag"] == "scrapbooks"
    assert report["file_metadata"][0]["metadata_type"] == "file_probe"
    assert report["artifacts"][0]["name"] == "sample-pipeline-results.jsonl"
    assert report["processing_artifacts"][0]["artifact_type"] == "extraction_result"
    assert report["parser_results"][0]["provider"] == "docling"
    assert report["parser_results"][0]["page_text_coverage_rate"] == 0.92
    assert report["chunks"][0]["chunk_kind"] == "segment_text"
    assert report["chunk_embeddings"][0]["semantic_quality"] is True
    assert report["run_events"][0]["node"] == "propose_document_segments"
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
            if "select ri.id, ri.run_id, ri.source_path" in normalized:
                return _Cursor(
                    {
                        "id": "review-id",
                        "run_id": "run-id",
                        "source_path": "/source/a.pdf",
                        "relative_path": "Sunshine/a.pdf",
                        "segment_id": None,
                        "proposed_class": "document",
                        "proposed_tag": "meeting_records",
                        "proposed_secondary_tags": ["meeting_minutes"],
                        "notes": "existing",
                        "sample_path": "/sample/a.pdf",
                        "result": {"quality": "ok", "extraction_text_snippet": "Meeting minutes text"},
                        "tag_confidence": 0.75,
                        "quality": "ok",
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
    golden_params = next(params for query, params in connection.executed if "insert into golden_labels_v2" in query)
    assert golden_params[:10] == (
        "review-id",
        "run-id",
        "/source/a.pdf",
        "Sunshine/a.pdf",
        "/sample/a.pdf",
        "",
        "Meeting minutes text",
        "document",
        "history_archive_general",
        '["history_archive"]',
    )
    assert connection.closed is True


def test_postgres_pipeline_store_records_segment_review_decision() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from document_segments ds join pipeline_runs r" in normalized and "where r.run_key = %s and ds.segment_id = %s" in normalized:
                return _Cursor(
                    {
                        "id": "segment-row-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "source_path": "/source/scrapbook.pdf",
                        "relative_path": "History/scrapbook.pdf",
                        "segment_id": "segment-001",
                        "segment_type": "scrapbook_page_group",
                        "segment_title": "Scrapbook pages 1-4",
                        "page_start": 1,
                        "page_end": 4,
                        "metadata": {"policy": "review_only"},
                    }
                )
            if "select id, notes from review_items_v2" in normalized:
                return _Cursor({"id": "review-id", "notes": "existing"})
            if "from document_segments ds join pipeline_runs r" in normalized and "where ds.id = %s" in normalized:
                return _Cursor(
                    {
                        "id": "segment-row-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "source_path": "/source/scrapbook.pdf",
                        "relative_path": "History/scrapbook.pdf",
                        "segment_id": "segment-001",
                        "parent_file_id": "file-id",
                        "page_start": 1,
                        "page_end": 4,
                        "segment_index": 1,
                        "segment_type": "scrapbook_page_group",
                        "segment_title": "Scrapbook pages 1-4",
                        "segment_confidence": 0.62,
                        "requires_segment_review": False,
                        "boundary_evidence": ["matched:scrapbook"],
                        "metadata": {"segment_review": {"decision": "accept", "status": "accepted"}},
                        "created_at": None,
                    }
                )
            return _Cursor()

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    result = store.record_segment_review_decision(
        run_key="run-1",
        segment_id="segment-001",
        decision="accept",
        notes="range is correct",
        reviewer="james",
    )

    assert result["review_status"] == "accepted"
    assert result["review_item_id"] == "review-id"
    assert result["segment"]["requires_segment_review"] is False
    update_segment_params = next(params for query, params in connection.executed if "update document_segments" in query)
    assert json.loads(update_segment_params[0])["segment_review"] == {
        "decision": "accept",
        "notes": "range is correct",
        "reviewer": "james",
        "status": "accepted",
    }
    review_update_params = next(params for query, params in connection.executed if "update review_items_v2" in query)
    assert review_update_params[:3] == ("accepted", "segment_boundary_accept", "existing\nrange is correct")
    assert connection.committed is True
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


def test_postgres_pipeline_store_searches_files_and_facets() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            return _Cursor(
                rows=[
                    {
                        "id": "result-1",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "preset_key": "qa",
                        "embedding_provider": "cortex",
                        "llm_provider": "cortex",
                        "extraction_provider": "docling",
                        "source_path": "/mnt/sunshine/Sunshine shared folders/History/history.pdf",
                        "relative_path": "Sunshine shared folders/History/history.pdf",
                        "sample_path": "/samples/history.pdf",
                        "route_status": "route_candidate",
                        "review_reason": None,
                        "final_class": "document",
                        "extraction_strategy": "text_extraction",
                        "extraction_status": "extracted",
                        "quality": "ok",
                        "top_tag_candidate": "history_archive_general",
                        "secondary_tags": ["club_history"],
                        "tag_confidence": 0.91,
                        "result": {
                            "top_tag_candidate": "history_archive_general",
                            "secondary_tags": ["club_history"],
                            "route_status": "route_candidate",
                            "quality": "ok",
                            "placement_status": "ready",
                            "extraction_text_snippet": "Founders history text",
                            "warnings": ["reviewed"],
                        },
                        "review_status": "accepted",
                        "created_at": "2026-05-28T00:00:00",
                        "updated_at": "2026-05-28T00:00:00",
                    },
                    {
                        "id": "result-2",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "preset_key": "qa",
                        "source_path": "/mnt/sunshine/archive-2026-05-25/Budget/report.pdf",
                        "relative_path": "archive-2026-05-25/Budget/report.pdf",
                        "route_status": "review_required",
                        "final_class": "scanned_document",
                        "quality": "poor",
                        "top_tag_candidate": "finance_treasurer_records",
                        "secondary_tags": ["budget"],
                        "result": {
                            "top_tag_candidate": "finance_treasurer_records",
                            "secondary_tags": ["budget"],
                            "route_status": "review_required",
                            "quality": "poor",
                            "placement_status": "needs_review",
                            "warnings": ["ocr_quality_below_threshold"],
                        },
                        "review_status": "open",
                        "created_at": "2026-05-28T00:00:00",
                        "updated_at": "2026-05-28T00:00:00",
                    },
                ]
            )

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    search = store.search_files(primary_tag="history_archive_general", q="founders")
    facets = store.file_facets(review_status="open")

    assert search["total_estimate"] == 1
    assert search["items"][0]["source"] == "postgres"
    assert search["items"][0]["filename"] == "history.pdf"
    assert search["items"][0]["source_collection"] == "sunshine_shared_folders"
    assert search["items"][0]["text_snippet"] == "Founders history text"
    assert facets["primary_tag"] == {"finance_treasurer_records": 1}
    assert facets["warning_type"] == {"ocr_quality_below_threshold": 1}
    assert connection.closed is True


def test_postgres_pipeline_store_reads_file_result_detail_and_text() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "from pipeline_chunks" in normalized:
                return _Cursor(rows=[{"content": "First chunk."}, {"content": "Second chunk."}])
            return _Cursor(
                row={
                    "id": "result-1",
                    "run_id": "run-id",
                    "run_key": "run-1",
                    "preset_key": "qa",
                    "embedding_provider": "cortex",
                    "llm_provider": "cortex",
                    "extraction_provider": "docling",
                    "source_path": "/mnt/sunshine/Sunshine shared folders/History/history.pdf",
                    "relative_path": "Sunshine shared folders/History/history.pdf",
                    "sample_path": "/samples/history.pdf",
                    "route_status": "route_candidate",
                    "review_reason": None,
                    "final_class": "document",
                    "extraction_strategy": "text_extraction",
                    "extraction_status": "extracted",
                    "quality": "ok",
                    "top_tag_candidate": "history_archive_general",
                    "secondary_tags": ["club_history"],
                    "tag_confidence": 0.91,
                    "result": {
                        "quality": "ok",
                        "extraction_text_snippet": "Fallback text.",
                        "warnings": [],
                    },
                    "review_status": "accepted",
                    "created_at": "2026-05-28T00:00:00",
                    "updated_at": "2026-05-28T00:00:00",
                }
            )

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    detail = store.get_file_result("result-1")
    text = store.file_text_for_file_result("result-1")
    inspection = store.file_inspection_for_file_result("result-1")

    assert detail["source"] == "postgres"
    assert detail["id"] == "result-1"
    assert detail["latest_result"]["extraction_text_snippet"] == "Fallback text."
    assert text["text"] == "First chunk.\n\nSecond chunk."
    assert inspection["file"]["source"] == "postgres"
    assert inspection["text"]["length"] == len("First chunk.\n\nSecond chunk.")
    assert connection.closed is True


def test_postgres_pipeline_store_adds_file_result_to_review() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if normalized.startswith("select id from review_items_v2"):
                return _Cursor(row=None)
            if "insert into review_items_v2" in normalized:
                return _Cursor(row={"id": "review-1"})
            return _Cursor(
                row={
                    "id": "result-1",
                    "run_id": "run-id",
                    "run_key": "run-1",
                    "preset_key": "qa",
                    "embedding_provider": "cortex",
                    "llm_provider": "cortex",
                    "extraction_provider": "docling",
                    "source_path": "/mnt/sunshine/history.pdf",
                    "relative_path": "Sunshine/history.pdf",
                    "sample_path": "/samples/history.pdf",
                    "route_status": "route_candidate",
                    "review_reason": None,
                    "final_class": "document",
                    "extraction_strategy": "text_extraction",
                    "extraction_status": "extracted",
                    "quality": "ok",
                    "top_tag_candidate": "history_archive_general",
                    "secondary_tags": ["club_history"],
                    "tag_confidence": 0.91,
                    "result": {"quality": "ok"},
                    "review_status": None,
                    "created_at": "2026-05-28T00:00:00",
                    "updated_at": "2026-05-28T00:00:00",
                }
            )

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    review = store.add_file_result_to_review("result-1", review_reason="manual_quality_check")

    assert review["id"] == "review-1"
    assert review["source"] == "postgres"
    assert review["status"] == "open"
    assert review["proposed_tag"] == "history_archive_general"
    assert connection.committed is True
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


def test_postgres_pipeline_store_lists_golden_labels_and_summary() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "select gl.id" in normalized:
                return _Cursor(
                    rows=[
                        {
                            "id": "golden-id",
                            "review_item_id": "review-id",
                            "run_id": "run-id",
                            "run_key": "run-1",
                            "preset_key": "qa",
                            "source_path": "/source/a.pdf",
                            "relative_path": "Sunshine/a.pdf",
                            "sample_path": "/sample/a.pdf",
                            "segment_id": "segment-1",
                            "content_class": "document",
                            "correct_primary_tag": "history_archive_general",
                            "correct_secondary_tags": ["history_archive"],
                            "proposed_tag": "meeting_records",
                            "proposed_secondary_tags": ["meeting_minutes"],
                        }
                    ]
                )
            if "count(*)" in normalized and "group by" not in normalized:
                return _Cursor({"count": 1})
            if "correct_primary_tag" in normalized:
                return _Cursor(rows=[{"key": "history_archive_general", "count": 1}])
            if "jsonb_array_elements_text" in normalized:
                return _Cursor(rows=[{"key": "history_archive", "count": 1}])
            return _Cursor()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    labels = store.list_golden_labels(limit=5)
    summary = store.golden_label_summary()

    assert labels[0]["id"] == "golden-id"
    assert labels[0]["correct_primary_tag"] == "history_archive_general"
    assert summary["source"] == "postgres"
    assert summary["total_golden_labels"] == 1
    assert summary["golden_by_primary_tag"] == {"history_archive_general": 1}
    assert summary["golden_by_secondary_tag"] == {"history_archive": 1}
    assert connection.closed is True


def test_postgres_pipeline_store_updates_deletes_and_resolves_golden_label_file(tmp_path: Path) -> None:
    source_file = tmp_path / "a.pdf"
    source_file.write_text("source", encoding="utf-8")

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False
            self.executed: list[tuple[str, tuple[Any, ...]]] = []

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            self.executed.append((query, params))
            normalized = " ".join(query.lower().split())
            if "select gl.id" in normalized:
                return _Cursor(
                    {
                        "id": "golden-id",
                        "review_item_id": "review-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "preset_key": "qa",
                        "source_path": str(source_file),
                        "relative_path": "Sunshine/a.pdf",
                        "sample_path": None,
                        "segment_id": "segment-1",
                        "content_class": "scanned_document",
                        "correct_primary_tag": "meeting_records",
                        "correct_secondary_tags": ["meeting_minutes"],
                        "ocr_quality_label": "poor",
                        "expected_review_required": True,
                        "sensitive_record": False,
                        "correct_destination_path": None,
                        "correct_placement_year": None,
                        "correct_privacy": None,
                        "reviewer": "james",
                        "notes": "before",
                        "proposed_tag": "meeting_records",
                        "proposed_secondary_tags": ["meeting_minutes"],
                    }
                )
            return _Cursor()

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: connection)

    edited = store.update_golden_label(
        "golden-id",
        content_class="document",
        correct_primary_tag="history_archive_general",
        correct_secondary_tags=["club_history"],
        ocr_quality_label="ok",
        expected_review_required=False,
        sensitive_record=True,
        reviewer="auditor",
        notes="after",
    )
    path = store.file_path_for_golden_label("golden-id")
    deleted = store.delete_golden_label("golden-id")

    assert edited["id"] == "golden-id"
    assert path == source_file
    assert deleted == {"deleted": True, "id": "golden-id", "source_path": str(source_file)}
    assert connection.committed is True
    update_params = next(params for query, params in connection.executed if "update golden_labels_v2" in query)
    assert update_params[:6] == ("document", "history_archive_general", '["club_history"]', "ok", False, True)
    assert any("delete from golden_labels_v2" in query for query, _params in connection.executed)


def test_postgres_pipeline_store_exports_golden_labels_to_sqlite(tmp_path: Path) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            return _Cursor(
                rows=[
                    {
                        "id": "golden-id",
                        "review_item_id": "review-id",
                        "run_id": "run-id",
                        "run_key": "run-1",
                        "preset_key": "qa",
                        "source_path": "/source/a.pdf",
                        "relative_path": "Sunshine/a.pdf",
                        "sample_path": "/sample/a.pdf",
                        "segment_id": "",
                        "extracted_text_snippet": "Reviewed text",
                        "content_class": "document",
                        "correct_primary_tag": "history_archive_general",
                        "correct_secondary_tags": ["history_archive"],
                        "ocr_quality_label": "ok",
                        "expected_review_required": True,
                        "sensitive_record": False,
                        "reviewer": "james",
                        "notes": "accepted",
                        "proposed_tag": "meeting_records",
                        "proposed_secondary_tags": ["meeting_minutes"],
                        "proposed_confidence": 0.75,
                        "reviewed_at": "2026-05-28T00:00:00",
                        "created_at": "2026-05-28T00:00:00",
                        "updated_at": "2026-05-28T00:00:00",
                    }
                ]
            )

        def close(self) -> None:
            self.closed = True

    output_db = tmp_path / "golden.sqlite"
    store = PostgresPipelineStore("postgresql://local/test", connect_factory=lambda _url: FakeConnection())

    result = store.export_golden_labels_sqlite(output_db)

    with sqlite3.connect(output_db) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("select * from golden_labels").fetchone()

    assert result["status"] == "exported"
    assert result["label_count"] == 1
    assert row["id"] == "golden-id"
    assert row["source_path"] == "/source/a.pdf"
    assert row["correct_primary_tag"] == "history_archive_general"
    assert row["correct_secondary_tags_json"] == '["history_archive"]'
    assert row["expected_review_required"] == 1


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


def test_rebuild_qdrant_from_postgres_accepts_collection_override(monkeypatch) -> None:
    class FakeConnection:
        def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Cursor:
            return _Cursor(rows=[])

        def close(self) -> None:
            pass

    captured: dict[str, Any] = {}

    class FakeQdrantVectorStore:
        provider_name = "qdrant"

        def __init__(self, *, collection: str | None = None) -> None:
            captured["collection"] = collection
            self.collection = collection

        def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
            return VectorStoreUpsertResult(
                provider="qdrant",
                collection=self.collection,
                status="skipped",
                indexed_count=0,
                skipped_count=0,
                indexed_chunk_ids=[],
                skipped_chunk_ids=[],
                warnings=["no_semantic_embeddings_to_index"],
                metadata={"local_only": True},
            )

    monkeypatch.setattr("sunshine_api.services.vector_index.QdrantVectorStoreProvider", FakeQdrantVectorStore)

    result = rebuild_qdrant_from_postgres(
        database_url="postgresql://local/test",
        collection="sunshine-review",
        connect_factory=lambda _url: FakeConnection(),
    )

    assert captured["collection"] == "sunshine-review"
    assert result["collection"] == "sunshine-review"
    assert result["vector_store"]["collection"] == "sunshine-review"


def _postgres_import_artifacts(tmp_path: Path) -> Path:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    _write_jsonl(
        output_dir / "sample-source-identity.jsonl",
        [
            {
                "file_id": "file-a",
                "content_sha256": "a" * 64,
                "size_bytes": 123,
                "modified_at_ns": 1000,
                "extension": ".pdf",
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-file-probes.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "provider": "native",
                "status": "probed",
                "mime_type": "application/pdf",
                "extension": ".pdf",
                "media_type": "pdf",
                "size_bytes": 123,
                "page_count": 1,
                "embedded_text_chars": 37,
                "image_only_pdf_likelihood": 0.0,
                "encrypted": False,
                "width": None,
                "height": None,
                "warnings": [],
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-inputs.jsonl",
        [
            {
                "sample_path": "/sample/a.pdf",
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_group": "qa",
                "sample_number": 1,
                "final_class": "document",
                "final_status": "accepted",
                "extraction_strategy": "text_extraction",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-structure.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "provider": "current",
                "page_count": 1,
                "text_length": 37,
                "sections": [],
                "pages": [{"page_number": 1, "text": "Meeting minutes"}],
                "tables": [],
                "figures": [],
                "metadata": {},
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-import-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "import_status": "skipped",
                "status": "skipped",
                "importer": "noop",
            }
        ],
    )
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
        output_dir / "sample-extraction-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "provider": "current",
                "extraction_status": "extracted",
                "quality": "ok",
                "extraction_strategy": "text_extraction",
                "text_length": 37,
                "text": "Meeting minutes and Sunshine Club notes.",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-ocr-documents.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "provider": "current",
                "status": "ok",
                "quality": "ok",
                "total_text_length": 37,
                "page_count": 1,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-ocr-pages.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "provider": "current",
                "status": "ok",
                "quality": "ok",
                "page_number": 1,
                "text": "Meeting minutes",
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
                "host": "cortex.vallery.net",
                "status": "ok",
                "runtime_ms": 12,
                "cost_basis": "local",
                "metadata": {"call_count": 1, "host": "cortex.vallery.net"},
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-embedding-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "embedding_provider": "cortex",
                "embedding_model": "local-embedding",
                "embedding_status": "embedded",
                "requested_count": 1,
                "embedded_count": 1,
                "dimensions": 3,
                "metadata": {"cache_hits": 0, "cache_misses": 1},
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
        output_dir / "graph-audit-events.jsonl",
        [
            {
                "run_id": "run-1",
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "node": "extract_content",
                "status": "ok",
                "timestamp": "2026-05-28T00:00:00+00:00",
                "duration_ms": 12.5,
                "attempts": 1,
                "summary": "extracted text",
                "warnings": [],
                "errors": [],
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
        output_dir / "sample-provider-selections.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "selected_provider": "current",
                "preferred_provider": "current",
                "configured_provider": "current",
                "provider_chain": ["current", "cortex_ocr"],
                "skipped_providers": [],
                "provider_selection_reason": "configured_provider_matches_preferred",
                "local_only": True,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-extraction-validations.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "status": "valid",
                "strategy": "text_extraction",
                "reason": None,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-extraction-repairs.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "status": "not_needed",
                "strategy": "text_extraction",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-quality-gates.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "status": "ok",
                "quality": "ok",
                "requires_review": False,
                "can_chunk": True,
                "can_embed": True,
                "provider": "current",
                "strategy": "text_extraction",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-chunking-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "status": "chunked",
                "provider": "current",
                "strategy": "structure_aware",
                "warnings": [],
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-parser-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "sample_path": "/sample/a.pdf",
                "sample_group": "qa",
                "sample_number": 1,
                "provider": "current",
                "status": "extracted",
                "quality": "ok",
                "requires_review": False,
                "strategy": "text_extraction",
                "document_subtype": "meeting_minutes",
                "review_reason": None,
                "text_length": 37,
                "page_count": 1,
                "page_structure_available": True,
                "page_text_coverage_rate": 1.0,
                "layout_signal_count": 1,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-retrieval-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "provider": "qdrant",
                "status": "ok",
                "query_count": 1,
                "result_count": 1,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-semantic-examples.jsonl",
        [
            {
                "source_path": "/source/example.pdf",
                "relative_path": "Sunshine/example.pdf",
                "correct_primary_tag": "meeting_records",
                "score": 0.89,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-llm-tag-inspection-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "provider": "cortex",
                "model": "gemma4-26b",
                "status": "inspected",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-llm-tag-inspections.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "provider": "cortex",
                "model": "gemma4-26b",
                "llm_status": "inspected",
                "primary_tag": "meeting_records",
                "confidence": 0.9,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-tag-candidates.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "tag": "meeting_records",
                "confidence": 0.95,
                "assignment_source": "deterministic+semantic",
                "evidence": ["matched:minutes"],
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-confidence-calibrations.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "status": "calibrated",
                "top_tag": "meeting_records",
                "calibrated_confidence": 0.95,
                "requires_review": False,
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-placement-proposals.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "primary_tag": "meeting_records",
                "proposal": {
                    "placement_status": "resolved",
                    "destination_path": "01_Governance_Admin/2026/a.pdf",
                },
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-route-decisions.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "route_status": "route_candidate",
                "review_reason": None,
                "evidence": ["tag_confidence:0.95"],
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
    raw_provider_path = output_dir / "raw-providers" / "docling-test.json"
    raw_provider_path.parent.mkdir(parents=True, exist_ok=True)
    raw_provider_path.write_text(json.dumps({"provider": "docling", "text": "raw text"}), encoding="utf-8")
    _write_jsonl(
        output_dir / "sample-raw-provider-artifacts.jsonl",
        [
            {
                "provider": "docling",
                "path": str(raw_provider_path),
                "relative_path": "raw-providers/docling-test.json",
                "kind": "raw_provider_snapshot",
                "exists": True,
                "size_bytes": raw_provider_path.stat().st_size,
                "sha256": "c" * 64,
            }
        ],
    )
    (output_dir / "artifact-manifest.json").write_text(
        json.dumps(
            {
                "artifact_count": 1,
                "existing_artifact_count": 1,
                "missing_artifact_count": 0,
                "artifacts": [
                    {
                        "name": "sample-pipeline-results.jsonl",
                        "path": str(output_dir / "sample-pipeline-results.jsonl"),
                        "kind": "jsonl",
                        "exists": True,
                        "row_count": 1,
                        "size_bytes": 123,
                        "sha256": "b" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "graph-run-metadata.json").write_text(
        json.dumps({"graph_runtime": {"latency_status": "ok", "runtime_ms": 42}}),
        encoding="utf-8",
    )
    return output_dir
