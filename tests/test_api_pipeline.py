from __future__ import annotations

from pathlib import Path
import threading
import json
import time
from typing import Any

from fastapi.testclient import TestClient

from sunshine_api.main import app
from sunshine_api.services.imports import import_langgraph_output_to_postgres_if_configured
from sunshine_api.services.model_usage import _model_usage_report, _read_model_usage_artifact


def test_api_pipeline_run_file_processes_one_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "placeholder")
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "api-out"
    checkpoint_path = tmp_path / "api-checkpoints.sqlite"

    response = TestClient(app).post(
        "/admin/pipeline/run-file",
        json={
            "input_file": str(source),
            "output_dir": str(output_dir),
            "source_path": "/source/tea.txt",
            "relative_path": "Sunshine shared folders/Teas/tea.txt",
            "checkpoint_path": str(checkpoint_path),
            "thread_id": "api-test-thread",
            "retry_attempts": 2,
            "enable_llm_tags": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_result"]["route_status"] == "route_candidate"
    assert payload["final_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert payload["graph_result_path"] == str(output_dir / "graph-result.json")
    assert payload["graph_audit_events_path"] == str(output_dir / "graph-audit-events.jsonl")
    assert Path(payload["graph_result_path"]).exists()
    assert Path(payload["graph_audit_events_path"]).exists()
    assert checkpoint_path.exists()


def test_import_langgraph_output_postgres_endpoint_wraps_service(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_import(output_dir: str, *, run_key: str, preset_key: str | None = None) -> dict:
        captured["output_dir"] = output_dir
        captured["run_key"] = run_key
        captured["preset_key"] = preset_key
        return {"run_id": "postgres-run-id", "imported": {"pipeline_results": 1}}

    monkeypatch.setattr("sunshine_api.routers.pipeline.import_langgraph_output_to_postgres", fake_import)

    response = TestClient(app).post(
        "/admin/review/import-langgraph-output-postgres",
        json={"output_dir": str(tmp_path), "run_key": "run-1", "preset_key": "qa"},
    )

    assert response.status_code == 200
    assert response.json()["import_result"]["run_id"] == "postgres-run-id"
    assert captured == {"output_dir": str(tmp_path), "run_key": "run-1", "preset_key": "qa"}


def test_postgres_import_helper_skips_when_database_is_not_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUNSHINE_DATABASE_URL", raising=False)

    result = import_langgraph_output_to_postgres_if_configured(tmp_path, run_key="run-1", preset_key="qa")

    assert result == {
        "import_status": "skipped",
        "importer": "postgres_runtime",
        "output_dir": str(tmp_path),
        "run_key": "run-1",
        "preset_key": "qa",
        "reason": "postgres_database_url_not_configured",
    }


def test_delete_run_includes_postgres_cleanup_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    output_dir = tmp_path / "dashboard-runs" / "delete-postgres"
    output_dir.mkdir(parents=True)
    client = TestClient(app)
    run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(output_dir), "start": False},
    )
    run_key = run.json()["run_key"]
    captured = {}

    def fake_delete(*, run_key: str) -> dict:
        captured["run_key"] = run_key
        return {"delete_status": "deleted", "store": "postgres_runtime"}

    monkeypatch.setattr("sunshine_api.routers.runs.delete_postgres_pipeline_run_if_configured", fake_delete)

    deleted = client.delete(f"/admin/runs/{run.json()['id']}")

    assert deleted.status_code == 200
    assert deleted.json()["postgres_delete"] == {"delete_status": "deleted", "store": "postgres_runtime"}
    assert captured == {"run_key": run_key}


def test_postgres_review_items_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_list_review_items(*, run_key: str | None = None, limit: int = 100) -> list[dict]:
        captured["run_key"] = run_key
        captured["limit"] = limit
        return [{"id": "review-1", "run_key": run_key, "status": "open"}]

    monkeypatch.setattr("sunshine_api.routers.health.list_postgres_review_items", fake_list_review_items)

    response = TestClient(app).get("/admin/system/postgres-runtime/review-items?run_key=run-1&limit=5")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "review-1"
    assert captured == {"run_key": "run-1", "limit": 5}


def test_postgres_run_detail_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_get_run(*, run_key: str) -> dict:
        captured["run_key"] = run_key
        return {"run_key": run_key, "summary": {"graph_runtime": {"latency_status": "ok"}}}

    monkeypatch.setattr("sunshine_api.routers.health.get_postgres_pipeline_run", fake_get_run)

    response = TestClient(app).get("/admin/system/postgres-runtime/runs/run-1")

    assert response.status_code == 200
    assert response.json()["run"]["summary"]["graph_runtime"]["latency_status"] == "ok"
    assert captured == {"run_key": "run-1"}


def test_postgres_run_report_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_get_report(*, run_key: str, limit: int = 500) -> dict:
        captured["run_key"] = run_key
        captured["limit"] = limit
        return {
            "run": {"run_key": run_key},
            "summary": {"result_count": 1, "segment_review_count": 1},
            "results": [{"source_path": "/source/scrapbook.pdf"}],
            "review_items": [{"segment_id": "segment-001"}],
            "model_usage": [{"provider": "cortex"}],
            "provider_attempts": [{"provider": "docling"}],
            "document_segments": [{"segment_type": "scrapbook_page_group", "requires_segment_review": True}],
            "run_events": [{"node": "propose_document_segments", "status": "ok"}],
        }

    monkeypatch.setattr("sunshine_api.routers.health.get_postgres_run_report", fake_get_report)

    response = TestClient(app).get("/admin/system/postgres-runtime/runs/run-1/report?limit=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["run_key"] == "run-1"
    assert payload["summary"]["segment_review_count"] == 1
    assert payload["document_segments"][0]["segment_type"] == "scrapbook_page_group"
    assert payload["run_events"][0]["node"] == "propose_document_segments"
    assert payload["provider_attempts"][0]["provider"] == "docling"
    assert captured == {"run_key": "run-1", "limit": 7}


def test_postgres_run_artifacts_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_list_artifacts(*, run_key: str, limit: int = 500) -> list[dict]:
        captured["run_key"] = run_key
        captured["limit"] = limit
        return [
            {
                "name": "sample-raw-provider-artifacts.jsonl",
                "kind": "jsonl",
                "exists": True,
                "row_count": 1,
            }
        ]

    monkeypatch.setattr("sunshine_api.routers.health.list_postgres_run_artifacts", fake_list_artifacts)

    response = TestClient(app).get("/admin/system/postgres-runtime/runs/run-1/artifacts?limit=9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_key"] == "run-1"
    assert payload["count"] == 1
    assert payload["artifacts"][0]["name"] == "sample-raw-provider-artifacts.jsonl"
    assert captured == {"run_key": "run-1", "limit": 9}


def test_postgres_run_model_usage_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_list_model_usage(*, run_key: str, limit: int = 500) -> list[dict]:
        captured["run_key"] = run_key
        captured["limit"] = limit
        return [
            {
                "purpose": "chunk_embedding",
                "provider": "cortex",
                "model": "local-embedding",
                "status": "ok",
                "call_count": 2,
                "cost_basis": "local",
                "runtime_ms": 12,
            }
        ]

    monkeypatch.setattr("sunshine_api.routers.health.list_postgres_run_model_usage", fake_list_model_usage)

    response = TestClient(app).get("/admin/system/postgres-runtime/runs/run-1/model-usage?limit=11")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_key"] == "run-1"
    assert payload["summary"]["total_calls"] == 2
    assert payload["summary"]["local_calls"] == 2
    assert payload["by_purpose"]["chunk_embedding"]["calls"] == 2
    assert captured == {"run_key": "run-1", "limit": 11}


def test_semantic_search_endpoint_wraps_local_qdrant_service(monkeypatch) -> None:
    captured = {}

    def fake_search(*, query: str, limit: int = 10, collection: str | None = None, metadata_filter: dict | None = None) -> dict:
        captured["query"] = query
        captured["limit"] = limit
        captured["collection"] = collection
        captured["metadata_filter"] = metadata_filter
        return {
            "ok": True,
            "query": query,
            "local_only": True,
            "provider": "qdrant",
            "collection": collection,
            "status": "retrieved",
            "warnings": [],
            "metadata_filter": metadata_filter or {},
            "attempt": {"provider": "qdrant", "status": "retrieved"},
            "matches": [
                {
                    "score": 0.91,
                    "relative_path": "History/founders.pdf",
                    "chunk_id": "chunk-1",
                    "text_snippet": "Founders of Sunshine Club",
                    "citation": {"page_start": 1, "page_end": 2},
                }
            ],
        }

    monkeypatch.setattr("sunshine_api.routers.semantic.search_semantic_content", fake_search)

    response = TestClient(app).post(
        "/admin/search/semantic",
        json={
            "query": "founders dental care",
            "collection": "sunshine-test",
            "limit": 3,
            "run_key": "run-1",
            "primary_tag": "history_archive_general",
            "metadata_filter": {"chunk_kind": "segment_text"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"][0]["relative_path"] == "History/founders.pdf"
    assert captured == {
        "query": "founders dental care",
        "limit": 3,
        "collection": "sunshine-test",
        "metadata_filter": {
            "chunk_kind": "segment_text",
            "run_key": "run-1",
            "primary_tag": "history_archive_general",
        },
    }


def test_postgres_segment_review_decision_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_record_segment_decision(*, run_key: str, segment_id: str, decision: str, notes: str | None = None, reviewer: str | None = None) -> dict:
        captured.update(
            {
                "run_key": run_key,
                "segment_id": segment_id,
                "decision": decision,
                "notes": notes,
                "reviewer": reviewer,
            }
        )
        return {
            "run_key": run_key,
            "segment_id": segment_id,
            "decision": decision,
            "review_status": "changed",
            "segment": {"segment_id": segment_id, "metadata": {"segment_review": {"decision": decision}}},
        }

    monkeypatch.setattr("sunshine_api.routers.health.record_postgres_segment_review_decision", fake_record_segment_decision)

    response = TestClient(app).post(
        "/admin/system/postgres-runtime/runs/run-1/segments/segment-001/decision",
        json={"decision": "split", "notes": "article boundary is too broad", "reviewer": "james"},
    )

    assert response.status_code == 200
    assert response.json()["review_status"] == "changed"
    assert captured == {
        "run_key": "run-1",
        "segment_id": "segment-001",
        "decision": "split",
        "notes": "article boundary is too broad",
        "reviewer": "james",
    }


def test_postgres_run_events_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_list_events(*, run_key: str, limit: int = 200) -> list[dict[str, Any]]:
        captured["run_key"] = run_key
        captured["limit"] = limit
        return [{"node": "extract_content", "status": "ok", "message": "extracted text"}]

    monkeypatch.setattr("sunshine_api.routers.health.list_postgres_run_events", fake_list_events)

    response = TestClient(app).get("/admin/system/postgres-runtime/runs/run-1/events?limit=9")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["events"][0]["node"] == "extract_content"
    assert captured == {"run_key": "run-1", "limit": 9}


def test_postgres_review_decision_endpoint_wraps_service(monkeypatch) -> None:
    captured = {}

    def fake_record_decision(item_id: str, **kwargs) -> dict:
        captured["item_id"] = item_id
        captured.update(kwargs)
        return {"id": item_id, "status": "changed", "corrected_tag": kwargs["correct_tag"]}

    monkeypatch.setattr("sunshine_api.routers.health.record_postgres_review_decision", fake_record_decision)

    response = TestClient(app).post(
        "/admin/system/postgres-runtime/review-items/review-1/decision",
        json={
            "decision": "change",
            "correct_class": "document",
            "correct_tag": "history_archive_general",
            "correct_secondary_tags": ["history_archive"],
            "notes": "fixed",
        },
    )

    assert response.status_code == 200
    assert response.json()["item"]["status"] == "changed"
    assert captured == {
        "item_id": "review-1",
        "decision": "change",
        "correct_class": "document",
        "correct_tag": "history_archive_general",
        "correct_secondary_tags": ["history_archive"],
        "notes": "fixed",
    }


def test_local_infrastructure_status_is_local_only(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://sunshine:local@localhost:5432/sunshine_club")
    monkeypatch.setenv("SUNSHINE_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("CORTEX_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("CORTEX_MODEL", "gemma4-26b")
    monkeypatch.setenv("CORTEX_API_KEY", "local")
    monkeypatch.setenv("SUNSHINE_RERANK_PROVIDER", "cortex")
    monkeypatch.setenv("SUNSHINE_RERANK_MODEL", "rerank-local")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("SUNSHINE_MODEL_CACHE_PATH", "/tmp/sunshine-model-cache.sqlite")

    response = TestClient(app).get("/admin/system/local-infrastructure")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_only"] is True
    assert payload["policy"]["hosted_third_party_apis_allowed"] is False
    assert payload["policy"]["source_files_mutable"] is False
    assert payload["postgres"]["configured"] is True
    assert payload["postgres"]["v2_migrations"]["complete"] is True
    assert "0007_pipeline_parser_results.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0008_model_usage_host.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0009_pipeline_provider_selections.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0010_pipeline_quality_checks.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0011_pipeline_tagging_evidence.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0012_pipeline_file_metadata.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0013_pipeline_artifacts.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert "0014_pipeline_processing_artifacts.sql" in payload["postgres"]["v2_migrations"]["present"]
    assert payload["qdrant"]["provider"] == "qdrant"
    assert payload["qdrant"]["local_only"] is True
    assert payload["qdrant"]["compose_service"] == "qdrant"
    assert payload["qdrant"]["required_for_production"] is True
    assert payload["qdrant"]["required_now"] is False
    assert payload["vector_store_policy"]["provider"] == "noop"
    assert payload["vector_store_policy"]["qdrant_required"] is False
    assert payload["runtime_policy"]["single_file_latency_target_ms"] == 120000
    assert payload["runtime_policy"]["raw_provider_storage"] == "artifact_file_by_run"
    assert payload["runtime_policy"]["source_files_mutable"] is False
    assert payload["qdrant_retrieval"]["provider"] == "qdrant"
    assert payload["cortex_rerank"]["provider"] == "cortex"
    assert payload["cortex_rerank"]["configured"] is True
    assert payload["cortex_rerank"]["available"] is True
    assert payload["cortex_rerank"]["model"] == "rerank-local"
    assert payload["cortex_rerank"]["local_only"] is True
    assert payload["docling"]["provider"] == "docling"
    assert payload["docling"]["local_only"] is True
    assert set(payload["parser_providers"]) == {"docling", "mineru", "ragflow_deepdoc", "unstructured"}
    assert all(status["local_only"] is True for status in payload["parser_providers"].values())
    assert payload["parser_policy"]["ocr_parser_provider"] == "docling"
    assert payload["parser_policy"]["hosted_allowed"] is False
    assert payload["cortex"]["configured"] is True
    assert payload["model_call_cache"]["configured"] is True
    assert payload["model_call_cache"]["local_only"] is True
    assert payload["model_call_cache"]["namespaces"] == ["embedding", "llm_tag_inspection", "reranking"]
    assert payload["temporal"]["configured"] is True
    assert "address_reachable" in payload["temporal"]
    assert payload["temporal"]["worker_registered"] is True
    assert payload["observability"]["local_only"] is True
    assert payload["provider_registry"]["validation"]["ok"] is True
    assert any(provider["key"] == "reranking.cortex" and provider["enabled"] is True for provider in payload["provider_registry"]["providers"])
    assert any(provider["key"] == "ocr.openai" and provider["enabled"] is False for provider in payload["provider_registry"]["providers"])


def test_qdrant_rebuild_endpoint_accepts_collection_override(monkeypatch) -> None:
    captured = {}

    def fake_rebuild(*, run_key: str | None = None, collection: str | None = None, limit: int | None = None) -> dict:
        captured["run_key"] = run_key
        captured["collection"] = collection
        captured["limit"] = limit
        return {
            "ok": True,
            "run_key": run_key,
            "collection": collection,
            "requested_limit": limit,
            "source_row_count": 1,
            "vector_store": {
                "provider": "qdrant",
                "collection": collection,
                "status": "indexed",
                "indexed_count": 1,
            },
        }

    monkeypatch.setattr("sunshine_api.routers.semantic.rebuild_qdrant_from_postgres", fake_rebuild)

    response = TestClient(app).post(
        "/admin/vector-index/qdrant/rebuild",
        json={"run_key": "run-1", "collection": "sunshine-review", "limit": 25},
    )

    assert response.status_code == 200
    assert response.json()["collection"] == "sunshine-review"
    assert captured == {"run_key": "run-1", "collection": "sunshine-review", "limit": 25}


def test_run_request_rejects_hosted_openai_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))

    response = TestClient(app).post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
            "embedding_provider": "openai",
            "start": False,
        },
    )

    assert response.status_code == 422


def test_run_creation_records_queued_state_to_postgres_when_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    captured: dict[str, Any] = {}

    def fake_record(*, run: dict[str, Any], status: str | None = None, summary: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
        captured["run_key"] = run["run_key"]
        captured["status"] = status
        captured["output_dir"] = run["output_dir"]
        captured["summary"] = summary
        captured["error"] = error
        return {"record_status": "recorded", "store": "postgres_runtime", "result": {"run_key": run["run_key"], "status": status}}

    monkeypatch.setattr("sunshine_api.routers.runs.record_postgres_pipeline_run_state_if_configured", fake_record)

    response = TestClient(app).post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
            "embedding_provider": "cortex",
            "start": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["postgres_record"]["record_status"] == "recorded"
    assert response.json()["execution_backend"] == "subprocess"
    assert captured["status"] == "queued"
    assert captured["output_dir"] == str(tmp_path / "output")
    assert captured["summary"] == {"execution_backend": "subprocess"}


def test_run_creation_can_dispatch_temporal_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    captured: dict[str, Any] = {}

    class ImmediateThread:
        def __init__(self, *, target, args, daemon: bool) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self) -> None:
            captured["thread_daemon"] = self.daemon
            self.target(*self.args)

    def fake_execute(run_id: int, payload: dict[str, Any], import_on_success: bool) -> None:
        captured["run_id"] = run_id
        captured["payload"] = payload
        captured["import_on_success"] = import_on_success

    monkeypatch.setattr("sunshine_api.routers.runs._batch_input_sample_count", lambda _root: 1)
    monkeypatch.setattr("sunshine_api.routers.runs._execute_temporal_batch_run", fake_execute)
    monkeypatch.setattr("sunshine_api.routers.runs.threading.Thread", ImmediateThread)

    response = TestClient(app).post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "execution_backend": "temporal",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
            "semantic_index_path": str(tmp_path / "semantic.sqlite"),
            "embedding_provider": "cortex",
            "start": True,
            "import_on_success": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_backend"] == "temporal"
    assert captured["thread_daemon"] is True
    assert captured["run_id"] == payload["id"]
    assert captured["import_on_success"] is True
    assert captured["payload"] == {
        "input_root": str(tmp_path / "input"),
        "output_dir": str(tmp_path / "output"),
        "progress": True,
        "retry_attempts": 1,
        "max_concurrency": 1,
        "semantic_index_path": str(tmp_path / "semantic.sqlite"),
    }


def test_runs_endpoint_can_read_postgres_v2_source(monkeypatch) -> None:
    def fake_list(*, limit: int = 100) -> list[dict[str, Any]]:
        assert limit == 7
        return [
            {
                "id": "postgres-id",
                "run_key": "qa_samples_fast-1",
                "preset_key": "qa_samples_fast",
                "input_root": "/mnt/sunshine/qa samples",
                "output_dir": "/mnt/sunshine/dashboard-runs/qa_samples_fast-1",
                "status": "running",
                "embedding_provider": "cortex",
                "llm_provider": "cortex",
                "extraction_provider": "docling",
                "started_at": "2026-05-28T00:00:00",
                "finished_at": None,
                "created_at": "2026-05-28T00:00:00",
                "updated_at": "2026-05-28T00:01:00",
                "summary": {"processed_count": 4, "run_role": "evaluation"},
                "result_count": 3,
                "review_required_count": 1,
                "model_usage_count": 2,
                "provider_attempt_count": 3,
                "document_segment_count": 4,
            }
        ]

    monkeypatch.setattr("sunshine_api.routers.runs.list_postgres_pipeline_runs", fake_list)

    response = TestClient(app).get("/admin/runs", params={"source": "postgres", "limit": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["source"] == "postgres"
    assert payload[0]["id"] == "qa_samples_fast-1"
    assert payload[0]["postgres_id"] == "postgres-id"
    assert payload[0]["run_role"] == "evaluation"
    assert payload[0]["processed_count"] == 4
    assert payload[0]["review_required_count"] == 1


def test_live_run_progress_records_running_state_to_postgres(monkeypatch) -> None:
    from sunshine_api.services import run_execution

    captured: dict[str, Any] = {}

    class FakeStore:
        def get_pipeline_run(self, run_id: int) -> dict[str, Any]:
            assert run_id == 42
            return {
                "id": run_id,
                "run_key": "qa-run-progress",
                "preset_key": "qa_samples_fast",
                "status": "running",
                "input_root": "/mnt/sunshine/qa samples",
                "output_dir": "/mnt/sunshine/dashboard-runs/qa-run-progress",
                "summary": {"processed_count": 1},
            }

    def fake_record(run: dict[str, Any], *, status: str, summary: dict[str, Any], error: str | None = None) -> None:
        captured["run_key"] = run["run_key"]
        captured["status"] = status
        captured["summary"] = summary
        captured["error"] = error

    monkeypatch.setattr(run_execution, "_record_postgres_run_state", fake_record)

    run_execution._record_postgres_run_progress(FakeStore(), 42, {"processed_count": 4, "selected_sample_count": 10})

    assert captured == {
        "run_key": "qa-run-progress",
        "status": "running",
        "summary": {"processed_count": 4, "selected_sample_count": 10},
        "error": None,
    }


def test_provider_benchmark_api_runs_current_provider(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    output_dir = tmp_path / "provider-benchmark"
    client = TestClient(app)

    run = client.post(
        "/admin/provider-benchmarks/run",
        json={"paths": [str(source)], "providers": ["current"], "output_dir": str(output_dir)},
    )
    latest = client.get("/admin/provider-benchmarks/latest", params={"output_dir": str(output_dir)})

    assert run.status_code == 200
    assert run.json()["summary"]["by_provider"]["current"] == 1
    assert run.json()["summary"]["local_only"] is True
    assert run.json()["postgres_import"]["import_status"] == "skipped"
    assert latest.status_code == 200
    assert latest.json()["summary"]["result_count"] == 1
    assert latest.json()["recommendations"][0]["provider"] == "current"
    assert latest.json()["recommendations"][0]["local_only"] is True
    assert latest.json()["results"][0]["provider"] == "current"
    assert latest.json()["parser_results"][0]["parser_provider"] == "current"
    assert latest.json()["parser_results"][0]["text_snippet"] == "Meeting minutes and Sunshine Club notes."
    assert latest.json()["artifact_manifest"]["existing_artifact_count"] == 5


def test_provider_benchmark_api_can_start_background_run(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "provider-benchmark"
    called = threading.Event()
    imported = threading.Event()

    def fake_benchmark(*args, **kwargs) -> dict:
        Path(kwargs["output_dir"]).mkdir(parents=True, exist_ok=True)
        (Path(kwargs["output_dir"]) / "provider-benchmark-results.jsonl").write_text(
            '{"provider":"current","status":"extracted","quality":"ok","requires_review":false}\n',
            encoding="utf-8",
        )
        called.set()
        return {"summary": {}, "results": [], "parser_results": [], "recommendations": []}

    def fake_import(output_dir: str) -> dict[str, Any]:
        imported.set()
        return {"import_status": "imported", "output_dir": output_dir, "result": {"benchmark_key": "provider-benchmark"}}

    monkeypatch.setattr("sunshine_api.routers.semantic.benchmark_extraction_providers", fake_benchmark)
    monkeypatch.setattr("sunshine_api.routers.semantic.import_provider_benchmark_output_to_postgres_if_configured", fake_import)

    response = TestClient(app).post(
        "/admin/provider-benchmarks/run",
        json={"paths": [str(tmp_path / "missing.txt")], "providers": ["current"], "output_dir": str(output_dir), "background": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["background"] is True
    assert called.wait(timeout=2)
    assert imported.wait(timeout=2)
    import_status_path = output_dir / "provider-benchmark-postgres-import.json"
    for _attempt in range(20):
        if import_status_path.exists() and import_status_path.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.05)
    import_status = json.loads(import_status_path.read_text(encoding="utf-8"))
    assert import_status["import_status"] == "imported"


def test_provider_benchmark_postgres_import_and_list_wrap_services(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_import(output_dir: str, *, benchmark_key: str | None = None) -> dict[str, Any]:
        captured["output_dir"] = output_dir
        captured["benchmark_key"] = benchmark_key
        return {
            "benchmark_run_id": "benchmark-id",
            "benchmark_key": benchmark_key,
            "output_dir": output_dir,
            "status": "completed",
            "partial": False,
            "imported": {"provider_benchmark_results": 1},
        }

    def fake_list(*, limit: int = 50) -> list[dict[str, Any]]:
        captured["limit"] = limit
        return [{"benchmark_key": "benchmark-1", "result_count": 1}]

    def fake_get(*, benchmark_key: str, result_limit: int = 500, parser_result_limit: int = 500) -> dict[str, Any]:
        captured["detail"] = {
            "benchmark_key": benchmark_key,
            "result_limit": result_limit,
            "parser_result_limit": parser_result_limit,
        }
        return {
            "run": {"benchmark_key": benchmark_key, "status": "completed"},
            "summary": {"result_count": 1, "parser_result_count": 1},
            "results": [{"provider": "docling", "status": "extracted"}],
            "parser_results": [{"provider": "docling", "quality": "ok"}],
            "recommendations": [{"provider": "docling", "recommendation": "candidate"}],
        }

    def fake_promotion_plan(*, benchmark_key: str) -> dict[str, Any]:
        captured["promotion_plan"] = {"benchmark_key": benchmark_key}
        return {
            "benchmark_key": benchmark_key,
            "status": "candidate",
            "selected_provider": "docling",
            "recommended_env": {"SUNSHINE_OCR_PARSER_PROVIDER": "docling"},
            "shell_exports": ["export SUNSHINE_OCR_PARSER_PROVIDER=docling"],
        }

    monkeypatch.setattr("sunshine_api.routers.semantic.import_provider_benchmark_output_to_postgres", fake_import)
    monkeypatch.setattr("sunshine_api.routers.semantic.list_postgres_provider_benchmark_runs", fake_list)
    monkeypatch.setattr("sunshine_api.routers.semantic.get_postgres_provider_benchmark_run", fake_get)
    monkeypatch.setattr("sunshine_api.routers.semantic.get_postgres_provider_benchmark_promotion_plan", fake_promotion_plan)

    imported = TestClient(app).post(
        "/admin/provider-benchmarks/import-postgres",
        json={"output_dir": "/tmp/provider-benchmark", "benchmark_key": "benchmark-1"},
    )
    listed = TestClient(app).get("/admin/provider-benchmarks/postgres?limit=7")
    detail = TestClient(app).get("/admin/provider-benchmarks/postgres/benchmark-1?result_limit=9&parser_result_limit=11")
    promotion_plan = TestClient(app).get("/admin/provider-benchmarks/postgres/benchmark-1/promotion-plan")

    assert imported.status_code == 200
    assert imported.json()["benchmark_run_id"] == "benchmark-id"
    assert listed.status_code == 200
    assert listed.json()["runs"][0]["benchmark_key"] == "benchmark-1"
    assert detail.status_code == 200
    assert detail.json()["run"]["benchmark_key"] == "benchmark-1"
    assert detail.json()["recommendations"][0]["recommendation"] == "candidate"
    assert promotion_plan.status_code == 200
    assert promotion_plan.json()["selected_provider"] == "docling"
    assert captured == {
        "output_dir": "/tmp/provider-benchmark",
        "benchmark_key": "benchmark-1",
        "limit": 7,
        "detail": {"benchmark_key": "benchmark-1", "result_limit": 9, "parser_result_limit": 11},
        "promotion_plan": {"benchmark_key": "benchmark-1"},
    }


def test_review_items_can_read_postgres_v2_source(monkeypatch) -> None:
    rows = [
        {
            "id": "review-1",
            "run_id": "run-db-id",
            "run_key": "qa_samples_full-1",
            "preset_key": "qa_samples_full",
            "source_path": "/mnt/sunshine/history.pdf",
            "relative_path": "History/history.pdf",
            "segment_id": "seg-1",
            "status": "open",
            "review_reason": "needs_segment_review",
            "proposed_class": "scanned_document",
            "proposed_tag": "scrapbooks",
            "proposed_secondary_tags": ["history_archive"],
            "corrected_class": None,
            "corrected_tag": None,
            "corrected_secondary_tags": [],
            "notes": "segment proposal",
        },
        {
            "id": "review-2",
            "run_id": "run-db-id",
            "run_key": "qa_samples_full-1",
            "preset_key": "qa_samples_full",
            "source_path": "/mnt/sunshine/finance.pdf",
            "relative_path": "Finance/finance.pdf",
            "segment_id": None,
            "status": "accepted",
            "review_reason": "accepted",
            "proposed_class": "document",
            "proposed_tag": "finance_treasurer_records",
            "proposed_secondary_tags": [],
            "corrected_class": "document",
            "corrected_tag": "finance_treasurer_records",
            "corrected_secondary_tags": [],
            "notes": None,
        },
    ]
    monkeypatch.setattr("sunshine_api.routers.review.list_postgres_review_items", lambda **kwargs: rows)

    response = TestClient(app).get(
        "/admin/review/items",
        params={"source": "postgres", "status": "open", "primary_tag": "scrapbooks", "run_key": "qa_samples_full-1"},
    )
    facets = TestClient(app).get("/admin/review/facets", params={"source": "postgres", "status": "all"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["source"] == "postgres"
    assert payload[0]["id"] == "review-1"
    assert payload[0]["run_key"] == "qa_samples_full-1"
    assert payload[0]["run_preset_key"] == "qa_samples_full"
    assert payload[0]["secondary_tags"] == ["history_archive"]
    assert payload[0]["result"]["top_tag_candidate"] == "scrapbooks"
    assert facets.status_code == 200
    assert facets.json()["primary_tag"]["scrapbooks"] == 1
    assert facets.json()["review_status"]["accepted"] == 1


def test_review_summary_can_read_postgres_v2_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "sunshine_api.routers.review.postgres_review_summary",
        lambda: {
            "db_path": "postgresql://local/test",
            "source": "postgres",
            "total_results": 4,
            "total_review_items": 3,
            "total_golden_labels": 0,
            "review_by_status": {"open": 1, "accepted": 1, "changed": 1, "resolved": 2},
            "results_by_route_status": {"route_candidate": 2, "review_required": 2},
            "results_by_quality": {"ok": 3, "poor": 1},
            "results_by_primary_tag": {"scrapbooks": 2},
            "results_by_secondary_tag": {},
        },
    )

    response = TestClient(app).get("/admin/review/summary", params={"source": "postgres"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "postgres"
    assert payload["total_review_items"] == 3
    assert payload["review_by_status"]["resolved"] == 2


def test_file_search_can_read_postgres_v2_source(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(**kwargs) -> dict:
        captured.update(kwargs)
        return {
            "items": [
                {
                    "id": "result-1",
                    "source": "postgres",
                    "filename": "history.pdf",
                    "compact_path": "Sunshine/.../history.pdf",
                    "source_path": "/mnt/sunshine/history.pdf",
                    "relative_path": "Sunshine/history.pdf",
                    "extension": ".pdf",
                    "source_collection": "sunshine_shared_folders",
                    "content_class": "document",
                    "primary_tag": "history_archive_general",
                    "secondary_tags": ["club_history"],
                    "route_status": "route_candidate",
                    "quality": "ok",
                    "review_status": None,
                    "placement_status": "ready",
                    "text_snippet": "Founders history",
                    "latest_run_id": "run-id",
                    "latest_run_key": "run-1",
                    "updated_at": "2026-05-28T00:00:00",
                }
            ],
            "next_cursor": None,
            "total_estimate": 1,
            "query": {"source": "postgres"},
        }

    def fake_facets(**kwargs) -> dict[str, dict[str, int]]:
        captured["facets"] = kwargs
        return {"primary_tag": {"history_archive_general": 1}, "extension": {".pdf": 1}}

    monkeypatch.setattr("sunshine_api.routers.files.search_postgres_files", fake_search)
    monkeypatch.setattr("sunshine_api.routers.files.postgres_file_facets", fake_facets)

    search = TestClient(app).get("/admin/files/search", params={"source": "postgres", "primary_tag": "history_archive_general"})
    facets = TestClient(app).get("/admin/files/facets", params={"source": "postgres", "primary_tag": "history_archive_general"})
    legacy_list = TestClient(app).get("/admin/files", params={"source": "postgres", "primary_tag": "history_archive_general"})

    assert search.status_code == 200
    assert search.json()["items"][0]["source"] == "postgres"
    assert search.json()["items"][0]["primary_tag"] == "history_archive_general"
    assert facets.status_code == 200
    assert facets.json()["primary_tag"] == {"history_archive_general": 1}
    assert legacy_list.status_code == 200
    assert legacy_list.json()[0]["id"] == "result-1"
    assert captured["primary_tag"] == "history_archive_general"


def test_file_detail_text_and_preview_can_read_postgres_v2_source(tmp_path: Path, monkeypatch) -> None:
    source_file = tmp_path / "history.pdf"
    source_file.write_text("source pdf bytes", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_detail(result_id: str) -> dict[str, Any]:
        captured["detail"] = result_id
        return {
            "id": result_id,
            "source": "postgres",
            "filename": "history.pdf",
            "source_path": str(source_file),
            "relative_path": "Sunshine/history.pdf",
            "latest_result": {"quality": "ok"},
        }

    def fake_text(result_id: str) -> dict[str, Any]:
        captured["text"] = result_id
        return {
            "file_id": result_id,
            "source": "postgres",
            "source_path": str(source_file),
            "relative_path": "Sunshine/history.pdf",
            "text": "Founders history text from chunks.",
        }

    def fake_inspection(result_id: str) -> dict[str, Any]:
        captured["inspection"] = result_id
        return {
            "file": {"id": result_id, "source": "postgres"},
            "latest_result": {"quality": "ok"},
            "text": {"text": "Founders history text from chunks.", "length": 27},
        }

    def fake_path(result_id: str) -> Path:
        captured["path"] = result_id
        return source_file

    monkeypatch.setattr("sunshine_api.routers.files.get_postgres_file_result", fake_detail)
    monkeypatch.setattr("sunshine_api.routers.files.postgres_file_result_text", fake_text)
    monkeypatch.setattr("sunshine_api.routers.files.postgres_file_result_inspection", fake_inspection)
    monkeypatch.setattr("sunshine_api.routers.files.file_path_for_postgres_file_result", fake_path)

    client = TestClient(app)
    detail = client.get("/admin/files/result-1", params={"source": "postgres"})
    text = client.get("/admin/files/result-1/text", params={"source": "postgres"})
    inspection = client.get("/admin/files/result-1/inspection", params={"source": "postgres"})
    preview = client.get("/admin/files/result-1/preview", params={"source": "postgres"})

    assert detail.status_code == 200
    assert detail.json()["source"] == "postgres"
    assert text.status_code == 200
    assert text.json()["text"] == "Founders history text from chunks."
    assert inspection.status_code == 200
    assert inspection.json()["file"]["source"] == "postgres"
    assert preview.status_code == 200
    assert preview.text == "source pdf bytes"
    assert captured == {"detail": "result-1", "text": "result-1", "inspection": "result-1", "path": "result-1"}


def test_file_review_enqueue_can_use_postgres_v2_source(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_add(result_id: str, *, review_reason: str) -> dict[str, Any]:
        captured["result_id"] = result_id
        captured["review_reason"] = review_reason
        return {
            "id": "review-1",
            "source": "postgres",
            "file_result_id": result_id,
            "status": "open",
            "review_reason": review_reason,
        }

    monkeypatch.setattr("sunshine_api.routers.files.add_postgres_file_result_to_review", fake_add)

    response = TestClient(app).post(
        "/admin/files/result-1/review",
        params={"source": "postgres"},
        json={"review_reason": "manual_quality_check"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "postgres"
    assert response.json()["review_reason"] == "manual_quality_check"
    assert captured == {"result_id": "result-1", "review_reason": "manual_quality_check"}


def test_file_run_can_use_postgres_v2_source(tmp_path: Path, monkeypatch) -> None:
    source_file = tmp_path / "history.pdf"
    source_file.write_text("source pdf bytes", encoding="utf-8")
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))

    def fake_detail(result_id: str) -> dict[str, Any]:
        return {
            "id": result_id,
            "source": "postgres",
            "filename": "history.pdf",
            "source_path": "/mnt/sunshine/history.pdf",
            "relative_path": "Sunshine/history.pdf",
        }

    monkeypatch.setattr("sunshine_api.routers.files.get_postgres_file_result", fake_detail)
    monkeypatch.setattr("sunshine_api.routers.files.file_path_for_postgres_file_result", lambda _result_id: source_file)

    response = TestClient(app).post(
        "/admin/files/result-1/run",
        params={"source": "postgres"},
        json={
            "output_dir": str(tmp_path / "single-file-postgres-run"),
            "start": False,
            "embedding_provider": "cortex",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "cortex",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preset_key"] == "single_file_debug"
    assert payload["input_root"] == str(source_file)
    assert "--input-file" in payload["command"]
    assert str(source_file) in payload["command"]
    assert "--source-path" in payload["command"]
    assert "/mnt/sunshine/history.pdf" in payload["command"]
    assert "--relative-path" in payload["command"]
    assert "Sunshine/history.pdf" in payload["command"]


def test_golden_labels_can_read_postgres_v2_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "sunshine_api.routers.review.list_postgres_golden_labels",
        lambda **kwargs: [
            {
                "id": "golden-1",
                "review_item_id": "review-1",
                "run_id": "run-db-id",
                "run_key": "qa_samples_full-1",
                "preset_key": "qa_samples_full",
                "source_path": "/mnt/sunshine/history.pdf",
                "relative_path": "History/history.pdf",
                "segment_id": "seg-1",
                "content_class": "document",
                "correct_primary_tag": "history_archive_general",
                "correct_secondary_tags": ["club_history"],
                "proposed_tag": "scrapbooks",
                "proposed_secondary_tags": ["history_archive"],
            }
        ],
    )
    monkeypatch.setattr(
        "sunshine_api.routers.review.postgres_golden_label_summary",
        lambda: {"source": "postgres", "total_golden_labels": 1, "golden_by_primary_tag": {"history_archive_general": 1}},
    )

    labels = TestClient(app).get("/admin/review/golden-labels", params={"source": "postgres"})
    summary = TestClient(app).get("/admin/review/golden-labels/summary", params={"source": "postgres"})
    export = TestClient(app).get("/admin/review/golden-labels/export", params={"source": "postgres", "format": "csv"})

    assert labels.status_code == 200
    assert labels.json()[0]["source"] == "postgres"
    assert labels.json()[0]["correct_primary_tag"] == "history_archive_general"
    assert labels.json()[0]["segment_id"] == "seg-1"
    assert summary.status_code == 200
    assert summary.json()["total_golden_labels"] == 1
    assert export.status_code == 200
    assert "history_archive_general" in export.text


def test_golden_label_mutations_can_use_postgres_v2_source(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    source_file = tmp_path / "history.pdf"
    source_file.write_text("history source", encoding="utf-8")

    def fake_update(label_id: str, **kwargs) -> dict:
        captured["update_label_id"] = label_id
        captured["update_kwargs"] = kwargs
        return {
            "id": label_id,
            "review_item_id": "review-1",
            "run_id": "run-db-id",
            "run_key": "qa_samples_full-1",
            "preset_key": "qa_samples_full",
            "source_path": str(source_file),
            "relative_path": "History/history.pdf",
            "segment_id": "seg-1",
            "content_class": kwargs["content_class"],
            "correct_primary_tag": kwargs["correct_primary_tag"],
            "correct_secondary_tags": kwargs["correct_secondary_tags"],
            "ocr_quality_label": kwargs["ocr_quality_label"],
            "expected_review_required": kwargs["expected_review_required"],
            "sensitive_record": kwargs["sensitive_record"],
            "proposed_tag": "scrapbooks",
            "proposed_secondary_tags": ["history_archive"],
        }

    def fake_delete(label_id: str) -> dict:
        captured["delete_label_id"] = label_id
        return {"deleted": True, "id": label_id, "source_path": str(source_file)}

    def fake_file_path(label_id: str) -> Path:
        captured["file_label_id"] = label_id
        return source_file

    monkeypatch.setattr("sunshine_api.routers.review.update_postgres_golden_label", fake_update)
    monkeypatch.setattr("sunshine_api.routers.review.delete_postgres_golden_label", fake_delete)
    monkeypatch.setattr("sunshine_api.routers.review.file_path_for_postgres_golden_label", fake_file_path)

    edited = TestClient(app).patch(
        "/admin/review/golden-labels/golden-1",
        params={"source": "postgres"},
        json={
            "content_class": "document",
            "correct_primary_tag": "history_archive_general",
            "correct_secondary_tags": ["club_history"],
            "ocr_quality_label": "ok",
            "expected_review_required": False,
            "sensitive_record": True,
            "reviewer": "auditor",
            "notes": "corrected",
        },
    )
    file_response = TestClient(app).get("/admin/review/golden-labels/golden-1/file", params={"source": "postgres"})
    deleted = TestClient(app).delete("/admin/review/golden-labels/golden-1", params={"source": "postgres"})

    assert edited.status_code == 200
    assert edited.json()["source"] == "postgres"
    assert edited.json()["correct_primary_tag"] == "history_archive_general"
    assert file_response.status_code == 200
    assert file_response.text == "history source"
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert captured["update_label_id"] == "golden-1"
    assert captured["delete_label_id"] == "golden-1"
    assert captured["file_label_id"] == "golden-1"


def test_semantic_index_build_can_use_postgres_golden_labels(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_export(output_db: str, **kwargs) -> dict:
        captured["export_output_db"] = output_db
        captured["export_kwargs"] = kwargs
        Path(output_db).parent.mkdir(parents=True, exist_ok=True)
        Path(output_db).write_text("sqlite placeholder", encoding="utf-8")
        return {"status": "exported", "label_count": 1, "output_db": output_db}

    def fake_build(labels_db: str, output_db: str, *, limit: int | None = None) -> dict:
        captured["build_labels_db"] = labels_db
        captured["build_output_db"] = output_db
        captured["build_limit"] = limit
        return {"indexed": 1, "labels_db": labels_db, "output_db": output_db}

    monkeypatch.setattr("sunshine_api.routers.semantic.export_postgres_golden_labels_sqlite", fake_export)
    monkeypatch.setattr("sunshine_api.routers.semantic.build_semantic_index", fake_build)

    response = TestClient(app).post(
        "/admin/semantic-index/build",
        json={
            "labels_source": "postgres",
            "labels_db": str(tmp_path / "v2-labels.sqlite"),
            "output_db": str(tmp_path / "semantic.sqlite"),
            "limit": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["indexed"] == 1
    assert captured["export_output_db"] == str(tmp_path / "v2-labels.sqlite")
    assert captured["export_kwargs"]["limit"] == 5
    assert captured["build_labels_db"] == str(tmp_path / "v2-labels.sqlite")
    assert captured["build_output_db"] == str(tmp_path / "semantic.sqlite")
    assert captured["build_limit"] == 5


def test_review_decision_can_write_postgres_v2_source(monkeypatch) -> None:
    captured = {}

    def fake_record_decision(item_id: str, **kwargs) -> dict:
        captured["item_id"] = item_id
        captured.update(kwargs)
        return {
            "id": item_id,
            "run_id": "run-db-id",
            "run_key": "qa_samples_full-1",
            "preset_key": "qa_samples_full",
            "source_path": "/mnt/sunshine/history.pdf",
            "relative_path": "History/history.pdf",
            "segment_id": "seg-1",
            "status": "changed",
            "review_reason": "needs_segment_review",
            "proposed_class": "scanned_document",
            "proposed_tag": "scrapbooks",
            "proposed_secondary_tags": ["history_archive"],
            "corrected_class": kwargs["correct_class"],
            "corrected_tag": kwargs["correct_tag"],
            "corrected_secondary_tags": kwargs["correct_secondary_tags"],
            "notes": kwargs["notes"],
        }

    monkeypatch.setattr("sunshine_api.routers.review.record_postgres_review_decision", fake_record_decision)

    response = TestClient(app).post(
        "/admin/review/items/review-1/decision",
        params={"source": "postgres"},
        json={
            "decision": "change",
            "correct_class": "document",
            "correct_tag": "history_archive_general",
            "correct_secondary_tags": ["club_history", "scrapbook"],
            "notes": "reviewed segment",
            "save_as_golden": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "postgres"
    assert payload["id"] == "review-1"
    assert payload["status"] == "changed"
    assert payload["correct_class"] == "document"
    assert payload["correct_tag"] == "history_archive_general"
    assert payload["correct_secondary_tags"] == ["club_history", "scrapbook"]
    assert payload["run_key"] == "qa_samples_full-1"
    assert payload["segment_id"] == "seg-1"
    assert captured == {
        "item_id": "review-1",
        "decision": "change",
        "correct_class": "document",
        "correct_tag": "history_archive_general",
        "correct_secondary_tags": ["club_history", "scrapbook"],
        "ocr_quality_label": None,
        "expected_review_required": None,
        "sensitive_record": None,
        "correct_destination_path": None,
        "correct_placement_year": None,
        "correct_privacy": None,
        "reviewer": None,
        "notes": "reviewed segment",
        "save_as_golden": False,
    }


def test_review_detail_can_read_postgres_v2_source(monkeypatch) -> None:
    captured = {}

    def fake_get_review_item(item_id: str) -> dict:
        captured["item_id"] = item_id
        return {
            "id": item_id,
            "run_id": "run-db-id",
            "run_key": "qa_samples_full-1",
            "preset_key": "qa_samples_full",
            "source_path": "/mnt/sunshine/history.pdf",
            "relative_path": "History/history.pdf",
            "segment_id": "seg-1",
            "status": "open",
            "review_reason": "needs_segment_review",
            "proposed_class": "scanned_document",
            "proposed_tag": "scrapbooks",
            "proposed_secondary_tags": ["history_archive"],
            "corrected_class": None,
            "corrected_tag": None,
            "corrected_secondary_tags": [],
            "notes": None,
        }

    monkeypatch.setattr("sunshine_api.routers.review.get_postgres_review_item", fake_get_review_item)

    response = TestClient(app).get("/admin/review/items/review-1", params={"source": "postgres"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "postgres"
    assert payload["id"] == "review-1"
    assert payload["run_key"] == "qa_samples_full-1"
    assert payload["segment_id"] == "seg-1"
    assert payload["result"]["top_tag_candidate"] == "scrapbooks"
    assert captured == {"item_id": "review-1"}


def test_review_text_can_read_postgres_v2_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "sunshine_api.routers.review.get_postgres_review_item",
        lambda item_id: {
            "id": item_id,
            "source_path": "/mnt/sunshine/history.pdf",
            "relative_path": "History/history.pdf",
            "result": {"extraction_text_snippet": "Founders of Sunshine Club extracted text."},
        },
    )

    response = TestClient(app).get("/admin/review/items/review-1/text", params={"source": "postgres"})

    assert response.status_code == 200
    assert response.text == "Founders of Sunshine Club extracted text."


def test_review_file_can_read_postgres_v2_source_file(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "history.txt"
    source.write_text("source file contents", encoding="utf-8")
    monkeypatch.setattr(
        "sunshine_api.routers.review.get_postgres_review_item",
        lambda item_id: {
            "id": item_id,
            "sample_path": str(source),
            "source_path": "/mnt/sunshine/history.txt",
            "relative_path": "History/history.txt",
        },
    )

    response = TestClient(app).get("/admin/review/items/review-1/file", params={"source": "postgres"})

    assert response.status_code == 200
    assert response.text == "source file contents"


def test_review_decision_rejects_string_id_for_sqlite_source() -> None:
    response = TestClient(app).post(
        "/admin/review/items/review-1/decision",
        json={"decision": "accept", "save_as_golden": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "sqlite review item id must be an integer"


def test_provider_benchmark_latest_returns_partial_incremental_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "provider-benchmark"
    output_dir.mkdir()
    (output_dir / "provider-benchmark-results.jsonl").write_text(
        '{"provider":"docling","status":"extracted","quality":"ok","sample_category":"image_scan","requires_review":false}\n',
        encoding="utf-8",
    )
    (output_dir / "sample-parser-results.jsonl").write_text(
        '{"parser_provider":"docling","status":"extracted","quality":"ok","sample_category":"image_scan","text_snippet":"Founders of Sunshine Club"}\n',
        encoding="utf-8",
    )

    response = TestClient(app).get("/admin/provider-benchmarks/latest", params={"output_dir": str(output_dir)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["exists"] is True
    assert payload["partial"] is True
    assert payload["summary"]["partial"] is True
    assert payload["summary"]["result_count"] == 1
    assert payload["summary"]["by_provider"] == {"docling": 1}
    assert payload["summary"]["sample_categories"] == {"image_scan": 1}
    assert payload["results"][0]["provider"] == "docling"
    assert payload["parser_results"][0]["text_snippet"] == "Founders of Sunshine Club"


def test_provider_benchmark_api_accepts_optional_local_providers(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake pdf")
    client = TestClient(app)

    response = client.post(
        "/admin/provider-benchmarks/run",
        json={"paths": [str(source)], "providers": ["mineru", "ragflow_deepdoc", "unstructured"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["result_count"] == 3
    assert payload["summary"]["local_only"] is True


def test_provider_benchmark_api_accepts_sample_manifest(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    manifest = tmp_path / "provider-benchmark-samples.json"
    manifest.write_text(
        json.dumps({"samples": [{"path": "minutes.txt", "category": "born_digital_text", "label": "text sample"}]}),
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/admin/provider-benchmarks/run",
        json={"sample_manifest": str(manifest), "providers": ["current"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["sample_count"] == 1
    assert payload["summary"]["sample_categories"] == {"born_digital_text": 1}
    assert payload["results"][0]["sample_label"] == "text sample"


def test_model_usage_report_infers_calls_from_legacy_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "legacy-run"
    output_dir.mkdir()
    (output_dir / "sample-pipeline-results.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/scan.pdf",
                "relative_path": "Scans/scan.pdf",
                "warnings": ["ocr_fallback_used:openai:gpt-4.1-mini"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-llm-tag-inspections.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/scan.pdf",
                "relative_path": "Scans/scan.pdf",
                "provider": "cortex",
                "model": "gemma4-26b",
                "llm_status": "inspected",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-embeddings.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/scan.pdf",
                "relative_path": "Scans/scan.pdf",
                "chunk_id": "scan:1",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-large",
                "embedding_status": "embedded",
                "embedding_dimensions": 3072,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = _read_model_usage_artifact(output_dir, run_id=123)
    report = _model_usage_report(rows)

    assert report["summary"]["total_calls"] == 3
    assert report["summary"]["external_calls"] == 2
    assert report["summary"]["local_calls"] == 1
    assert report["summary"]["unknown_cost_basis_calls"] == 0
    assert report["summary"]["cost_basis_completeness_rate"] == 1.0
    assert report["summary"]["unknown_external_cost_calls"] == 2
    assert report["by_purpose"]["ocr_fallback"]["calls"] == 1
    assert report["by_purpose"]["tag_inspection"]["calls"] == 1
    assert report["by_purpose"]["chunk_embedding"]["calls"] == 1


def test_run_report_reads_live_graph_run_artifacts_before_batch_finalize(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    output_dir = tmp_path / "live-run"
    first_run_dir = output_dir / "graph-runs" / "00001"
    second_run_dir = output_dir / "graph-runs" / "00002"
    first_run_dir.mkdir(parents=True)
    second_run_dir.mkdir(parents=True)
    accepted = {
        "sample_path": str(tmp_path / "accepted.pdf"),
        "source_path": "/source/accepted.pdf",
        "relative_path": "Accepted/accepted.pdf",
        "route_status": "route_candidate",
        "final_class": "document",
        "extraction_strategy": "text_extraction",
        "extraction_status": "extracted",
        "quality": "ok",
        "top_tag_candidate": "meeting_records",
        "secondary_tags": ["meeting_minutes"],
        "tag_confidence": 0.96,
        "placement_status": "ready",
    }
    review_required = {
        "sample_path": str(tmp_path / "review.pdf"),
        "source_path": "/source/review.pdf",
        "relative_path": "Review/review.pdf",
        "route_status": "review_ocr_quality",
        "review_reason": "ocr_quality_not_trusted",
        "final_class": "scanned_document",
        "extraction_strategy": "ocr_page_level",
        "extraction_status": "extracted",
        "quality": "poor",
        "top_tag_candidate": "scrapbooks",
        "secondary_tags": ["scrapbook_page"],
        "tag_confidence": 0.64,
        "placement_status": "needs_review",
        "warnings": ["ocr_fallback_used:openai:gpt-4.1-mini"],
    }
    (first_run_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(accepted) + "\n", encoding="utf-8")
    (second_run_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(review_required) + "\n", encoding="utf-8")
    (second_run_dir / "sample-review-queue.jsonl").write_text(json.dumps(review_required) + "\n", encoding="utf-8")
    (second_run_dir / "sample-ocr-documents.jsonl").write_text(
        json.dumps({**review_required, "total_text_length": 42, "mean_confidence": 52.0}) + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-ocr-pages.jsonl").write_text(
        json.dumps({**review_required, "page_number": 1, "ocr_status": "ok"}) + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-extraction-results.jsonl").write_text(
        json.dumps({**review_required, "text": "Live OCR text snippet."}) + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-model-usage.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "purpose": "ocr_fallback",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "status": "ok",
                "cost_basis": "external",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-provider-attempts.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "provider": "current",
                "capability": "extraction",
                "status": "extracted",
                "strategy": "ocr_page_level",
                "seconds": 0.5,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-source-identity.jsonl").write_text(
        json.dumps(
            {
                "file_id": "file-review",
                "content_sha256": "a" * 64,
                "size_bytes": 123,
                "modified_at_ns": 1000,
                "extension": ".pdf",
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-file-probes.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "provider": "native",
                "status": "probed",
                "mime_type": "application/pdf",
                "extension": ".pdf",
                "media_type": "pdf",
                "size_bytes": 123,
                "page_count": 12,
                "embedded_text_chars": 0,
                "image_only_pdf_likelihood": 0.95,
                "encrypted": False,
                "width": None,
                "height": None,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-provider-selections.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "selected_provider": "current",
                "provider_chain": ["docling", "cortex_ocr", "current"],
                "provider_selection_reason": "preferred_docling_unavailable_fell_back_to_configured",
                "preferred_provider": "docling",
                "configured_provider": "current",
                "local_only_required": True,
                "skipped_providers": [{"provider": "docling", "reason": "dependency_unavailable"}],
                "metadata": {"strategy": "ocr_page_level", "media_type": "pdf"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-extraction-validations.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "status": "ok",
                "reason": None,
                "strategy": "ocr_page_level",
                "extraction_status": "extracted",
                "text_length": 42,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-extraction-repairs.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "status": "not_needed",
                "reason": None,
                "repair_strategy": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-quality-gates.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "quality": "poor",
                "can_chunk": True,
                "can_embed": True,
                "requires_review": True,
                "extraction_status": "extracted",
                "strategy": "ocr_page_level",
                "provider": "current",
                "text_length": 42,
                "validation_status": "ok",
                "validation_reason": None,
                "repair_status": "not_needed",
                "quality_evidence": ["quality:poor", "requires_review:true"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-document-segments.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "segment_id": "review:1:segment-001",
                "page_start": 1,
                "page_end": 12,
                "segment_index": 1,
                "segment_type": "scrapbook_page_group",
                "segment_confidence": 0.55,
                "requires_segment_review": True,
                "segment_boundary_evidence": ["matched:scrapbook"],
                "metadata": {"policy": "conservative_single_segment"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-indexing.jsonl").write_text(
        json.dumps(
            {
                "provider": "noop",
                "collection": None,
                "status": "skipped",
                "indexed_count": 0,
                "skipped_count": 1,
                "semantic_embedding_count": 1,
                "placeholder_embedding_count": 0,
                "indexed_chunk_ids": [],
                "skipped_chunk_ids": ["chunk-1"],
                "warnings": ["vector_store_not_configured"],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-placement-proposals.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "primary_tag": "scrapbooks",
                "proposal": {
                    "placement_status": "needs_review",
                    "placement_rule": "by_year",
                    "destination_path": "90_Intake_Needs_Review/06_History_Archive",
                    "date_confidence": "missing",
                },
                "metadata": {"tag_confidence": 0.52, "candidate_count": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-route-decisions.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "route_status": "review_ocr_quality",
                "review_reason": "ocr_quality_not_trusted",
                "priority": "high",
                "review_stage": "needs_ocr_review",
                "accepted": False,
                "evidence": ["route_status:review_ocr_quality", "quality:poor"],
                "metadata": {"quality": "poor", "strategy": "ocr_page_level"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-import-results.jsonl").write_text(
        json.dumps(
            {
                "import_status": "skipped",
                "importer": "noop",
                "output_dir": str(second_run_dir),
                "reason": "run_results_importer_not_configured",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(output_dir), "start": False},
    )
    report = client.get(f"/admin/runs/{run.json()['id']}/report")

    assert report.status_code == 200
    payload = report.json()
    assert payload["progress"]["summary"]["processed_count"] == 2
    assert payload["status_buckets"]["accepted"] == 1
    assert payload["status_buckets"]["review_required"] == 1
    assert payload["review_queue"]["count"] == 1
    assert payload["ocr"]["document_count"] == 1
    assert payload["ocr"]["page_count"] == 1
    assert payload["source_identity"]["count"] == 1
    assert payload["source_identity"]["items"][0]["file_id"] == "file-review"
    assert payload["file_probes"]["count"] == 1
    assert payload["file_probes"]["by_media_type"]["pdf"] == 1
    assert payload["provider_selections"]["count"] == 1
    assert payload["provider_selections"]["by_selected_provider"]["current"] == 1
    assert payload["extraction"]["count"] == 1
    assert payload["extraction"]["validation_count"] == 1
    assert payload["extraction"]["repair_count"] == 1
    assert payload["extraction"]["quality_gate_count"] == 1
    assert payload["extraction"]["validation_status"]["ok"] == 1
    assert payload["extraction"]["repair_status"]["not_needed"] == 1
    assert payload["extraction"]["quality_gate_quality"]["poor"] == 1
    assert payload["extraction"]["quality_gate_review_required"]["True"] == 1
    assert payload["provider_attempts"]["count"] == 1
    assert payload["provider_attempts"]["by_provider"]["current"] == 1
    assert payload["segments"]["count"] == 1
    assert payload["segments"]["requires_review_count"] == 1
    assert payload["segments"]["by_type"]["scrapbook_page_group"] == 1
    assert payload["indexing"]["by_status"]["skipped"] == 1
    assert payload["indexing"]["skipped_count"] == 1
    assert payload["indexing"]["semantic_embedding_count"] == 1
    assert payload["placement"]["proposal_count"] == 1
    assert payload["placement"]["proposal_status"]["needs_review"] == 1
    assert payload["routing"]["count"] == 1
    assert payload["routing"]["by_status"]["review_ocr_quality"] == 1
    assert payload["routing"]["by_priority"]["high"] == 1
    assert payload["routing"]["by_review_stage"]["needs_ocr_review"] == 1
    assert payload["imports"]["count"] == 1
    assert payload["imports"]["by_status"]["skipped"] == 1
    assert payload["model_usage"]["summary"]["total_calls"] == 1
    assert payload["model_usage"]["summary"]["external_calls"] == 1
    assert payload["distributions"]["primary_tag"]["meeting_records"] == 1
    assert payload["distributions"]["primary_tag"]["scrapbooks"] == 1


def test_delete_run_removes_run_owned_dashboard_rows_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    output_dir = tmp_path / "dashboard-runs" / "delete-me"
    output_dir.mkdir(parents=True)
    sample_file = tmp_path / "scan.pdf"
    sample_file.write_bytes(b"not a real source corpus file")
    result = {
        "sample_path": str(sample_file),
        "source_path": "/source/delete-me.pdf",
        "relative_path": "Review/delete-me.pdf",
        "route_status": "review_ocr_quality",
        "review_reason": "ocr_quality_not_trusted",
        "final_class": "scanned_document",
        "extraction_strategy": "ocr_page_level",
        "extraction_status": "extracted",
        "quality": "poor",
        "top_tag_candidate": "meeting_records",
        "secondary_tags": ["meeting_minutes"],
        "tag_confidence": 0.42,
        "llm_status": "skipped",
        "warnings": ["ocr_fallback_used:openai:gpt-4.1-mini"],
    }
    (output_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-review-queue.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-extraction-results.jsonl").write_text(json.dumps({**result, "text": "bad OCR text"}) + "\n", encoding="utf-8")
    (output_dir / "sample-model-usage.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/delete-me.pdf",
                "relative_path": "Review/delete-me.pdf",
                "purpose": "ocr_fallback",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "status": "ok",
                "cost_basis": "external",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-provider-attempts.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/delete-me.pdf",
                "relative_path": "Review/delete-me.pdf",
                "provider": "current",
                "capability": "extraction",
                "status": "extracted",
                "strategy": "ocr_page_level",
                "seconds": 0.2,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-document-segments.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/delete-me.pdf",
                "relative_path": "Review/delete-me.pdf",
                "segment_id": "delete:segment-001",
                "page_start": 1,
                "page_end": 4,
                "segment_index": 1,
                "segment_type": "single_document",
                "segment_confidence": 0.8,
                "requires_segment_review": False,
                "segment_boundary_evidence": ["default:single_document"],
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(output_dir), "start": False},
    )
    run_id = run.json()["id"]
    imported = client.post(f"/admin/runs/{run_id}/import-results", json={})
    items_before = client.get("/admin/review/items", params={"status": "all", "run_id": run_id})
    files_before = client.get("/admin/files/search", params={"run_id": run_id})
    usage_before = client.get(f"/admin/runs/{run_id}/model-usage")

    deleted = client.delete(f"/admin/runs/{run_id}")
    run_after = client.get(f"/admin/runs/{run_id}")
    items_after = client.get("/admin/review/items", params={"status": "all", "run_id": run_id})
    files_after = client.get("/admin/files/search", params={"run_id": run_id})

    assert imported.status_code == 200
    assert imported.json()["imported_review_items"] == 1
    assert imported.json()["imported_model_usage"] == 1
    assert imported.json()["imported_provider_attempts"] == 1
    assert imported.json()["imported_document_segments"] == 1
    assert len(items_before.json()) == 1
    assert files_before.json()["items"][0]["source_path"] == "/source/delete-me.pdf"
    assert usage_before.json()["summary"]["total_calls"] == 1
    assert deleted.status_code == 200
    assert deleted.json()["deleted_counts"]["review_items"] == 1
    assert deleted.json()["deleted_counts"]["file_index"] == 1
    assert deleted.json()["deleted_counts"]["pipeline_results"] == 1
    assert deleted.json()["deleted_counts"]["model_usage"] == 1
    assert deleted.json()["deleted_counts"]["provider_attempts"] == 1
    assert deleted.json()["deleted_counts"]["document_segments"] == 1
    assert deleted.json()["deleted_counts"]["pipeline_runs"] == 1
    assert deleted.json()["artifacts"]["deleted"] is True
    assert run_after.status_code == 404
    assert items_after.json() == []
    assert files_after.json()["items"] == []
    assert not output_dir.exists()


def test_api_pipeline_run_file_missing_file_returns_review_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "placeholder")
    output_dir = tmp_path / "api-out"

    response = TestClient(app).post(
        "/admin/pipeline/run-file",
        json={
            "input_file": str(tmp_path / "missing.pdf"),
            "output_dir": str(output_dir),
            "retry_attempts": 1,
            "enable_llm_tags": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_result"]["route_status"] == "review_failed_extraction"
    assert payload["final_result"]["review_reason"] == "file_missing"
    assert "file_missing" in payload["final_result"]["warnings"]


def test_api_review_import_list_and_decision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "placeholder")
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "disabled")
    output_dir = tmp_path / "langgraph-out"
    output_dir.mkdir()
    sample_file = tmp_path / "review.pdf"
    sample_file.write_bytes(b"review pdf bytes")
    result = {
        "sample_path": str(sample_file),
        "source_path": "/source/review.pdf",
        "relative_path": "Sunshine shared folders/review.pdf",
        "route_status": "review_low_confidence_tag",
        "review_reason": "tag_confidence_below_threshold",
        "final_class": "document",
        "extraction_strategy": "text_extraction",
        "extraction_status": "extracted",
        "quality": "ok",
        "top_tag_candidate": "meeting_records",
        "secondary_tags": ["meeting_minutes", "financial_report"],
        "tag_confidence": 0.52,
        "llm_status": "skipped",
        "placement_status": "missing_date",
        "placement_date_confidence": "missing",
        "default_privacy": "club_internal",
        "destination_path": "01_Governance_Admin/needs-date",
        "warnings": [
            "ocr_fallback_note:mostly clear",
            "ocr_fallback_used:openai:gpt-4.1-mini",
            "ocr_original_snippet:xqz",
            "ocr_fallback_snippet:Extracted meeting minutes OCR snippet for review.",
        ],
    }
    (output_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-review-queue.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-extraction-results.jsonl").write_text(
        json.dumps({**result, "text": "Extracted meeting minutes OCR snippet for review."}) + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    imported = client.post("/admin/review/import-langgraph-output", json={"output_dir": str(output_dir), "sample_routed_per_bucket": 0})
    summary = client.get("/admin/review/summary")
    placement_report = client.get("/admin/review/placement-report")
    review_export = client.get("/admin/review/export", params={"status": "all", "limit": 10})
    items = client.get("/admin/review/items")
    filtered_items = client.get(
        "/admin/review/items",
        params={"warning_type": "ocr_fallback_used", "source_collection": "sunshine_shared_folders"},
    )
    fallback_used_items = client.get("/admin/review/items", params={"status": "all", "ocr_fallback_used": "used"})
    fallback_not_used_items = client.get("/admin/review/items", params={"status": "all", "ocr_fallback_used": "not_used"})
    low_confidence_items = client.get("/admin/review/items", params={"status": "all", "confidence_bucket": "low"})
    item_id = items.json()[0]["id"]
    item_detail = client.get(f"/admin/review/items/{item_id}")
    ocr_poor = client.post(
        f"/admin/review/items/{item_id}/ocr-quality",
        json={"ocr_quality_label": "poor", "review_stage": "needs_ocr_review", "notes": "OCR is unreadable."},
    )
    review_facets = client.get("/admin/review/facets", params={"status": "all"})
    assigned_item = client.post(
        f"/admin/review/items/{item_id}/assign",
        json={"assigned_reviewer": "reviewer-a", "review_stage": "needs_tag_review", "priority": "high"},
    )
    decision = client.post(
        f"/admin/review/items/{item_id}/decision",
        json={
            "decision": "change",
            "correct_class": "document",
            "correct_tag": "annual_spring_tea",
            "correct_secondary_tags": ["event_material"],
            "correct_destination_path": "05_Events/2025",
            "correct_placement_year": "2025",
            "correct_privacy": "club_internal",
            "review_stage": "resolved",
            "reviewer": "james",
            "notes": "Path says tea.",
        },
    )
    golden_labels = client.get("/admin/review/golden-labels")
    golden_export_csv = client.get("/admin/review/golden-labels/export")
    golden_export_jsonl = client.get("/admin/review/golden-labels/export", params={"format": "jsonl"})
    label_id = golden_labels.json()[0]["id"]
    golden_file = client.get(f"/admin/review/golden-labels/{label_id}/file")
    edited_label = client.patch(
        f"/admin/review/golden-labels/{label_id}",
        json={
            "content_class": "document",
            "correct_primary_tag": "meeting_records",
            "correct_secondary_tags": ["meeting_minutes"],
            "ocr_quality_label": "ok",
            "expected_review_required": False,
            "sensitive_record": True,
            "correct_destination_path": "01_Governance_Admin/2025",
            "correct_placement_year": "2025",
            "correct_privacy": "restricted",
            "reviewer": "auditor",
            "notes": "Corrected from dashboard.",
        },
    )
    golden_summary = client.get("/admin/review/golden-labels/summary")
    semantic_status_before = client.get("/admin/semantic-index/status", params={"index_db": str(tmp_path / "semantic.sqlite")})
    semantic_build = client.post(
        "/admin/semantic-index/build",
        json={"output_db": str(tmp_path / "semantic.sqlite")},
    )
    eval_output_dir = tmp_path / "semantic-eval"
    semantic_eval = client.post("/admin/semantic-eval/run", json={"output_dir": str(eval_output_dir)})
    semantic_eval_latest = client.get("/admin/semantic-eval/latest", params={"output_dir": str(eval_output_dir)})
    pipeline_eval_output_dir = tmp_path / "pipeline-eval"
    pipeline_eval = client.post(
        "/admin/pipeline-eval/run",
        json={"output_dir": str(pipeline_eval_output_dir), "disable_semantic_index": True, "embedding_provider": "placeholder"},
    )
    pipeline_eval_latest = client.get("/admin/pipeline-eval/latest", params={"output_dir": str(pipeline_eval_output_dir)})
    pipeline_eval_import = client.post("/admin/pipeline-eval/import", json={"output_dir": str(pipeline_eval_output_dir)})
    pipeline_eval_runs = client.get("/admin/pipeline-eval/runs")
    pipeline_eval_run_id = pipeline_eval.json()["eval_run"]["id"]
    pipeline_eval_results = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results")
    pipeline_eval_failures = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "failures"})
    pipeline_eval_failure_groups = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "failure_groups"})
    pipeline_eval_model_usage = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "model_usage"})
    pipeline_eval_artifact_manifest = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "artifact_manifest"})
    pipeline_eval_output_dir_2 = tmp_path / "pipeline-eval-2"
    pipeline_eval_2 = client.post(
        "/admin/pipeline-eval/run",
        json={"output_dir": str(pipeline_eval_output_dir_2), "disable_semantic_index": True},
    )
    pipeline_eval_comparison = client.get(
        f"/admin/pipeline-eval/runs/{pipeline_eval_2.json()['eval_run']['id']}/compare",
        params={"baseline_eval_run_id": pipeline_eval_run_id},
    )
    deleted_label = client.delete(f"/admin/review/golden-labels/{label_id}")
    file_response = client.get(f"/admin/review/items/{item_id}/file")
    files = client.get("/admin/files", params={"q": "meeting minutes"})
    file_id = files.json()[0]["id"]
    file_text = client.get(f"/admin/files/{file_id}/text")
    file_review = client.post(f"/admin/files/{file_id}/review", json={"review_reason": "manual_file_review"})
    file_run = client.post(
        f"/admin/files/{file_id}/run",
        json={
            "output_dir": str(tmp_path / "single-file-run"),
            "start": False,
            "embedding_provider": "cortex",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "cortex",
        },
    )
    presets = client.get("/admin/runs/presets")
    run = client.post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "run_role": "evaluation",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "run-output"),
            "embedding_provider": "cortex",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "cortex",
            "start": False,
        },
    )
    assert run.json()["run_role"] == "evaluation"
    assert run.json()["run_metadata"]["run_role"] == "evaluation"
    failed_empty_run = client.post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "input_root": str(tmp_path / "empty-input"),
            "output_dir": str(tmp_path / "empty-run-output"),
            "start": True,
        },
    )
    run_results = client.get(f"/admin/runs/{run.json()['id']}/results")
    cancelled_run = client.post(f"/admin/runs/{run.json()['id']}/cancel", json={})
    previous_output = tmp_path / "previous-run-output"
    current_output = tmp_path / "current-run-output"
    previous_output.mkdir()
    current_output.mkdir()
    previous_result = {**result, "top_tag_candidate": "meeting_records", "route_status": "review_low_confidence_tag"}
    current_result = {**result, "top_tag_candidate": "annual_spring_tea", "route_status": "route_candidate"}
    (previous_output / "sample-pipeline-results.jsonl").write_text(json.dumps(previous_result) + "\n", encoding="utf-8")
    (current_output / "sample-pipeline-results.jsonl").write_text(json.dumps(current_result) + "\n", encoding="utf-8")
    (current_output / "sample-model-usage.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "purpose": "tag_inspection",
                        "provider": "cortex",
                        "model": "gemma4-26b",
                        "status": "ok",
                        "runtime_ms": 1200,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "cost_basis": "local",
                    }
                ),
                json.dumps(
                    {
                        "purpose": "ocr_fallback",
                        "provider": "openai",
                        "model": "gpt-4.1-mini",
                        "status": "failed",
                        "runtime_ms": 800,
                        "input_tokens": 200,
                        "output_tokens": 50,
                        "total_tokens": 250,
                        "estimated_cost_usd": 0.0123,
                        "cost_basis": "external",
                        "error": "timeout",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    previous_run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(previous_output), "start": False},
    )
    current_run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(current_output), "embedding_provider": "cortex", "start": False},
    )
    imported_run_results = client.post(f"/admin/runs/{current_run.json()['id']}/import-results", json={})
    run_comparison = client.get(f"/admin/runs/{current_run.json()['id']}/compare-previous")
    run_artifacts = client.get(f"/admin/runs/{current_run.json()['id']}/artifacts")
    run_model_usage = client.get(f"/admin/runs/{current_run.json()['id']}/model-usage")
    run_report = client.get(f"/admin/runs/{current_run.json()['id']}/report")
    file_search = client.get("/admin/files/search", params={"q": "meeting minutes", "limit": 10})
    file_search_by_tag = client.get("/admin/files/search", params={"primary_tag": "annual_spring_tea", "limit": 10})
    file_search_by_review = client.get("/admin/files/search", params={"review_status": "open", "limit": 10})
    file_facets = client.get("/admin/files/facets", params={"q": "meeting"})
    file_inspection = client.get(f"/admin/files/{file_id}/inspection")
    runs = client.get("/admin/runs")
    run_events = client.get(f"/admin/runs/{run.json()['id']}/events")
    run_progress = client.get(f"/admin/runs/{run.json()['id']}/progress")

    assert imported.status_code == 200
    assert imported.json()["imported_review_items"] == 1
    assert summary.json()["total_review_items"] == 1
    assert summary.json()["results_by_secondary_tag"]["financial_report"] == 1
    assert placement_report.status_code == 200
    assert placement_report.json()["by_placement_status"]["missing_date"] == 1
    assert placement_report.json()["by_privacy"]["club_internal"] == 1
    assert placement_report.json()["missing_date_queue"]
    assert review_export.status_code == 200
    assert "relative_path,source_path" in review_export.text
    assert "Sunshine shared folders/review.pdf" in review_export.text
    assert items.json()[0]["review_reason"] == "tag_confidence_below_threshold"
    assert items.json()[0]["secondary_tags"] == ["meeting_minutes", "financial_report"]
    assert items.json()[0]["extraction_text_snippet"] == "Extracted meeting minutes OCR snippet for review."
    assert items.json()[0]["display_warnings"] == ["ocr_fallback_used:openai:gpt-4.1-mini"]
    assert items.json()[0]["ocr_evidence"]["fallback_used"] is True
    assert items.json()[0]["ocr_evidence"]["original_text_snippet"] == "xqz"
    assert items.json()[0]["ocr_evidence"]["fallback_text_snippet"] == "Extracted meeting minutes OCR snippet for review."
    assert filtered_items.status_code == 200
    assert len(filtered_items.json()) == 1
    assert fallback_used_items.status_code == 200
    assert len(fallback_used_items.json()) == 1
    assert fallback_not_used_items.status_code == 200
    assert fallback_not_used_items.json() == []
    assert low_confidence_items.status_code == 200
    assert low_confidence_items.json()[0]["confidence"] == 0.52
    assert item_detail.status_code == 200
    assert item_detail.json()["id"] == item_id
    assert ocr_poor.status_code == 200
    assert ocr_poor.json()["ocr_quality_label"] == "poor"
    assert ocr_poor.json()["review_stage"] == "needs_ocr_review"
    assert "OCR is unreadable." in ocr_poor.json()["notes"]
    assert review_facets.status_code == 200
    assert review_facets.json()["review_reason"]["tag_confidence_below_threshold"] == 1
    assert review_facets.json()["confidence_bucket"]["low"] == 1
    assert review_facets.json()["ocr_fallback_used"]["used"] == 1
    assert review_facets.json()["primary_tag"]["meeting_records"] == 1
    assert assigned_item.status_code == 200
    assert assigned_item.json()["assigned_reviewer"] == "reviewer-a"
    assert assigned_item.json()["priority"] == "high"
    assert decision.json()["status"] == "resolved"
    assert decision.json()["correct_tag"] == "annual_spring_tea"
    assert decision.json()["correct_secondary_tags"] == ["event_material"]
    assert decision.json()["correct_destination_path"] == "05_Events/2025"
    assert decision.json()["correct_placement_year"] == "2025"
    assert decision.json()["correct_privacy"] == "club_internal"
    assert decision.json()["review_stage"] == "resolved"
    assert golden_labels.status_code == 200
    assert golden_labels.json()[0]["correct_primary_tag"] == "annual_spring_tea"
    assert golden_labels.json()[0]["correct_secondary_tags"] == ["event_material"]
    assert golden_labels.json()[0]["ocr_quality_label"] == "poor"
    assert golden_labels.json()[0]["reviewed_at"]
    assert golden_export_csv.status_code == 200
    assert "correct_primary_tag" in golden_export_csv.text
    assert "reviewed_at" in golden_export_csv.text
    assert "annual_spring_tea" in golden_export_csv.text
    assert golden_export_jsonl.status_code == 200
    assert json.loads(golden_export_jsonl.text.splitlines()[0])["correct_primary_tag"] == "annual_spring_tea"
    assert golden_file.status_code == 200
    assert golden_file.content == b"review pdf bytes"
    assert edited_label.status_code == 200
    assert edited_label.json()["content_class"] == "document"
    assert edited_label.json()["correct_primary_tag"] == "meeting_records"
    assert edited_label.json()["correct_secondary_tags"] == ["meeting_minutes"]
    assert edited_label.json()["ocr_quality_label"] == "ok"
    assert edited_label.json()["expected_review_required"] is False
    assert edited_label.json()["sensitive_record"] is True
    assert edited_label.json()["correct_destination_path"] == "01_Governance_Admin/2025"
    assert edited_label.json()["correct_placement_year"] == "2025"
    assert edited_label.json()["correct_privacy"] == "restricted"
    assert golden_summary.json()["total_golden_labels"] == 1
    assert semantic_status_before.status_code == 200
    assert semantic_status_before.json()["exists"] is False
    assert semantic_build.status_code == 200
    assert semantic_build.json()["indexed"] == 1
    assert semantic_build.json()["status"]["indexed"] == 1
    assert semantic_eval.status_code == 200
    assert semantic_eval.json()["report"]["total_golden_labels"] == 1
    assert semantic_eval_latest.status_code == 200
    assert semantic_eval_latest.json()["exists"] is True
    assert pipeline_eval.status_code == 200
    assert pipeline_eval.json()["report"]["total_golden_labels"] == 1
    assert pipeline_eval.json()["report"]["evaluated_predictions"] == 1
    assert pipeline_eval.json()["report"]["run_metadata"]["taxonomy_version"].endswith(".json")
    assert pipeline_eval.json()["report"]["run_metadata"]["embedding_provider"] == "placeholder"
    assert pipeline_eval.json()["report"]["run_metadata"]["extraction_provider"] == "current"
    assert pipeline_eval.json()["report"]["run_metadata"]["ocr_fallback_mode"] == "disabled"
    assert "git_commit" in pipeline_eval.json()["eval_run"]["run_metadata"]
    assert pipeline_eval.json()["eval_run"]["evaluated_predictions"] == 1
    assert (pipeline_eval_output_dir / "eval-summary.json").exists()
    assert pipeline_eval_latest.status_code == 200
    assert pipeline_eval_latest.json()["exists"] is True
    assert pipeline_eval_import.status_code == 200
    assert pipeline_eval_import.json()["eval_run"]["output_dir"] == str(pipeline_eval_output_dir)
    assert pipeline_eval_import.json()["report"]["artifacts"]["summary"] == str(pipeline_eval_output_dir / "eval-summary.json")
    assert pipeline_eval_runs.status_code == 200
    assert pipeline_eval_runs.json()[0]["output_dir"] == str(pipeline_eval_output_dir)
    assert pipeline_eval_results.status_code == 200
    assert pipeline_eval_results.json()["result_type"] == "results"
    assert pipeline_eval_results.json()["count"] == 1
    assert pipeline_eval_failures.status_code == 200
    assert pipeline_eval_failures.json()["result_type"] == "failures"
    assert pipeline_eval_failure_groups.status_code == 200
    assert pipeline_eval_failure_groups.json()["result_type"] == "failure_groups"
    assert pipeline_eval_model_usage.status_code == 200
    assert pipeline_eval_model_usage.json()["result_type"] == "model_usage"
    assert pipeline_eval_artifact_manifest.status_code == 200
    assert pipeline_eval_artifact_manifest.json()["result_type"] == "artifact_manifest"
    assert any(item["name"] == "summary" and len(item["sha256"]) == 64 for item in pipeline_eval_artifact_manifest.json()["items"])
    assert pipeline_eval_2.status_code == 200
    assert pipeline_eval_comparison.status_code == 200
    assert pipeline_eval_comparison.json()["shared_file_count"] == 1
    assert "primary_accuracy" in pipeline_eval_comparison.json()["metric_deltas"]
    assert pipeline_eval_comparison.json()["changed_prediction_count"] == 0
    assert pipeline_eval_comparison.json()["changed_secondary_tag_count"] == 0
    assert pipeline_eval_comparison.json()["changed_secondary_tags"] == []
    assert deleted_label.status_code == 200
    assert deleted_label.json()["deleted"] is True
    assert file_response.status_code == 200
    assert file_response.content == b"review pdf bytes"
    assert files.status_code == 200
    assert files.json()[0]["latest_result"]["top_tag_candidate"] == "meeting_records"
    assert files.json()[0]["latest_result"]["ocr_evidence"]["fallback_provider"] == "openai:gpt-4.1-mini"
    assert file_text.json()["text"] == "Extracted meeting minutes OCR snippet for review."
    assert file_review.status_code == 200
    assert file_review.json()["review_reason"] == "manual_file_review"
    assert file_run.status_code == 200
    assert file_run.json()["preset_key"] == "single_file_debug"
    assert file_run.json()["embedding_provider"] == "cortex"
    assert file_run.json()["llm_tag_provider"] == "cortex"
    assert file_run.json()["ocr_fallback_provider"] == "cortex"
    assert "--input-file" in file_run.json()["command"]
    assert "--embedding-provider" in file_run.json()["command"]
    assert presets.status_code == 200
    assert any(preset["preset_key"] == "qa_samples_fast" for preset in presets.json())
    assert any(preset["preset_key"] == "single_file_debug" for preset in presets.json())
    assert run.status_code == 200
    assert run.json()["status"] == "queued"
    assert run.json()["embedding_provider"] == "cortex"
    assert run.json()["llm_tag_provider"] == "cortex"
    assert run.json()["ocr_fallback_provider"] == "cortex"
    assert "--embedding-provider" in run.json()["command"]
    assert failed_empty_run.status_code == 200
    assert failed_empty_run.json()["status"] == "failed"
    assert "No runnable QA sample indexes" in failed_empty_run.json()["error"]
    assert run_results.status_code == 200
    assert run_results.json()["result_type"] == "none"
    assert cancelled_run.status_code == 200
    assert cancelled_run.json()["status"] == "cancelled"
    assert previous_run.status_code == 200
    assert current_run.status_code == 200
    assert current_run.json()["embedding_provider"] == "cortex"
    assert current_run.json()["run_metadata"]["embedding_provider"] == "cortex"
    assert current_run.json()["run_metadata"]["taxonomy_version"].endswith(".json")
    assert imported_run_results.status_code == 200
    assert imported_run_results.json()["imported_model_usage"] == 2
    assert run_comparison.status_code == 200
    assert run_comparison.json()["previous_run_id"] == previous_run.json()["id"]
    assert run_comparison.json()["summary"]["changed"] == 1
    assert "top_tag_candidate" in run_comparison.json()["changed"][0]["changed_fields"]
    assert run_artifacts.status_code == 200
    assert any(artifact["name"] == "sample-pipeline-results.jsonl" and artifact["exists"] for artifact in run_artifacts.json()["artifacts"])
    assert any(artifact["name"] == "sample-structure.jsonl" for artifact in run_artifacts.json()["artifacts"])
    result_artifact = next(artifact for artifact in run_artifacts.json()["artifacts"] if artifact["name"] == "sample-pipeline-results.jsonl")
    assert len(result_artifact["sha256"]) == 64
    assert run_model_usage.status_code == 200
    assert run_model_usage.json()["summary"]["total_calls"] == 2
    assert run_model_usage.json()["summary"]["failed_calls"] == 1
    assert run_model_usage.json()["summary"]["local_calls"] == 1
    assert run_model_usage.json()["summary"]["external_calls"] == 1
    assert run_model_usage.json()["summary"]["unknown_cost_basis_calls"] == 0
    assert run_model_usage.json()["summary"]["cost_basis_completeness_rate"] == 1.0
    assert run_model_usage.json()["summary"]["total_tokens"] == 370
    assert run_model_usage.json()["summary"]["estimated_external_cost_usd"] == 0.0123
    assert run_report.status_code == 200
    assert run_report.json()["model_usage"]["summary"]["total_calls"] == 2
    assert run_report.json()["status_buckets"]["accepted"] == 1
    assert run_report.json()["status_buckets"]["review_required"] == 0
    assert run_report.json()["status_buckets"]["failed"] == 0
    assert run_report.json()["status_buckets"]["deferred"] == 0
    assert run_report.json()["overview"]["status_buckets"]["accepted"] == 1
    assert run_report.json()["distributions"]["primary_tag"]["annual_spring_tea"] == 1
    assert run_report.json()["review_queue"]["links"]["all"] == f"/review?run_id={current_run.json()['id']}&status=all"
    assert "tag_disagreements" in run_report.json()["review_queue"]["links"]
    assert "review_rate" in run_report.json()["training_cycle"]
    assert run_report.json()["artifacts"]
    assert file_search.status_code == 200
    assert file_search.json()["items"][0]["filename"] == "review.pdf"
    assert "latest_result" not in file_search.json()["items"][0]
    assert file_search.json()["items"][0]["text_snippet"] == "Extracted meeting minutes OCR snippet for review."
    assert "latest_run_key" in file_search.json()["items"][0]
    assert file_search_by_tag.status_code == 200
    assert file_search_by_tag.json()["items"][0]["primary_tag"] == "annual_spring_tea"
    assert file_search_by_review.status_code == 200
    assert file_search_by_review.json()["items"][0]["review_status"] == "open"
    assert file_facets.status_code == 200
    assert file_facets.json()["primary_tag"]["annual_spring_tea"] == 1
    assert file_facets.json()["review_status"]["open"] == 1
    assert file_inspection.status_code == 200
    assert file_inspection.json()["file"]["filename"] == "review.pdf"
    assert file_inspection.json()["latest_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert file_inspection.json()["review_item"]["status"] == "open"
    assert file_inspection.json()["text"]["text"] == "Extracted meeting minutes OCR snippet for review."
    assert "preview_url" in file_inspection.json()["actions"]
    assert runs.json()[0]["preset_key"] == "qa_samples_fast"
    assert run_events.status_code == 200
    assert run_events.json()
    assert run_progress.status_code == 200
    assert run_progress.json()["run_id"] == run.json()["id"]
    assert "summary" in run_progress.json()
