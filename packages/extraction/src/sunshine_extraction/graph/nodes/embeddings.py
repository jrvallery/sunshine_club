"""Chunk embedding node."""

from __future__ import annotations

import time
from typing import Any

from sunshine_extraction.graph.model_usage import _embedding_model_usage_row
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState


def _embed_chunks_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    chunks = state.get("chunks", [])
    started = time.monotonic()
    provider = deps["embedding_provider"]
    embeddings, embedding_attempt = deps["chunk_embedding_provider"].embed_chunks(
        chunks,
        failure_mode=str(deps.get("embedding_failure_mode") or "fallback"),
    )
    embedding_warnings = embedding_attempt.warnings
    error_message = str(embedding_attempt.metadata.get("error") or ";".join(embedding_warnings) or "") or None

    if embedding_attempt.status == "placeholder":
        usage_status = "placeholder"
    elif embedding_warnings:
        usage_status = "failed"
    else:
        usage_status = "ok"
    usage_row = _embedding_model_usage_row(
        state,
        provider,
        node="embed_chunks",
        purpose="chunk_embedding",
        status=usage_status,
        call_count=len(chunks),
        started=started,
        error=error_message,
    )
    return {
        "embeddings": embeddings,
        "embedding_result": embedding_attempt.as_row(),
        "warnings": [*state.get("warnings", []), *embedding_warnings],
        "model_usage": [*state.get("model_usage", []), usage_row] if usage_row else state.get("model_usage", []),
    }
