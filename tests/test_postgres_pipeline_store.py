from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sunshine_api.postgres_pipeline_store import PostgresPipelineStore
from sunshine_api.services.imports import import_langgraph_output_to_postgres


class _Cursor:
    def __init__(self, row: Any = None) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


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
    assert any("[0.1,0.2,0.3]" in str(params) for _query, params in connection.executed)


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
    return output_dir
