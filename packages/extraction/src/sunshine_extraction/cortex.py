"""Small Cortex gateway client used by pipeline and future LangGraph nodes."""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_CORTEX_BASE_URL = "https://cortex.vallery.net"
DEFAULT_CORTEX_CHAT_MODEL = "gemma4-26b"
DEFAULT_CORTEX_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_CORTEX_RERANK_MODEL = "cortex-lexical-rerank"


class CortexError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, request_id: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class CortexClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 300,
    ) -> None:
        self.base_url = (base_url or os.environ.get("CORTEX_BASE_URL") or DEFAULT_CORTEX_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("CORTEX_API_KEY", "")
        self.timeout_seconds = timeout_seconds

    @property
    def openai_base_url(self) -> str:
        return self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", authenticated=False)

    def ready(self) -> dict[str, Any]:
        return self._request("GET", "/ready")

    def models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models")

    def chat_completions(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = DEFAULT_CORTEX_CHAT_MODEL,
        temperature: float = 0,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        return self._request("POST", "/v1/chat/completions", json_payload=payload)

    def responses(
        self,
        input_text: str,
        *,
        model: str = DEFAULT_CORTEX_CHAT_MODEL,
        max_output_tokens: int = 1024,
        text: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "input": input_text,
            "max_output_tokens": max_output_tokens,
        }
        if text is not None:
            payload["text"] = text
        return self._request("POST", "/v1/responses", json_payload=payload)

    def embeddings(
        self,
        texts: list[str],
        *,
        model: str = DEFAULT_CORTEX_EMBEDDING_MODEL,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/embeddings",
            json_payload={"model": model, "input": texts, "encoding_format": "float"},
        )

    def create_collection(self, collection_id: str, *, name: str | None = None, description: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"collection_id": collection_id}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if metadata is not None:
            payload["metadata"] = metadata
        return self._request("POST", "/v1/collections", json_payload=payload)

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/collections/{urllib.parse.quote(collection_id)}")

    def patch_collection(self, collection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/collections/{urllib.parse.quote(collection_id)}", json_payload=payload)

    def create_text_document(
        self,
        *,
        collection_id: str,
        filename: str,
        text: str,
        content_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/documents",
            json_payload={
                "collection_id": collection_id,
                "filename": filename,
                "content_type": content_type,
                "text": text,
                "metadata": metadata or {},
            },
        )

    def upload_document(self, *, collection_id: str, path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        file_path = Path(path)
        body, content_type = _multipart_form_data({"collection_id": collection_id, "metadata": json.dumps(metadata or {})}, "file", file_path)
        return self._request("POST", "/v1/documents", body=body, content_type=content_type)

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/documents/{urllib.parse.quote(document_id)}")

    def delete_document(self, document_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/documents/{urllib.parse.quote(document_id)}")

    def ingest_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/ingest-jobs/{urllib.parse.quote(job_id)}")

    def retry_ingest_job(self, job_id: str, *, force: bool = False) -> dict[str, Any]:
        payload = {"force": True} if force else {}
        return self._request("POST", f"/v1/ingest-jobs/{urllib.parse.quote(job_id)}/retry", json_payload=payload)

    def wait_for_ingest(self, job_id: str, *, timeout_seconds: float = 180, poll_seconds: float = 1) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            job = self.ingest_job(job_id)
            status = job.get("status")
            if status == "completed":
                return job
            if status == "failed":
                self.retry_ingest_job(job_id)
            time.sleep(poll_seconds)
        raise TimeoutError(f"Cortex ingest did not complete: {job_id}")

    def retrieve(self, *, collection_id: str, query: str, search_mode: str = "hybrid", top_k: int = 8, **extra: Any) -> dict[str, Any]:
        payload = {"collection_id": collection_id, "query": query, "search_mode": search_mode, "top_k": top_k, **extra}
        return self._request("POST", "/v1/retrieve", json_payload=payload)

    def search(self, *, collection_id: str, query: str, search_mode: str = "hybrid", top_k: int = 8, **extra: Any) -> dict[str, Any]:
        payload = {"collection_id": collection_id, "query": query, "search_mode": search_mode, "top_k": top_k, **extra}
        return self._request("POST", "/v1/search", json_payload=payload)

    def rag_query(self, *, collection_id: str, query: str, include_chunks: bool = True, **extra: Any) -> dict[str, Any]:
        payload = {"collection_id": collection_id, "query": query, "include_chunks": include_chunks, **extra}
        return self._request("POST", "/v1/rag/query", json_payload=payload)

    def rerank(
        self,
        *,
        query: str,
        documents: list[dict[str, Any]],
        model: str = DEFAULT_CORTEX_RERANK_MODEL,
        top_n: int = 5,
        return_documents: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/rerank",
            json_payload={
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "return_documents": return_documents,
            },
        )

    def ocr_file(self, path: str | Path, *, model: str | None = None) -> dict[str, Any]:
        fields = {"model": model} if model else {}
        body, content_type = _multipart_form_data(fields, "file", Path(path))
        return self._request("POST", "/v1/ocr", body=body, content_type=content_type)

    def feedback(self, *, rating: int, trace_id: str | None = None, response_id: str | None = None, comment: str | None = None, correction: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/feedback",
            json_payload={
                "trace_id": trace_id,
                "response_id": response_id,
                "rating": rating,
                "comment": comment,
                "correction": correction,
                "metadata": metadata or {},
            },
        )

    def metrics_text(self) -> str:
        return self._request_text("GET", "/metrics")

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        json_payload: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if authenticated and not self.api_key:
            raise CortexError("CORTEX_API_KEY is required")
        data = body
        headers: dict[str, str] = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if json_payload is not None:
            data = json.dumps(json_payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            request_id = error.headers.get("x-request-id") if error.headers else None
            raise CortexError(_error_message(error_body), status_code=error.code, request_id=request_id) from error
        if not response_body:
            return {}
        payload = json.loads(response_body)
        if not isinstance(payload, dict):
            raise CortexError("Cortex response was not a JSON object")
        return payload

    def _request_text(self, method: str, path: str) -> str:
        if not self.api_key:
            raise CortexError("CORTEX_API_KEY is required")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            request_id = error.headers.get("x-request-id") if error.headers else None
            raise CortexError(_error_message(error_body), status_code=error.code, request_id=request_id) from error


def _multipart_form_data(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = f"sunshine-cortex-{int(time.time() * 1000)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return str(error["message"])
    return body
