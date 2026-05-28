"""Embedding and semantic-example retrieval nodes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sunshine_extraction.embeddings import EmbeddingConfigurationError, EmbeddingProviderError, PlaceholderEmbeddingProvider
from sunshine_extraction.graph.model_usage import _cost_basis, _embedding_model_usage_row, _model_usage_row
from sunshine_extraction.graph.node_utils import _empty_extraction
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.vectorization import embed_chunks, embed_chunks_with_fallback
from sunshine_extraction.semantic_index import search_semantic_index


def _embed_chunks_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    chunks = state.get("chunks", [])
    started = time.monotonic()
    provider = deps["embedding_provider"]
    embedding_warnings: list[str] = []
    if deps.get("embedding_failure_mode") == "review":
        try:
            embeddings = embed_chunks(chunks, provider)
        except (EmbeddingConfigurationError, EmbeddingProviderError) as error:
            embeddings = []
            embedding_warnings = [
                "embedding_provider_failed",
                "embedding_quality_unavailable",
            ]
            error_message = f"{type(error).__name__}: {error}"
        else:
            error_message = None
            if isinstance(provider, PlaceholderEmbeddingProvider) or any(row.get("embedding_status") == "placeholder" for row in embeddings):
                embedding_warnings = [
                    "embedding_placeholder_disallowed_in_eval",
                    "embedding_quality_unavailable",
                ]
    else:
        embeddings, embedding_warnings = embed_chunks_with_fallback(chunks, provider)
        error_message = ";".join(embedding_warnings) if embedding_warnings else None

    if isinstance(provider, PlaceholderEmbeddingProvider) or any(row.get("embedding_status") == "placeholder" for row in embeddings):
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
        "warnings": [*state.get("warnings", []), *embedding_warnings],
        "model_usage": [*state.get("model_usage", []), usage_row] if usage_row else state.get("model_usage", []),
    }

def _retrieve_labeled_examples_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    index_path = deps.get("semantic_index_path")
    if not index_path or not Path(index_path).exists():
        warnings = [*state.get("warnings", [])]
        warnings.append("semantic_index_missing")
        provider_name = str(
            getattr(deps["embedding_provider"], "provider_name", "")
            or deps["embedding_provider"].__class__.__name__.replace("EmbeddingProvider", "").lower()
            or "embedding"
        )
        usage_row = _model_usage_row(
            state,
            node="retrieve_labeled_examples",
            purpose="semantic_retrieval_embedding",
            provider=provider_name,
            model=str(getattr(deps["embedding_provider"], "model", "unknown")),
            status="skipped",
            runtime_ms=0,
            cost_basis=_cost_basis(provider_name),
            metadata={
                "call_count": 0,
                "reason": "semantic_index_missing",
                "semantic_index_path": str(index_path) if index_path else None,
                "cost_estimate": "unavailable",
            },
        )
        return {
            "semantic_examples": [],
            "warnings": warnings,
            "model_usage": [*state.get("model_usage", []), usage_row],
        }
    extraction = state.get("extraction_result") or _empty_extraction(state)
    query_text = "\n".join(
        [
            f"relative_path: {state.get('relative_path', '')}",
            f"filename: {state.get('filename', '')}",
            f"content_class: {state.get('content_class', {}).get('final_class', '')}",
            f"document_subtype: {state.get('extraction_plan', {}).get('document_subtype', '')}",
            f"text: {extraction.text[:2500]}",
        ]
    )
    warnings = [*state.get("warnings", [])]
    started = time.monotonic()
    try:
        examples = search_semantic_index(index_path, query_text, embedding_provider=deps["embedding_provider"], limit=5)
    except Exception as error:  # noqa: BLE001 - retrieval failure should not block extraction.
        warnings.append(f"semantic_example_retrieval_failed:{type(error).__name__}")
        usage_row = _embedding_model_usage_row(
            state,
            deps["embedding_provider"],
            node="retrieve_labeled_examples",
            purpose="semantic_retrieval_embedding",
            status="failed",
            call_count=1,
            started=started,
            error=f"{type(error).__name__}: {error}",
        )
        return {
            "semantic_examples": [],
            "warnings": warnings,
            "model_usage": [*state.get("model_usage", []), usage_row] if usage_row else state.get("model_usage", []),
        }
    usage_row = _embedding_model_usage_row(
        state,
        deps["embedding_provider"],
        node="retrieve_labeled_examples",
        purpose="semantic_retrieval_embedding",
        status="placeholder" if isinstance(deps["embedding_provider"], PlaceholderEmbeddingProvider) else "ok",
        call_count=1,
        started=started,
    )
    return {
        "semantic_examples": examples,
        "warnings": warnings,
        "model_usage": [*state.get("model_usage", []), usage_row] if usage_row else state.get("model_usage", []),
    }
