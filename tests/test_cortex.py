from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

from sunshine_extraction.cortex import CortexClient, CortexError


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_cortex_client_calls_ready_with_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _Response({"status": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="test-key", timeout_seconds=12)

    assert client.ready() == {"status": True}
    assert captured["url"] == "https://cortex.vallery.net/ready"
    assert captured["method"] == "GET"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["timeout"] == 12


def test_cortex_client_health_is_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        return _Response({"status": True, "service": "cortex-rag-gateway"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="")

    assert client.health()["status"] is True
    assert "Authorization" not in captured["headers"]


def test_cortex_client_rag_query_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response({"answer": "Answer [1]", "citations": [], "trace_id": "trace-1"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="test-key")

    result = client.rag_query(
        collection_id="sunshine-archive",
        query="What is this?",
        document_ids=["doc_1"],
        filters={"page_number": 1},
        retrieve_top_k=20,
    )

    assert captured["url"] == "https://cortex.vallery.net/v1/rag/query"
    assert captured["payload"]["collection_id"] == "sunshine-archive"
    assert captured["payload"]["document_ids"] == ["doc_1"]
    assert captured["payload"]["filters"] == {"page_number": 1}
    assert captured["payload"]["include_chunks"] is True
    assert result["trace_id"] == "trace-1"


def test_cortex_client_responses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response({"status": "completed", "output_text": "OK"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="test-key")

    result = client.responses("Return JSON", text={"format": {"type": "json_object"}})

    assert captured["url"] == "https://cortex.vallery.net/v1/responses"
    assert captured["payload"]["input"] == "Return JSON"
    assert captured["payload"]["text"] == {"format": {"type": "json_object"}}
    assert result["output_text"] == "OK"


def test_cortex_client_uploads_documents_as_multipart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "note.md"
    file_path.write_text("# Note", encoding="utf-8")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        return _Response({"document": {"id": "doc_1"}, "ingest_job": {"id": "job_1"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="test-key")

    result = client.upload_document(collection_id="sunshine", path=file_path, metadata={"source_uri": "test://note"})

    assert captured["url"] == "https://cortex.vallery.net/v1/documents"
    assert captured["headers"]["Content-type"].startswith("multipart/form-data")
    assert b'name="collection_id"' in captured["body"]
    assert b'name="file"; filename="note.md"' in captured["body"]
    assert result["document"]["id"] == "doc_1"


def test_cortex_client_metrics_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TextResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b"cortex_requests_total 1\n"

    def fake_urlopen(request, timeout):
        return _TextResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="test-key")

    assert client.metrics_text() == "cortex_requests_total 1\n"


def test_cortex_client_surfaces_openai_style_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://cortex.vallery.net/v1/rag/query",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"error":{"message":"query is required"}}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = CortexClient(base_url="https://cortex.vallery.net", api_key="test-key")

    with pytest.raises(CortexError, match="query is required") as error:
        client.rag_query(collection_id="sunshine", query="")

    assert error.value.status_code == 400
